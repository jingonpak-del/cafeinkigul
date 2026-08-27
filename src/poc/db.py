"""SQLite persistence for the tracker (PoC).

Dedup is global per (cafe_id, article_id) because the same article can surface
on both a normal board and the popular board — we must crawl it once, but record
every board that surfaced it. Schema maps 1:1 to a future Postgres version.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    cafe_id            INTEGER NOT NULL,
    article_id         INTEGER NOT NULL,
    menu_id            INTEGER,
    title              TEXT,
    writer_nickname    TEXT,
    member_key         TEXT,
    write_ts           INTEGER,
    first_seen_at      INTEGER,          -- our detection time (ms)
    first_read_count   INTEGER,
    first_comment_count INTEGER,
    like_count         INTEGER,
    content_text       TEXT,
    content_html       TEXT,
    body_crawled       INTEGER DEFAULT 0,
    revisit_at         INTEGER,          -- when to re-check (ms)
    revisit_done       INTEGER DEFAULT 0,
    second_read_count  INTEGER,
    read_delta         INTEGER,
    second_comment_count INTEGER,
    status             TEXT DEFAULT 'active',   -- active | deleted
    PRIMARY KEY (cafe_id, article_id)
);

CREATE TABLE IF NOT EXISTS board_detections (
    cafe_id     INTEGER NOT NULL,
    article_id  INTEGER NOT NULL,
    board_key   TEXT NOT NULL,           -- 'menu:70' | 'popular'
    detected_at INTEGER NOT NULL,
    PRIMARY KEY (cafe_id, article_id, board_key)
);

CREATE TABLE IF NOT EXISTS comments (
    cafe_id     INTEGER NOT NULL,
    article_id  INTEGER NOT NULL,
    comment_id  INTEGER NOT NULL,
    ref_id      INTEGER,
    writer_nickname TEXT,
    member_key  TEXT,
    content     TEXT,
    update_ts   INTEGER,
    is_reply    INTEGER DEFAULT 0,
    is_deleted  INTEGER DEFAULT 0,
    phase       TEXT,                    -- 'first' | 'revisit'
    crawled_at  INTEGER,
    PRIMARY KEY (cafe_id, article_id, comment_id, phase)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- 카페 발굴 후보: 섹션 페이지/수동 조사로 발견한 '참조할 만한' 카페.
-- 체크(등록)하면 config.cafes로 승격되어 크롤 대상이 된다.
CREATE TABLE IF NOT EXISTS cafe_candidates (
    club_id       INTEGER PRIMARY KEY,
    cluburl       TEXT,
    name          TEXT,
    source        TEXT,               -- theme:2 | area:<code> | power | manual
    theme         TEXT,               -- 대표주제(섹션 테마명)
    is_power      INTEGER DEFAULT 0,  -- 대표(파워)카페 여부
    is_local      INTEGER DEFAULT 0,  -- 동네(지역)카페 여부
    member_count  INTEGER,
    daily_posts   REAL,               -- 하루 발행량(추정)
    open_level    TEXT,               -- 공개수준
    join_required INTEGER DEFAULT 0,  -- 인기글/글 열람에 가입 필요
    sample_boards TEXT,               -- 대표 게시판명(콤마)
    score         REAL,               -- 참조가치 점수(정렬용)
    discovered_at INTEGER,
    updated_at    INTEGER,
    status        TEXT DEFAULT 'new'  -- new | tracked | dismissed | join_needed
);

CREATE INDEX IF NOT EXISTS idx_articles_revisit
    ON articles (revisit_done, revisit_at);
CREATE INDEX IF NOT EXISTS idx_articles_pending_body
    ON articles (body_crawled);
-- 대시보드 로드 핵심: 최신순 정렬(ORDER BY write_ts) + 급상승/호응(write_ts>= 범위).
-- 통째 수집으로 수십만 건이 되면 이 인덱스 없이는 전체 스캔/정렬로 쿼리가 1~2초 걸린다.
CREATE INDEX IF NOT EXISTS idx_articles_write_ts
    ON articles (write_ts);
CREATE INDEX IF NOT EXISTS idx_articles_status_write
    ON articles (status, write_ts);
-- 카테고리 필터(게시판 지정 목록 OR 매칭)가 menu_id로 좁혀지도록.
CREATE INDEX IF NOT EXISTS idx_articles_menu
    ON articles (menu_id);
-- 카테고리+최신순: (cafe_id,menu_id) 각 게시판 조건이 이미 write_ts 정렬 순서로
-- 색인되게 해 MULTI-INDEX OR 병합 비용을 낮춘다(실측 20게시판 68k건: 700ms→430ms).
-- UNION으로 브랜치별 LIMIT을 미리 건 방식은 오히려 느려서(재정렬 중복) 폐기했다 —
-- SQLite가 OR을 자체적으로 병합·정렬하는 현재 방식이 최선이었다.
CREATE INDEX IF NOT EXISTS idx_articles_board_write
    ON articles (cafe_id, menu_id, write_ts DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_status
    ON cafe_candidates (status, score);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        # WAL: 워처가 쓰는 동안 웹서버가 동시에 읽을 수 있게.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """기존 DB에 없는 컬럼을 추가 (폴링 시 갱신되는 현재 카운트)."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(articles)")}
        for col, decl in (("cur_read", "INTEGER"), ("cur_comment", "INTEGER"),
                          ("cur_like", "INTEGER"), ("cur_snapshot_at", "INTEGER"),
                          ("used", "INTEGER DEFAULT 0"), ("used_by", "TEXT"), ("used_at", "INTEGER"),
                          ("menu_name", "TEXT"),
                          # Phase 0: HTML은 raw 아카이브로 빠지고, 스튜디오용 링크/이미지만 남긴다.
                          ("material_json", "TEXT"),
                          # Phase 1: 어느 레인이 수집했는지(stream | backfill). 보고서용.
                          ("lane", "TEXT")):
            if col not in cols:
                self.conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {decl}")

        # Phase 1: 발굴 후보의 학습가치 신호 (표본 본문을 실제로 읽어 잰 값).
        ccols = {r[1] for r in self.conn.execute("PRAGMA table_info(cafe_candidates)")}
        for col, decl in (("avg_text_len", "INTEGER"), ("avg_comments", "REAL"),
                          ("ad_ratio", "REAL"), ("text_richness", "REAL"),
                          ("comment_density", "REAL"), ("topic_novelty", "REAL"),
                          ("sample_bodies", "INTEGER"), ("probed_at", "INTEGER")):
            if col not in ccols:
                self.conn.execute(f"ALTER TABLE cafe_candidates ADD COLUMN {col} {decl}")

    def close(self):
        self.conn.close()

    # --- detection -----------------------------------------------------------
    def upsert_article_seen(self, a, board_key: str, revisit_after_s: int) -> bool:
        """Insert a freshly seen article. Returns True if it is NEW (first time
        across all boards), False if already known. Always records the board."""
        ts = now_ms()
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO articles
               (cafe_id, article_id, menu_id, menu_name, title, writer_nickname, member_key,
                write_ts, first_seen_at, first_read_count, first_comment_count,
                like_count, revisit_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (a.cafe_id, a.article_id, a.menu_id, a.menu_name, a.title, a.writer_nickname, a.member_key,
             a.write_ts, ts, a.read_count, a.comment_count, a.like_count,
             ts + revisit_after_s * 1000),
        )
        is_new = cur.rowcount > 0
        self.conn.execute(
            """INSERT OR IGNORE INTO board_detections
               (cafe_id, article_id, board_key, detected_at) VALUES (?,?,?,?)""",
            (a.cafe_id, a.article_id, board_key, ts),
        )
        self.conn.commit()
        return is_new

    def upsert_article_from_body(self, body, lane: str = "backfill") -> bool:
        """백필용: 목록 감지 없이 본문 응답만으로 게시글 행을 만든다.

        스트림은 목록에서 먼저 보고 나중에 본문을 받지만, 백필은 article_id를 직접 찍어
        본문부터 받는다. 과거 글은 조회수가 더 오르지 않으므로 재방문 대상에서 뺀다."""
        ts = now_ms()
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO articles
               (cafe_id, article_id, menu_id, title, writer_nickname, member_key,
                write_ts, first_seen_at, first_read_count, first_comment_count,
                revisit_done, lane)
               VALUES (?,?,?,?,?,?,?,?,?,?,1,?)""",
            (body.cafe_id, body.article_id, body.menu_id, body.title,
             body.writer_nickname, body.member_key, body.write_ts, ts,
             body.read_count, body.comment_count, lane),
        )
        is_new = cur.rowcount > 0
        self.conn.execute(
            """INSERT OR IGNORE INTO board_detections
               (cafe_id, article_id, board_key, detected_at) VALUES (?,?,?,?)""",
            (body.cafe_id, body.article_id, lane, ts),
        )
        self.conn.commit()
        return is_new

    def update_current_counts_bulk(self, arts):
        """폴링 시 목록이 준 현재 조회/댓글/좋아요를 일괄 갱신 (인기점수용)."""
        if not arts:
            return
        ts = now_ms()
        self.conn.executemany(
            """UPDATE articles SET cur_read=?, cur_comment=?, cur_like=?, cur_snapshot_at=?,
                   menu_name=COALESCE(NULLIF(?, ''), menu_name)
               WHERE cafe_id=? AND article_id=?""",
            [(a.read_count, a.comment_count, a.like_count, ts, a.menu_name, a.cafe_id, a.article_id)
             for a in arts],
        )
        self.conn.commit()

    # --- body / comments -----------------------------------------------------
    def save_body(self, body):
        """본문 저장. HTML은 DB가 아니라 raw 아카이브로 간다(Phase 0).

        스튜디오가 쓰던 링크·이미지 목록은 크롤 시점에 뽑아 material_json으로 남겨,
        HTML 없이도 재크롤 없이 쓸 수 있게 한다."""
        from . import raw_archive, studio
        raw_archive.get().write(cafe_id=body.cafe_id, article_id=body.article_id,
                                write_ts=getattr(body, "write_ts", None),
                                html=body.content_html)
        try:
            material = json.dumps(
                studio.extract_material(body.content_html, body.content_text),
                ensure_ascii=False)
        except Exception:
            material = None
        self.conn.execute(
            """UPDATE articles SET content_text=?, material_json=?, body_crawled=1
               WHERE cafe_id=? AND article_id=?""",
            (body.content_text, material, body.cafe_id, body.article_id),
        )
        self.conn.commit()

    def save_comments(self, cafe_id, article_id, comments, phase: str):
        ts = now_ms()
        self.conn.executemany(
            """INSERT OR REPLACE INTO comments
               (cafe_id, article_id, comment_id, ref_id, writer_nickname, member_key,
                content, update_ts, is_reply, is_deleted, phase, crawled_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(cafe_id, article_id, c.comment_id, c.ref_id, c.writer_nickname, c.member_key,
              c.content, c.update_ts, int(c.is_reply), int(c.is_deleted), phase, ts)
             for c in comments],
        )
        self.conn.commit()

    # --- revisit -------------------------------------------------------------
    def due_revisits(self, limit: int = 50):
        return self.conn.execute(
            """SELECT cafe_id, article_id, menu_id, first_read_count
               FROM articles
               WHERE revisit_done=0 AND revisit_at<=? AND body_crawled=1
               ORDER BY revisit_at LIMIT ?""",
            (now_ms(), limit),
        ).fetchall()

    # --- meta ----------------------------------------------------------------
    def get_meta(self, key: str):
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def set_meta(self, key: str, value: str):
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        self.conn.commit()

    def mark_deleted(self, cafe_id, article_id):
        self.conn.execute(
            "UPDATE articles SET status='deleted', revisit_done=1 WHERE cafe_id=? AND article_id=?",
            (cafe_id, article_id))
        self.conn.commit()

    def complete_revisit(self, cafe_id, article_id, second_read, second_comment, first_read):
        self.conn.execute(
            """UPDATE articles SET revisit_done=1, second_read_count=?,
               second_comment_count=?, read_delta=? WHERE cafe_id=? AND article_id=?""",
            (second_read, second_comment, (second_read or 0) - (first_read or 0),
             cafe_id, article_id),
        )
        self.conn.commit()

    # --- export --------------------------------------------------------------
    def all_articles_with_boards(self):
        """각 글 + 그 글이 감지된 보드(들)를 합쳐 반환 (시트 적재용)."""
        return self.conn.execute(
            """SELECT a.*,
                      (SELECT group_concat(board_key, ',') FROM board_detections d
                       WHERE d.cafe_id=a.cafe_id AND d.article_id=a.article_id) AS board_keys
               FROM articles a ORDER BY a.first_seen_at"""
        ).fetchall()

    def comments_for(self, cafe_id, article_id, phase: str | None = None):
        if phase:
            return self.conn.execute(
                "SELECT * FROM comments WHERE cafe_id=? AND article_id=? AND phase=? ORDER BY comment_id",
                (cafe_id, article_id, phase)).fetchall()
        return self.conn.execute(
            "SELECT * FROM comments WHERE cafe_id=? AND article_id=? ORDER BY comment_id",
            (cafe_id, article_id)).fetchall()

    # --- cafe 발굴 후보 -------------------------------------------------------
    _CAND_FIELDS = ("cluburl", "name", "source", "theme", "is_power", "is_local",
                    "member_count", "daily_posts", "open_level", "join_required",
                    "sample_boards", "score")
    # probe로만 채워지는 학습가치 신호. 열거만 한 후보는 값이 없으므로 별도로 쓴다
    # (열거 결과가 probe 결과를 NULL로 덮어쓰지 않게).
    # daily_posts·sample_boards·join_required도 여기 넣는다. 열거 단계에서는 알 수 없고
    # probe에서만 채워지는데, 이 목록에 없으면 점수 계산에만 쓰이고 저장되지 않는다.
    _SIGNAL_FIELDS = ("avg_text_len", "avg_comments", "ad_ratio", "text_richness",
                      "comment_density", "topic_novelty", "sample_bodies",
                      "daily_posts", "sample_boards", "join_required")

    def upsert_candidate(self, c: dict, status: str = "enumerated"):
        """후보 저장/갱신. 기존 후보면 지표만 갱신하고 status는 보존
        (한번 dismissed/tracked한 카페가 다시 new로 돌아오지 않게).

        status 기본값이 'enumerated'인 이유: 섹션 열거는 하루 700개 넘게 쏟아내는데
        이걸 전부 'new'(승인 대기)로 넣으면 사람이 볼 큐가 무너진다. 열거 결과는 풀에
        쌓아두고, probe로 검증해 뽑힌 소수만 'new'로 올린다."""
        ts = now_ms()
        p = {k: c.get(k) for k in self._CAND_FIELDS}
        p["club_id"] = c["club_id"]
        p["ts"] = ts
        p["status"] = status
        self.conn.execute(
            """INSERT INTO cafe_candidates
               (club_id, cluburl, name, source, theme, is_power, is_local,
                member_count, daily_posts, open_level, join_required,
                sample_boards, score, discovered_at, updated_at, status)
               VALUES (:club_id,:cluburl,:name,:source,:theme,:is_power,:is_local,
                :member_count,:daily_posts,:open_level,:join_required,
                :sample_boards,:score,:ts,:ts,:status)
               ON CONFLICT(club_id) DO UPDATE SET
                 cluburl=excluded.cluburl, name=excluded.name, source=excluded.source,
                 theme=excluded.theme, is_power=excluded.is_power, is_local=excluded.is_local,
                 member_count=excluded.member_count,
                 open_level=excluded.open_level,
                 -- 아래 셋은 probe로만 제대로 채워진다. 매일 도는 열거가 NULL/추정치로
                 -- 덮어쓰면 힘들게 조사한 값이 사라진다(실측: 점수 104.0 → 43.2).
                 daily_posts=CASE WHEN cafe_candidates.probed_at IS NOT NULL
                                  THEN cafe_candidates.daily_posts ELSE excluded.daily_posts END,
                 join_required=CASE WHEN cafe_candidates.probed_at IS NOT NULL
                                    THEN cafe_candidates.join_required ELSE excluded.join_required END,
                 sample_boards=CASE WHEN cafe_candidates.probed_at IS NOT NULL
                                    THEN cafe_candidates.sample_boards ELSE excluded.sample_boards END,
                 score=CASE WHEN cafe_candidates.probed_at IS NOT NULL
                            THEN cafe_candidates.score ELSE excluded.score END,
                 updated_at=excluded.updated_at""",
            p,
        )
        self.conn.commit()

    def unprobed_candidates(self, exclude_ids=()):
        """아직 표본 조사를 안 한 후보 풀. 매일 상위 몇 개씩 꺼내 조사한다.
        probed_at이 있는 행을 빼지 않으면 매일 같은 카페만 다시 조사하게 된다."""
        rows = self.conn.execute(
            "SELECT * FROM cafe_candidates "
            "WHERE probed_at IS NULL AND status NOT IN ('tracked','dismissed') "
            "ORDER BY score DESC").fetchall()
        ex = set(exclude_ids)
        return [r for r in rows if r["club_id"] not in ex]

    def save_candidate_signals(self, club_id: int, sig: dict, score: float):
        """probe로 잰 학습가치 신호와 재계산된 점수를 후보에 기록."""
        sets = ", ".join(f"{k}=:{k}" for k in self._SIGNAL_FIELDS)
        p = {k: sig.get(k) for k in self._SIGNAL_FIELDS}
        p.update(club_id=club_id, score=score, ts=now_ms())
        self.conn.execute(
            f"UPDATE cafe_candidates SET {sets}, score=:score, probed_at=:ts, updated_at=:ts "
            "WHERE club_id=:club_id", p)
        self.conn.commit()

    def list_candidates(self, status: str | None = None):
        if status:
            return self.conn.execute(
                "SELECT * FROM cafe_candidates WHERE status=? ORDER BY score DESC, member_count DESC",
                (status,)).fetchall()
        return self.conn.execute(
            "SELECT * FROM cafe_candidates ORDER BY status, score DESC").fetchall()

    def get_candidate(self, club_id: int):
        return self.conn.execute(
            "SELECT * FROM cafe_candidates WHERE club_id=?", (club_id,)).fetchone()

    def set_candidate_status(self, club_id: int, status: str):
        self.conn.execute(
            "UPDATE cafe_candidates SET status=?, updated_at=? WHERE club_id=?",
            (status, now_ms(), club_id))
        self.conn.commit()

    def candidate_exists(self, club_id: int) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM cafe_candidates WHERE club_id=?", (club_id,)).fetchone() is not None

    # --- stats ---------------------------------------------------------------
    def counts(self) -> dict:
        c = self.conn.execute
        return {
            "articles": c("SELECT COUNT(*) FROM articles").fetchone()[0],
            "bodies": c("SELECT COUNT(*) FROM articles WHERE body_crawled=1").fetchone()[0],
            "comments": c("SELECT COUNT(*) FROM comments").fetchone()[0],
            "revisited": c("SELECT COUNT(*) FROM articles WHERE revisit_done=1").fetchone()[0],
            "pending_revisit": c("SELECT COUNT(*) FROM articles WHERE revisit_done=0").fetchone()[0],
            "deleted": c("SELECT COUNT(*) FROM articles WHERE status='deleted'").fetchone()[0],
        }

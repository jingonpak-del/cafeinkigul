"""SQLite persistence for the tracker (PoC).

Dedup is global per (cafe_id, article_id) because the same article can surface
on both a normal board and the popular board — we must crawl it once, but record
every board that surfaced it. Schema maps 1:1 to a future Postgres version.
"""
from __future__ import annotations

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
                          ("menu_name", "TEXT")):
            if col not in cols:
                self.conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {decl}")

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
        self.conn.execute(
            """UPDATE articles SET content_text=?, content_html=?, body_crawled=1
               WHERE cafe_id=? AND article_id=?""",
            (body.content_text, body.content_html, body.cafe_id, body.article_id),
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

    def upsert_candidate(self, c: dict):
        """후보 저장/갱신. 기존 후보면 지표만 갱신하고 status는 보존
        (한번 dismissed/tracked한 카페가 다시 new로 돌아오지 않게)."""
        ts = now_ms()
        p = {k: c.get(k) for k in self._CAND_FIELDS}
        p["club_id"] = c["club_id"]
        p["ts"] = ts
        self.conn.execute(
            """INSERT INTO cafe_candidates
               (club_id, cluburl, name, source, theme, is_power, is_local,
                member_count, daily_posts, open_level, join_required,
                sample_boards, score, discovered_at, updated_at, status)
               VALUES (:club_id,:cluburl,:name,:source,:theme,:is_power,:is_local,
                :member_count,:daily_posts,:open_level,:join_required,
                :sample_boards,:score,:ts,:ts,'new')
               ON CONFLICT(club_id) DO UPDATE SET
                 cluburl=excluded.cluburl, name=excluded.name, source=excluded.source,
                 theme=excluded.theme, is_power=excluded.is_power, is_local=excluded.is_local,
                 member_count=excluded.member_count, daily_posts=excluded.daily_posts,
                 open_level=excluded.open_level, join_required=excluded.join_required,
                 sample_boards=excluded.sample_boards, score=excluded.score,
                 updated_at=excluded.updated_at""",
            p,
        )
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

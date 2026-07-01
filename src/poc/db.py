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

CREATE INDEX IF NOT EXISTS idx_articles_revisit
    ON articles (revisit_done, revisit_at);
CREATE INDEX IF NOT EXISTS idx_articles_pending_body
    ON articles (body_crawled);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- detection -----------------------------------------------------------
    def upsert_article_seen(self, a, board_key: str, revisit_after_s: int) -> bool:
        """Insert a freshly seen article. Returns True if it is NEW (first time
        across all boards), False if already known. Always records the board."""
        ts = now_ms()
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO articles
               (cafe_id, article_id, menu_id, title, writer_nickname, member_key,
                write_ts, first_seen_at, first_read_count, first_comment_count,
                like_count, revisit_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (a.cafe_id, a.article_id, a.menu_id, a.title, a.writer_nickname, a.member_key,
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

    # --- stats ---------------------------------------------------------------
    def counts(self) -> dict:
        c = self.conn.execute
        return {
            "articles": c("SELECT COUNT(*) FROM articles").fetchone()[0],
            "bodies": c("SELECT COUNT(*) FROM articles WHERE body_crawled=1").fetchone()[0],
            "comments": c("SELECT COUNT(*) FROM comments").fetchone()[0],
            "revisited": c("SELECT COUNT(*) FROM articles WHERE revisit_done=1").fetchone()[0],
            "pending_revisit": c("SELECT COUNT(*) FROM articles WHERE revisit_done=0").fetchone()[0],
        }

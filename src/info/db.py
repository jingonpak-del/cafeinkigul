"""SQLite persistence for the info aggregator.

여러 사이트(블로그·정부·비영리·교육 등)에서 가져온 글을 하나의 범용 posts
테이블에 저장한다. 소스마다 항목이 다르므로 없는 값(조회수·작성자 등)은 NULL로
둔다. 중복은 (source_id, post_key)로 전역 판별.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    source_id     TEXT NOT NULL,          -- 'naver_blog:mltmkr'
    post_key      TEXT NOT NULL,          -- 소스 내 고유 id (블로그 logNo 등)
    source_name   TEXT,                   -- 표시용 출처명 '국토교통부'
    source_type   TEXT,                   -- 'naver_blog' | 'rss' | ...
    category      TEXT,                   -- '정부' | '비영리' | ...
    title         TEXT,
    author        TEXT,                   -- 작성자(없으면 NULL)
    url           TEXT,                   -- 원문 링크
    published_at  INTEGER,                -- 원문 작성일(ms, 없으면 NULL)
    collected_at  INTEGER,                -- 우리가 가져온 시각(ms)
    view_count    INTEGER,                -- 조회수(없으면 NULL)
    content_text  TEXT,                   -- 본문 txt(요약/발췌)
    PRIMARY KEY (source_id, post_key)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_published ON posts (published_at);
CREATE INDEX IF NOT EXISTS idx_posts_source    ON posts (source_id);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def upsert_post(self, p: dict) -> bool:
        """새 글이면 INSERT하고 True, 이미 있으면 무시하고 False.
        p keys: source_id, post_key, source_name, source_type, category,
                title, author, url, published_at, view_count, content_text"""
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO posts
               (source_id, post_key, source_name, source_type, category, title,
                author, url, published_at, collected_at, view_count, content_text)
               VALUES (:source_id, :post_key, :source_name, :source_type, :category,
                       :title, :author, :url, :published_at, :collected_at,
                       :view_count, :content_text)""",
            {**p, "collected_at": now_ms()},
        )
        self.conn.commit()
        return cur.rowcount > 0

    def latest_published(self, source_id: str) -> int | None:
        r = self.conn.execute(
            "SELECT MAX(published_at) FROM posts WHERE source_id=?", (source_id,)
        ).fetchone()
        return r[0] if r and r[0] else None

    def get_meta(self, key: str):
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
        )
        self.conn.commit()

    def counts(self) -> dict:
        c = self.conn.execute
        return {
            "posts": c("SELECT COUNT(*) FROM posts").fetchone()[0],
            "sources": c("SELECT COUNT(DISTINCT source_id) FROM posts").fetchone()[0],
        }

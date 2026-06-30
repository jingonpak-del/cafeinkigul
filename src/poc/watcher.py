"""Watcher skeleton — the real-time engine, single-process PoC version.

Round-robins through configured boards (1 board per tick) so a single account's
request rate stays modest. New articles (deduped globally per cafe+article) get
their body + comments crawled immediately and scheduled for a 4-hour revisit that
records the read-count delta. This maps directly onto the future async server:
Watcher -> queue -> Crawl Worker -> DB / Sheets, plus a Revisit scheduler.
"""
from __future__ import annotations

import itertools
import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import cafe_api
from .db import Database, now_ms
from .session import SessionManager

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Board:
    cluburl: str
    club_id: int
    board_key: str       # 'menu:70' | 'popular'
    kind: str            # 'menu' | 'popular'
    menu_id: int
    name: str


def load_boards(cfg: dict) -> list[Board]:
    boards: list[Board] = []
    for cafe in cfg["cafes"]:
        for b in cafe["boards"]:
            if b["type"] == "popular":
                boards.append(Board(cafe["cluburl"], cafe["club_id"], "popular", "popular", 0, b.get("name", "인기글")))
            else:
                mid = b["menu_id"]
                boards.append(Board(cafe["cluburl"], cafe["club_id"], f"menu:{mid}", "menu", mid, b.get("name", "")))
    return boards


class Watcher:
    def __init__(self, cfg: dict, db: Database, client, *,
                 per_page: int = 30, revisit_after_s: int = 4 * 3600,
                 min_request_gap_s: float = 1.0, log=print):
        self.cfg = cfg
        self.db = db
        self.client = client
        self.per_page = per_page
        self.revisit_after_s = revisit_after_s
        self.min_gap = min_request_gap_s
        self.log = log
        self.boards = load_boards(cfg)
        self._last_request = 0.0

    # --- rate limit ----------------------------------------------------------
    def _throttle(self):
        wait = self.min_gap - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    # --- one board poll ------------------------------------------------------
    def poll_board(self, b: Board):
        self._throttle()
        if b.kind == "popular":
            arts = cafe_api.fetch_popular_list(b.club_id, per_page=self.per_page, client=self.client)
        else:
            arts = cafe_api.fetch_article_list(b.club_id, menu_id=b.menu_id,
                                               per_page=self.per_page, client=self.client)
        new_count = 0
        for a in arts:
            if a.blinded or a.is_notice:
                continue
            is_new = self.db.upsert_article_seen(a, b.board_key, self.revisit_after_s)
            if is_new:
                new_count += 1
                self._crawl_new(a, b)
        return len(arts), new_count

    def _crawl_new(self, a, b: Board):
        """First-detection crawl: body + comments."""
        try:
            self._throttle()
            body = cafe_api.fetch_article_body(a.cafe_id, a.article_id, menu_id=b.menu_id, client=self.client)
            self.db.save_body(body)
            self._throttle()
            comments = cafe_api.fetch_comments(a.cafe_id, a.article_id, client=self.client)
            self.db.save_comments(a.cafe_id, a.article_id, comments, phase="first")
            self.log(f"  + NEW {b.cluburl}/{b.name} [{a.article_id}] {a.title[:30]} "
                     f"(조회{a.read_count} 댓글{len(comments)})")
        except Exception as e:
            self.log(f"  ! 본문/댓글 크롤 실패 [{a.article_id}]: {e}")

    # --- revisit -------------------------------------------------------------
    def process_revisits(self):
        due = self.db.due_revisits()
        for row in due:
            try:
                self._throttle()
                body = cafe_api.fetch_article_body(row["cafe_id"], row["article_id"],
                                                   menu_id=row["menu_id"] or 0, client=self.client)
                self._throttle()
                comments = cafe_api.fetch_comments(row["cafe_id"], row["article_id"], client=self.client)
                self.db.save_comments(row["cafe_id"], row["article_id"], comments, phase="revisit")
                self.db.complete_revisit(row["cafe_id"], row["article_id"],
                                         body.read_count, body.comment_count, row["first_read_count"])
                delta = (body.read_count or 0) - (row["first_read_count"] or 0)
                self.log(f"  ~ REVISIT [{row['article_id']}] 조회 {row['first_read_count']}→{body.read_count} (+{delta})")
            except Exception as e:
                self.log(f"  ! 재방문 실패 [{row['article_id']}]: {e}")

    # --- main loops ----------------------------------------------------------
    def sweep_once(self):
        """One full pass over every board (used for testing / seeding)."""
        for b in self.boards:
            total, new = self.poll_board(b)
            self.log(f"■ {b.cluburl}/{b.name}: {total}건 조회, 신규 {new}건")
        self.process_revisits()
        self.log(f"  통계: {self.db.counts()}")

    def run(self, tick_s: float = 1.0):
        """Continuous round-robin: 1 board per tick + revisit sweep each cycle."""
        self.log(f"Watcher 시작 — {len(self.boards)}개 보드, tick {tick_s}s, "
                 f"재방문 {self.revisit_after_s}s 후")
        cycle = itertools.cycle(self.boards)
        i = 0
        while True:
            b = next(cycle)
            try:
                total, new = self.poll_board(b)
                if new:
                    self.log(f"■ {b.cluburl}/{b.name}: 신규 {new}건 (조회 {total})")
            except Exception as e:
                self.log(f"■ {b.cluburl}/{b.name} 폴링 실패: {e}")
            i += 1
            if i % len(self.boards) == 0:   # once per full cycle
                self.process_revisits()
            time.sleep(tick_s)


def build(account: str | None, db_path: Path, config_path: Path):
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    account = account or cfg.get("account")
    sm = SessionManager(ROOT / "data" / "sessions")
    cookies = sm.load_cookies(account) if account and sm.verify(account).ok else None
    client = cafe_api.make_client(cookies)
    return cfg, Database(db_path), client

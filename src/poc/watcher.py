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
                 min_request_gap_s: float = 1.0, sheets=None, on_event=None, log=print):
        self.cfg = cfg
        self.db = db
        self.client = client
        self.per_page = per_page
        self.revisit_after_s = revisit_after_s
        self.min_gap = min_request_gap_s
        self.sheets = sheets          # SheetsBuffer | None (실시간 시트 push)
        self.on_event = on_event      # callable(kind:str, payload:dict) | None (대시보드 push)
        self.log = log
        self.boards = load_boards(cfg)
        self._cluburl = {c["club_id"]: c["cluburl"] for c in cfg["cafes"]}
        self._last_request = 0.0
        # 하드닝 상태
        self.session_ok = True
        self._errors = 0                  # 연속 오류 → 지수 백오프
        self._max_backoff = 60.0
        self._last_session_check = 0.0
        self._session_check_gap = 60.0    # 세션 체크 최소 간격(초)

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
            self._push_sheets_new(a, b, body, comments)
            self._emit("new", {
                "cafe_id": a.cafe_id, "article_id": a.article_id, "cluburl": b.cluburl,
                "board_key": b.board_key, "board_name": b.name, "menu_id": a.menu_id,
                "title": a.title, "writer": a.writer_nickname, "url": a.url,
                "read_count": a.read_count, "comment_count": len(comments),
                "like_count": a.like_count, "write_ts": a.write_ts, "is_popular": a.is_popular,
            })
        except Exception as e:
            self.log(f"  ! 본문/댓글 크롤 실패 [{a.article_id}]: {e}")

    def _emit(self, kind: str, payload: dict):
        if self.on_event:
            try:
                self.on_event(kind, payload)
            except Exception as e:
                self.log(f"  ! 이벤트 전송 실패: {e}")

    # --- 하드닝: 세션 체크 / 백오프 --------------------------------------------
    def check_session(self, force: bool = False):
        """주기적으로 로그인 유효성 확인. 상태 변화 시 대시보드에 알림."""
        if not force and (time.monotonic() - self._last_session_check) < self._session_check_gap:
            return
        self._last_session_check = time.monotonic()
        ok = cafe_api.check_login(self.client)
        if ok != self.session_ok:
            self.session_ok = ok
            if ok:
                self.log("  ✓ 세션 정상 복구")
            else:
                self.log("  ⚠ 세션 만료 감지 — 재로그인 필요 (capture 다시 실행)")
            self._emit("session", {"ok": ok})

    def _on_error(self):
        self._errors += 1
        backoff = min(self._max_backoff, self.min_gap * (2 ** self._errors))
        self.log(f"  … 오류 {self._errors}회 연속 → {backoff:.1f}s 백오프")
        time.sleep(backoff)
        # 오류가 이어지면 세션 만료일 수 있으니 확인
        if self._errors >= 3:
            self.check_session(force=True)

    def _on_success(self):
        self._errors = 0

    def _push_sheets_new(self, a, b: Board, body, comments):
        if not self.sheets:
            return
        from .sheets import SheetsSink
        self.sheets.add_article(SheetsSink.article_row({
            "first_seen_at": now_ms(), "cluburl": b.cluburl, "board_key": b.board_key,
            "menu_id": a.menu_id, "article_id": a.article_id, "title": a.title,
            "writer_nickname": a.writer_nickname, "url": a.url, "write_ts": a.write_ts,
            "first_read_count": a.read_count, "first_comment_count": a.comment_count,
            "like_count": a.like_count, "content_text": body.content_text,
        }))
        self.sheets.add_comments(SheetsSink.comment_rows(a.article_id, a.title, comments, "first"))

    # --- revisit -------------------------------------------------------------
    def process_revisits(self):
        due = self.db.due_revisits()
        for row in due:
            try:
                self._throttle()
                try:
                    body = cafe_api.fetch_article_body(row["cafe_id"], row["article_id"],
                                                       menu_id=row["menu_id"] or 0, client=self.client)
                except cafe_api.ArticleGoneError:
                    self.db.mark_deleted(row["cafe_id"], row["article_id"])
                    self.log(f"  x DELETED [{row['article_id']}] 삭제/비공개 감지")
                    self._emit("deleted", {"cafe_id": row["cafe_id"], "article_id": row["article_id"]})
                    continue
                self._throttle()
                comments = cafe_api.fetch_comments(row["cafe_id"], row["article_id"], client=self.client)
                self.db.save_comments(row["cafe_id"], row["article_id"], comments, phase="revisit")
                self.db.complete_revisit(row["cafe_id"], row["article_id"],
                                         body.read_count, body.comment_count, row["first_read_count"])
                delta = (body.read_count or 0) - (row["first_read_count"] or 0)
                self.log(f"  ~ REVISIT [{row['article_id']}] 조회 {row['first_read_count']}→{body.read_count} (+{delta})")
                if self.sheets:
                    self.sheets.update_revisit(row["article_id"], body.read_count, delta, body.comment_count)
                self._emit("revisit", {
                    "cafe_id": row["cafe_id"], "article_id": row["article_id"],
                    "second_read_count": body.read_count, "read_delta": delta,
                    "second_comment_count": body.comment_count,
                })
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
        self.check_session(force=True)      # 시작 시 1회 확인
        i = 0
        while True:
            b = next(cycle)
            try:
                total, new = self.poll_board(b)
                self._on_success()
                if new:
                    self.log(f"■ {b.cluburl}/{b.name}: 신규 {new}건 (조회 {total})")
            except Exception as e:
                self.log(f"■ {b.cluburl}/{b.name} 폴링 실패: {e}")
                self._on_error()
            i += 1
            if i % len(self.boards) == 0:   # 한 사이클마다
                self.process_revisits()
                self.check_session()
                if self.sheets:
                    self.sheets.flush()
            time.sleep(tick_s)


def build(account: str | None, db_path: Path, config_path: Path):
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    account = account or cfg.get("account")
    sm = SessionManager(ROOT / "data" / "sessions")
    cookies = sm.load_cookies(account) if account and sm.verify(account).ok else None
    client = cafe_api.make_client(cookies)
    return cfg, Database(db_path), client

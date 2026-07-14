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
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path

from . import cafe_api
from .db import Database, now_ms
from .session import SessionManager

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "targets.json"


def _cfg_mtime():
    try:
        return CONFIG_PATH.stat().st_mtime
    except OSError:
        return 0


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
        all_boards = load_boards(cfg)
        # 일반글은 연속 라운드로빈, 인기글은 하루 2회 스케줄 수집.
        self.menu_boards = [b for b in all_boards if b.kind == "menu"]
        self.popular_boards = [b for b in all_boards if b.kind == "popular"]
        self.popular_hours = (2, 16)   # 매일 02:00 / 16:00 (네이버 1시/15시 갱신 직후)
        self._cluburl = {c["club_id"]: c["cluburl"] for c in cfg["cafes"]}
        self._cafe_name = {c["club_id"]: c.get("name") or c["cluburl"] for c in cfg["cafes"]}
        self._cfg_mtime = _cfg_mtime()   # config 핫리로드 감지용
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
        live = [a for a in arts if not (a.blinded or a.is_notice)]
        for a in live:
            is_new = self.db.upsert_article_seen(a, b.board_key, self.revisit_after_s)
            if is_new:
                new_count += 1
                self._crawl_new(a, b)
        # 기존/신규 모두 현재 카운트 갱신 (인기점수 실시간 반영, 추가 크롤 없음)
        self.db.update_current_counts_bulk(live)
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
                "cafe_name": self._cafe_name.get(a.cafe_id, b.cluburl),
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

    # --- 인기글 스케줄 수집 (매일 2시/16시, 놓치면 보충) -------------------------
    def _latest_scheduled(self, now: datetime) -> datetime:
        """now 시점에서 가장 최근에 지난 예정시각(오늘 또는 어제)."""
        hours = sorted(self.popular_hours)
        today = now.date()
        past = [datetime.combine(today, dt_time(h)) for h in hours
                if datetime.combine(today, dt_time(h)) <= now]
        if past:
            return max(past)
        return datetime.combine(today - timedelta(days=1), dt_time(max(hours)))

    def maybe_collect_popular(self):
        """예정시각이 지났고 그 이후 아직 수집 안 했으면 인기글 수집(보충 포함)."""
        if not self.popular_boards:
            return
        now = datetime.now()
        sched = self._latest_scheduled(now)
        last = self.db.get_meta("last_popular_run")
        last_dt = None
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
            except ValueError:
                last_dt = None
        if last_dt is None or last_dt < sched:
            # 수집 시작 시점에 먼저 기록 → 중간에 서버가 죽어도 재시작 때
            # 인기글 수집을 처음부터 다시 하지 않음(일반글 폴링 정지 방지).
            self.db.set_meta("last_popular_run", now.isoformat())
            self.log(f"🔥 인기글 수집 시작 (예정 {sched:%m-%d %H:%M} 회차)")
            self.collect_popular()

    def collect_popular(self):
        for b in self.popular_boards:
            try:
                total, new = self.poll_board(b)
                self.log(f"🔥 {b.cluburl}/{b.name}: {total}개 인기글, 신규 {new}건")
            except Exception as e:
                self.log(f"  ! 인기글 수집 실패 {b.cluburl}: {e}")
        if self.sheets:
            self.sheets.flush()

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
        for b in self.menu_boards + self.popular_boards:
            total, new = self.poll_board(b)
            self.log(f"■ {b.cluburl}/{b.name}: {total}건 조회, 신규 {new}건")
        self.process_revisits()
        self.log(f"  통계: {self.db.counts()}")

    def reload_boards_if_changed(self) -> bool:
        """config 파일이 바뀌었으면 게시판 목록을 다시 읽어 갱신(재시작 불필요). 변경 시 True."""
        m = _cfg_mtime()
        if m == self._cfg_mtime:
            return False
        self._cfg_mtime = m
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            self.log(f"  ! config 재읽기 실패: {e}")
            return False
        all_boards = load_boards(cfg)
        new_menu = [b for b in all_boards if b.kind == "menu"]
        new_pop = [b for b in all_boards if b.kind == "popular"]
        changed = ({(b.club_id, b.menu_id) for b in new_menu} != {(b.club_id, b.menu_id) for b in self.menu_boards}
                   or len(new_pop) != len(self.popular_boards))
        self.menu_boards = new_menu
        self.popular_boards = new_pop
        self._cluburl = {c["club_id"]: c["cluburl"] for c in cfg["cafes"]}
        self._cafe_name = {c["club_id"]: c.get("name") or c["cluburl"] for c in cfg["cafes"]}
        if changed:
            self.log(f"⟳ 게시판 목록 갱신 — 일반 {len(new_menu)}개 / 인기글 {len(new_pop)}개")
        return changed

    def run(self, tick_s: float = 1.0):
        """일반글: 라운드로빈 실시간 폴링. 인기글: 하루 2회 스케줄 수집."""
        self.log(f"Watcher 시작 — 일반 {len(self.menu_boards)}개(실시간) / "
                 f"인기글 {len(self.popular_boards)}개(매일 {self.popular_hours[0]}·{self.popular_hours[1]}시), "
                 f"tick {tick_s}s, 재방문 {self.revisit_after_s}s 후")
        self.check_session(force=True)        # 시작 시 1회 확인
        self.maybe_collect_popular()          # 시작 시 놓친 인기글 회차 보충
        n = max(1, len(self.menu_boards))
        cycle = itertools.cycle(self.menu_boards) if self.menu_boards else None
        i = 0
        while True:
            if cycle is not None:
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
            if i % n == 0:                    # 한 사이클마다
                self.process_revisits()
                self.check_session()
                self.maybe_collect_popular()  # 예정시각 도래 시 인기글 수집
                if self.sheets:
                    self.sheets.flush()
                if self.reload_boards_if_changed():   # config 변경 시 게시판 갱신 + 사이클 재구성
                    cycle = itertools.cycle(self.menu_boards) if self.menu_boards else None
                    n = max(1, len(self.menu_boards))
                    i = 0
            time.sleep(tick_s)


def build(account: str | None, db_path: Path, config_path: Path):
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    account = account or cfg.get("account")
    sm = SessionManager(ROOT / "data" / "sessions")
    cookies = sm.load_cookies(account) if account and sm.verify(account).ok else None
    client = cafe_api.make_client(cookies)
    return cfg, Database(db_path), client

"""과거글 백필 — article_id를 직접 훑어 카페 아카이브를 긁는다.

스트림 워처는 '지금부터의 글'만 잡는다. 실측 일 2,400건, 연 2.6억 토큰으로는 목표(10억)에
못 미친다. 볼륨은 과거 아카이브에서 나온다. 게시글 번호가 단조 증가한다는 점을 이용해
최신 번호에서 아래로 내려가며 본문·댓글을 받는다.

기존 `네이버커페게시글 추출\\naver_cafe_crawler_gui.py`의 순차 스캔 로직을 GUI에서 떼어내
워커로 옮긴 것이다. 달라진 점:
  · 카페별 커서를 DB에 두어 중단·재개가 안전하다(GUI는 파일 기반이었다)
  · 요청은 ratelimit 공유 버킷에서 받는다. 스트림과 같은 계정을 쓰므로 합산 레이트가
    두 배가 되면 안 되고, 우선순위는 스트림에 양보한다(RESERVE_BACKFILL)
  · 최신→과거 역방향. 최근 글이 문체상 더 쓸모 있다
  · 시간 경계(기본 2년)에서 멈춘다. 오래된 글은 말투가 지금과 다르다

실행:
    python -m src.poc.backfill run --until 08:00      # 야간 창까지
    python -m src.poc.backfill run --cafe masanmam --limit 200
    python -m src.poc.backfill status
"""
from __future__ import annotations

import argparse
import datetime
import json
import threading
import time
from pathlib import Path

from . import cafe_api, ratelimit
from .db import Database, now_ms
from .paths import CONFIG_PATH, DB_PATH, prune_logs

CURSOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS backfill_cursor (
    cafe_id      INTEGER PRIMARY KEY,
    cluburl      TEXT,
    head_id      INTEGER,      -- 스캔 시작(최신) 번호
    cursor_id    INTEGER,      -- 다음에 시도할 번호 (역방향이라 감소한다)
    floor_id     INTEGER,      -- 여기까지 내려가면 종료 (0=제한 없음)
    missing      INTEGER DEFAULT 0,   -- 연속 결번
    old_streak   INTEGER DEFAULT 0,   -- 연속 '너무 오래된 글'
    collected    INTEGER DEFAULT 0,
    skipped      INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'active',   -- active | done | paused
    note         TEXT,
    updated_at   INTEGER
);
"""

DEFAULTS = {
    "max_missing": 300,        # 연속 결번 N개 → 그 카페 구간 종료
    "old_streak_stop": 20,     # 연속 '기준일 이전' N개 → 시간 경계 도달로 판정
    "years": 2,                # 몇 년치까지 내려갈지
}


# ── 커서 관리 ───────────────────────────────────────────────────────────────
def ensure_schema(db: Database) -> None:
    db.conn.executescript(CURSOR_SCHEMA)
    db.conn.commit()


def get_cursor(db: Database, cafe_id: int):
    return db.conn.execute(
        "SELECT * FROM backfill_cursor WHERE cafe_id=?", (cafe_id,)).fetchone()


def init_cursor(db: Database, cafe_id: int, cluburl: str, head_id: int,
                floor_id: int = 0) -> None:
    db.conn.execute(
        """INSERT INTO backfill_cursor
           (cafe_id, cluburl, head_id, cursor_id, floor_id, updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(cafe_id) DO UPDATE SET
             cluburl=excluded.cluburl, head_id=excluded.head_id,
             floor_id=excluded.floor_id, updated_at=excluded.updated_at""",
        (cafe_id, cluburl, head_id, head_id, floor_id, now_ms()))
    db.conn.commit()


def save_cursor(db: Database, cafe_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = now_ms()
    sets = ", ".join(f"{k}=:{k}" for k in fields)
    db.conn.execute(f"UPDATE backfill_cursor SET {sets} WHERE cafe_id=:cafe_id",
                    {**fields, "cafe_id": cafe_id})
    db.conn.commit()


def _resolve_head(db: Database, cafe_id: int, cluburl: str, client) -> int | None:
    """스캔 시작점. 이미 아는 최대 번호를 쓰고, 없으면 게시판 목록에서 받아온다."""
    row = db.conn.execute(
        "SELECT max(article_id) FROM articles WHERE cafe_id=?", (cafe_id,)).fetchone()
    known = row[0] or 0
    latest = 0
    try:
        boards = cafe_api.fetch_board_list(cafe_id, client=client)
        for b in boards[:3]:
            arts = cafe_api.fetch_article_list(cafe_id, b["menu_id"], per_page=5, client=client)
            for a in arts:
                latest = max(latest, a.article_id)
    except Exception:
        pass
    head = max(known, latest)
    return head or None


# ── 워커 ────────────────────────────────────────────────────────────────────
class Backfiller:
    def __init__(self, db: Database, client, account: str, *, log=print, **opts):
        self.db = db
        self.client = client
        self.log = log
        self.opt = {**DEFAULTS, **opts}
        self.limiter = ratelimit.get(account)
        self.stop = False
        cutoff_days = 365 * int(self.opt["years"])
        self.cutoff_ms = int((time.time() - cutoff_days * 86400) * 1000)

    def _budget(self) -> None:
        """요청 1건 분의 예산. 스트림에 양보하므로 낮에는 거의 안 돈다."""
        self.limiter.acquire(reserve=ratelimit.RESERVE_BACKFILL)

    def crawl_one(self, cafe_id: int, article_id: int, *,
                  skip_menus: set[int] | None = None, lane: str = "backfill") -> str:
        """한 건 시도. 'saved' | 'dup' | 'gone' | 'old' | 'skip' | 'error'.

        skip_menus: 이 menu_id 게시판 글은 저장하지 않고 'skip'을 돌려준다. 승격(등록형)
        게시판은 스트림 워처가 실시간+호응도로 담당하므로, frontfill이 그 글을 먼저
        낚아채(revisit_done=1로) 호응도 측정을 막지 않게 한다.
        """
        try:
            self._budget()
            body = cafe_api.fetch_article_body(cafe_id, article_id, client=self.client)
        except cafe_api.ArticleGoneError:
            return "gone"
        except Exception as e:
            msg = str(e)
            if "401" in msg:
                self.limiter.note_auth_error()
            elif "429" in msg or "403" in msg:
                self.limiter.penalize()
            return "error"

        if body.write_ts and body.write_ts < self.cutoff_ms:
            return "old"

        if skip_menus and body.menu_id in skip_menus:
            return "skip"          # 승격 게시판 — 스트림이 담당(선점 방지)

        is_new = self.db.upsert_article_from_body(body, lane=lane)
        self.db.save_body(body)          # 텍스트·material 저장 + HTML은 raw 아카이브로
        if not is_new:
            return "dup"

        try:
            if body.comment_count:
                self._budget()
                cmts = cafe_api.fetch_comments(cafe_id, body.article_id, client=self.client)
                self.db.save_comments(cafe_id, body.article_id, cmts, phase="first")
        except Exception:
            pass                          # 댓글 실패로 본문까지 버리지 않는다
        return "saved"

    def run_cafe(self, cafe_id: int, cluburl: str, *, deadline: float | None = None,
                 limit: int | None = None) -> dict:
        cur = get_cursor(self.db, cafe_id)
        if cur is None or cur["status"] == "done":
            if cur is None:
                head = _resolve_head(self.db, cafe_id, cluburl, self.client)
                if not head:
                    self.log(f"  {cluburl}: 시작 번호를 못 찾음 — 건너뜀")
                    return {"cafe": cluburl, "saved": 0, "reason": "no_head"}
                init_cursor(self.db, cafe_id, cluburl, head)
                cur = get_cursor(self.db, cafe_id)
            else:
                return {"cafe": cluburl, "saved": 0, "reason": "done"}

        aid = cur["cursor_id"]
        missing, old_streak = cur["missing"], cur["old_streak"]
        saved = skipped = 0
        reason = "limit"

        while aid > max(1, cur["floor_id"]):
            if self.stop:
                reason = "stopped"
                break
            if deadline and time.time() >= deadline:
                reason = "deadline"
                break
            if limit is not None and (saved + skipped) >= limit:
                reason = "limit"
                break

            r = self.crawl_one(cafe_id, aid)
            if r == "saved":
                saved += 1
                missing = old_streak = 0
            elif r == "dup":
                skipped += 1
                missing = old_streak = 0
            elif r == "old":
                old_streak += 1
                missing = 0
                if old_streak >= self.opt["old_streak_stop"]:
                    reason = "cutoff"
                    break
            elif r == "gone":
                missing += 1
                if missing >= self.opt["max_missing"]:
                    reason = "missing"
                    break
            else:
                skipped += 1

            aid -= 1
            if (saved + skipped) % 50 == 0 and (saved + skipped):
                save_cursor(self.db, cafe_id, cursor_id=aid, missing=missing,
                            old_streak=old_streak,
                            collected=cur["collected"] + saved, skipped=cur["skipped"] + skipped)
                self.log(f"  {cluburl}: {aid}번 진행 중 (신규 {saved} / 중복 {skipped})")

        status = "done" if reason in ("cutoff", "missing") else "active"
        save_cursor(self.db, cafe_id, cursor_id=aid, missing=missing, old_streak=old_streak,
                    collected=cur["collected"] + saved, skipped=cur["skipped"] + skipped,
                    status=status, note=reason)
        self.log(f"  {cluburl}: 신규 {saved} / 중복 {skipped} → {aid}번에서 멈춤 ({reason})")
        return {"cafe": cluburl, "saved": saved, "skipped": skipped,
                "cursor": aid, "reason": reason, "status": status}

    def run(self, cafes: list[dict], *, deadline: float | None = None,
            limit_per_cafe: int | None = None) -> list[dict]:
        out = []
        for c in cafes:
            if self.stop or (deadline and time.time() >= deadline):
                break
            try:
                out.append(self.run_cafe(c["club_id"], c["cluburl"],
                                         deadline=deadline, limit=limit_per_cafe))
            except ratelimit.Tripped as e:
                self.log(f"⛔ {e} — 백필 중단")
                break
            except Exception as e:
                self.log(f"  {c['cluburl']} 실패: {e}")
        return out


# ── CLI ─────────────────────────────────────────────────────────────────────
def _config() -> dict:
    return json.loads(Path(CONFIG_PATH).read_text(encoding="utf-8"))


def _client(account: str | None):
    from .session import SessionManager
    root = Path(__file__).resolve().parents[2]
    sm = SessionManager(root / "data" / "sessions")
    cookies = sm.load_cookies(account) if account and sm.verify(account).ok else None
    if cookies is None:
        print("⚠️  로그인 세션이 없습니다 — 비회원으로 접근 가능한 글만 수집됩니다.")
    return cafe_api.make_client(cookies)


def _deadline(until: str | None, max_hours: float | None = None) -> float | None:
    """'07:50' → 다음 07:50의 epoch. 이미 지났으면 내일.

    max_hours로 한 번 더 자른다. 스케줄대로 00:10에 돌면 07:50은 7시간 40분 뒤지만,
    사람이 낮에 손으로 돌리면 '다음 07:50'이 17시간 뒤가 되어 하루 종일 긁는다.
    그 사고를 막는 상한이다."""
    cap = time.time() + max_hours * 3600 if max_hours else None
    if not until:
        return cap
    h, m = (int(x) for x in until.split(":"))
    now = datetime.datetime.now()
    d = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if d <= now:
        d += datetime.timedelta(days=1)
    ts = d.timestamp()
    return min(ts, cap) if cap else ts


def run_multi(cafes, *, deadline=None, limit_per_cafe=None, max_missing=None,
              years=2, log=print) -> int:
    """다계정 병렬 백필: 카페를 접근가능 계정에 배정 → 계정별 스레드로 과거글 동시 수집.
    각 스레드는 자기 계정 client·rate 예산과 자기 DB 커넥션(WAL) 사용. 반환: 신규 합계."""
    from . import accountpool
    assign: dict[str, list] = {}
    for c in cafes:
        key, _ = accountpool.account_for_cafe(c["club_id"])
        if key:
            assign.setdefault(key, []).append(c)
    log("  배정: " + ", ".join(f"{k}={len(v)}" for k, v in assign.items()))
    total, tlock = [0], threading.Lock()

    def worker(key: str, clist: list):
        tdb = Database(DB_PATH)
        try:
            tdb.conn.execute("PRAGMA busy_timeout=15000")
        except Exception:
            pass
        ensure_schema(tdb)
        client = accountpool.client_for(key)
        bf = Backfiller(tdb, client, key,
                        max_missing=max_missing or DEFAULTS["max_missing"], years=years)
        # 미초기화(커서 없음) 카페 우선(frontfill과 동일 이유 — 목록 뒤쪽 신규 카페가
        # 시간상한에 밀려 영원히 시작을 못 하는 것 방지). 지금은 야간 8h라 여유 있지만
        # 카페 풀이 계속 느는 만큼 선제 조치.
        uninit = [c for c in clist if get_cursor(tdb, c["club_id"]) is None]
        rest = [c for c in clist if c not in uninit]
        for c in uninit + rest:
            if deadline and time.time() >= deadline:
                break
            try:
                r = bf.run_cafe(c["club_id"], c["cluburl"], deadline=deadline, limit=limit_per_cafe)
                with tlock:
                    total[0] += r.get("saved", 0)
            except ratelimit.Tripped as e:
                log(f"⛔ [{key}] {e}")
                break
            except Exception as e:
                log(f"  {c['cluburl']} 실패([{key}]): {e}")
        tdb.close()

    threads = [threading.Thread(target=worker, args=(k, v), daemon=True)
               for k, v in assign.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return total[0]


def cmd_run(args):
    prune_logs("backfill")
    cfg = _config()
    cafes = cfg.get("cafes", [])
    if args.cafe:
        cafes = [c for c in cafes if c["cluburl"] == args.cafe]
        if not cafes:
            raise SystemExit(f"config에 없는 카페: {args.cafe}")
    dl = _deadline(args.until, args.max_hours)
    when = f"{datetime.datetime.fromtimestamp(dl):%m-%d %H:%M}까지, " if dl else ""
    try:
        if args.account:
            # 단일 계정(명시 지정 시)
            db = Database(DB_PATH)
            ensure_schema(db)
            client = _client(args.account)
            bf = Backfiller(db, client, args.account,
                            max_missing=args.max_missing, years=args.years)
            print(f"백필(단일계정 {args.account}) — {when}{len(cafes)}개, 최근 {args.years}년치")
            res = bf.run(cafes, deadline=dl, limit_per_cafe=args.limit)
            total = sum(r.get("saved", 0) for r in res)
            client.close()
            db.close()
        else:
            # 다계정 병렬(기본)
            from . import accountpool
            n = len(accountpool.usable_accounts())
            print(f"백필(다계정 {n}개 병렬) — {when}{len(cafes)}개, 최근 {args.years}년치")
            total = run_multi(cafes, deadline=dl, limit_per_cafe=args.limit,
                              max_missing=args.max_missing, years=args.years)
            accountpool.close_all()
        print(f"\n백필 완료: 신규 {total}건")
    except KeyboardInterrupt:
        print("\n중단됨 — 커서는 저장되어 있습니다.")


def cmd_status(args):
    db = Database(DB_PATH)
    ensure_schema(db)
    rows = db.conn.execute(
        "SELECT * FROM backfill_cursor ORDER BY collected DESC").fetchall()
    if not rows:
        print("백필 커서 없음 — 아직 실행한 적이 없습니다.")
    print(f"{'카페':18} {'head':>10} {'커서':>10} {'진행':>7} {'수집':>8} {'상태':8} 사유")
    for r in rows:
        span = max(1, (r["head_id"] or 0) - (r["floor_id"] or 0))
        done = (r["head_id"] or 0) - (r["cursor_id"] or 0)
        print(f"{(r['cluburl'] or '')[:18]:18} {r['head_id'] or 0:>10,} {r['cursor_id'] or 0:>10,} "
              f"{done / span * 100:>6.1f}% {r['collected'] or 0:>8,} {r['status']:8} {r['note'] or ''}")
    print()
    for r in db.conn.execute(
            "SELECT lane, count(*) c FROM articles GROUP BY lane ORDER BY c DESC"):
        print(f"  레인 {r['lane'] or 'stream(기존)':16} {r['c']:,}건")
    db.close()


def main():
    p = argparse.ArgumentParser(prog="backfill")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="백필 실행")
    r.add_argument("--account")
    r.add_argument("--cafe", help="특정 카페만 (cluburl)")
    r.add_argument("--until", help="종료 시각 HH:MM (예: 07:50)")
    r.add_argument("--max-hours", type=float, default=8.0,
                   help="최대 실행 시간(시). --until과 함께 쓰면 둘 중 빠른 쪽")
    r.add_argument("--limit", type=int, help="카페당 시도 상한")
    r.add_argument("--max-missing", type=int, default=DEFAULTS["max_missing"])
    r.add_argument("--years", type=int, default=DEFAULTS["years"])
    r.set_defaults(func=cmd_run)
    s = sub.add_parser("status", help="커서 현황")
    s.set_defaults(func=cmd_status)
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()

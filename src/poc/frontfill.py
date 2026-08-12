"""상시 전량 신규글 포착 — crawl_all 카페의 새 글을 '헤드전진'으로 잡는다.

backfill이 '과거'를 내려간다면(head→floor), frontfill은 '지금부터의 신규'를 올라간다.
게시판을 일일이 폴링하지 않고, 카페 최신 article_id를 주기적으로 확인해
`직전에 본 id ~ 현재 최신 id` 구간만 훑는다 → **전 게시판 신규글**을 저비용으로 커버.
crawl_all 카페면 지정 게시판이 없어도 새 글이 전부 들어온다.

  과거 = backfill, 지금부터 = frontfill → 둘이 만나 '전량'이 된다.

crawl 로직은 backfill.Backfiller.crawl_one을 재사용한다(요청 예산·에러·중복처리 공유,
스트림에 양보). 커서는 자체 테이블(frontfill_cursor)에 두어 중단·재개가 안전하다.

실행:
    python -m src.poc.frontfill run                 # crawl_all 카페 1회 전진
    python -m src.poc.frontfill run --cafe masanmam --max 500
    python -m src.poc.frontfill status
"""
from __future__ import annotations

import argparse
import time

from . import accountpool, ratelimit
from .backfill import Backfiller, _client, _config, _deadline, _resolve_head
from .db import Database, now_ms
from .paths import DB_PATH, prune_logs

CURSOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS frontfill_cursor (
    cafe_id    INTEGER PRIMARY KEY,
    cluburl    TEXT,
    last_id    INTEGER,          -- 여기까지(포함) 신규 전진 완료
    collected  INTEGER DEFAULT 0,
    updated_at INTEGER,
    note       TEXT
);
"""


def ensure_schema(db: Database) -> None:
    db.conn.executescript(CURSOR_SCHEMA)
    db.conn.commit()


def get_cursor(db: Database, cafe_id: int):
    return db.conn.execute("SELECT * FROM frontfill_cursor WHERE cafe_id=?", (cafe_id,)).fetchone()


def set_cursor(db: Database, cafe_id: int, cluburl: str, last_id: int,
               collected_add: int = 0, note: str | None = None) -> None:
    db.conn.execute(
        """INSERT INTO frontfill_cursor (cafe_id, cluburl, last_id, collected, updated_at, note)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(cafe_id) DO UPDATE SET
             cluburl=excluded.cluburl, last_id=excluded.last_id,
             collected=frontfill_cursor.collected+?, updated_at=excluded.updated_at,
             note=excluded.note""",
        (cafe_id, cluburl, last_id, collected_add, now_ms(), note, collected_add))
    db.conn.commit()


def run_cafe(db: Database, bf: Backfiller, cafe: dict, *,
             deadline: float | None = None, max_ids: int | None = None, log=print) -> dict:
    cid, cluburl = cafe["club_id"], cafe["cluburl"]
    # 승격(등록형) 게시판 = 스트림이 실시간+호응도로 담당 → frontfill은 건너뛴다.
    skip = {b["menu_id"] for b in cafe.get("boards", [])
            if b.get("type") == "menu" and b.get("menu_id") is not None}
    head = _resolve_head(db, cid, cluburl, bf.client)
    if not head:
        return {"cafe": cluburl, "reason": "no_head", "saved": 0}

    cur = get_cursor(db, cid)
    if cur is None:
        # 첫 실행: 현재 헤드에 커서만 심는다(과거는 backfill 담당, 중복 크롤 방지).
        set_cursor(db, cid, cluburl, head, note="init")
        return {"cafe": cluburl, "reason": "init", "head": head, "saved": 0}

    start = (cur["last_id"] or 0) + 1
    if head < start:
        return {"cafe": cluburl, "reason": "nonew", "saved": 0}
    end = min(head, start + max_ids - 1) if max_ids else head

    saved, aid, reason = 0, start, "caught_up"
    while aid <= end:
        if bf.stop:
            reason = "stopped"; break
        if deadline and time.time() >= deadline:
            reason = "deadline"; break
        r = bf.crawl_one(cid, aid, skip_menus=skip, lane="frontfill")
        if r == "saved":
            saved += 1
        aid += 1
        if (aid - start) % 50 == 0:                 # 진행 저장(collected는 끝에 한 번만 가산)
            set_cursor(db, cid, cluburl, aid - 1, collected_add=0, note="run")
    last = aid - 1 if aid - 1 >= start else cur["last_id"]
    set_cursor(db, cid, cluburl, last, collected_add=saved, note=reason)
    return {"cafe": cluburl, "saved": saved, "from": start, "to": end, "reason": reason}


def run(db: Database, bf: Backfiller, cafes: list[dict], *,
        deadline: float | None = None, max_ids: int | None = None, log=print) -> list[dict]:
    out = []
    for cafe in cafes:
        if deadline and time.time() >= deadline:
            break
        try:
            res = run_cafe(db, bf, cafe, deadline=deadline, max_ids=max_ids, log=log)
        except ratelimit.Tripped as e:
            log(f"⛔ {e} — frontfill 중단")
            break
        except Exception as e:
            log(f"  {cafe['cluburl']} 실패: {e}")
            continue
        out.append(res)
        log(f"  {cafe['cluburl']}: {res.get('reason')} 신규 {res.get('saved', 0)} "
            f"({res.get('from', '-')}~{res.get('to', '-')})")
    return out


def run_multi(db: Database, cafes: list[dict], *, deadline: float | None = None,
              max_ids: int | None = None, log=print) -> list[dict]:
    """다계정 분산: 카페마다 '접근 가능한(회원/공개) 계정'을 배정해 그 계정으로 전진.
    접근 가능 계정이 없으면 가입필요로 건너뛴다."""
    out, join_needed = [], []
    for cafe in cafes:
        if deadline and time.time() >= deadline:
            break
        key, client = accountpool.account_for_cafe(cafe["club_id"])
        if not key:
            join_needed.append(cafe["cluburl"])
            log(f"  🔒 {cafe['cluburl']}: 접근 가능 계정 없음 → 가입필요")
            continue
        bf = Backfiller(db, client, key)          # 계정별 rate 예산
        try:
            res = run_cafe(db, bf, cafe, deadline=deadline, max_ids=max_ids, log=log)
        except ratelimit.Tripped as e:
            log(f"⛔ [{key}] {e}")
            continue
        except Exception as e:
            log(f"  {cafe['cluburl']} 실패([{key}]): {e}")
            continue
        res["account"] = key
        out.append(res)
        log(f"  {cafe['cluburl']} [{key}]: {res.get('reason')} 신규 {res.get('saved', 0)}")
    if join_needed:
        log(f"  가입필요 {len(join_needed)}개: {', '.join(join_needed[:12])}")
    return out


# ── crawl_all 카페 목록 ──────────────────────────────────────────────────────
def crawl_all_cafes(cfg: dict, only: str | None = None) -> list[dict]:
    """통째 수집 대상. **기본은 모든 카페**(전 게시판 저장 = 학습 base).
    특정 카페만 빼려면 config에서 그 카페에 crawl_all:false 를 준다."""
    cafes = [c for c in cfg.get("cafes", []) if c.get("crawl_all", True)]
    if only:
        cafes = [c for c in cafes if c["cluburl"] == only]
    return cafes


# ── CLI ─────────────────────────────────────────────────────────────────────
def cmd_run(args):
    prune_logs("frontfill")
    cfg = _config()
    cafes = crawl_all_cafes(cfg, args.cafe)
    if not cafes:
        print("통째 대상 카페가 없습니다.")
        return
    db = Database(DB_PATH)
    ensure_schema(db)
    dl = _deadline(args.until, args.max_hours)
    client = None
    try:
        if args.account:
            # 단일 계정(명시 지정 시)
            client = _client(args.account)
            bf = Backfiller(db, client, args.account)
            print(f"frontfill(단일계정 {args.account}) — {len(cafes)}개 카페"
                  + (f", {args.max}건/카페 상한" if args.max else ""))
            res = run(db, bf, cafes, deadline=dl, max_ids=args.max)
        else:
            # 다계정 분산(기본): 카페별 회원 계정 배정
            n = len(accountpool.usable_accounts())
            print(f"frontfill(다계정 {n}개 분산) — {len(cafes)}개 카페"
                  + (f", {args.max}건/카페 상한" if args.max else ""))
            res = run_multi(db, cafes, deadline=dl, max_ids=args.max)
        print(f"\n완료: 신규 {sum(r.get('saved', 0) for r in res)}건")
    except KeyboardInterrupt:
        print("\n중단됨 — 커서는 저장되어 있습니다.")
    finally:
        if client:
            client.close()
        accountpool.close_all()
        db.close()


def cmd_status(args):
    db = Database(DB_PATH)
    ensure_schema(db)
    rows = db.conn.execute("SELECT * FROM frontfill_cursor ORDER BY updated_at DESC").fetchall()
    if not rows:
        print("frontfill 커서 없음 — 아직 실행한 적이 없습니다.")
    print(f"{'카페':20} {'last_id':>11} {'수집':>9}  사유")
    for r in rows:
        print(f"{(r['cluburl'] or '')[:20]:20} {r['last_id'] or 0:>11,} {r['collected'] or 0:>9,}  {r['note'] or ''}")
    db.close()


def main():
    p = argparse.ArgumentParser(prog="frontfill")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="crawl_all 카페 신규글 전진")
    r.add_argument("--account")
    r.add_argument("--cafe", help="특정 카페만 (cluburl)")
    r.add_argument("--until", help="종료 시각 HH:MM")
    r.add_argument("--max-hours", type=float, default=1.0, help="최대 실행 시간(시)")
    r.add_argument("--max", type=int, help="카페당 id 스캔 상한")
    r.set_defaults(func=cmd_run)
    s = sub.add_parser("status", help="커서 현황")
    s.set_defaults(func=cmd_status)
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()

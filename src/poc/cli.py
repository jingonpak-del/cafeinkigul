"""PoC CLI — verify the core assumption of the 인기글 tracker:
single-account session can read a board's latest articles over lightweight HTTP.

Usage (run from the project root, C:\\Users\\USER\\인기글):

    python -m src.poc.cli resolve   --cafe memberupup3
    python -m src.poc.cli fetch     --cafe memberupup3 --menu 1 --n 30
    python -m src.poc.cli capture   --account NAVER_ID
    python -m src.poc.cli verify    --account NAVER_ID
    python -m src.poc.cli fetch     --cafe memberupup3 --menu 1 --account NAVER_ID   # authenticated
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from . import cafe_api
from .session import SessionManager

ROOT = Path(__file__).resolve().parents[2]
SESSION_DIR = ROOT / "data" / "sessions"
CONFIG_PATH = ROOT / "config" / "targets.json"


def _fmt_ts(ms: int) -> str:
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000).strftime("%m-%d %H:%M")


def cmd_resolve(args):
    print(cafe_api.resolve_club_id(args.cafe))


def cmd_capture(args):
    path = SessionManager(SESSION_DIR).capture(args.account)
    print(f"세션 저장됨: {path}")


def cmd_verify(args):
    res = SessionManager(SESSION_DIR).verify(args.account)
    print(("OK  " if res.ok else "FAIL ") + res.reason)


def cmd_fetch(args):
    cookies = None
    if args.account:
        sm = SessionManager(SESSION_DIR)
        v = sm.verify(args.account)
        if not v.ok:
            print(f"[경고] 세션 검증 실패: {v.reason} (비로그인으로 시도)")
        else:
            cookies = sm.load_cookies(args.account)

    client = cafe_api.make_client(cookies)
    try:
        club_id = args.club or cafe_api.resolve_club_id(args.cafe, client=client)
        tag = ("  [인증]" if cookies else "  [비로그인]")
        if args.popular:
            print(f"clubId={club_id}  인기글  perPage={args.n}{tag}")
            arts = cafe_api.fetch_popular_list(club_id, per_page=args.n, client=client)
        else:
            print(f"clubId={club_id}  menu={args.menu}  perPage={args.n}{tag}")
            arts = cafe_api.fetch_article_list(club_id, menu_id=args.menu, per_page=args.n, client=client)
        _print_table(arts)
        print(f"\n총 {len(arts)}건")
    finally:
        client.close()


def _print_table(arts):
    print(f"{'articleId':>9}  {'조회':>5} {'댓글':>4} {'추천':>4}  {'작성':>11}  인기 제목")
    for a in arts:
        flag = "★" if a.is_popular else " "
        print(f"{a.article_id:>9}  {a.read_count:>5} {a.comment_count:>4} "
              f"{a.like_count:>4}  {_fmt_ts(a.write_ts):>11}   {flag} {a.title[:38]}")


def cmd_track(args):
    """Read config/targets.json and fetch every configured board once
    (the seed of the real-time Watcher)."""
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sm = SessionManager(SESSION_DIR)
    account = cfg.get("account")
    cookies = sm.load_cookies(account) if account and sm.verify(account).ok else None
    client = cafe_api.make_client(cookies)
    try:
        for cafe in cfg["cafes"]:
            club_id = cafe.get("club_id") or cafe_api.resolve_club_id(cafe["cluburl"], client=client)
            for b in cafe["boards"]:
                label = f"{cafe['cluburl']} / {b.get('name','')}"
                try:
                    if b["type"] == "popular":
                        arts = cafe_api.fetch_popular_list(club_id, per_page=args.n, client=client)
                    else:
                        arts = cafe_api.fetch_article_list(club_id, menu_id=b["menu_id"], per_page=args.n, client=client)
                    print(f"\n■ {label}  ({len(arts)}건)")
                    _print_table(arts)
                except Exception as e:
                    print(f"\n■ {label}  → 실패: {e}")
    finally:
        client.close()


DB_PATH = ROOT / "data" / "tracker.db"


def cmd_sweep(args):
    from . import watcher
    cfg, db, client = watcher.build(args.account, DB_PATH, CONFIG_PATH)
    try:
        w = watcher.Watcher(cfg, db, client, per_page=args.n, revisit_after_s=args.revisit_after)
        w.sweep_once()
    finally:
        client.close(); db.close()


def cmd_watch(args):
    from . import watcher
    cfg, db, client = watcher.build(args.account, DB_PATH, CONFIG_PATH)
    try:
        w = watcher.Watcher(cfg, db, client, per_page=args.n, revisit_after_s=args.revisit_after,
                            min_request_gap_s=args.gap)
        w.run(tick_s=args.tick)
    except KeyboardInterrupt:
        print("\n중단됨")
    finally:
        client.close(); db.close()


def cmd_stats(args):
    from .db import Database
    db = Database(DB_PATH)
    print(db.counts())
    db.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="ingigeul-poc")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("resolve"); sp.add_argument("--cafe", required=True); sp.set_defaults(func=cmd_resolve)
    sp = sub.add_parser("capture"); sp.add_argument("--account", required=True); sp.set_defaults(func=cmd_capture)
    sp = sub.add_parser("verify");  sp.add_argument("--account", required=True); sp.set_defaults(func=cmd_verify)
    sp = sub.add_parser("fetch")
    sp.add_argument("--cafe"); sp.add_argument("--club", type=int)
    sp.add_argument("--menu", type=int, default=0); sp.add_argument("--n", type=int, default=30)
    sp.add_argument("--popular", action="store_true", help="인기글 보드 조회")
    sp.add_argument("--account")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("track", help="config/targets.json의 모든 보드를 1회 조회")
    sp.add_argument("--n", type=int, default=15)
    sp.set_defaults(func=cmd_track)

    sp = sub.add_parser("sweep", help="전체 보드 1회 폴링+크롤 (DB 적재)")
    sp.add_argument("--account"); sp.add_argument("--n", type=int, default=30)
    sp.add_argument("--revisit-after", dest="revisit_after", type=int, default=4 * 3600)
    sp.set_defaults(func=cmd_sweep)

    sp = sub.add_parser("watch", help="실시간 라운드로빈 폴링 (계속 실행)")
    sp.add_argument("--account"); sp.add_argument("--n", type=int, default=30)
    sp.add_argument("--tick", type=float, default=1.0)
    sp.add_argument("--gap", type=float, default=1.0, help="요청 간 최소 간격(초)")
    sp.add_argument("--revisit-after", dest="revisit_after", type=int, default=4 * 3600)
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("stats", help="DB 적재 현황")
    sp.set_defaults(func=cmd_stats)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

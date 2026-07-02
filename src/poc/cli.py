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
    buf = None
    if not args.no_sheets:
        s = cfg.get("sheets", {})
        sid = s.get("spreadsheet_id")
        if sid:
            from .sheets import SheetsSink, SheetsBuffer
            sink = SheetsSink(s["credentials_path"], spreadsheet_id=sid)
            buf = SheetsBuffer(sink)
            print(f"실시간 시트 push 활성화 → {sink.url}")
        else:
            print("[알림] config에 sheets.spreadsheet_id 없음 → 시트 push 비활성 (DB만 적재)")
    try:
        w = watcher.Watcher(cfg, db, client, per_page=args.n, revisit_after_s=args.revisit_after,
                            min_request_gap_s=args.gap, sheets=buf)
        w.run(tick_s=args.tick)
    except KeyboardInterrupt:
        print("\n중단됨")
    finally:
        if buf:
            buf.flush()
        client.close(); db.close()


def cmd_export_sheets(args):
    """DB에 쌓인 글/댓글을 구글시트로 적재."""
    from .db import Database
    from .sheets import SheetsSink, COMMENT_HEADER
    from datetime import datetime

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    s = cfg["sheets"]
    sid = args.sheet or s.get("spreadsheet_id")
    if not sid:
        print("스프레드시트 ID가 없습니다. config의 sheets.spreadsheet_id를 채우거나 --sheet 로 지정하세요.")
        print("→ 시트를 만들고 다음 계정을 '편집자'로 공유하세요:", s.get("service_account_email"))
        return
    cluburl = {c["club_id"]: c["cluburl"] for c in cfg["cafes"]}
    sink = SheetsSink(s["credentials_path"], spreadsheet_id=sid)
    db = Database(DB_PATH)
    try:
        arts = db.all_articles_with_boards()
        a_rows, c_rows = [], []
        for a in arts:
            url = f"https://cafe.naver.com/ca-fe/cafes/{a['cafe_id']}/articles/{a['article_id']}"
            a_rows.append(sink.article_row({
                "first_seen_at": a["first_seen_at"], "cluburl": cluburl.get(a["cafe_id"], a["cafe_id"]),
                "board_key": a["board_keys"] or "", "menu_id": a["menu_id"], "article_id": a["article_id"],
                "title": a["title"], "writer_nickname": a["writer_nickname"], "url": url,
                "write_ts": a["write_ts"], "first_read_count": a["first_read_count"],
                "first_comment_count": a["first_comment_count"], "like_count": a["like_count"],
                "second_read_count": a["second_read_count"], "read_delta": a["read_delta"],
                "second_comment_count": a["second_comment_count"], "content_text": a["content_text"],
            }))
            for c in db.comments_for(a["cafe_id"], a["article_id"]):
                c_rows.append([a["article_id"], a["title"], c["comment_id"], c["writer_nickname"],
                               c["content"], datetime.fromtimestamp((c["update_ts"] or 0)/1000).strftime("%Y-%m-%d %H:%M:%S") if c["update_ts"] else "",
                               "Y" if c["is_reply"] else "", c["phase"]])
        sink.append_articles(a_rows)
        sink.append_comments(c_rows)
        print(f"적재 완료: 글 {len(a_rows)}행, 댓글 {len(c_rows)}행")
        print("시트:", sink.url)
    finally:
        db.close()


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
    sp.add_argument("--no-sheets", action="store_true", help="구글시트 실시간 push 끄기")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("export-sheets", help="DB의 글/댓글을 구글시트로 적재")
    sp.add_argument("--sheet", help="스프레드시트 ID (없으면 config 사용)")
    sp.set_defaults(func=cmd_export_sheets)

    sp = sub.add_parser("stats", help="DB 적재 현황")
    sp.set_defaults(func=cmd_stats)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

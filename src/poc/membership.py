"""계정↔카페 가입상태 관리 (다계정 크롤의 토대).

다계정으로 크롤을 분산하되, '가입해야 보이는' 카페는 **크롤할 계정마다 그 카페 회원**이어야
한다. 이 모듈은 `(account_key, club_id, status)`를 기록하고, 카페별로 '크롤 가능한 계정'을
돌려준다. 판정은 그 계정 세션으로 인기글/게시판을 실제로 열어 접근 가능 여부로 한다
(공개 카페는 비회원도 접근되므로 'member'=크롤가능 으로 본다).

자동 가입은 하지 않는다(CAPTCHA·약관). 가입은 사람(또는 가입 자동화 fork)이 하고,
여기서는 확인·기록만 한다.

DB 스키마는 fork가 바꾸는 db.py와 충돌하지 않도록 이 모듈이 독립적으로 소유한다.

실행:
    python -m src.poc.membership scan            # 등록 카페 × 전 계정 확인
    python -m src.poc.membership scan --cafe masanmam
    python -m src.poc.membership need-join        # 회원 계정 없는 카페(가입 필요)
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from . import cafe_api, idstore
from .paths import DB_PATH, CONFIG_PATH

DDL = """
CREATE TABLE IF NOT EXISTS account_membership (
    account_key TEXT NOT NULL,
    club_id     INTEGER NOT NULL,
    status      TEXT DEFAULT 'unknown',   -- member(크롤가능) | not_member | unknown
    checked_at  INTEGER,
    PRIMARY KEY (account_key, club_id)
);
"""


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("PRAGMA busy_timeout=10000")
    c.executescript(DDL)
    return c


# ── 저장/조회 ────────────────────────────────────────────────────────────────
def set_membership(account_key: str, club_id: int, status: str):
    c = _conn()
    try:
        c.execute(
            """INSERT INTO account_membership (account_key, club_id, status, checked_at)
               VALUES (?,?,?,?)
               ON CONFLICT(account_key, club_id) DO UPDATE SET
                 status=excluded.status, checked_at=excluded.checked_at""",
            (account_key, club_id, status, int(time.time() * 1000)))
        c.commit()
    finally:
        c.close()


def get_membership(account_key: str, club_id: int) -> str:
    c = _conn()
    try:
        r = c.execute("SELECT status FROM account_membership WHERE account_key=? AND club_id=?",
                      (account_key, club_id)).fetchone()
        return r[0] if r else "unknown"
    finally:
        c.close()


def member_accounts(club_id: int) -> list[str]:
    """이 카페를 크롤할 수 있는(=member로 확인된) 계정 키 목록."""
    c = _conn()
    try:
        return [r[0] for r in c.execute(
            "SELECT account_key FROM account_membership WHERE club_id=? AND status='member'",
            (club_id,)).fetchall()]
    finally:
        c.close()


# ── 접근성 판정 ──────────────────────────────────────────────────────────────
def check_membership(club_id: int, client) -> str:
    """주어진 계정 client로 카페 접근 시도 → 'member'(크롤가능) | 'not_member'.
    인기글이 막혀도 일반 게시판이 열리면 크롤 가능으로 본다."""
    try:
        cafe_api.fetch_popular_list(club_id, per_page=3, client=client)
        return "member"
    except Exception:
        pass
    try:
        boards = cafe_api.fetch_board_list(club_id, client=client)
        if boards:
            cafe_api.fetch_article_list(club_id, boards[0]["menu_id"], per_page=3, client=client)
            return "member"
    except Exception:
        pass
    return "not_member"


# ── 스캔 ─────────────────────────────────────────────────────────────────────
def _cafes(club_ids=None) -> list[dict]:
    cfg = json.loads(Path(CONFIG_PATH).read_text(encoding="utf-8"))
    cafes = cfg.get("cafes", [])
    if club_ids:
        ids = set(club_ids)
        cafes = [c for c in cafes if c["club_id"] in ids]
    return cafes


def scan(club_ids=None, *, log=print) -> dict[int, list[str]]:
    """등록 카페 × 전 계정의 접근 상태를 확인·기록.
    반환: {club_id: [member account_keys]}. 회원 계정 0 = 가입 필요."""
    cafes = _cafes(club_ids)
    accounts = idstore.list_accounts()
    if not accounts:
        log("⚠ 아이디관리에 계정이 없습니다 (idstore).")
        return {}
    log(f"계정 {len(accounts)}개 × 카페 {len(cafes)}개 확인")
    result: dict[int, list[str]] = {}
    for cafe in cafes:
        cid = cafe["club_id"]
        members: list[str] = []
        for acct in accounts:
            cookies = idstore.load_cookies(acct)
            if not idstore.has_login_cookies(cookies):
                set_membership(acct.key, cid, "unknown")
                continue
            client = cafe_api.make_client(cookies)
            try:
                st = check_membership(cid, client)
            finally:
                client.close()
            set_membership(acct.key, cid, st)
            if st == "member":
                members.append(acct.key)
        result[cid] = members
        flag = f"회원계정 {len(members)}/{len(accounts)}" + ("" if members else "  ⚠ 가입 필요")
        log(f"  {(cafe.get('name') or cafe['cluburl'])[:22]:22} {flag}")
    return result


def cafes_needing_join(*, log=print) -> list[dict]:
    """등록 카페 중 회원 계정이 하나도 없는 것(가입시켜야 크롤 가능)."""
    out = []
    for cafe in _cafes():
        if not member_accounts(cafe["club_id"]):
            out.append(cafe)
            log(f"  🔒 {(cafe.get('name') or cafe['cluburl'])[:22]:22} ({cafe['cluburl']}) — 회원 계정 없음")
    if not out:
        log("  ✓ 모든 등록 카페에 회원 계정이 있습니다.")
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────
def main():
    import argparse
    p = argparse.ArgumentParser(prog="membership")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="계정×카페 접근 확인")
    s.add_argument("--cafe", help="cluburl 하나만")
    sub.add_parser("need-join", help="회원 계정 없는 카페 목록")
    a = p.parse_args()
    if a.cmd == "scan":
        ids = None
        if a.cafe:
            cfg = json.loads(Path(CONFIG_PATH).read_text(encoding="utf-8"))
            ids = [c["club_id"] for c in cfg.get("cafes", []) if c["cluburl"] == a.cafe]
        scan(ids)
    elif a.cmd == "need-join":
        cafes_needing_join()


if __name__ == "__main__":
    main()

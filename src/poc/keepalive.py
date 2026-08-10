"""유휴 계정 세션 유지 잡.

왜 필요한가 — 지금은 등록된 계정이 전부 크롤링에 쓰여서 세션이 저절로 굴러간다.
계정이 50개 규모가 되면 한 달 내내 한 번도 안 쓰이는 계정이 생기고, 그건 만료돼 죽는다.
죽은 계정은 사람이 브라우저를 띄워 다시 로그인해야만 살아나므로, 계정 수에 비례해
수작업이 늘어난다. 그걸 막는 게 이 잡이다.

근거(실측) — 네이버는 인증 요청을 받으면 NID_AUT 만료를 다시 +30일로 밀어준다.
2026-08-04로 만료된 세션이 요청 1건 뒤 2026-09-07이 됐다. 브라우저를 띄울 필요도,
재로그인도 필요 없다. 가벼운 열람 요청 몇 건이면 세션이 계속 산다.

설계 원칙:
  - **핑만 찍지 않는다.** 매주 정확히 1회, API 1건만 때리는 계정은 그 자체가 패턴이다.
    카페 홈 → 게시판 목록 순으로 사람이 잠깐 둘러본 것처럼 몇 건을 흩어서 보낸다.
  - **요청 예산은 기존 토큰버킷을 쓴다.** 스트림 크롤링을 밀어내지 않도록 가장 낮은
    우선순위(RESERVE_BACKFILL)로 가져온다.
  - **실패는 조용히 대기함으로.** 죽은 세션은 여기서 살릴 수 없다(재로그인은 사람 몫).
    막지 말고 기록만 남긴다.
"""
from __future__ import annotations

import argparse
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import cafe_api, idstore, ratelimit
from .db import Database
from .paths import DB_PATH
from .session import SessionManager, auth_expiry, days_left

ROOT = Path(__file__).resolve().parents[2]
CRAWLER_SESSIONS = ROOT / "data" / "sessions"

# 이 안에 쓰인 계정은 크롤링이 이미 세션을 굴리고 있으므로 건드리지 않는다.
FRESH_DAYS = 7.0
# 만료가 이 안쪽이면 사용 여부와 무관하게 살린다.
EXPIRY_URGENT_DAYS = 10.0
# 둘러보기용 카페(공개 게시판). 계정마다 다른 곳을 보게 섞는다.
BROWSE_POOL = [
    (14793916, 87), (10298136, 25), (12730407, 0), (10094499, 0), (11262350, 68),
]


def fmt_days(days: float | None) -> str:
    if days is None:
        return "만료정보 없음"
    if days < 0:
        return f"만료 {-days:.1f}일 지남"
    return f"D-{days:.1f}"


@dataclass
class Result:
    key: str
    naver_id: str
    action: str                 # skipped | refreshed | dead | no_session
    detail: str = ""
    days_before: float | None = None
    days_after: float | None = None


@dataclass
class KeepAlive:
    sm: SessionManager
    db: Database
    log: object = print
    dry_run: bool = False
    results: list[Result] = field(default_factory=list)

    # --- 상태 기록 (마지막 핑 시각) -------------------------------------------
    def _last_ping(self, key: str) -> float | None:
        v = self.db.get_meta(f"keepalive:{key}")
        try:
            return float(v) if v else None
        except (TypeError, ValueError):
            return None

    def _mark_ping(self, key: str):
        if not self.dry_run:
            self.db.set_meta(f"keepalive:{key}", str(time.time()))

    # --- 대상 판정 -------------------------------------------------------------
    def needs_ping(self, cookies: list[dict], key: str) -> tuple[bool, str]:
        exp = auth_expiry(cookies)
        days = None if exp is None else (exp - time.time()) / 86400.0
        last = self._last_ping(key)
        since_ping = None if last is None else (time.time() - last) / 86400.0

        if days is not None and days <= EXPIRY_URGENT_DAYS:
            return True, f"만료 임박({fmt_days(days)})"
        if since_ping is None:
            return True, "핑 이력 없음"
        if since_ping >= FRESH_DAYS:
            return True, f"{since_ping:.1f}일 미접속"
        return False, f"{since_ping:.1f}일 전 확인됨"

    # --- 한 계정 살리기 ---------------------------------------------------------
    def touch(self, acct, cookies: list[dict]) -> Result:
        before = days_left(cookies)
        limiter = ratelimit.get(acct.naver_id or acct.key)
        client = cafe_api.make_client(cookies)
        try:
            limiter.acquire(reserve=ratelimit.RESERVE_BACKFILL)
            if not cafe_api.check_login(client):
                return Result(acct.key, acct.naver_id, "dead",
                              "로그인 만료 — 재로그인 필요", before, None)
            # 사람이 잠깐 둘러본 것처럼 2~3건을 흩어서. 실패해도 세션 유지엔 지장 없다.
            for club_id, menu_id in random.sample(BROWSE_POOL, k=min(2, len(BROWSE_POOL))):
                time.sleep(random.uniform(1.5, 4.0))
                limiter.acquire(reserve=ratelimit.RESERVE_BACKFILL)
                try:
                    if menu_id:
                        cafe_api.fetch_article_list(club_id, menu_id=menu_id, per_page=10, client=client)
                    else:
                        cafe_api.fetch_board_list(club_id, client=client)
                except Exception:
                    pass        # 가입 안 된 카페 등 — 세션 유지가 목적이라 무시
            fresh = cafe_api.dump_cookies(client)
            # 네이버가 이번 요청에 새 만료를 안 실어줬으면 기존 만료가 그대로 유효하다.
            # (persist()의 _merge_expiry가 파일에 그렇게 남긴다 — 표시도 그에 맞춘다)
            after = days_left(fresh)
            if after is None:
                after = before
            if not self.dry_run:
                self._persist(acct, client)
            self._mark_ping(acct.key)
            return Result(acct.key, acct.naver_id, "refreshed", "정상", before, after)
        except ratelimit.Tripped as e:
            return Result(acct.key, acct.naver_id, "dead", f"레이트 서킷 차단: {e}", before, None)
        except Exception as e:
            return Result(acct.key, acct.naver_id, "dead", f"오류: {e}", before, None)
        finally:
            client.close()

    def _persist(self, acct, client):
        """갱신된 쿠키를 크롤러 세션 저장소에 남긴다.

        아이디관리 쪽 storageState는 건드리지 않는다 — 그쪽은 브라우저가 소유자다.
        크롤러가 읽는 사본만 최신으로 유지한다.
        """
        try:
            self.sm.persist(acct.naver_id or acct.key, client)
        except Exception as e:
            self.log(f"    ! 세션 저장 실패 {acct.key}: {e}")

    # --- 전체 실행 -------------------------------------------------------------
    def _all_accounts(self) -> list[tuple[idstore.Account, list[dict] | None]]:
        """아이디관리 계정 + 크롤러 저장소에만 있는 계정.

        크롤러 쪽에 아이디관리를 안 거치고 캡처된 세션이 남아 있다(`내네이버아이디`).
        그것도 유지 대상이다 — 오히려 지금 실제로 크롤링을 돌리는 세션이라 더 중요하다.
        계정 레지스트리를 아이디관리로 합치기 전까지는 양쪽을 다 본다.
        """
        pairs: list[tuple[idstore.Account, list[dict] | None]] = []
        seen: set[str] = set()
        for a in idstore.list_accounts():
            pairs.append((a, idstore.load_cookies(a)))
            seen.add((a.naver_id or a.key).lower())
        for rec in self.sm.store.list_records():
            aid = rec.account_id
            if aid.lower() in seen:
                continue
            seen.add(aid.lower())
            pairs.append((idstore.Account(key=aid, naver_id=aid, memo="크롤러 저장소",
                                          source="crawler"), rec.cookies))
        return pairs

    def run(self, only: str | None = None) -> list[Result]:
        accounts = self._all_accounts()
        if only:
            accounts = [p for p in accounts if p[0].key.upper() == only.upper()]
        if not accounts:
            self.log("등록된 계정이 없습니다.")
            return []
        self.log(f"세션 유지 점검 — 계정 {len(accounts)}개"
                 + (" (드라이런)" if self.dry_run else ""))
        for acct, cookies in accounts:
            if not idstore.has_login_cookies(cookies):
                r = Result(acct.key, acct.naver_id, "no_session",
                           "로그인 쿠키 없음 — 최초 로그인 필요")
                self.results.append(r)
                self.log(f"  · {acct.key:<16} 세션없음 — 최초 로그인 필요")
                continue
            need, why = self.needs_ping(cookies, acct.key)
            if not need:
                r = Result(acct.key, acct.naver_id, "skipped", why,
                           days_left(cookies), None)
                self.results.append(r)
                self.log(f"  · {acct.key:<16} 건너뜀 ({why})")
                continue
            self.log(f"  → {acct.key:<16} 갱신 시도 ({why})")
            r = self.touch(acct, cookies)
            self.results.append(r)
            if r.action == "refreshed":
                self.log(f"    ✓ 세션 유효 — {fmt_days(r.days_before)} → {fmt_days(r.days_after)}")
            else:
                self.log(f"    ✗ {r.detail}")
        return self.results

    def summary(self) -> str:
        by = {}
        for r in self.results:
            by[r.action] = by.get(r.action, 0) + 1
        parts = [f"{k} {v}" for k, v in sorted(by.items())]
        dead = [r for r in self.results if r.action in ("dead", "no_session")]
        s = "세션 유지 결과 — " + ", ".join(parts)
        if dead:
            s += "\n재로그인 필요: " + ", ".join(f"{r.key}({r.detail})" for r in dead)
        return s


def main(argv=None):
    p = argparse.ArgumentParser(description="유휴 계정 네이버 세션 유지")
    p.add_argument("--account", help="특정 계정만 (아이디관리 key)")
    p.add_argument("--dry-run", action="store_true", help="요청은 보내되 저장은 안 함")
    args = p.parse_args(argv)

    db = Database(DB_PATH)
    try:
        ka = KeepAlive(sm=SessionManager(CRAWLER_SESSIONS), db=db, dry_run=args.dry_run)
        ka.run(only=args.account)
        print()
        print(ka.summary())
    finally:
        db.close()


if __name__ == "__main__":
    main()

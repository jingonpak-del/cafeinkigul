"""다계정 풀 — 아이디관리(idstore) 로그인 계정을 카페 크롤에 배분한다.

원칙:
  · 각 카페는 '접근 가능한(member/공개) 계정'에만 배정 → 가입 안 된 카페에 헛요청 안 함.
  · 회원여부는 membership 테이블에 캐시. 모르면 실제 접근을 시도해 판정(lazy) 후 저장.
  · 부하는 계정별 라운드로빈으로 분산 → 밴·레이트 회피(ratelimit이 계정별 예산).

idstore(아이디관리 Playwright 세션) 쿠키를 cafe_api 클라이언트로 바로 만든다.
크롤 잡(frontfill/backfill)이 카페별로 account_for_cafe()로 계정을 받아 쓴다.
"""
import json
from pathlib import Path

from . import cafe_api, idstore, membership

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "targets.json"
_client_cache: dict[str, object] = {}
_acct_cache = None
_rr: dict[int, int] = {}          # club_id -> 라운드로빈 인덱스


def _configured_keys() -> set[str]:
    """config.crawl_accounts — 크롤에 쓸 계정(키/네이버ID, 대문자). 없으면 빈 set(전체 허용)."""
    try:
        cfg = json.loads(_CONFIG.read_text(encoding="utf-8"))
        return {str(k).strip().upper() for k in cfg.get("crawl_accounts", []) if str(k).strip()}
    except Exception:
        return set()


def usable_accounts() -> list:
    """크롤 가능 계정 = 로그인 유지 + (config.crawl_accounts 지정 시 그 계정만)."""
    global _acct_cache
    if _acct_cache is None:
        allowed = _configured_keys()
        out = []
        for a in idstore.list_accounts():
            if not idstore.has_login_cookies(idstore.load_cookies(a)):
                continue
            if allowed and a.key.upper() not in allowed and (a.naver_id or "").upper() not in allowed:
                continue
            out.append(a)
        _acct_cache = out
    return _acct_cache


def client_for(key: str):
    """계정 키 → cafe_api 클라이언트(캐시). 없으면 None."""
    if key not in _client_cache:
        acct = next((a for a in usable_accounts() if a.key == key), None)
        if acct is None:
            return None
        _client_cache[key] = cafe_api.make_client(idstore.load_cookies(acct))
    return _client_cache[key]


def can_access(key: str, club_id: int) -> bool:
    """이 계정이 이 카페를 크롤할 수 있는가. 캐시 우선, 모르면 실제 접근 판정 후 저장."""
    st = membership.get_membership(key, club_id)
    if st in ("member", "not_member"):
        return st == "member"
    cl = client_for(key)
    if cl is None:
        return False
    st = membership.check_membership(club_id, cl)      # 인기글/게시판 접근 시도
    membership.set_membership(key, club_id, st)
    return st == "member"


def member_pool(club_id: int) -> list[str]:
    """캐시상 member로 확인된 계정 키(사용가능한 것만)."""
    usable_keys = {a.key for a in usable_accounts()}
    return [k for k in membership.member_accounts(club_id) if k in usable_keys]


def account_for_cafe(club_id: int, discover: bool = True):
    """이 카페를 크롤할 (account_key, client). 접근 가능 계정 없으면 (None, None)=가입필요.

    이미 member로 확인된 계정 풀에서 라운드로빈. 아직 아무도 확인 안 됐고 discover=True면
    계정을 순서대로 접근 시도해 첫 member를 찾는다(그 결과는 캐시된다)."""
    pool = sorted(member_pool(club_id))                # 안정 순서(분배 결정성)
    if not pool and discover:
        accts = usable_accounts()
        if accts:
            off = club_id % len(accts)                 # 카페마다 시작 계정을 돌려 분산
            for a in accts[off:] + accts[:off]:
                if can_access(a.key, club_id):
                    pool = [a.key]
                    break
    if not pool:
        return None, None
    key = pool[club_id % len(pool)]                    # 카페별 계정 분산(결정적)
    return key, client_for(key)


def scan_cafe(club_id: int) -> list[str]:
    """이 카페에 대해 '모든' 계정의 접근여부를 확인·캐시하고 member 목록 반환.
    (배정 분산을 넓히려면 이걸로 풀을 미리 채운다.)"""
    members = []
    for a in usable_accounts():
        if can_access(a.key, club_id):
            members.append(a.key)
    return members


def close_all():
    for cl in _client_cache.values():
        try:
            cl.close()
        except Exception:
            pass
    _client_cache.clear()

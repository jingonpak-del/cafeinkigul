"""카페 발굴 — 섹션(파워/동네/테마)에서 후보 카페를 열거하고, 필요 시 개별 조사.

열거 API (2026-07 캡처, 로그인 세션 재사용):
  파워/대표: GET cafe-home-web/cafe-home/v1/powercafes?sectorId=popular
  동네/지역: GET cafe-home-web/cafe-home/v3/region-cafes?rcodeDepth1=09&page=&perPage=
  테마:      GET cafe-home-web/cafe-home/v2/themecafes?themeDir1Id=&themeDir2Id=&sort=uppoint&type=ar
  테마 하위: GET cafe-home-web/cafe-home/v1/directories/{dir1}/sub-directories
공통 응답: {message:{status,result:{pageInfo{...,lastPage}, cafes:[...]}}}
목록 항목: cafeId, cafeUrl, cafeName, introduction, memberCount, powerCafe,
           townCafe, themeDir2Name, regionName, upPoint, hasNewArticle ...

열거는 회원수·대표/동네 여부·주제를 바로 준다(카페별 조사 불필요).
일발행량·가입필요는 probe_cafe()로 개별 보강한다(등록 검토 시).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import cafe_api

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "targets.json"
DB_PATH = ROOT / "data" / "tracker.db"

APIS = "https://apis.naver.com/cafe-home-web/cafe-home"
SECTION_REFERER = "https://section.cafe.naver.com/"

# 발굴 계획 기본값(config.discovery로 덮어씀).
# themes.dir1_ids="auto" → 대분류 목록을 동적으로 받아 '모든 테마'를 훑는다
# (한 페이지만이 아니라 테마별 여러 페이지까지). 다양한 카페 확보용.
DEFAULT_PLAN = {
    "daily_batch": 5,
    "powers": {"sectors": ["popular"], "max_pages": 1},
    "regions": {"codes": [], "max_pages": 1},          # 예: ["09"](서울) — 확인된 코드만
    "themes": {"dir1_ids": "auto", "sort": "uppoint", "type": "ar", "max_pages": 2},
}


# ── 개별 조사(probe) ────────────────────────────────────────────────────────
def _estimate_daily_posts(arts) -> float | None:
    ts = sorted((a.write_ts for a in arts if a.write_ts), reverse=True)
    if len(ts) < 2:
        return None
    span_ms = ts[0] - ts[-1]
    if span_ms <= 0:
        return None
    days = span_ms / 86_400_000
    return round((len(ts) - 1) / days, 1) if days > 0 else None


def _score(c: dict) -> float:
    """참조가치 점수(정렬용): 규모(회원수) + 활동성(일발행) − 가입장벽 + 대표/동네 보너스."""
    s = 0.0
    if c.get("member_count"):
        s += math.log10(c["member_count"] + 1) * 10
    s += min(c.get("daily_posts") or 0, 50)
    if c.get("is_power"):
        s += 5
    if c.get("is_local"):
        s += 3
    if c.get("join_required"):
        s -= 15
    return round(s, 1)


def probe_cafe(cluburl: str, *, source: str = "manual", theme: str = "",
               client=None) -> dict:
    """카페 주소를 개별 조사해 후보 dict 반환(이름·게시판·일발행량·가입필요 보강)."""
    own = client is None
    client = client or cafe_api.make_client()
    out = {
        "cluburl": cluburl, "club_id": None, "name": cluburl,
        "source": source, "theme": theme, "is_power": 0, "is_local": 0,
        "member_count": None, "daily_posts": None, "open_level": None,
        "join_required": 0, "sample_boards": "", "score": 0.0,
    }
    try:
        cid = cafe_api.resolve_club_id(cluburl, client=client)
        out["club_id"] = cid
        boards = []
        try:
            boards = cafe_api.fetch_board_list(cid, client=client)
            out["sample_boards"] = ", ".join(b["name"] for b in boards[:5])
        except Exception:
            pass
        info = cafe_api.fetch_cafe_info(cid, client=client)
        if info.get("name"):
            out["name"] = info["name"]
        out["member_count"] = info.get("member_count")
        out["open_level"] = info.get("open_level")
        join_required = 0
        if boards:
            try:
                arts = cafe_api.fetch_article_list(
                    cid, boards[0]["menu_id"], per_page=30, client=client)
                out["daily_posts"] = _estimate_daily_posts(arts)
            except Exception:
                join_required = 1
        try:
            cafe_api.fetch_popular_list(cid, per_page=5, client=client)
        except Exception:
            join_required = 1
        out["join_required"] = join_required
        out["score"] = _score(out)
        return out
    finally:
        if own:
            client.close()


# ── 섹션 열거 ────────────────────────────────────────────────────────────────
def _api_get(client, path: str, params: dict) -> dict:
    r = client.get(f"{APIS}/{path}", params=params,
                   headers={"Referer": SECTION_REFERER, "X-Cafe-Product": "pc"}, timeout=12)
    msg = r.json().get("message", {})
    if str(msg.get("status")) != "200":
        raise RuntimeError(f"{path} status={msg.get('status')} err={msg.get('error')}")
    return msg.get("result", {})


def _norm(item: dict, source: str, theme: str) -> dict:
    c = {
        "club_id": item.get("cafeId"),
        "cluburl": item.get("cafeUrl"),
        "name": item.get("cafeName") or item.get("cafeUrl"),
        "source": source,
        "theme": theme or item.get("themeDir2Name") or item.get("regionName") or "",
        "is_power": 1 if item.get("powerCafe") else 0,
        "is_local": 1 if item.get("townCafe") else 0,
        "member_count": item.get("memberCount"),
        "daily_posts": None,
        "open_level": None,
        "join_required": 0,
        "sample_boards": "",            # 게시판명은 등록 검토 시 probe로 채움
        "score": 0.0,
    }
    c["score"] = _score(c)
    return c


def _paged(client, path: str, base_params: dict, source_fn, max_pages: int) -> list[dict]:
    out = []
    for page in range(1, max_pages + 1):
        params = {**base_params, "page": page}
        try:
            res = _api_get(client, path, params)
        except Exception:
            break
        for it in res.get("cafes", []):
            out.append(source_fn(it))
        if res.get("pageInfo", {}).get("lastPage", True):
            break
    return out


def fetch_power_cafes(client, sector="popular", max_pages=1) -> list[dict]:
    return _paged(client, "v1/powercafes", {"sectorId": sector, "perPage": 20},
                  lambda it: _norm(it, f"power:{sector}", it.get("themeDir2Name", "")), max_pages)


def fetch_region_cafes(client, rcode1="09", max_pages=1) -> list[dict]:
    return _paged(client, "v3/region-cafes", {"rcodeDepth1": rcode1, "perPage": 15},
                  lambda it: _norm(it, f"area:{rcode1}", it.get("regionName", "")), max_pages)


def fetch_theme_cafes(client, dir1, dir2=0, sort="uppoint", type_="ar", max_pages=1) -> list[dict]:
    return _paged(client, "v2/themecafes",
                  {"perPage": 15, "sort": sort, "type": type_, "themeDir1Id": dir1, "themeDir2Id": dir2},
                  lambda it: _norm(it, f"theme:{dir1}", it.get("themeDir2Name", "")), max_pages)


def fetch_theme_subdirs(client, dir1) -> list[dict]:
    try:
        return _api_get(client, f"v1/directories/{dir1}/sub-directories", {}).get("directories", [])
    except Exception:
        return []


def fetch_top_directories(client) -> list[int]:
    """테마 대분류(dir1) id 목록. 엔드포인트 best-effort → 실패 시 1..25 범위 탐색
    (무효 id는 열거 시 빈 결과라 자동 걸러짐)."""
    for path in ("v1/directories", "v1/theme-directories", "v2/directories"):
        try:
            res = _api_get(client, path, {})
            dirs = res.get("directories") or res.get("themeDirectories") or []
            ids = [d.get("directoryId") or d.get("themeDir1Id") or d.get("id") for d in dirs]
            ids = [int(i) for i in ids if i]
            if ids:
                return ids
        except Exception:
            continue
    return list(range(1, 26))


def discover(client, plan: dict | None = None) -> list[dict]:
    """계획대로 섹션을 훑어 후보 dict 리스트(club_id 기준 dedup) 반환."""
    plan = {**DEFAULT_PLAN, **(plan or {})}
    found: list[dict] = []
    p = plan.get("powers", {})
    for sector in p.get("sectors", []):
        found += fetch_power_cafes(client, sector, p.get("max_pages", 1))
    r = plan.get("regions", {})
    for code in r.get("codes", []):
        found += fetch_region_cafes(client, code, r.get("max_pages", 1))
    t = plan.get("themes", {})
    dir_ids = t.get("dir1_ids", [])
    if dir_ids in ("auto", ["auto"]):
        dir_ids = fetch_top_directories(client)
    for d1 in dir_ids:
        found += fetch_theme_cafes(client, d1, 0, t.get("sort", "uppoint"),
                                   t.get("type", "ar"), t.get("max_pages", 1))
    dedup: dict[int, dict] = {}
    for c in found:
        if c.get("club_id"):
            dedup[c["club_id"]] = c
    return sorted(dedup.values(), key=lambda x: x.get("score", 0), reverse=True)


# ── 실행 헬퍼(수동/스케줄) ──────────────────────────────────────────────────
def _config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def authed_client():
    """크롤 계정 세션으로 인증된 httpx 클라이언트(없으면 미인증)."""
    from .session import SessionManager
    from .dpapi import unprotect
    cfg = _config()
    sess_dir = ROOT / "data" / "sessions"
    acct = cfg.get("account")
    sm = SessionManager(sess_dir)
    if acct and sm.verify(acct).ok:
        return cafe_api.make_client(sm.load_cookies(acct))
    for pth in sess_dir.glob("*.session"):     # 폴백: 로그인 쿠키 보유 세션 아무거나
        try:
            rec = json.loads(unprotect(pth.read_bytes()).decode("utf-8"))
            names = {c.get("name") for c in rec.get("cookies", [])}
            if "NID_AUT" in names and "NID_SES" in names:
                return cafe_api.make_client(rec["cookies"])
        except Exception:
            continue
    return cafe_api.make_client(None)


def run_discovery(db, client, plan: dict | None = None) -> dict:
    """섹션 열거 → 이미 등록된 카페 제외 → cafe_candidates upsert.
    반환: {found, upserted, skipped_registered}."""
    cfg = _config()
    registered = {c["club_id"] for c in cfg.get("cafes", [])}
    cands = discover(client, plan or cfg.get("discovery"))
    upserted = 0
    for c in cands:
        if c["club_id"] in registered:
            continue
        db.upsert_candidate(c)
        upserted += 1
    return {"found": len(cands), "upserted": upserted,
            "skipped_registered": sum(1 for c in cands if c["club_id"] in registered)}


def main():
    from .db import Database
    cfg = _config()
    client = authed_client()
    db = Database(DB_PATH)
    try:
        stat = run_discovery(db, client, cfg.get("discovery"))
        print(f"발굴 결과: 열거 {stat['found']} / 신규저장 {stat['upserted']} / "
              f"등록됨제외 {stat['skipped_registered']}")
        print("\n[점수 상위 후보]")
        for r in db.list_candidates("new")[:12]:
            flags = "".join(f for f, on in (("⭐", r["is_power"]), ("📍", r["is_local"])) if on)
            mc = f"{r['member_count']:,}" if r["member_count"] else "-"
            print(f"  {r['score']:6.1f} {flags:2} {r['name'][:30]:30} "
                  f"회원 {mc:>10}  주제 {r['theme'] or '-'}  ({r['cluburl']})")
    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    main()

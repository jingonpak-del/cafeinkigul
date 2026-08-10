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
import re
import statistics
from pathlib import Path

from . import cafe_api, ratelimit

from .paths import DB_PATH  # 데이터는 D:\cafe-corpus (paths.py 참고)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "targets.json"

APIS = "https://apis.naver.com/cafe-home-web/cafe-home"
SECTION_REFERER = "https://section.cafe.naver.com/"

# 발굴 계획 기본값(config.discovery로 덮어씀).
# themes.dir1_ids="auto" → 대분류 목록을 동적으로 받아 '모든 테마'를 훑는다
# (한 페이지만이 아니라 테마별 여러 페이지까지). 다양한 카페 확보용.
DEFAULT_PLAN = {
    "daily_batch": 5,
    "auto_adopt": True,     # 심사 통과한 picked를 자동으로 crawl_all 편입(가입필요 제외)
    "probe_top": 15,        # 열거 상위 N개만 본문 표본을 읽는다(카페당 약 7요청)
    "theme_cap": 2,         # 하루 배치에서 같은 주제는 N개까지 — 코퍼스 편중 방지
    "powers": {"sectors": ["popular"], "max_pages": 1},
    "regions": {"codes": [], "max_pages": 1},          # 예: ["09"](서울) — 확인된 코드만
    "themes": {"dir1_ids": "auto", "sort": "uppoint", "type": "ar", "max_pages": 2},
}


# ── 표본 기반 학습가치 신호 ─────────────────────────────────────────────────
SAMPLE_BODIES = 5          # 카페당 본문 표본 수 (요청 예산과의 절충)


def _account() -> str:
    try:
        return _config().get("account") or "default"
    except Exception:
        return "default"

# 광고·바이럴 원고의 표면적 신호. 정식 분류기는 Phase 3, 여기서는 규칙만 쓴다.
_AD_PATTERNS = [
    r"0(?:1[016-9])[-. ]?\d{3,4}[-. ]?\d{4}",     # 휴대폰
    r"카톡|카카오톡|오픈\s*채팅|오픈톡",
    r"문의\s*(?:주세요|주시면|환영|바랍니다)",
    r"상담\s*(?:문의|신청|환영)",
    r"예약\s*(?:문의|필수)",
    r"@[A-Za-z0-9_]{3,}",                          # 아이디 노출
    r"http[s]?://(?:open\.kakao|pf\.kakao|booking\.naver|smartstore)",
]
_AD_RE = [re.compile(p) for p in _AD_PATTERNS]


def _ad_score(text: str) -> float:
    """0~1. 광고 신호가 몇 종류나 걸리는지로 본다(같은 신호 반복은 1회로)."""
    if not text:
        return 0.0
    hits = sum(1 for r in _AD_RE if r.search(text))
    return min(1.0, hits / 3.0)


def _sample_signals(club_id: int, arts, client) -> dict:
    """표본 게시글의 본문을 실제로 읽어 본문 길이·댓글밀도·광고비율을 잰다.

    열거 API가 주는 회원수·활동성만으로는 '글이 어떤 글인지'를 알 수 없다. 여기서
    카페당 SAMPLE_BODIES건만 실제로 열어 본다. 요청 예산은 발굴 레인 몫에서 쓴다."""
    lim = ratelimit.get(_account())
    bodies, lengths = 0, []
    ads = 0.0
    # 공지·블라인드는 표본에서 뺀다(본문이 정형적이라 신호를 왜곡한다).
    live = [a for a in arts if not (a.is_notice or a.blinded)][:SAMPLE_BODIES]
    for a in live:
        try:
            lim.acquire(reserve=ratelimit.RESERVE_DISCOVERY)
            body = cafe_api.fetch_article_body(club_id, a.article_id,
                                               menu_id=a.menu_id, client=client)
        except Exception:
            continue
        bodies += 1
        lengths.append(len(body.content_text or ""))
        ads += _ad_score(f"{body.title}\n{body.content_text}")

    avg_len = (sum(lengths) / len(lengths)) if lengths else 0.0

    # 댓글은 평균이 아니라 중앙값을 쓴다. 여행카페의 '누적 질문 스레드' 하나가 댓글 수천 개를
    # 달고 있으면 평균이 2,000을 넘어(실측) 카페 전체가 대화가 활발한 것처럼 보인다.
    # 글당 100개에서 한 번 자르고 중앙값을 취해 그런 한두 글의 영향을 없앤다.
    cmts = sorted(min(a.comment_count or 0, 100) for a in arts if a.comment_count is not None)
    med_cmt = statistics.median(cmts) if cmts else 0.0
    return {
        "sample_bodies": bodies,
        "avg_text_len": round(avg_len),
        "avg_comments": round(med_cmt, 1),      # 이름은 유지하되 값은 중앙값
        # 600자를 '충분히 긴 글'의 기준으로 잡는다(현재 코퍼스 평균이 222자).
        "text_richness": round(min(1.0, avg_len / 600.0), 3),
        "comment_density": round(min(1.0, med_cmt / 8.0), 3),
        "ad_ratio": round(ads / bodies, 3) if bodies else 0.0,
    }


AD_REJECT = 0.5            # 표본의 절반이 광고 신호를 달고 있으면 학습 대상이 아니다
MIN_TEXT_LEN = 120         # 표본 평균 본문이 이보다 짧으면 "자연스러운 글"로 보기 어렵다

# 거래·홍보가 본질인 주제는 애초에 조사하지 않는다. 광고 규칙만으로 거르려 했더니
# 표본을 어떻게 뽑느냐에 따라 중고나라의 ad_ratio가 0.60↔0.40으로 흔들려 통과했다.
# 판매글은 길어도 "자연스러운 커뮤니티 글"이 아니므로 주제 단위로 빼는 게 안정적이다.
# (수집 자체를 막는 게 아니라 발굴 대상에서 뺀다 — 핫딜·쇼핑 tier C 결정과 같은 취지.)
DEFAULT_THEME_BLOCKLIST = [
    "중고용품", "중고차", "쇼핑", "공동구매", "할인/쿠폰", "부업/재택",
    "대출/금융", "성인", "분양/임대",
]


def _reject_reason(c: dict, min_samples: int) -> str | None:
    """채택 자격 심사. 통과하면 None, 아니면 사람이 읽을 사유 문자열.

    점수만으로 뽑으면 (a) 표본 수집이 실패해 근거가 없는데도 회원수만으로 상위에 오거나,
    (b) 중고거래·홍보성 카페가 본문이 길다는 이유로 뽑힌다. 실제로 첫 실행에서 둘 다 나왔다.
    """
    if c.get("join_required"):
        return "가입 필요 — 가입 후 재조사"
    if (c.get("sample_bodies") or 0) < min_samples:
        return f"표본 부족({c.get('sample_bodies') or 0}건) — 재조사 필요"
    if (c.get("ad_ratio") or 0) >= AD_REJECT:
        return f"광고 비중 {c['ad_ratio']:.2f}"
    if (c.get("avg_text_len") or 0) < MIN_TEXT_LEN:
        return f"본문 평균 {c.get('avg_text_len') or 0}자"
    if (c.get("score") or 0) <= 0:
        return "점수 0 이하"
    return None


def _topic_novelty(db, theme: str) -> float:
    """이미 채택한 카페에 같은 주제가 많을수록 0에 가까워진다."""
    if not theme:
        return 0.5
    try:
        n = db.conn.execute(
            "SELECT count(*) FROM cafe_candidates WHERE status='tracked' AND theme=?",
            (theme,)).fetchone()[0]
    except Exception:
        n = 0
    return round(1.0 / (1.0 + n), 3)


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
    """학습가치 점수.

    원래는 회원수·활동성 위주였는데, 그렇게 뽑으면 핫딜·쇼핑 카페가 상위를 채운다.
    실측상 그런 카페는 본문의 23%가 50자 미만이라 "자연스러운 커뮤니티 글"을 배우려는
    목적에 맞지 않는다. 그래서 규모 가중을 낮추고 **글이 실제로 얼마나 길고 대화가 붙는지**를
    주 신호로 쓴다. text_richness/comment_density/ad_ratio는 probe 단계에서 표본을 직접
    읽어 채운다(열거 단계에서는 없으므로 0 → 규모·주제만으로 1차 정렬).
    """
    s = 0.0
    if c.get("member_count"):
        s += math.log10(c["member_count"] + 1) * 6      # 규모: 10 → 6으로 축소
    # 활동성 가중을 1.0에서 낮춘다. 큰 카페는 전부 상한(50)에 걸려 +50을 받는 바람에
    # 정작 구분하고 싶은 본문 품질(+25)보다 영향이 커져 있었다.
    s += min(c.get("daily_posts") or 0, 50) * 0.4
    s += (c.get("text_richness") or 0.0) * 25           # ★ 본문이 긴가
    s += (c.get("comment_density") or 0.0) * 15         # ★ 대화가 붙는가
    s += (c.get("topic_novelty") or 0.0) * 20           # ★ 아직 안 덮은 주제인가
    s -= (c.get("ad_ratio") or 0.0) * 30                # ★ 광고글 비중
    if c.get("is_power"):
        s += 5
    if c.get("is_local"):
        s += 3
    if c.get("join_required"):
        s -= 15
    return round(s, 1)


def probe_cafe(cluburl: str, *, source: str = "manual", theme: str = "",
               client=None, db=None) -> dict:
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
                # 표본 본문을 실제로 읽어 학습가치 신호를 채운다.
                sig = _sample_signals(cid, arts, client)
                out.update(sig)
                # 목록은 보이는데 본문이 하나도 안 열리면 비회원 열람 제한이다.
                # (실측상 절반 가까이가 이 경우 — 인기글 조회 성공 여부만으로는 안 잡힌다.)
                if arts and sig["sample_bodies"] == 0:
                    join_required = 1
            except Exception:
                join_required = 1
        try:
            cafe_api.fetch_popular_list(cid, per_page=5, client=client)
        except Exception:
            join_required = 1
        out["join_required"] = join_required
        if db is not None:
            out["topic_novelty"] = _topic_novelty(db, out.get("theme", ""))
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


def run_discovery(db, client, plan: dict | None = None, *, log=print) -> dict:
    """2단계 발굴.

      1단계 열거  — 섹션 API로 수백 개를 훑는다. 값싸지만 회원수·주제만 안다.
      2단계 probe — 상위 probe_top개만 게시판·본문 표본을 실제로 읽어 학습가치를 잰다.
                    카페당 약 7요청이라 전수 조사는 예산이 안 된다.
      선별       — 재계산된 점수로 정렬하되 주제당 theme_cap개까지만 뽑는다.
                    점수만 보면 같은 주제가 상위를 독식해 코퍼스가 편중된다.

    이미 등록됐거나 dismissed/tracked인 카페는 건너뛴다.
    """
    cfg = _config()
    plan = {**DEFAULT_PLAN, **(plan or cfg.get("discovery") or {})}
    probe_top = int(plan.get("probe_top", 15))
    theme_cap = int(plan.get("theme_cap", 2))
    daily_batch = int(plan.get("daily_batch", 5))
    min_samples = int(plan.get("min_samples", 3))
    blocked = set(plan.get("theme_blocklist", DEFAULT_THEME_BLOCKLIST))

    registered = {c["club_id"] for c in cfg.get("cafes", [])}
    enumerated = discover(client, plan)
    log(f"1단계 열거: {len(enumerated)}개")

    added = 0
    for c in enumerated:
        if c["club_id"] in registered:
            continue
        row = db.get_candidate(c["club_id"])
        if row is not None and row["status"] in ("tracked", "dismissed"):
            continue          # 사람이 이미 판단한 카페는 다시 올리지 않는다
        db.upsert_candidate(c, status="enumerated")   # 풀에만 넣는다(승인 큐 아님)
        added += 1
    log(f"후보 풀 갱신: {added}개")

    # 2단계: 아직 조사 안 한 풀에서 상위 N개만 실제로 열어 본다.
    pool = [r for r in db.unprobed_candidates(exclude_ids=registered)
            if (r["theme"] or "") not in blocked]
    log(f"미조사 풀 {len(pool)}개 → 상위 {probe_top}개 조사")
    probed = []
    for r in pool[:probe_top]:
        c = dict(r)
        try:
            p = probe_cafe(c["cluburl"], source=c.get("source") or "",
                           theme=c.get("theme") or "", client=client, db=db)
        except Exception as e:
            log(f"  probe 실패 {c['cluburl']}: {e}")
            continue
        merged = {**c, **{k: v for k, v in p.items() if v is not None}}
        merged["club_id"] = c["club_id"]
        merged["score"] = _score(merged)
        db.save_candidate_signals(merged["club_id"], merged, merged["score"])
        probed.append(merged)
        log(f"  probe {(merged['name'] or '')[:20]:20} 점수 {merged['score']:6.1f} "
            f"본문평균 {merged.get('avg_text_len', 0):>5}자 "
            f"댓글 {merged.get('avg_comments', 0):>4} 광고 {merged.get('ad_ratio', 0):.2f}")

    # 선별: 자격 심사 → 점수순 → 주제당 상한 → daily_batch개
    picked, per_theme, rejected = [], {}, []
    for c in sorted(probed, key=lambda x: x["score"], reverse=True):
        why = _reject_reason(c, min_samples)
        if why:
            rejected.append((c.get("name", ""), why))
            continue
        t = c.get("theme") or "기타"
        if per_theme.get(t, 0) >= theme_cap:
            continue
        per_theme[t] = per_theme.get(t, 0) + 1
        picked.append(c)
        if len(picked) >= daily_batch:
            break
    for name, why in rejected:
        log(f"  ✕ {(name or '')[:24]:24} {why}")

    # 점수상위 자동 채택: 심사 통과한 picked를 crawl_all로 편입(가입필요 제외).
    # auto_adopt=False면 기존처럼 '승인 대기(new)'로만 올린다.
    auto_adopt = bool(plan.get("auto_adopt", True))
    adopted_ids: set[int] = set()
    if auto_adopt and picked:
        cfg2 = _config()
        reg2 = {c["club_id"] for c in cfg2.get("cafes", [])}
        names = []
        for c in picked:
            cid = c["club_id"]
            if c.get("join_required") or cid in reg2:
                continue
            cfg2["cafes"] = [x for x in cfg2.get("cafes", []) if x["club_id"] != cid]
            cfg2["cafes"].append({"cluburl": c["cluburl"], "club_id": cid,
                                  "name": c.get("name") or c["cluburl"],
                                  "crawl_all": True,
                                  "boards": [{"type": "popular", "name": "인기글"}]})
            reg2.add(cid); adopted_ids.add(cid); names.append(c["cluburl"])
        if adopted_ids:
            CONFIG.write_text(json.dumps(cfg2, ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"  ✅ 자동 채택(crawl_all) {len(adopted_ids)}건: {', '.join(names)}")

    # 나머지 상태 부여: 자동채택=tracked, (수동모드 picked)=new, 가입필요=join_needed, 그 외 backlog.
    picked_ids = {c["club_id"] for c in picked}
    join_needed = 0
    for c in probed:
        cid = c["club_id"]
        if cid in adopted_ids:
            st = "tracked"
        elif cid in picked_ids:
            st = "new"
        elif c.get("join_required"):
            st = "join_needed"      # 가입만 하면 후보가 된다 — 사람 개입 대기
            join_needed += 1
        else:
            st = "backlog"
        db.set_candidate_status(cid, st)
    if join_needed:
        log(f"  🔒 가입 필요 {join_needed}건 — 가입 후 재조사하면 후보가 됩니다")

    return {"found": len(enumerated), "pool": len(pool), "probed": len(probed),
            "picked": len(picked), "adopted": len(adopted_ids), "themes": per_theme,
            "picked_list": [{"name": c["name"], "cluburl": c["cluburl"],
                             "score": c["score"], "theme": c.get("theme", "")}
                            for c in picked]}


def main():
    from .db import Database
    from .paths import prune_logs
    prune_logs("discovery")
    cfg = _config()
    client = authed_client()
    db = Database(DB_PATH)
    try:
        stat = run_discovery(db, client, cfg.get("discovery"))
        print(f"\n발굴 결과: 열거 {stat['found']} / 미조사풀 {stat['pool']} / "
              f"probe {stat['probed']} / 선별 {stat['picked']} / 자동채택 {stat.get('adopted', 0)}")
        print(f"주제 분포: {stat['themes']}")
        print("\n[승인 대기 후보]")
        for r in db.list_candidates("new")[:12]:
            flags = "".join(f for f, on in (("⭐", r["is_power"]), ("📍", r["is_local"])) if on)
            mc = f"{r['member_count']:,}" if r["member_count"] else "-"
            print(f"  {r['score']:6.1f} {flags:2} {r['name'][:24]:24} 회원 {mc:>10} "
                  f"본문 {r['avg_text_len'] or 0:>5}자 댓글 {r['avg_comments'] or 0:>4} "
                  f"광고 {r['ad_ratio'] or 0:.2f}  {r['theme'] or '-'}  ({r['cluburl']})")
    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    main()

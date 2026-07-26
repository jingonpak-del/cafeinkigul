"""기관 발굴 파이프라인 (Phase 1).

여러 루트로 신규 기관 후보를 모아 정규화·중복제거하고, 크롤 가능성을 자동 판별해
candidates 테이블에 저장한다. 대시보드에서 검토 후 원클릭 등록.

루트: gov_links(지자체 홈 링크추출), self_expand(수집데이터 자기확장),
      cleaneye(지방공공기관 통합공시, best-effort).
사용: python -m src.info.discovery [창원 김해 ...]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, urljoin

from .collectors import fetch_text
from .classify import classify_org_type
from .db import Database

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "info_sources.json"
DB_PATH = ROOT / "data" / "info.db"

# 지역 → 지자체 홈(관련기관 링크 추출용). 경남 18개 시·군.
# 새 지역 확장 시 여기에 {지역명: 홈URL}만 추가하면 된다.
REGION_GOV = {
    "창원": "https://www.changwon.go.kr/portal/main.do",
    "마산": "https://www.changwon.go.kr/portal/main.do",   # 창원 구
    "진해": "https://www.changwon.go.kr/portal/main.do",   # 창원 구
    "김해": "https://www.gimhae.go.kr/gimhae.web",
    "함안": "https://www.haman.go.kr/",
    "진주": "https://www.jinju.go.kr/", "양산": "https://www.yangsan.go.kr/",
    "거제": "https://www.geoje.go.kr/", "통영": "https://www.tongyeong.go.kr/",
    "사천": "https://www.sacheon.go.kr/", "밀양": "https://www.miryang.go.kr/",
    "거창": "https://www.geochang.go.kr/", "창녕": "https://www.cng.go.kr/",
    "고성": "https://www.goseong.go.kr/", "남해": "https://www.namhae.go.kr/",
    "하동": "https://www.hadong.go.kr/", "산청": "https://www.sancheong.go.kr/",
    "함양": "https://www.hamyang.go.kr/", "의령": "https://www.uiryeong.go.kr/",
    "합천": "https://www.hapcheon.go.kr/",
}
GOV_SEEDS = REGION_GOV   # 하위호환

# 홈에서 따라갈 기관/시설 인덱스 링크(1단계 심층) 판별
_INDEX_KW = re.compile(
    r"(산하기관|유관기관|출자|출연|직속기관|사업소|시설|기관|도서관|복지|청소년|문화|"
    r"체육|보건|여성|가족|평생학습|박물관|미술관|재단)")

# 기관이 아닌 유틸/포털/전국기관 도메인(제외)
_UTIL = re.compile(
    r"(google|naver|kakao|youtube|facebook|instagram|twitter|wetax|hometax|"
    r"minwon|gov\.kr$|open\.go\.kr|epeople|1365|15774129|animal\.go\.kr|"
    r"korean\.go\.kr|molit\.go\.kr|cleaneye|nps\.or\.kr|law\.go\.kr|data\.go\.kr|"
    # 전국 단위 유틸/기관(지역 발굴에서 노이즈)
    r"knto\.or\.kr|^129\.|/129\.|acrc\.go\.kr|lawmaking|cleanbudongsan|kotsa|"
    r"0404\.go\.kr|webwatch|chari\.re\.kr|pharm114|safekorea|foodsafetykorea|"
    r"g4c\.go\.kr|barunuse|clean\.nts|nhis\.or\.kr|kepco|korail|118\.or\.kr|"
    r"privacy\.go\.kr|saferoad|utradehub|work\.go\.kr|alio\.go\.kr)")


def _ondongne_reg() -> dict:
    p = Path(__file__).resolve().parent / "ondongne" / "sources.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        srcs = data if isinstance(data, list) else data.get("sources", [])
        return {s["id"]: s for s in srcs}
    except Exception:
        return {}


def known_domains() -> set:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    reg = _ondongne_reg()
    doms = set()
    for s in cfg.get("sources", []):
        u = s.get("board_url") or s.get("list_url") or s.get("url") or ""
        if s.get("type") == "adapter":                      # 어댑터는 온동네 레지스트리 URL
            u = reg.get(s.get("adapter_id"), {}).get("base_url", "")
        if u:
            doms.add(urlparse(u).netloc.replace("www.", ""))
        if s.get("type") == "naver_blog":
            doms.add("blog.naver.com/" + s.get("blog_id", ""))
    return doms


def _org_name_hint(domain: str, html: str = "") -> str:
    """도메인/페이지 title에서 기관명 추정."""
    if html:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        if m:
            t = re.split(r"[|<>\-:]", re.sub(r"\s+", " ", m.group(1)))[0].strip()
            if 2 < len(t) < 30:
                return t
    return domain


# ── 크롤 가능성 자동 판별 ──────────────────────────────────────────────────
def detect_crawl_type(url: str) -> dict:
    """URL을 받아 크롤 유형과 제안 config를 반환.
    반환: {crawl_type, suggest(dict|None), name}."""
    if "blog.naver.com" in url:
        m = re.search(r"blog\.naver\.com/([A-Za-z0-9_-]+)", url)
        if m:
            return {"crawl_type": "naver_blog", "name": m.group(1),
                    "suggest": {"type": "naver_blog", "blog_id": m.group(1)}}
    try:
        html = fetch_text(url)
    except Exception:
        return {"crawl_type": "unknown", "name": urlparse(url).netloc, "suggest": None}

    name = _org_name_hint(urlparse(url).netloc, html)
    low = html.lower()
    # gnuboard
    if "bo_table=" in url or "board.php" in url or "bo_table" in low:
        return {"crawl_type": "gnuboard", "name": name,
                "suggest": {"type": "gnuboard", "board_url": url, "max_pages": 1}}
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    # 표준 지자체 .web 템플릿(li.li1)
    li1 = [r for r in soup.select("li.li1") if r.find("a")]
    if len(li1) >= 3:
        return {"crawl_type": "html", "name": name,
                "suggest": {"type": "html", "list_url": url, "item_selector": "li.li1",
                            "link_selector": "a.a1", "title_selector": ".t1"}}
    # RSS 링크 존재?
    if re.search(r'type=["\']application/(rss|atom)\+xml', html, re.I):
        m = re.search(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)', html, re.I)
        feed = urljoin(url, m.group(1)) if m else url.rstrip("/") + "/rss"
        return {"crawl_type": "rss", "name": name, "suggest": {"type": "rss", "url": feed}}
    # 서버렌더 게시판(날짜 있는 테이블/리스트 + 상세링크)
    rows = [r for r in soup.select("table tbody tr, table tr, ul li")
            if r.find("a") and re.search(r"20\d{2}[.\-]\d{1,2}[.\-]\d{1,2}", r.get_text())]
    if len(rows) >= 3:
        return {"crawl_type": "html?", "name": name,
                "suggest": {"type": "html", "list_url": url, "note": "선택자 확인 필요"}}
    return {"crawl_type": "unknown", "name": name, "suggest": None}   # AJAX/브라우저 필요


# ── 발굴 루트 ─────────────────────────────────────────────────────────────
def _extract_org_domains(html: str, base: str) -> set:
    doms = set()
    for dom in set(re.findall(r"https?://([a-zA-Z0-9.\-]+\.(?:or\.kr|go\.kr|re\.kr))", html)):
        d = dom.replace("www.", "")
        if _UTIL.search(dom) or base.replace("www.", "") in d:
            continue
        doms.add((d, "https://" + dom))
    return doms


def route_gov_links(regions: list[str]) -> list[dict]:
    """지자체 홈 + 산하기관/시설 인덱스(1단계 심층)에서 관련기관 도메인 추출."""
    from bs4 import BeautifulSoup
    out, done_home = [], set()
    for region in regions:
        home = REGION_GOV.get(region)
        if not home or home in done_home:
            continue
        done_home.add(home)
        try:
            html = fetch_text(home)
        except Exception:
            continue
        base = urlparse(home).netloc
        # 홈에서 기관/시설 인덱스 페이지 링크(동일도메인) 수집 → 1단계 더 크롤
        pages, soup = [home], BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a"):
            txt, href = (a.get_text() or ""), (a.get("href") or "")
            if href and _INDEX_KW.search(txt):
                full = urljoin(home, href)
                if urlparse(full).netloc == base and full not in pages:
                    pages.append(full)
        pages = pages[:10]
        found = set()
        for p in pages:
            try:
                h = html if p == home else fetch_text(p)
            except Exception:
                continue
            found |= _extract_org_domains(h, base)
        for d, u in found:
            out.append({"domain": d, "url": u, "region": region,
                        "route": "gov_links", "evidence": home})
    return out


def route_self_expand() -> list[dict]:
    """이미 수집한 글의 원문 URL 도메인 중, 등록 안 된 기관 도메인 추출."""
    conn = _ro()
    try:
        rows = conn.execute(
            "SELECT DISTINCT url, region, region2 FROM posts WHERE url LIKE 'http%'").fetchall()
    finally:
        conn.close()
    seen, out = set(), []
    for url, region, region2 in rows:
        dom = urlparse(url).netloc.replace("www.", "")
        if not dom or dom in seen or _UTIL.search(dom):
            continue
        if not re.search(r"\.(or|go|re)\.kr$", dom) and "blog.naver.com" not in dom:
            continue
        seen.add(dom)
        out.append({"domain": dom, "url": "https://" + urlparse(url).netloc,
                    "region": region or "", "region2": region2 or "",
                    "route": "self_expand", "evidence": url})
    return out


def _ro():
    import sqlite3
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    return c


# 클린아이(지방공공기관 통합공시) 헤더/엔드포인트
_CE = "https://www.cleaneye.go.kr"
_CE_HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest",
               "Referer": _CE + "/user/itemGongsi.do"}
# 순수 유틸(뉴스보드 없음) 제외
_CE_SKIP = re.compile(r"(상수도|하수도|공영개발|자동차운송|지하철|도시철도)")


def route_cleaneye(regions: list[str]) -> list[dict]:
    """클린아이 지방공기업 + 출자·출연기관 목록에서 지역 기관 + 홈페이지 추출."""
    import httpx
    terms = list(dict.fromkeys(list(regions) + ["경상남도", "경남"]))  # 경남 광역기관 포함
    tre = re.compile("|".join(re.escape(t) for t in terms))
    r2_terms = [r for r in regions if r not in ("경남", "경상남도")] or ["창원", "김해", "함안"]
    out, seen = [], set()
    try:
        with httpx.Client(timeout=20, headers=_CE_HEADERS, follow_redirects=True) as cl:
            lists = [("공기업", "/user/selectNewItemEntList.do", "data"),
                     ("출자출연", "/user/selectIptItemEntList.do", "data")]
            for label, ep, key in lists:
                try:
                    arr = cl.post(_CE + ep, data={}).json().get(key, [])
                except Exception:
                    continue
                orgs = [(o["itemNm"], o["itemId"]) for o in arr
                        if len(str(o.get("itemId", ""))) >= 6 and tre.search(o.get("itemNm", ""))
                        and not _CE_SKIP.search(o.get("itemNm", ""))]
                for name, ent in orgs:
                    try:
                        t = cl.post(_CE + "/user/empItemContent.do", data={"entId": ent}).text
                        hp = [u for u in re.findall(r"https?://[a-zA-Z0-9.\-/]+", t)
                              if "cleaneye" not in u and "/user/" not in u and "go.kr/gongsi" not in u]
                    except Exception:
                        hp = []
                    if not hp:
                        continue
                    home = hp[0].rstrip("/")
                    dom = urlparse(home).netloc.replace("www.", "")
                    if not dom or dom in seen:
                        continue
                    seen.add(dom)
                    r2 = next((r for r in r2_terms if r in name), "")
                    if r2 in ("마산", "진해"):
                        r2 = "창원"
                    out.append({"domain": dom, "url": home, "name": name, "region": "경남",
                                "region2": r2, "route": "cleaneye", "evidence": "클린아이 " + ent})
    except Exception:
        pass
    return out


# ── 홈페이지 → 게시판 자동탐색 → 검증된 config ──────────────────────────────
def find_board_urls(home: str) -> list[str]:
    """홈페이지에서 공지/게시판 링크 후보(동일 도메인)를 추출."""
    from bs4 import BeautifulSoup
    try:
        html = fetch_text(home)
    except Exception:
        return []
    soup = BeautifulSoup(html, "html.parser")
    base = urlparse(home).netloc
    seen, out = set(), []
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        txt = a.get_text() or ""
        full = urljoin(home, href)
        hit = ("board.php" in href or "bo_table=" in href
               or re.search(r"(공지|알림|소식|notice|news|board|bbs)", txt + href, re.I))
        if hit and full.startswith("http") and urlparse(full).netloc == base and full not in seen:
            seen.add(full); out.append(full)
    # 게시판성(board.php/bo_table) 우선 정렬
    out.sort(key=lambda u: 0 if ("board.php" in u or "bo_table=" in u) else 1)
    return out[:8]


def resolve_source_from_home(home: str) -> dict | None:
    """홈페이지에서 실제 수집 가능한 게시판을 찾아 검증된 config(dict) 반환(없으면 None)."""
    from .collectors import collect
    for board in find_board_urls(home):
        det = detect_crawl_type(board)
        sug = det.get("suggest")
        if not sug or det["crawl_type"] not in ("gnuboard", "html", "rss"):
            continue
        try:
            if len(collect({**sug, "id": "probe", "name": "probe", "category": ""})) >= 2:
                return sug
        except Exception:
            continue
    return None


def register_candidate(cand_key: str, overrides: dict | None = None) -> dict:
    """후보를 게시판 자동탐색·검증 후 config에 등록하고 즉시 수집. 요약 반환."""
    from . import ingest
    overrides = overrides or {}
    db = Database(DB_PATH)
    try:
        row = db.conn.execute("SELECT * FROM candidates WHERE cand_key=?", (cand_key,)).fetchone()
        if not row:
            return {"ok": False, "error": "후보 없음"}
        cols = [d[0] for d in db.conn.execute("SELECT * FROM candidates WHERE cand_key=?", (cand_key,)).description]
        cand = dict(zip(cols, row))
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        # 이미 board형 suggest가 있으면 그대로, 아니면 홈에서 게시판 탐색
        sug = None
        try:
            sug = json.loads(cand["suggest"]) if cand.get("suggest") else None
        except Exception:
            sug = None
        if not (sug and (sug.get("board_url") or sug.get("list_url") or sug.get("url"))
                and _looks_like_board(sug)):
            sug = resolve_source_from_home(cand["url"])
        if not sug:
            return {"ok": False, "error": "수집 가능한 게시판을 찾지 못함(AJAX 등)"}
        name = overrides.get("name") or cand["name"]
        base_dom = urlparse(cand["url"]).netloc.replace("www.", "").split(".")[0]
        sid = "%s:disc_%s" % (sug["type"], base_dom)
        if any(s["id"] == sid for s in cfg["sources"]):
            db.set_candidate_status(cand_key, "added")
            return {"ok": False, "error": "이미 등록됨"}
        entry = {"id": sid, "name": name, "category": overrides.get("category", "지자체"),
                 "enabled": True, "region": overrides.get("region") or cand.get("region") or "경남",
                 "region2": overrides.get("region2") or cand.get("region2") or "",
                 "org_type": overrides.get("org_type") or cand.get("org_type") or "기타", **sug}
        cfg["sources"].append(entry)
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        res = ingest.run(sid)
        inserted = sum(r.get("inserted", 0) for r in res)
        db.set_candidate_status(cand_key, "added")
        return {"ok": True, "id": sid, "name": name, "type": sug["type"], "inserted": inserted}
    finally:
        db.close()


def _looks_like_board(sug: dict) -> bool:
    u = sug.get("board_url") or sug.get("list_url") or sug.get("url") or ""
    return "board.php" in u or "bo_table=" in u or ".web" in u or "list" in u.lower()


# ── 파이프라인 ────────────────────────────────────────────────────────────
def run(regions: list[str], probe: bool = True) -> dict:
    """루트 실행 → 정규화·dedup → 판별 → candidates 저장. 요약 반환."""
    db = Database(DB_PATH)
    known = known_domains()
    existing = db.candidate_keys()
    raw = route_gov_links(regions) + route_self_expand() + route_cleaneye(regions)

    added = 0
    by_type: dict[str, int] = {}
    for r in raw:
        dom = r["domain"]
        if dom in known or dom in existing:
            continue
        existing.add(dom)
        crawl_type, suggest, name = "unknown", None, r.get("name") or dom
        if probe:
            det = detect_crawl_type(r["url"])
            crawl_type, suggest = det["crawl_type"], det.get("suggest")
            name = r.get("name") or det["name"]   # 클린아이 등 실제 기관명 우선
        by_type[crawl_type] = by_type.get(crawl_type, 0) + 1
        db.upsert_candidate({
            "cand_key": dom, "name": name, "url": r["url"],
            "region": r.get("region", ""), "region2": r.get("region2", ""),
            "org_type": classify_org_type(name), "route": r["route"],
            "crawl_type": crawl_type, "suggest": json.dumps(suggest, ensure_ascii=False) if suggest else "",
            "evidence": r.get("evidence", ""),
        })
        added += 1
    total_new = len(db.list_candidates(status="new"))
    db.close()
    return {"scanned": len(raw), "added": added, "by_crawl_type": by_type, "total_new": total_new}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    regions = sys.argv[1:] or ["창원", "김해"]
    res = run(regions)
    print("발굴 완료:", res)


if __name__ == "__main__":
    main()

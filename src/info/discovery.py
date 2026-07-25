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

# 지자체 홈(관련기관 링크 추출용). 마산·진해는 창원 구청 포함.
GOV_SEEDS = {
    "창원": ["https://www.changwon.go.kr/portal/main.do"],
    "김해": ["https://www.gimhae.go.kr/gimhae.web"],
}

# 기관이 아닌 유틸/포털 도메인(제외)
_UTIL = re.compile(
    r"(google|naver|kakao|youtube|facebook|instagram|twitter|wetax|hometax|"
    r"minwon|gov\.kr$|open\.go\.kr|epeople|1365|15774129|animal\.go\.kr|"
    r"korean\.go\.kr|molit\.go\.kr|cleaneye|nps\.or\.kr|law\.go\.kr|data\.go\.kr)")


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
def route_gov_links(regions: list[str]) -> list[dict]:
    """지자체 홈페이지에서 관련기관(.or.kr/.go.kr) 도메인 추출."""
    out = []
    for region in regions:
        for home in GOV_SEEDS.get(region, []):
            try:
                html = fetch_text(home)
            except Exception:
                continue
            base = urlparse(home).netloc
            for dom in set(re.findall(r"https?://([a-zA-Z0-9.\-]+\.(?:or\.kr|go\.kr|re\.kr))", html)):
                d = dom.replace("www.", "")
                if _UTIL.search(dom) or base.replace("www.", "") in d:
                    continue
                out.append({"domain": d, "url": "https://" + dom, "region": region,
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


# ── 파이프라인 ────────────────────────────────────────────────────────────
def run(regions: list[str], probe: bool = True) -> dict:
    """루트 실행 → 정규화·dedup → 판별 → candidates 저장. 요약 반환."""
    db = Database(DB_PATH)
    known = known_domains()
    existing = db.candidate_keys()
    raw = route_gov_links(regions) + route_self_expand()

    added = 0
    by_type: dict[str, int] = {}
    for r in raw:
        dom = r["domain"]
        if dom in known or dom in existing:
            continue
        existing.add(dom)
        crawl_type, suggest, name = "unknown", None, dom
        if probe:
            det = detect_crawl_type(r["url"])
            crawl_type, suggest, name = det["crawl_type"], det.get("suggest"), det["name"]
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

"""사이트별 수집기.

각 소스 type → 수집 함수. 수집 함수는 표준화된 post dict 리스트를 돌려준다:
    {source_id, post_key, source_name, source_type, category, title,
     author, url, published_at(ms|None), view_count(int|None), content_text}

새 사이트 유형을 추가할 때는 COLLECTORS에 함수를 등록하면 된다.
현재: naver_blog(RSS), rss(범용 RSS/Atom).
"""
from __future__ import annotations

import html
import re
import time
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

UA = "Mozilla/5.0 (compatible; InfoAggregator/1.0)"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]*\n\s*\n\s*", re.S)


def fetch_text(url: str, timeout: int = 20) -> str:
    """HTML 본문을 다중 인코딩 폴백으로 안전 디코딩.
    옛 정부/공공 사이트는 euc-kr/cp949가 많아 헤더 charset만 믿으면 깨진다."""
    r = httpx.get(url, timeout=timeout, headers={"User-Agent": UA}, follow_redirects=True)
    r.raise_for_status()
    raw = r.content
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _strip_html(s: str, limit: int = 2000) -> str:
    """HTML → 순수 txt. 태그 제거 + 공백 정리 + 길이 제한."""
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n", s, flags=re.I)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    lines = [ln.strip() for ln in s.splitlines()]
    s = "\n".join(ln for ln in lines if ln)
    s = s.strip()
    if len(s) > limit:
        s = s[:limit].rstrip() + " …"
    return s


def _to_ms(pubdate: str) -> int | None:
    if not pubdate:
        return None
    try:
        return int(parsedate_to_datetime(pubdate).timestamp() * 1000)
    except Exception:
        return None


def _txt(el, tag: str) -> str:
    v = el.findtext(tag)
    return v.strip() if v else ""


def collect_rss(source: dict, feed_url: str, name: str) -> list[dict]:
    """범용 RSS 2.0 파서. naver_blog 및 일반 RSS 소스 공용."""
    r = httpx.get(feed_url, timeout=20, headers={"User-Agent": UA}, follow_redirects=True)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    channel = root.find("channel")
    if channel is None:
        return []
    ch_title = _txt(channel, "title") or name
    out = []
    for it in channel.findall("item"):
        link = _txt(it, "link")
        title = _txt(it, "title")
        if not link and not title:
            continue
        author = _txt(it, "author") or _txt(it, "{http://purl.org/dc/elements/1.1/}creator")
        published = _to_ms(_txt(it, "pubDate"))
        desc = it.findtext("description") or ""
        content = _strip_html(desc)
        out.append({
            "source_id": source["id"],
            "post_key": _post_key_from_link(link) or link or title,
            "source_name": name or ch_title,
            "source_type": source.get("type", "rss"),
            "category": source.get("category", ""),
            "title": title,
            "author": author or None,
            "url": _clean_url(link),
            "published_at": published,
            "view_count": None,   # RSS는 조회수 미제공 → 빈칸
            "content_text": content,
        })
    return out


def _clean_url(link: str) -> str:
    """RSS 링크의 추적 파라미터 제거."""
    if not link:
        return link
    return re.split(r"[?#]", link)[0]


def _post_key_from_link(link: str) -> str | None:
    """네이버 블로그 링크 .../{blogId}/{logNo} 에서 logNo 추출."""
    m = re.search(r"/(\d{6,})", link or "")
    return m.group(1) if m else None


def collect_naver_blog(source: dict) -> list[dict]:
    blog_id = source["blog_id"]
    feed = f"https://rss.blog.naver.com/{blog_id}.xml"
    # 이름 미지정 시 collect_rss가 RSS 채널 제목으로 자동 채움
    return collect_rss(source, feed, source.get("name", ""))


def collect_generic_rss(source: dict) -> list[dict]:
    return collect_rss(source, source["url"], source.get("name", ""))


_DATE_RE = re.compile(r"(20\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})")


def _parse_date_ms(text: str) -> int | None:
    """'2026-07-21' '2026.07.21' '2026년 7월 21일' 등에서 날짜 추출 → ms."""
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    try:
        import datetime as _dt
        y, mo, d = (int(x) for x in m.groups())
        return int(_dt.datetime(y, mo, d).timestamp() * 1000)
    except Exception:
        return None


_ID_KEYS = ("wr_id", "nttId", "not_ancmt_mgt_no", "mng_no", "articleNo", "boardSeq",
            "bbsSeq", "idx", "seq", "no", "id", "num")


def _normalize_article_url(link: str) -> str:
    """휘발성 세션토큰(;jsessionid=...) 제거. 글 식별 쿼리는 유지."""
    return re.sub(r";jsessionid=[^?#]*", "", link, flags=re.I)


def _html_post_key(link: str) -> str:
    """게시판 상세 링크에서 안정적인 글 키 추출.
    쿼리의 nttId/seq 등 id 파라미터 우선, 없으면 세션제거한 URL."""
    from urllib.parse import urlparse, parse_qs
    clean = _normalize_article_url(link)
    qs = parse_qs(urlparse(clean).query)
    for k in _ID_KEYS:
        if k in qs and qs[k]:
            return f"{k}={qs[k][0]}"
    return clean


def _to_int(text: str) -> int | None:
    d = re.sub(r"[^\d]", "", text or "")
    return int(d) if d else None


def _extract_items(html: str, base_url: str, source: dict) -> list[dict]:
    """렌더된 HTML에서 목록 항목 추출 (html·browser 수집기 공용).

    선택자: item_selector(행), title_selector, link_selector,
            date_selector, author_selector, view_selector, summary_selector.
    링크가 javascript:/# 이면 onclick에서 id_regex로 글ID를 뽑아
    url_template(있으면)로 상세URL 구성, post_key는 그 ID 사용.
    """
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select(source["item_selector"])
    name = source.get("name") or base_url
    id_re = re.compile(source["id_regex"]) if source.get("id_regex") else None
    url_tmpl = source.get("url_template")

    def cell(row, sel):
        n = row.select_one(sel) if sel else None
        return n.get_text(" ", strip=True) if n else ""

    out = []
    for row in rows:
        if source.get("link_selector"):
            a = row.select_one(source["link_selector"])
        else:
            a = row if row.name == "a" else row.find("a")   # 항목 자체가 <a>인 경우 지원
        link, post_key = None, None
        if a is None:
            # 앵커 없는 카드(예: <li data-idx="..."> 클릭형): id_regex로 글ID 추출
            if not id_re:
                continue
            m = id_re.search(str(row))
            if not m:
                continue
            pid = m.group(1)
            post_key = f"id={pid}"
            link = url_tmpl.format(id=pid) if url_tmpl else urljoin(base_url, f"#{pid}")
        else:
            href = a.get("href") or ""
            if href and not href.startswith("javascript") and not href.startswith("#"):
                link = _normalize_article_url(urljoin(base_url, href))
                post_key = _html_post_key(link)
            elif id_re:                              # onclick 기반 상세 링크
                m = id_re.search(a.get("onclick") or "") or id_re.search(str(row))
                if not m:
                    continue
                pid = m.group(1)
                post_key = f"id={pid}"
                link = url_tmpl.format(id=pid) if url_tmpl else urljoin(base_url, f"#{pid}")
            else:
                continue
        title = cell(row, source["title_selector"]) if source.get("title_selector") \
            else ((a.get_text(strip=True) or (a.get("title") or "").strip()) if a else "")
        if not title:
            continue
        # 날짜: date_selector 지정 시 그 셀, 없거나 못찾으면 행 전체 텍스트에서 첫 날짜
        date_txt = cell(row, source["date_selector"]) if source.get("date_selector") else ""
        published = _parse_date_ms(date_txt) or _parse_date_ms(row.get_text(" ", strip=True))
        views = _to_int(cell(row, source["view_selector"])) if source.get("view_selector") else None
        author = cell(row, source["author_selector"]) if source.get("author_selector") else source.get("author")
        summary = cell(row, source.get("summary_selector"))
        out.append({
            "source_id": source["id"],
            "post_key": post_key,
            "source_name": name,
            "source_type": source.get("type", "html"),
            "category": source.get("category", ""),
            "title": title,
            "author": author or None,
            "url": link,
            "published_at": published,
            "view_count": views,
            "content_text": (summary[:2000] if summary else ""),
        })
    return out


def collect_html(source: dict) -> list[dict]:
    """범용 HTML 목록 크롤러 (RSS 없는 서버렌더링 게시판용).

    config 예:
      {"type":"html", "list_url":"...", "item_selector":"table tbody tr",
       "title_selector":"td.l a", "link_selector":"td.l a",
       "date_selector":"td:nth-of-type(5)", "author_selector":"td:nth-of-type(4)",
       "view_selector":"td:nth-of-type(6)"}
    title/link_selector 미지정 시 행 안의 첫 <a>를 사용.
    """
    url = source["list_url"]
    return _extract_items(fetch_text(url), url, source)


def collect_post_html(source: dict) -> list[dict]:
    """POST로 목록 HTML 조각을 받아 파싱 (AJAX 목록 엔드포인트용).

    로그인 없이 접근 가능한 XHR 목록 API에 사용. 응답 HTML을 html 수집기와
    동일한 선택자 규칙으로 파싱한다. 상대경로 링크 보정을 위해 base_url 지정.

    config 예:
      {"type":"post_html", "list_url":"https://.../search/list.ajax",
       "post_data":{"type":"branch","brchCd":"0017","pageIndex":"1","pageUnit":"60"},
       "referer":"https://.../search/list.do?...", "base_url":"https://...",
       "item_selector":"a.lec_list", "title_selector":"p.tit",
       "summary_selector":"div.info_con"}
    """
    url = source["list_url"]
    headers = {"User-Agent": UA, "X-Requested-With": "XMLHttpRequest"}
    if source.get("referer"):
        headers["Referer"] = source["referer"]
    base = source.get("base_url") or url
    max_pages = int(source.get("max_pages", 1))
    page_param = source.get("page_param", "pageIndex")
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        data = dict(source.get("post_data", {}))
        if max_pages > 1:
            data[page_param] = str(page)
        r = httpx.post(url, data=data, headers=headers, timeout=25, follow_redirects=True)
        r.raise_for_status()
        raw = r.content
        text = None
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("utf-8", errors="ignore")
        items = _extract_items(text, base, source)
        fresh = [it for it in items if it["post_key"] not in seen]
        if not fresh:                      # 더 이상 새 항목 없으면 종료
            break
        seen.update(it["post_key"] for it in fresh)
        out.extend(fresh)
    return out


def _chrome_major() -> int | None:
    """설치된 Chrome 주버전 감지 (undetected-chromedriver 버전 매칭용)."""
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                k = winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon")
                ver, _ = winreg.QueryValueEx(k, "version")
                return int(ver.split(".")[0])
            except Exception:
                continue
    except Exception:
        pass
    return None


def collect_browser(source: dict) -> list[dict]:
    """헤드리스 브라우저(undetected-chromedriver)로 SPA 렌더 후 수집.
    RSS·API 없는 자바스크립트 사이트용. 창은 표시하지 않음(headless).

    config 예:
      {"type":"browser", "url":"...", "wait_selector":"table tbody tr td.tit a",
       "item_selector":"table tbody tr", "title_selector":"td.tit a",
       "date_selector":"td.date", "link_selector":"td.tit a",
       "id_regex":"viewSubmit\\((\\d+)\\)",
       "url_template":"https://.../{id}/view.gn", "wait_seconds":8}
    """
    import undetected_chromedriver as uc
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By

    url = source["url"]
    opts = uc.ChromeOptions()
    for arg in ("--headless=new", "--no-sandbox", "--disable-gpu",
                "--window-size=1400,1000", "--disable-dev-shm-usage",
                "--lang=ko-KR"):
        opts.add_argument(arg)
    driver = uc.Chrome(options=opts, version_main=_chrome_major())
    try:
        driver.set_page_load_timeout(40)
        driver.get(url)
        wait_sel = source.get("wait_selector") or source.get("item_selector")
        try:
            WebDriverWait(driver, int(source.get("wait_seconds", 8))).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, wait_sel)))
        except Exception:
            pass
        import time as _t
        _t.sleep(1.5)   # 렌더 안정화
        html = driver.page_source
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return _extract_items(html, url, source)


# ── Gnuboard 게시판 collector (한국 공공기관 표준 CMS) ──────────────────────
# 온동네 플랫폼 GenericGnuboardAdapter에서 이식. bo_table/wr_id 패턴 기반.
_GNU_INCLUDE = [
    "모집", "신청", "참여", "교육", "프로그램", "행사", "공모", "공모전", "지원사업",
    "상담", "강좌", "체험", "특강", "설명회", "멘토링", "컨설팅", "워크숍", "세미나",
    "입주", "참가", "수강", "접수", "운영", "공연", "전시", "안내",
]
_GNU_EXCLUDE = [
    "채용", "합격", "서류전형", "면접", "휴관", "휴무", "점검", "공사", "결산", "예산",
    "선정결과", "선정 결과", "수상자", "당선", "대관", "회의결과", "회의 결과",
]


def _gnu_canonical(board_url: str, url: str) -> str:
    from urllib.parse import urljoin
    mb = re.search(r"bo_table=([^&]+)", url)
    mi = re.search(r"wr_id=(\d+)", url)
    if mb and mi:
        return urljoin(board_url, f"/bbs/board.php?bo_table={mb.group(1)}&wr_id={mi.group(1)}")
    return _normalize_article_url(url)


def _gnu_clean_title(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\b\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}\b", " ", text)
    text = re.sub(r"조회수?\s*[:：]?\s*\d+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(공지|알림)\s*", "", text).strip()


def collect_gnuboard(source: dict) -> list[dict]:
    """Gnuboard 게시판 목록 수집. 상세 본문은 fetch_detail=True일 때만.

    config 예:
      {"type":"gnuboard", "name":"...", "category":"...",
       "board_url":"https://site/bbs/board.php?bo_table=notice",
       "include_keywords":[...], "exclude_keywords":[...],
       "max_pages":3, "since_days":30, "fetch_detail":false}
    include/exclude 미지정 시 행사·모집 기본 어휘 사용(빈 리스트로 끄기 가능).
    """
    from urllib.parse import urljoin
    from .html_utils import strip_tags, first_match, all_links
    from . import date_parser as dp

    board_url = source["board_url"]
    # 기본은 전체 수집(필터 없음) — 주제 유무와 무관하게 다 가져온 뒤 분류한다.
    # 특정 소스만 좁히고 싶으면 config에 include_keywords/exclude_keywords 지정.
    include = source.get("include_keywords", [])
    exclude = source.get("exclude_keywords", [])
    since_days = int(source.get("since_days", 30))
    max_pages = int(source.get("max_pages", 3))
    limit = int(source.get("limit", 100))
    name = source.get("name") or board_url
    href_re = r'<a[^>]+href=["\']([^"\']*wr_id=\d+[^"\']*)["\'][^>]*>(.*?)</a>'

    def relevant(title: str) -> bool:
        norm = re.sub(r"\s+", "", title)
        if any(k.replace(" ", "") in norm for k in exclude):
            return False
        return (not include) or any(k in title for k in include)

    items, seen = [], set()
    for page in range(1, max_pages + 1):
        if len(items) >= limit:
            break
        sep = "&" if "?" in board_url else "?"
        url = board_url if page == 1 else f"{board_url}{sep}page={page}"
        try:
            html_text = fetch_text(url)
        except Exception:
            break
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S | re.I) \
            or re.findall(r"<li[^>]*>(.*?)</li>", html_text, re.S | re.I)
        added = 0
        for row in rows:
            m = re.search(href_re, row, re.S | re.I)
            if not m:
                continue
            href, inner = m.groups()
            title = _gnu_clean_title(strip_tags(inner))
            subj = strip_tags(first_match(
                r'<td[^>]+class=["\'][^"\']*(?:td_subject|subject|title)[^"\']*["\'][^>]*>(.*?)</td>', row))
            if subj and len(subj) > len(title):
                title = _gnu_clean_title(subj)
            date_text = strip_tags(first_match(
                r'<td[^>]+class=["\'][^"\']*(?:td_datetime|date|time)[^"\']*["\'][^>]*>(.*?)</td>', row)) \
                or first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', row)
            published = dp.parse_first_ms(date_text)
            if len(title) < 4 or not relevant(title):
                continue
            if published is not None and published < time.time() * 1000 - since_days * 86400 * 1000:
                continue   # 목록에 날짜가 있고 창 밖이면 제외(발행일 없으면 통과)
            link = _gnu_canonical(board_url, urljoin(board_url, html.unescape(href).replace("&amp;", "&")))
            if link in seen:
                continue
            seen.add(link)
            items.append({
                "source_id": source["id"],
                "post_key": _html_post_key(link),
                "source_name": name,
                "source_type": "gnuboard",
                "category": source.get("category", ""),
                "title": title,
                "author": source.get("author") or None,
                "url": link,
                "published_at": published,
                "view_count": None,
                "content_text": "",
            })
            added += 1
            if len(items) >= limit:
                break
        if added == 0 and page > 1:
            break

    if source.get("fetch_detail"):
        for it in items:
            try:
                dh = fetch_text(it["url"])
            except Exception:
                continue
            body_html = first_match(
                r'<div[^>]+id=["\']bo_v_con["\'][^>]*>(.*?)</div>\s*(?:<script|<section|</article)', dh) \
                or first_match(r'<div[^>]+id=["\']bo_v_con["\'][^>]*>(.*?)</div>', dh)
            body = strip_tags(body_html)
            if body:
                it["content_text"] = body[:2000]
    return items


# ── 온동네 어댑터 브릿지 (창원 기관별 맞춤 크롤러 재사용) ────────────────────
_ONDONGNE_REG = None


def _ondongne_registry() -> dict:
    """온동네 sources.json → {source_id: 레지스트리 entry} (캐시)."""
    global _ONDONGNE_REG
    if _ONDONGNE_REG is None:
        import json
        from pathlib import Path
        p = Path(__file__).resolve().parent / "ondongne" / "sources.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        srcs = data if isinstance(data, list) else data.get("sources", [])
        _ONDONGNE_REG = {s["id"]: s for s in srcs}
    return _ONDONGNE_REG


def collect_adapter(source: dict) -> list[dict]:
    """온동네 기관별 어댑터를 실행해 Event를 posts로 변환.
    config 예: {"type":"adapter", "adapter_id":"changwon_library", "name":..., "category":"지자체", ...}
    """
    from .ondongne.cli import ADAPTER_BY_SOURCE_ID
    from . import date_parser as dp

    aid = source["adapter_id"]
    cls = ADAPTER_BY_SOURCE_ID.get(aid)
    if not cls:
        raise ValueError(f"어댑터 없음: {aid}")
    reg = _ondongne_registry().get(aid)
    if not reg:
        raise ValueError(f"온동네 레지스트리에 없음: {aid}")
    adapter = cls(reg)
    events = adapter.crawl(since_days=int(source.get("since_days", 30)),
                           limit=int(source.get("limit", 50)))
    out = []
    for e in events:
        d = e.to_dict() if hasattr(e, "to_dict") else dict(getattr(e, "__dict__", {}))
        if not d.get("title") or not d.get("source_url"):
            continue
        out.append({
            "source_id": source["id"],
            "post_key": d.get("id") or _normalize_article_url(d["source_url"]),
            "source_name": source.get("name") or d.get("source_name") or "",
            "source_type": "adapter",
            "category": source.get("category", ""),
            "title": d.get("title"),
            "author": None,
            "url": d.get("source_url"),
            "published_at": (dp.to_ms(d.get("published_at")) or dp.to_ms(d.get("event_start_date"))
                             or dp.to_ms(d.get("application_start_date"))),
            "view_count": None,
            "content_text": (d.get("body_text") or d.get("summary") or "")[:2000],
            "event_start_at": dp.to_ms(d.get("event_start_date")),
            "event_end_at": dp.to_ms(d.get("event_end_date")),
            "apply_start_at": dp.to_ms(d.get("application_start_date")),
            "apply_end_at": dp.to_ms(d.get("application_end_date")),
            "target_audience": d.get("target_audience") or None,
            "location": d.get("location_name") or None,
        })
    return out


COLLECTORS = {
    "naver_blog": collect_naver_blog,
    "rss": collect_generic_rss,
    "html": collect_html,
    "post_html": collect_post_html,
    "browser": collect_browser,
    "gnuboard": collect_gnuboard,
    "adapter": collect_adapter,
}


def collect(source: dict) -> list[dict]:
    """소스 type에 맞는 수집기 실행. 미지원이면 예외."""
    fn = COLLECTORS.get(source.get("type"))
    if not fn:
        raise ValueError(f"지원하지 않는 소스 유형: {source.get('type')}")
    return fn(source)


def within_window(posts: list[dict], window_days: int) -> list[dict]:
    """등록 시점 기준 window_days 이내 발행 글만. 발행일 없는 글은 포함."""
    cutoff = int(time.time() * 1000) - window_days * 86400 * 1000
    return [p for p in posts if p["published_at"] is None or p["published_at"] >= cutoff]


# ── 입력값 → 소스 자동판별 (관리 UI '블로그 추가' 용) ────────────────────────
def parse_naver_blog_id(s: str) -> str | None:
    """네이버 블로그 ID 추출. 허용 입력:
    'mltmkr' | 'blog.naver.com/mltmkr' | 'https://m.blog.naver.com/mltmkr/123'
    | 'https://blog.naver.com/PostList.naver?blogId=mltmkr'"""
    s = s.strip()
    m = re.search(r"blogId=([A-Za-z0-9_-]+)", s)
    if m:
        return m.group(1)
    m = re.search(r"blog\.naver\.com/([A-Za-z0-9_-]+)", s)
    if m and m.group(1).lower() not in ("postlist", "postview"):
        return m.group(1)
    # 순수 ID (슬래시·점·공백 없음)
    if re.fullmatch(r"[A-Za-z0-9_-]+", s):
        return s
    return None


def resolve_source(raw: str) -> dict:
    """입력 문자열을 소스 dict로 판별하고 실제 피드를 확인.
    반환: {source, sample_count, sample_name}. 실패 시 ValueError."""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("입력이 비었습니다.")

    is_url = raw.startswith("http")
    is_naver = ("blog.naver.com" in raw) or ("blogId=" in raw)
    is_gnu = ("bo_table=" in raw) or ("board.php" in raw)
    bid = parse_naver_blog_id(raw)

    if bid and (is_naver or not is_url):
        src = {"id": f"naver_blog:{bid}", "type": "naver_blog", "blog_id": bid}
    elif is_gnu:
        src = {"id": f"gnuboard:{raw}", "type": "gnuboard", "board_url": raw}   # Gnuboard 게시판
    elif is_url:
        src = {"id": f"rss:{raw}", "type": "rss", "url": raw}   # RSS/Atom 주소로 간주
    else:
        raise ValueError("네이버 블로그 ID/주소 또는 RSS/게시판 주소를 입력하세요.")

    # 실제 수집 시도로 유효성 확인 + 기본 이름 추출
    posts = collect({**src, "name": "", "category": ""})
    if not posts:
        raise ValueError("글을 찾지 못했습니다. 주소/ID를 확인하세요(비공개·잘못된 주소일 수 있음).")
    return {"source": src, "sample_count": len(posts),
            "sample_name": posts[0].get("source_name") or src.get("blog_id") or src["id"]}

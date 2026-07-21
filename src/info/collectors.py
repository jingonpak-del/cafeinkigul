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


_ID_KEYS = ("nttId", "articleNo", "boardSeq", "bbsSeq", "idx", "seq", "no", "id", "num")


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
        if a is None:
            continue
        href = a.get("href") or ""
        link, post_key = None, None
        if href and not href.startswith("javascript") and not href.startswith("#"):
            link = _normalize_article_url(urljoin(base_url, href))
            post_key = _html_post_key(link)
        elif id_re:                                  # onclick 기반 상세 링크
            m = id_re.search(a.get("onclick") or "") or id_re.search(str(row))
            if not m:
                continue
            pid = m.group(1)
            post_key = f"id={pid}"
            link = url_tmpl.format(id=pid) if url_tmpl else urljoin(base_url, f"#{pid}")
        else:
            continue
        title = cell(row, source["title_selector"]) if source.get("title_selector") \
            else (a.get_text(strip=True) or (a.get("title") or "").strip())
        if not title:
            continue
        published = _parse_date_ms(cell(row, source.get("date_selector")))
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
    r = httpx.get(url, timeout=20, headers={"User-Agent": UA}, follow_redirects=True)
    r.raise_for_status()
    return _extract_items(r.text, url, source)


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


COLLECTORS = {
    "naver_blog": collect_naver_blog,
    "rss": collect_generic_rss,
    "html": collect_html,
    "browser": collect_browser,
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
    bid = parse_naver_blog_id(raw)

    if bid and (is_naver or not is_url):
        src = {"id": f"naver_blog:{bid}", "type": "naver_blog", "blog_id": bid}
    elif is_url:
        src = {"id": f"rss:{raw}", "type": "rss", "url": raw}   # RSS/Atom 주소로 간주
    else:
        raise ValueError("네이버 블로그 ID/주소 또는 RSS 주소를 입력하세요.")

    # 실제 수집 시도로 유효성 확인 + 기본 이름 추출
    posts = collect({**src, "name": "", "category": ""})
    if not posts:
        raise ValueError("글을 찾지 못했습니다. 주소/ID를 확인하세요(비공개·잘못된 주소일 수 있음).")
    return {"source": src, "sample_count": len(posts),
            "sample_name": posts[0].get("source_name") or src.get("blog_id") or src["id"]}

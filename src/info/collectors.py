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
    return collect_rss(source, feed, source.get("name") or blog_id)


def collect_generic_rss(source: dict) -> list[dict]:
    return collect_rss(source, source["url"], source.get("name") or source.get("url", ""))


COLLECTORS = {
    "naver_blog": collect_naver_blog,
    "rss": collect_generic_rss,
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

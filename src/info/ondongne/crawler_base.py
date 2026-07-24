from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import re

from .models import Event
from .classify import (
    classify_category,
    classify_audience,
    detect_price_type,
    extract_first_date,
    make_summary,
)


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._text)).strip()
            if text:
                self.links.append((text, self._href))
            self._href = None
            self._text = []


def fetch_html(url: str, timeout: int = 15) -> str:
    req = Request(
        url,
        headers={"User-Agent": "OndongneBot/0.1 (+local public event aggregation MVP)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ["utf-8", "cp949", "euc-kr"]:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


class GenericBoardCrawler:
    def __init__(self, source: dict):
        self.source = source

    def crawl(self, limit: int = 10) -> list[Event]:
        try:
            html = fetch_html(self.source["base_url"])
        except (HTTPError, URLError, TimeoutError, Exception) as exc:
            print(f"WARN crawl failed {self.source['id']}: {exc}")
            return []

        parser = LinkExtractor()
        parser.feed(html)
        events: list[Event] = []
        seen: set[str] = set()
        include = self.source.get("include_keywords", [])
        exclude = self.source.get("exclude_keywords", [])

        global_exclude = [
            "본문", "메뉴", "로그인", "회원가입", "사이트맵", "개인정보", "저작권",
            "빠른예약", "교육강좌", "체험견학", "이의신청안내", "일반여권", "온라인 재발급 신청",
            "창원문화재단", "평생학습", "평생학습프로그램", "평생학습 소식",
        ]

        for title, href in parser.links:
            clean_title = re.sub(r"\s+", " ", title).strip()
            if not href or href.startswith("#"):
                continue
            if len(clean_title) < 4 or clean_title in seen:
                continue
            if clean_title in {self.source.get("organization_name"), self.source.get("name")}:
                continue
            title_lower = clean_title.lower()
            if any(k.lower() in title_lower for k in global_exclude):
                continue
            if include and not any(k.lower() in title_lower for k in include):
                continue
            if exclude and any(k.lower() in title_lower for k in exclude):
                continue
            url = urljoin(self.source["base_url"], href)
            category = classify_category(clean_title, self.source.get("category_hint", "기타"))
            event = Event(
                source_id=self.source["id"],
                source_name=self.source["name"],
                organization_name=self.source["organization_name"],
                region_level1=self.source.get("region_level1", ""),
                region_level2=self.source.get("region_level2", ""),
                title=clean_title,
                source_url=url,
                category=category,
                summary=make_summary(clean_title, self.source["name"], category),
                target_audience=classify_audience(clean_title),
                event_start_date=extract_first_date(clean_title),
                price_type=detect_price_type(clean_title),
                tags=[category, self.source.get("region_level2", "")],
            ).finalize()
            events.append(event)
            seen.add(clean_title)
            if len(events) >= limit:
                break
        return events

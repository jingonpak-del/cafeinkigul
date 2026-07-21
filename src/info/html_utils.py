"""HTML 텍스트 유틸 (온동네 플랫폼에서 이식, stdlib 기반).

bs4 없이도 쓸 수 있는 순수 표준 라이브러리 도구. gnuboard collector 등에서 사용.
"""
from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import re


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "dt", "dd"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def get_text(self) -> str:
        text = unescape("".join(self.parts))
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text)
        return text.strip()


def strip_tags(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html or "")
    return parser.get_text()


def first_match(pattern: str, text: str, flags: int = re.S | re.I) -> str:
    m = re.search(pattern, text or "", flags)
    return m.group(1) if m else ""


def all_links(html: str, base_url: str = "") -> list[tuple[str, str]]:
    from urllib.parse import urljoin
    links = []
    for href, inner in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html or "", re.S | re.I):
        links.append((strip_tags(inner), urljoin(base_url, unescape(href))))
    return links

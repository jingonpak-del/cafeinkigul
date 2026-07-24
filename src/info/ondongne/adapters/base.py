from __future__ import annotations

from dataclasses import dataclass
from urllib.request import Request, urlopen

from ..attachment_extractor import MAX_ATTACHMENT_BYTES


@dataclass
class ListingItem:
    title: str
    url: str
    status: str = ""
    application_period_text: str = ""
    department: str = ""
    published_at: str | None = None


class AdapterBase:
    parser_version = "v1"

    def __init__(self, source: dict):
        self.source = source

    def fetch_html(self, url: str, timeout: int = 20) -> str:
        raw = self.fetch_bytes(url, timeout=timeout)
        for enc in ["utf-8", "cp949", "euc-kr"]:
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")

    def fetch_bytes(self, url: str, timeout: int = 20, max_bytes: int = MAX_ATTACHMENT_BYTES) -> bytes:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 OndongneBot/0.2"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read(max_bytes + 1)[:max_bytes]

    def crawl(self, since_days: int = 30, limit: int = 100):
        events = []
        for item in self.list_items(since_days=since_days, limit=limit):
            events.append(self.parse_detail(item))
        return events

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        raise NotImplementedError

    def parse_detail(self, item: ListingItem):
        raise NotImplementedError

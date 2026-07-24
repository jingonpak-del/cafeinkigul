from __future__ import annotations

from dataclasses import dataclass
from urllib.request import Request, urlopen

from ...procurement_models import ProcurementNotice


@dataclass
class ProcurementListingItem:
    title: str
    url: str
    notice_number: str = ""
    published_at: str | None = None
    application_period_text: str = ""
    organization_name: str = ""


class ProcurementAdapterBase:
    parser_version = "v1"

    def __init__(self, source: dict):
        self.source = source

    def fetch_bytes(self, url: str, timeout: int = 20, max_bytes: int = 5_000_000) -> bytes:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 OndongneProcurementBot/0.1"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read(max_bytes + 1)[:max_bytes]

    def fetch_html(self, url: str, timeout: int = 20) -> str:
        raw = self.fetch_bytes(url, timeout=timeout)
        for enc in ["utf-8", "cp949", "euc-kr"]:
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")

    def crawl(self, since_days: int = 30, limit: int = 100) -> list[ProcurementNotice]:
        notices: list[ProcurementNotice] = []
        for item in self.list_items(since_days=since_days, limit=limit):
            notice = self.parse_detail(item)
            notices.append(notice.finalize())
        return notices

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ProcurementListingItem]:
        raise NotImplementedError

    def parse_detail(self, item: ProcurementListingItem) -> ProcurementNotice:
        raise NotImplementedError

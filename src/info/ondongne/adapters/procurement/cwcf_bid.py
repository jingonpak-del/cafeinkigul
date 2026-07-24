from __future__ import annotations

from html import unescape
import re
from urllib.parse import quote, urljoin

from .base import ProcurementAdapterBase, ProcurementListingItem
from ...date_parser import is_within_days
from ...html_utils import all_links, first_match, strip_tags
from ...procurement_classifier import score_procurement_text
from ...procurement_models import NoticeAttachment, ProcurementNotice
from ...summarizer import summarize_event


class ChangwonCultureFoundationBidAdapter(ProcurementAdapterBase):
    """창원문화재단 열린마당 > 공지사항 > 입찰공고 parser."""

    parser_version = "cwcf_bid_v1"

    def fetch_html(self, url: str, timeout: int = 20) -> str:
        raw = self.fetch_bytes(url, timeout=timeout)
        return raw.decode("cp949", errors="ignore")

    def _list_url(self, page: int) -> str:
        base_url = self.source.get("base_url") or "https://www.cwcf.or.kr/commu/notice_list.asp?BCATE=BD00001&BSUBCATE=%C0%D4%C2%FB%B0%F8%B0%ED&place_idx="
        sep = "&" if "?" in base_url else "?"
        if page == 1:
            return base_url
        return f"{base_url}{sep}page={page}"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ProcurementListingItem]:
        items: list[ProcurementListingItem] = []
        seen: set[str] = set()
        page = 1
        while len(items) < limit and page <= 30:
            html = self.fetch_html(self._list_url(page))
            added = 0
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
                if "notice_view.asp" not in row:
                    continue
                href = first_match(r'href="([^"]*notice_view\.asp[^"]*)"', row)
                title = strip_tags(first_match(r"<a[^>]*>(.*?)</a>", row))
                cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
                published_at = self._parse_date(" ".join(cells))
                if published_at and not is_within_days(published_at, since_days):
                    continue
                if not href or not title:
                    continue
                href = quote(unescape(href), safe="/:?=&%")
                url = urljoin("https://www.cwcf.or.kr", href)
                if url in seen:
                    continue
                seen.add(url)
                items.append(ProcurementListingItem(title=title, url=url, published_at=published_at))
                added += 1
                if len(items) >= limit:
                    break
            if added == 0:
                break
            page += 1
        return items

    def crawl(self, since_days: int = 30, limit: int = 100) -> list[ProcurementNotice]:
        notices: list[ProcurementNotice] = []
        for item in self.list_items(since_days=since_days, limit=limit):
            notice = self.parse_detail(item)
            scored = score_procurement_text(" ".join([notice.title, notice.body_text, " ".join(a.name for a in notice.attachments)]))
            if scored["decision"] != "collect":
                continue
            notice.relevance_score = scored["score"]
            notice.matched_keywords = scored["matched_keywords"]
            notices.append(notice.finalize())
        return notices

    def parse_detail(self, item: ProcurementListingItem) -> ProcurementNotice:
        html = self.fetch_html(item.url)
        title = strip_tags(first_match(r'<span class="m-board-title">(.*?)</span>', html)) or item.title
        body_html = first_match(r'<div class="Detail-content">(.*?)(?:<div class="m-boardDetail-prev">|<div class="m-boards-btns)', html) or html
        body_text = strip_tags(body_html)
        published_at = self._parse_date(html) or item.published_at
        attachments = [
            NoticeAttachment(name=text or url, url=url)
            for text, url in all_links(html, item.url)
            if "download_file.asp" in url or "download" in url.lower()
        ]
        end_date = self._extract_deadline(body_text)
        return ProcurementNotice(
            source_id=self.source["id"],
            source_name=self.source["name"],
            organization_name=self.source.get("organization_name", "창원문화재단"),
            region_level1=self.source.get("region_level1", "경상남도"),
            region_level2=self.source.get("region_level2", "창원시"),
            title=title,
            source_url=item.url,
            notice_type="입찰공고",
            summary=summarize_event(title, body_text),
            body_text=body_text,
            published_at=published_at,
            application_end_date=end_date,
            apply_url=item.url,
            attachments=attachments,
            status="수집완료",
            parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _parse_date(text: str) -> str | None:
        m = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text or "")
        if m:
            y, mo, d = map(int, m.groups())
            return f"{y:04d}-{mo:02d}-{d:02d}"
        m = re.search(r"(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text or "")
        if m:
            y, mo, d = map(int, m.groups())
            return f"20{y:02d}-{mo:02d}-{d:02d}"
        return None

    @classmethod
    def _extract_deadline(cls, text: str) -> str | None:
        for label in ["접수기간", "제출기간", "입찰기간", "공고기간", "마감"]:
            idx = (text or "").find(label)
            if idx >= 0:
                dates = re.findall(r"20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}", text[idx:idx+200])
                if dates:
                    return cls._parse_date(dates[-1])
        return None

from __future__ import annotations

from html import unescape
import re
from urllib.parse import urljoin

from .base import ProcurementAdapterBase, ProcurementListingItem
from ...date_parser import is_within_days
from ...html_utils import all_links, first_match, strip_tags
from ...procurement_classifier import score_procurement_text
from ...procurement_models import NoticeAttachment, ProcurementNotice
from ...summarizer import summarize_event


class ChangwonCityBidAdapter(ProcurementAdapterBase):
    """창원특례시 기업경제정보 > 경제고시공고 parser.

    This board includes employment/economy notices and occasional event-related
    bid notices such as 행사 대행 용역. The adapter fetches list rows, filters by
    publication date window, parses detail pages, then applies the procurement
    relevance classifier so unrelated hiring notices are dropped.
    """

    parser_version = "changwon_city_bid_v1"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ProcurementListingItem]:
        items: list[ProcurementListingItem] = []
        page = 1
        base_url = self.source["base_url"]
        while len(items) < limit and page <= 80:
            sep = "&" if "?" in base_url else "?"
            url = base_url if page == 1 else f"{base_url}{sep}cpage={page}"
            html = self.fetch_html(url)
            tbody = first_match(r'<tbody[^>]*class="tb"[^>]*>(.*?)</tbody>', html) or first_match(r'<tbody[^>]*>(.*?)</tbody>', html)
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.S | re.I)
            if not rows:
                break
            added_on_page = 0
            stop_for_old = False
            for row in rows:
                cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
                if len(cells) < 5:
                    continue
                notice_number = strip_tags(cells[1])
                href = first_match(r'<a[^>]+href="([^"]+)"', cells[2])
                title = strip_tags(cells[2])
                department = strip_tags(cells[3])
                published_at = strip_tags(cells[4])
                if published_at and not is_within_days(published_at, since_days):
                    stop_for_old = True
                    continue
                if not href or "amode=view" not in href:
                    continue
                detail_url = urljoin(url, unescape(href))
                items.append(
                    ProcurementListingItem(
                        title=title,
                        url=detail_url,
                        notice_number=notice_number,
                        published_at=published_at,
                        organization_name=department,
                    )
                )
                added_on_page += 1
                if len(items) >= limit:
                    break
            if stop_for_old and added_on_page == 0:
                break
            page += 1
        return items

    def crawl(self, since_days: int = 30, limit: int = 100) -> list[ProcurementNotice]:
        notices: list[ProcurementNotice] = []
        for item in self.list_items(since_days=since_days, limit=limit):
            notice = self.parse_detail(item)
            attachment_text = " ".join(a.name for a in notice.attachments)
            scored = score_procurement_text(" ".join([notice.title, notice.body_text, attachment_text]))
            if scored["decision"] != "collect" or not self._has_event_anchor(scored["matched_keywords"]):
                continue
            notice.relevance_score = scored["score"]
            notice.matched_keywords = scored["matched_keywords"]
            notices.append(notice.finalize())
        return notices

    @staticmethod
    def _has_event_anchor(matched_keywords: list[str]) -> bool:
        anchors = {
            "행사",
            "축제",
            "페스티벌",
            "문화행사",
            "기념행사",
            "개막식",
            "폐막식",
            "콘서트",
            "공연",
            "전시",
            "박람회",
            "부스",
            "체험부스",
            "홍보부스",
            "푸드트럭",
            "플리마켓",
            "프리마켓",
        }
        return any(term in anchors for term in matched_keywords)

    def parse_detail(self, item: ProcurementListingItem) -> ProcurementNotice:
        html = self.fetch_html(item.url)
        view_html = first_match(r'<div class="bbs1view1">(.*?)(?:<div class="infomenu1">|</form>)', html) or html
        title = strip_tags(first_match(r'<h1[^>]*class="h1"[^>]*>(.*?)</h1>', view_html)) or item.title
        info_html = first_match(r'<div class="info1">(.*?)</div>', view_html)
        info_text = strip_tags(info_html)
        notice_number = self._info_value(info_text, "고시번호") or item.notice_number
        published_at = self._info_value(info_text, "게재일자") or item.published_at
        period_text = self._info_value(info_text, "공고기간")
        department = self._info_value(info_text, "담당부서") or item.organization_name
        contact = self._info_value(info_text, "연락처")
        application_start_date, application_end_date = self._parse_period(period_text)
        body_html = first_match(r'<div class="substance">(.*?)</div>', view_html) or ""
        body_text = strip_tags(body_html)
        summary = summarize_event(title, body_text)
        attachments = [
            NoticeAttachment(name=text or url, url=url)
            for text, url in all_links(first_match(r'<div class="attach1">(.*?)</div>', view_html) or "", item.url)
        ]
        scored = score_procurement_text(" ".join([title, body_text, " ".join(a.name for a in attachments)]))
        return ProcurementNotice(
            source_id=self.source["id"],
            source_name=self.source["name"],
            organization_name=self.source.get("organization_name", "창원특례시"),
            region_level1=self.source.get("region_level1", "경상남도"),
            region_level2=self.source.get("region_level2", "창원시"),
            title=title,
            source_url=item.url,
            notice_type="입찰공모",
            summary=summary,
            body_text=body_text,
            published_at=published_at,
            application_start_date=application_start_date,
            application_end_date=application_end_date,
            target=department,
            apply_url=item.url,
            notice_number=notice_number,
            attachments=attachments,
            matched_keywords=scored["matched_keywords"],
            relevance_score=scored["score"],
            status="수집완료",
            parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _info_value(info_text: str, label: str) -> str:
        text = re.sub(r"\s+", " ", info_text or "").strip()
        pattern = re.escape(label) + r"\s*:?\s*(.*?)(?=고시번호|게재일자|공고기간|담당부서|연락처|$)"
        m = re.search(pattern, text)
        return m.group(1).strip(" :") if m else ""

    @staticmethod
    def _parse_period(period_text: str) -> tuple[str | None, str | None]:
        text = re.sub(r"\D", "", period_text or "")
        if len(text) >= 16:
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}", f"{text[8:12]}-{text[12:14]}-{text[14:16]}"
        return None, None

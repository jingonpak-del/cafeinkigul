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


class GimhaeCityNoticeAdapter(ProcurementAdapterBase):
    """김해시청 > 고시공고 parser.

    Gimhae's dedicated 입찰공고 page is a G2B handoff page, so this adapter first
    stabilizes the municipal 고시공고 board for event-related public calls and
    모집/지원 notices that are mirrored as normal GET pages with body text and
    attachments. A separate G2B adapter can be added later for full bid coverage.
    """

    parser_version = "gimhae_city_notice_v1"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ProcurementListingItem]:
        items: list[ProcurementListingItem] = []
        seen_urls: set[str] = set()
        base_url = self.source["base_url"]
        page = 1
        while len(items) < limit and page <= 160:
            sep = "&" if "?" in base_url else "?"
            url = f"{base_url}{sep}cpage={page}"
            html = self.fetch_html(url)
            list_html = first_match(r'<div[^>]+class="list1f1t3i1"[^>]*>(.*?)(?:<div class="paging|<div class="infomenu1">)', html) or html
            rows = re.findall(r'<li[^>]+class="li1"[^>]*>(.*?)</li>', list_html, re.S | re.I)
            if not rows:
                break
            added_on_page = 0
            stop_for_old = False
            for row in rows:
                href = first_match(r'<a[^>]+href="([^"]+)"', row)
                title = strip_tags(first_match(r'<strong[^>]+class="t1"[^>]*>(.*?)</strong>', row))
                if not href or not title:
                    continue
                meta = self._parse_meta(row)
                published_at = meta.get("등록일") or meta.get("게재일자")
                if published_at and not is_within_days(published_at, since_days):
                    stop_for_old = True
                    continue
                detail_url = urljoin(url, unescape(href))
                if detail_url in seen_urls:
                    continue
                seen_urls.add(detail_url)
                items.append(
                    ProcurementListingItem(
                        title=title,
                        url=detail_url,
                        notice_number=meta.get("고시번호", ""),
                        published_at=published_at,
                        application_period_text=meta.get("공고기간", ""),
                        organization_name=meta.get("담당부서", ""),
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
            # 김해 고시공고는 도시계획/차량/행정공고가 매우 많다. 제목에 행사성
            # anchor가 없는 행은 상세 fetch 전에 제외하고, 상세 파싱 후 다시
            # 본문+첨부명 기준 점수화를 수행한다.
            if not self._has_event_anchor_in_text(item.title):
                continue
            notice = self.parse_detail(item)
            attachment_text = " ".join(a.name for a in notice.attachments)
            relevance_text = " ".join([notice.title, notice.body_text, attachment_text])
            scored = score_procurement_text(relevance_text)
            if scored["decision"] != "collect" or not self._has_event_anchor_in_text(relevance_text):
                continue
            notice.relevance_score = scored["score"]
            notice.matched_keywords = scored["matched_keywords"]
            notices.append(notice.finalize())
        return notices

    @classmethod
    def _has_event_anchor_in_text(cls, text: str) -> bool:
        text = text or ""
        anchors = {
            "축제",
            "페스티벌",
            "문화행사",
            "기념행사",
            "개막식",
            "폐막식",
            "콘서트",
            "공연",
            "박람회",
            "부스",
            "체험부스",
            "홍보부스",
            "푸드트럭",
            "플리마켓",
            "프리마켓",
        }
        if any(term in text for term in anchors):
            return True
        # Avoid Korean substring traps: 권리행사/여행사 are not events.
        if re.search(r"(?<!권리)(?<!여)행사", text):
            return True
        # 전시 is often legitimate, but appears as a substring in 시설/충전시설.
        if re.search(r"(?<!충전)(?<!전)전시", text):
            return True
        return False

    def parse_detail(self, item: ProcurementListingItem) -> ProcurementNotice:
        html = self.fetch_html(item.url)
        view_html = first_match(r'<div class="bbs1view1">(.*?)(?:<div class="infomenu1">|</form>)', html) or html
        title = strip_tags(first_match(r'<h1[^>]*class="h1"[^>]*>(.*?)</h1>', view_html)) or item.title
        info_html = first_match(r'<div class="info1">(.*?)</div>', view_html) or ""
        info = self._parse_dt_dd(info_html)
        notice_number = info.get("고시번호") or item.notice_number
        published_at = info.get("게재일자") or item.published_at
        period_text = info.get("공고기간") or item.application_period_text
        department = info.get("담당부서") or item.organization_name
        contact = info.get("연락처") or ""
        application_start_date, application_end_date = self._parse_period(period_text)
        body_html = first_match(r'<div class="substance">(.*?)</div>', view_html) or ""
        body_text = strip_tags(body_html)
        if contact and contact not in body_text:
            body_text = f"{body_text}\n문의: {contact}".strip()
        summary = summarize_event(title, body_text)
        attachments = [
            NoticeAttachment(name=text or url, url=url)
            for text, url in all_links(first_match(r'<div class="attach1">(.*?)</div>', view_html) or "", item.url)
        ]
        scored = score_procurement_text(" ".join([title, body_text, " ".join(a.name for a in attachments)]))
        return ProcurementNotice(
            source_id=self.source["id"],
            source_name=self.source["name"],
            organization_name=self.source.get("organization_name", "김해시"),
            region_level1=self.source.get("region_level1", "경상남도"),
            region_level2=self.source.get("region_level2", "김해시"),
            title=title,
            source_url=item.url,
            notice_type="고시공고",
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
    def _parse_meta(row_html: str) -> dict[str, str]:
        meta: dict[str, str] = {}
        for text in re.findall(r'<span[^>]+class="t3"[^>]*>(.*?)</span>', row_html, re.S | re.I):
            clean = strip_tags(text)
            if ":" in clean:
                key, value = clean.split(":", 1)
                meta[key.strip()] = value.strip()
        return meta

    @staticmethod
    def _parse_dt_dd(info_html: str) -> dict[str, str]:
        info: dict[str, str] = {}
        pairs = re.findall(r'<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>', info_html, re.S | re.I)
        for key_html, value_html in pairs:
            key = strip_tags(key_html).strip(" :")
            value = strip_tags(value_html).strip()
            if key:
                info[key] = value
        return info

    @staticmethod
    def _parse_period(period_text: str) -> tuple[str | None, str | None]:
        text = period_text or ""
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        if len(dates) >= 2:
            return dates[0], dates[1]
        digits = re.findall(r"\d{8}", text)
        if len(digits) >= 2:
            return f"{digits[0][:4]}-{digits[0][4:6]}-{digits[0][6:8]}", f"{digits[1][:4]}-{digits[1][4:6]}-{digits[1][6:8]}"
        if len(digits) == 1:
            return f"{digits[0][:4]}-{digits[0][4:6]}-{digits[0][6:8]}", None
        return None, None

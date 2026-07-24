from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

import requests

from .base import AdapterBase, ListingItem
from .generic_gnuboard import GenericGnuboardAdapter
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range, parse_first_date
from ..html_utils import first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class ChangwonWomenAssociationNoticeAdapter(GenericGnuboardAdapter):
    parser_version = "changwon_women_association_notice_v1"
    board_url = "http://cwwoman.org/bbs/board.php?bo_table=notice"
    default_location = "창원시"
    default_category = "공익활동"
    tags_extra = ["여성", "성평등", "돌봄"]
    include_keywords = ["모집", "신청", "참여", "교육", "프로그램", "상담", "캠페인", "돌봄", "여성", "평등", "강좌"]
    negative_keywords = [
        *GenericGnuboardAdapter.negative_keywords,
        "정기총회", "후원", "결산", "채용", "활동보고", "소식지", "보도자료",
    ]


class ChangwonDisabledFamilySupportNoticeAdapter(GenericGnuboardAdapter):
    parser_version = "changwon_disabled_family_support_notice_v1"
    board_url = "http://ns2.barom.net/~cwbumo/bbs/board.php?bo_table=06_01"
    default_location = "창원장애인가족지원센터"
    default_category = "복지건강"
    tags_extra = ["장애인가족", "부모교육", "상담"]
    include_keywords = ["모집", "신청", "참여", "교육", "프로그램", "상담", "부모", "가족", "장애", "체험", "공연"]
    negative_keywords = [
        *GenericGnuboardAdapter.negative_keywords,
        "채용", "합격", "제공인력", "실습생", "공고", "예산", "결산",
    ]

    def _canonical_url(self, url: str) -> str:
        m_board = re.search(r"bo_table=([^&]+)", url)
        m_id = re.search(r"wr_id=(\d+)", url)
        if m_board and m_id:
            return f"http://ns2.barom.net/~cwbumo/bbs/board.php?bo_table={m_board.group(1)}&wr_id={m_id.group(1)}"
        return url.replace("http://ns2.barom.net/bbs/", "http://ns2.barom.net/~cwbumo/bbs/")


class ChangwonDisabledRightsCenterNoticeAdapter(GenericGnuboardAdapter):
    parser_version = "changwon_disabled_rights_center_notice_v1"
    board_url = "http://www.cwdhl.or.kr/bbs/board.php?bo_table=sub04_01"
    default_location = "창원장애인인권센터"
    default_category = "복지건강"
    tags_extra = ["장애인권", "인식개선", "교육"]
    include_keywords = ["모집", "신청", "참여", "교육", "프로그램", "강사", "인권", "인식개선", "상담", "캠페인"]
    negative_keywords = [
        *GenericGnuboardAdapter.negative_keywords,
        "채용", "합격", "회의", "총회", "결산", "성명서", "보도자료",
    ]


class GyeongnamRegionalChildCenterNoticeAdapter(GenericGnuboardAdapter):
    parser_version = "gyeongnam_regional_child_center_notice_v1"
    board_url = "https://www.gnicare.kr/bbs/board.php?bo_table=03_01"
    default_location = "경남/창원 지역아동센터"
    default_category = "아동청소년"
    tags_extra = ["지역아동센터", "아동복지", "지원사업"]
    include_keywords = ["모집", "신청", "지원", "사업", "교육", "프로그램", "아동", "돌봄", "체험", "상담", "기관"]
    negative_keywords = [
        *GenericGnuboardAdapter.negative_keywords,
        "채용", "합격", "직원", "연장공고", "현황조사", "시스템", "점검",
    ]


class ChangwonChildcareSupportCenterNoticeAdapter(AdapterBase):
    """Source-specific adapter for the ASP board used by 창원시육아종합지원센터."""

    parser_version = "changwon_childcare_support_center_notice_v1"
    list_url = "http://ec.changwon.go.kr/community/board_list.asp"
    default_location = "창원시육아종합지원센터"
    default_category = "아동청소년"
    tags_extra = ["육아", "보육", "부모교육"]
    include_keywords = ["신청", "모집", "교육", "프로그램", "상담", "체험", "육아", "부모", "보육", "대체교사"]
    negative_keywords = ["채용", "합격", "공고", "입찰", "계약", "점검", "휴관", "보도자료", "결과", "자료집"]

    def fetch_html(self, url: str, timeout: int = 20) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept": "text/html",
        }
        resp = requests.get(url, headers=headers, timeout=timeout, verify=False)
        resp.raise_for_status()
        resp.encoding = resp.encoding or "utf-8"
        return resp.text

    def _page_url(self, page: int) -> str:
        return self.list_url if page == 1 else f"{self.list_url}?page={page}"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, 3):
            html = self.fetch_html(self._page_url(page))
            for item in self.parse_list_html(html):
                if item.url in seen or not self._is_relevant(item.title):
                    continue
                if item.published_at and not is_within_days(item.published_at, since_days):
                    continue
                items.append(item)
                seen.add(item.url)
                if len(items) >= limit:
                    return items
        return items

    def parse_list_html(self, html: str) -> list[ListingItem]:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I)
        items: list[ListingItem] = []
        for row in rows:
            m = re.search(r'<a[^>]+href=["\']([^"\']*board_view\.asp\?sn=\d+[^"\']*)["\'][^>]*>(.*?)</a>', row, re.S | re.I)
            if not m:
                continue
            href, inner = m.groups()
            title = self._clean_title(strip_tags(inner))
            date_text = first_match(r"(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})", row)
            if title:
                items.append(ListingItem(title=title, url=urljoin(self.list_url, unescape(href).replace("&amp;", "&")), status="공지사항", published_at=parse_first_date(date_text)))
        return items

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = self._clean_title(strip_tags(first_match(r'<div[^>]+class=["\'][^"\']*(?:view_tit|title|subject)[^"\']*["\'][^>]*>(.*?)</div>', html)))
        if not title:
            title = self._clean_title(strip_tags(first_match(r'<th[^>]*>\s*제목\s*</th>\s*<td[^>]*>(.*?)</td>', html)))
        if not title:
            title = self._clean_title(strip_tags(first_match(r"<title[^>]*>(.*?)</title>", html)))
        if fallback and (not title or title.startswith("공지사항 HOME") or title == "공지사항"):
            title = fallback.title
        body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:view_cont|view_content|board_view|contents)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\'][^"\']*(?:btn|prev|next)|</section>)', html)
        if not body_html:
            body_html = first_match(r'<td[^>]+class=["\'][^"\']*(?:content|view)[^"\']*["\'][^>]*>(.*?)</td>', html)
        body_text = strip_tags(body_html) or title
        if len(body_text) < 40 and fallback:
            body_text = fallback.title
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        app_rng = self._extract_range(body_text, ["신청기간", "접수기간", "모집기간", "신청", "접수"])
        event_rng = self._extract_range(body_text, ["교육기간", "운영기간", "행사기간", "일시", "일정", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "신청대상", "참여대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "운영장소", "위치"])
        text = f"{title} {body_text}"
        category = classify_category(text, self.source.get("category_hint", self.default_category))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text), location_name=location or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=(fallback.published_at if fallback else None),
            apply_url=url, attachment_urls=[], image_urls=image_urls,
            tags=[t for t in [category, "창원시", *self.tags_extra] if t], parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\b\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}\b", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|[\n\r\s▶□○-])" + re.escape(label) + r"(?![가-힣A-Za-z0-9])\s*[:：-]?\s*([^\n\r]{2,100})", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

    @staticmethod
    def _extract_range(text: str, labels: list[str]) -> DateRange:
        for label in labels:
            m = re.search(re.escape(label) + r"\s*[:：-]?\s*([^\n\r]{0,180})", text or "")
            if m:
                rng = parse_date_range(m.group(0))
                if rng.start:
                    return rng
        return extract_labeled_range(text, labels) or DateRange()

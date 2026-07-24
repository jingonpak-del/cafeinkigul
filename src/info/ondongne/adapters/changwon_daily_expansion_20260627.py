from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from .changwon_city_public_boards_20260620 import ChangwonCityPublicBoardAdapter
from .generic_gnuboard import GenericGnuboardAdapter
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class ChangwonMilitaryBandFestivalAdapter(ChangwonCityPublicBoardAdapter):
    """진해군악의장페스티벌 공지사항: 축제 주관/참여/운영 공지."""

    parser_version = "changwon_military_band_festival_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11063/11090/14438.web?gcode=1439"
    default_location = "진해군악의장페스티벌"
    default_category = "문화"
    tags_extra = ["진해", "군악의장페스티벌", "축제"]
    include_keywords = ["모집", "공모", "참여", "행사", "축제", "페스티벌", "공연", "평가위원", "주관단체", "운영"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "교통통제", "분실물", "결과 발표", "선정 결과"]


class ChangwonDemocracyNoticeAdapter(ChangwonCityPublicBoardAdapter):
    """민주성지 창원 공지사항: 민주화 탐방/기념행사/교육 공지."""

    parser_version = "changwon_democracy_notice_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/12480/12827.web"
    default_location = "민주성지 창원"
    default_category = "문화"
    tags_extra = ["민주성지", "민주화운동", "탐방"]
    include_keywords = ["모집", "신청", "참여", "탐방", "교육", "체험", "기념", "행사", "해설", "프로그램"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "자료", "기록물", "회의", "결과"]


class ChangwonYmcaNoticeAdapter(AdapterBase):
    """창원YMCA 자체 보드(`/board/index/<menu>/view/b_seq/<id>`) 공지사항."""

    parser_version = "changwon_ymca_notice_v1"
    board_url = "http://www.cwymca.or.kr/board/index/MUSW1560415640"
    base = "http://www.cwymca.or.kr"
    default_location = "창원YMCA"
    include_keywords = ["모집", "신청", "참여", "교육", "프로그램", "강좌", "교실", "공모전", "청소년", "기후", "환경", "소비자"]
    negative_keywords = ["채용", "합격", "입찰", "계약", "결산", "총회", "회의", "성명서", "기부몰", "보도자료"]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, 4):
            url = self.board_url if page == 1 else f"{self.board_url}/page/{page}"
            try:
                html = self.fetch_html(url)
            except Exception:
                break
            added = 0
            for item in self.parse_list_html(html):
                if item.url in seen or not self._is_relevant(item.title):
                    continue
                if item.published_at and not is_within_days(item.published_at, since_days):
                    continue
                items.append(item); seen.add(item.url); added += 1
                if len(items) >= limit:
                    return items
            if page > 1 and added == 0:
                break
        return items

    def parse_list_html(self, html: str) -> list[ListingItem]:
        items: list[ListingItem] = []
        pat = r'<a[^>]+href=["\']([^"\']*/board/index/MUSW1560415640/view/b_seq/\d+)["\'][^>]*>(.*?)</a>'
        for href, inner in re.findall(pat, html or "", re.S | re.I):
            title = self._clean_title(strip_tags(inner))
            if not title or title.isdigit():
                continue
            around = html[max(0, (html or "").find(href) - 300):(html or "").find(href) + 500]
            published_at = parse_first_date(around)
            items.append(ListingItem(title=title, url=urljoin(self.base, unescape(href)), status="공지사항", published_at=published_at))
        return self._dedupe(items)

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = self._clean_title(strip_tags(first_match(r'<h[1234][^>]*>(.*?)</h[1234]>', html))) or (fallback.title if fallback else "")
        if not title or title in {"공지사항", "창원YMCA"}:
            title = fallback.title if fallback else title
        body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:board_view|view|contents|content)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\'][^"\']*(?:btn|comment)|</section>|</article>)', html)
        if not body_html:
            body_html = first_match(r'<body[^>]*>(.*?)</body>', html)
        body_text = strip_tags(body_html) or title
        body_text = re.sub(r"조회수\s*\d+", " ", body_text)
        body_text = re.sub(r"\s+", " ", body_text).strip()[:7000]
        published_at = parse_first_date(body_text) or (fallback.published_at if fallback else None)
        return self._make_event(title, body_text, url, published_at, html)

    def _make_event(self, title: str, body_text: str, url: str, published_at: str | None, html: str) -> Event:
        app_rng = self._extract_range(body_text, ["신청기간", "접수기간", "모집기간", "접수", "신청"])
        event_rng = self._extract_range(body_text, ["행사기간", "교육기간", "운영기간", "일시", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "참여대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소"])
        text = title + " " + body_text
        category = classify_category(text, self.source.get("category_hint", "공익활동"))
        attachment_urls = [link for _, link in all_links(html, url) if "download" in link.lower() or "file" in link.lower()]
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text), location_name=location or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status="공지사항", published_at=published_at,
            apply_url=url, attachment_urls=attachment_urls, tags=[category, "창원시", "YMCA"], parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"-->", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:180].rstrip() + ("…" if len(text) > 180 else "")

    @staticmethod
    def _dedupe(items: list[ListingItem]) -> list[ListingItem]:
        out: list[ListingItem] = []
        seen: set[str] = set()
        for item in items:
            if item.url not in seen:
                out.append(item); seen.add(item.url)
        return out

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


class ChangwonYwcaNoticeAdapter(AdapterBase):
    """창원YWCA base64-query board parser."""

    parser_version = "changwon_ywca_notice_v1"
    board_url = "http://www.cwywca.or.kr/sub/board/board_list.html?Ym9hcmRfY29kZT0x"
    base = "http://www.cwywca.or.kr"
    default_location = "창원YWCA"
    include_keywords = ["모집", "신청", "참여", "교육", "프로그램", "강좌", "교실", "특강", "일본어", "파크골프", "돌봄", "여성"]
    negative_keywords = ["채용", "합격", "결산", "공시", "선거", "정책제안", "성명서", "자료", "결과"]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for url in [self.board_url]:
            html = self.fetch_html(url)
            for item in self.parse_list_html(html):
                if item.url in seen or not self._is_relevant(item.title):
                    continue
                if item.published_at and not is_within_days(item.published_at, since_days):
                    continue
                items.append(item); seen.add(item.url)
                if len(items) >= limit:
                    return items
        return items

    def parse_list_html(self, html: str) -> list[ListingItem]:
        items: list[ListingItem] = []
        pat = r'<a[^>]+href=["\']([^"\']*board_read\.html\?[^"\']+)["\'][^>]*>(.*?)</a>'
        for href, inner in re.findall(pat, html or "", re.S | re.I):
            title = self._clean_title(strip_tags(inner))
            if not title or title.isdigit():
                continue
            pos = (html or "").find(href)
            around = html[max(0, pos - 300):pos + 600]
            items.append(ListingItem(title=title, url=urljoin(self.base, unescape(href)), status="공지사항", published_at=parse_first_date(around)))
        return ChangwonYmcaNoticeAdapter._dedupe(items)

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = self._clean_title(strip_tags(first_match(r'<h[1234][^>]*>(.*?)</h[1234]>', html))) or (fallback.title if fallback else "")
        if not title or "공지사항" in title:
            title = fallback.title if fallback else title
        body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:board_view|view|content|board_read)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\'][^"\']*(?:btn|comment|reply)|</section>|</article>)', html)
        if not body_html:
            body_html = first_match(r'<body[^>]*>(.*?)</body>', html)
        body_text = strip_tags(body_html) or title
        body_text = re.sub(r"조회수\s*\d+", " ", body_text)
        body_text = re.sub(r"\s+", " ", body_text).strip()[:7000]
        published_at = parse_first_date(body_text) or (fallback.published_at if fallback else None)
        app_rng = ChangwonYmcaNoticeAdapter._extract_range(body_text, ["신청기간", "접수기간", "모집기간", "접수", "신청"])
        event_rng = ChangwonYmcaNoticeAdapter._extract_range(body_text, ["교육기간", "행사기간", "운영기간", "일시", "기간"])
        target = ChangwonYmcaNoticeAdapter._extract_labeled_value(body_text, ["대상", "모집대상", "참여대상"])
        location = ChangwonYmcaNoticeAdapter._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소"])
        text = title + " " + body_text
        category = classify_category(text, self.source.get("category_hint", "공익활동"))
        attachment_urls = [link for _, link in all_links(html, url) if "download" in link.lower() or "file" in link.lower()]
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text), location_name=location or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status="공지사항", published_at=published_at,
            apply_url=url, attachment_urls=attachment_urls, tags=[category, "창원시", "YWCA"], parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _clean_title(text: str) -> str:
        return ChangwonYmcaNoticeAdapter._clean_title(text)


class GyeongnamCultureArtsNoticeAdapter(GenericGnuboardAdapter):
    """경남문화예술진흥원 공고/공지: 도민 대상 문화·콘텐츠 프로그램."""

    parser_version = "gyeongnam_culture_arts_notice_v1"
    board_url = "https://www.gcaf.or.kr/bbs/board.php?bo_table=sub3_1"
    allowed_boards = ["sub3_1"]
    default_location = "경남문화예술진흥원/도민의 집/경남 일원"
    default_category = "문화"
    tags_extra = ["경남문화예술진흥원", "문화예술", "콘텐츠"]
    include_keywords = ["모집", "참여", "수강생", "행사", "교육", "아카데미", "캠프", "프로그램", "문화", "예술", "콘텐츠", "이스포츠"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "입찰", "용역", "평가 결과", "심사 결과", "이벤트 결과", "선정심사 결과", "대관(전시홀) 심사"]

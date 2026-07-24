from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from .changwon_public_extra_boards import PublicSimpleBoardAdapter
from .generic_gnuboard import GenericGnuboardAdapter
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class ChangwonSocialWelfareCenterAdapter(PublicSimpleBoardAdapter):
    """창원종합사회복지관 Rhymix/XE 공지사항."""

    parser_version = "changwon_social_welfare_center_v1"
    board_url = "http://cs.cathms.kr/xe/board_cbSK71"
    page_param = "page"
    url_pattern = r"(?:https?://cs\.cathms\.kr)?/xe/board_cbSK71/\d+"
    default_location = "창원종합사회복지관"
    default_category = "복지건강"
    tags_extra = ["종합사회복지관", "복지", "창원"]
    include_keywords = ["모집", "신청", "프로그램", "수강", "교육", "참여", "복지", "상담", "공간"]
    negative_keywords = [*PublicSimpleBoardAdapter.negative_keywords, "채용", "합격", "서류", "납품 업체", "업무추진비", "후원금", "결산", "푸드마켓"]

    def _canonical_url(self, url: str) -> str:
        m = re.search(r"/xe/board_cbSK71/(\d+)", url)
        if m:
            return f"http://cs.cathms.kr/xe/board_cbSK71/{m.group(1)}"
        return url


class ChangwonDisabledParentsAssociationAdapter(GenericGnuboardAdapter):
    """창원시장애인부모회 공지사항."""

    parser_version = "changwon_disabled_parents_association_v1"
    board_url = "https://www.cwbumo.or.kr/bbs/board.php?bo_table=06_01"
    allowed_boards = ["06_01"]
    default_location = "창원시장애인부모회"
    default_category = "복지건강"
    tags_extra = ["장애인가족", "부모회", "복지"]
    include_keywords = ["모집", "신청", "프로그램", "교육", "장애인", "가족", "부모", "상담", "티켓", "수영대회", "자조모임"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "제공인력", "전담인력", "선정 안내", "수령 방법", "정회원", "이사회"]


class ChangwonIndependentLivingCenterAdapter(GenericGnuboardAdapter):
    """창원장애인자립생활센터 공지사항."""

    parser_version = "changwon_independent_living_center_v1"
    board_url = "http://www.cwil.or.kr/bbs/board.php?bo_table=sub05_01"
    allowed_boards = ["sub05_01"]
    default_location = "창원장애인자립생활센터"
    default_category = "복지건강"
    tags_extra = ["장애인자립생활", "동료상담", "일자리"]
    include_keywords = ["모집", "참여자", "동료상담", "교육", "일자리", "권리중심", "인권", "복지박람회", "현장실습"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "전담인력", "직원", "정기총회", "대표 선출"]


class ChangwonScienceGiftedEducationCenterAdapter(GenericGnuboardAdapter):
    """국립창원대학교 과학영재교육원 공지사항."""

    parser_version = "changwon_science_gifted_education_center_v1"
    board_url = "http://www.ctysc.or.kr/bbs/board.php?bo_table=06_01"
    allowed_boards = ["06_01"]
    default_location = "국립창원대학교 과학영재교육원"
    default_category = "교육"
    tags_extra = ["과학", "영재교육", "청소년"]
    include_keywords = ["모집", "신청", "교육", "프로그램", "캠프", "선교육", "영재", "과학", "탐험대", "올림피아드"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "휴무", "대체휴무", "공실", "통행료", "주차요금", "명단", "선정자", "확정자"]


class JinhaeWestSeniorWelfareCenterAdapter(GenericGnuboardAdapter):
    """진해서부노인종합복지관 프로그램 소식."""

    parser_version = "jinhae_west_senior_welfare_center_v1"
    board_url = "https://www.jhsbsw.or.kr/bbs/board.php?bo_table=04_01&sca=%ED%94%84%EB%A1%9C%EA%B7%B8%EB%9E%A8+%EC%86%8C%EC%8B%9D"
    allowed_boards = ["04_01"]
    default_location = "진해서부노인종합복지관"
    default_category = "복지건강"
    tags_extra = ["노인복지", "진해", "평생교육"]
    include_keywords = ["모집", "참여자", "수강생", "교육", "프로그램", "상담", "특강", "문화체험", "건강", "디지털", "노년사회화"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "마감", "선정", "결과", "일정 안내", "커트", "네일"]


class ChangwonWomenWorkCenterAdapter(AdapterBase):
    """창원여성인력개발센터 자체 UTF-8 board."""

    parser_version = "changwon_women_work_center_v1"
    board_url = "http://cwcenter.or.kr/kor/information/notice.html"
    default_location = "창원여성인력개발센터"
    include_keywords = ["모집", "교육", "훈련", "수강", "취업", "창업", "신청", "직무", "국비", "새일", "참가"]
    negative_keywords = ["채용", "합격", "면접", "점검", "휴관", "보도자료", "결과", "선정", "사용 안내", "피해지원금", "생활지원금"]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, 3):
            url = self.board_url if page == 1 else f"{self.board_url}?code=notice&subcode=&page={page}&bbsData=&search=&p=&searchstring="
            html = self.fetch_html(url)
            for item in self.parse_list_html(html, url):
                if item.url in seen or not self._is_relevant(item.title):
                    continue
                if item.published_at and not is_within_days(item.published_at, since_days):
                    continue
                items.append(item)
                seen.add(item.url)
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
        return items

    def parse_list_html(self, html: str, base_url: str | None = None) -> list[ListingItem]:
        base_url = base_url or self.board_url
        items: list[ListingItem] = []
        href_re = r'<a[^>]+href=["\']([^"\']*bbsData=[^"\']+mode=view[^"\']*)["\'][^>]*>(.*?)</a>'
        for href, inner in re.findall(href_re, html or "", re.S | re.I):
            title = self._clean_title(strip_tags(inner))
            if not title or title in {"공지사항", "정보마당"}:
                continue
            full = urljoin(base_url, unescape(href).replace("&amp;", "&"))
            items.append(ListingItem(title=title, url=self._canonical_url(full), status="공지사항"))
        deduped: list[ListingItem] = []
        seen: set[str] = set()
        for item in items:
            if item.url not in seen:
                deduped.append(item)
                seen.add(item.url)
        return deduped

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = self._clean_title(strip_tags(first_match(r'<h3[^>]+class=["\']bbs_head_top["\'][^>]*>(.*?)</h3>', html)) or (fallback.title if fallback else ""))
        info = strip_tags(first_match(r'<div[^>]+class=["\']bbs_head["\'][^>]*>(.*?)</div>', html))
        published_at = parse_first_date(info) or (fallback.published_at if fallback else None)
        body_html = first_match(r'<div[^>]+class=["\']bbs_content["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\']bbs_buttons|<!-- 권한)', html) or first_match(r'<span[^>]+class=["\']p_content["\'][^>]*>(.*?)</span>', html)
        body_text = strip_tags(body_html) or title
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        attachment_urls = [link for _, link in all_links(html, url) if "bbs_download" in link or "bbsDown" in link]
        body_text = append_attachment_text(body_text, extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes))
        app_rng = self._extract_range(body_text, ["신청기간", "접수기간", "모집기간", "교육기간", "접수", "신청"])
        event_rng = self._extract_range(body_text, ["교육기간", "훈련기간", "운영기간", "일시", "일정", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "교육대상", "모집대상", "참여대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "훈련장소"])
        text = f"{title} {body_text}"
        category = classify_category(text, self.source.get("category_hint", "취업창업"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text), location_name=location or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=published_at,
            apply_url=url, attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[category, "창원시", "여성", "직업교육"], parser_version=self.parser_version,
        ).finalize()

    def _canonical_url(self, url: str) -> str:
        m = re.search(r"bbsData=([^&]+)", url)
        if m:
            return f"{self.board_url}?p=&code=notice&subcode=&page=1&bbsData={m.group(1)}&search=&searchstring=&mode=view"
        return url

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _clean_title(text: str) -> str:
        return re.sub(r"\s+", " ", unescape(text or "")).strip()

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

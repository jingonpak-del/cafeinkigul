from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class ChangwonCityPublicBoardAdapter(AdapterBase):
    """Source-specific base for Changwon city department public notice boards.

    The boards share the official Changwon `*.web?gcode=...&idx=...&amode=view`
    structure, but each subclass pins one institution/menu, relevance vocabulary,
    and operational-notice exclusions.
    """

    parser_version = "changwon_city_public_board_v1"
    list_url = ""
    default_location = "창원시"
    default_category = "기타"
    tags_extra: list[str] = []
    max_pages = 2
    include_keywords = [
        "모집", "신청", "참여", "교육", "프로그램", "특강", "체험", "상담",
        "봉사", "수강", "접수", "운영", "지원", "강좌", "교실", "행사",
    ]
    negative_keywords = [
        "채용", "합격", "서류", "면접", "기간제", "공무직", "상담원 채용", "강사 모집",
        "입찰", "계약", "용역", "공사", "휴관", "휴무", "점검", "보도자료", "결과",
        "선정결과", "수상자", "자료실", "회의", "만족도", "홍보 이미지", "안내문 및 의뢰서",
    ]

    def _page_url(self, page: int) -> str:
        sep = "&" if "?" in self.list_url else "?"
        return self.list_url if page == 1 else f"{self.list_url}{sep}cpage={page}"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            html = self.fetch_html(self._page_url(page))
            added = 0
            for item in self.parse_list_html(html):
                if item.url in seen or not self._is_relevant(item.title):
                    continue
                if item.published_at and not is_within_days(item.published_at, since_days):
                    continue
                items.append(item)
                seen.add(item.url)
                added += 1
                if len(items) >= limit:
                    break
            if len(items) >= limit or (page > 1 and added == 0):
                break
        return items

    def parse_list_html(self, html: str) -> list[ListingItem]:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I)
        items: list[ListingItem] = []
        for row in rows:
            m = re.search(r'<a[^>]+href=["\']([^"\']*amode=view[^"\']*)["\'][^>]*>(.*?)</a>', row, re.S | re.I)
            if not m:
                continue
            href, inner = m.groups()
            title = self._clean_title(strip_tags(inner))
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', row)
            url = urljoin(self.list_url, unescape(href).replace("&amp;", "&"))
            url = self._canonical_url(url)
            if title:
                items.append(ListingItem(title=title, url=url, status="공지사항", published_at=parse_first_date(date_text)))
        return items

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = self._clean_title(strip_tags(first_match(r'<h1[^>]+id=["\']sns_bbs_title["\'][^>]*>(.*?)</h1>', html)))
        if not title:
            title = self._clean_title(strip_tags(first_match(r'<h1[^>]+class=["\']h1["\'][^>]*>(.*?)</h1>', html)))
        if not title:
            title = self._clean_title(strip_tags(first_match(r'<title[^>]*>(.*?)</title>', html)))
        if (not title or title == "공지사항 | 분야별정보") and fallback:
            title = fallback.title
        info = strip_tags(first_match(r'<div[^>]+class=["\']info1["\'][^>]*>(.*?)</div>', html))
        published_at = parse_first_date(info) or (fallback.published_at if fallback else None)
        view_html = first_match(r'<div[^>]+class=["\']bbs1view1["\'][^>]*>(.*?)</div>\s*<!-- //bbs1view1 -->', html)
        body_html = first_match(r'<div[^>]+class=["\']cont["\'][^>]*>(.*?)</div>', view_html) or view_html
        # Remove title/info/attachment chrome but keep useful uploaded poster alt text and linked file names.
        body_html = re.sub(r'<h1\b.*?</h1>', ' ', body_html or '', flags=re.S | re.I)
        body_html = re.sub(r'<div[^>]+class=["\']info1["\'][^>]*>.*?</div>', ' ', body_html, flags=re.S | re.I)
        body_text = strip_tags(body_html) or title
        if len(body_text) > 7000:
            body_text = body_text[:7000]
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        image_alts = [strip_tags(x) for x in re.findall(r'<img[^>]+(?:alt|title)=["\']([^"\']*)["\']', body_html or "", re.I) if x]
        if len(body_text) < 40 and image_alts:
            body_text = "\n".join([body_text, *image_alts]).strip()
        attachment_urls = [link for _, link in all_links(html, url) if "cmsfile/download.do" in link or "download" in link.lower()][:5]
        body_text = append_attachment_text(body_text or title, extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes))
        app_rng = self._extract_range(body_text, ["신청기간", "접수기간", "모집기간", "공고기간", "신청", "접수", "모집"])
        event_rng = self._extract_range(body_text, ["교육기간", "운영기간", "프로그램", "행사기간", "활동기간", "일시", "일정", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "참여대상", "신청대상", "지원대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소", "운영장소", "위치"])
        text = f"{title} {body_text}"
        category = classify_category(text, self.source.get("category_hint", self.default_category))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text), location_name=location or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=published_at,
            apply_url=url, attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [category, "창원시", *self.tags_extra] if t], parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _canonical_url(url: str) -> str:
        m_g = re.search(r"gcode=([^&]+)", url)
        m_i = re.search(r"idx=(\d+)", url)
        if m_g and m_i:
            base = url.split("?")[0]
            return f"{base}?gcode={m_g.group(1)}&idx={m_i.group(1)}&amode=view"
        return url

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\[[^\]]*공지[^\]]*\]", " ", text)
        text = re.sub(r"\b\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}\b", " ", text)
        text = re.sub(r"조회수\s*[:：]?\s*[\d,]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|[\n\r\s▶□○\-])" + re.escape(label) + r"(?![가-힣A-Za-z0-9])\s*[:：-]?\s*([^\n\r]{2,100})", text or "")
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


class ChangwonYouthCounselingCenterAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_youth_counseling_center_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11067/14051/14057.web?gcode=1375"
    default_location = "창원시 청소년상담복지센터"
    default_category = "아동청소년"
    tags_extra = ["청소년상담", "부모교육"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "상담원", "기간제", "동반자 사업안내문"]


class ChangwonOutOfSchoolYouthCenterAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_out_of_school_youth_center_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11067/14074/14075.web?gcode=1377"
    default_location = "창원시 학교밖청소년지원센터"
    default_category = "아동청소년"
    tags_extra = ["학교밖청소년", "꿈드림"]
    include_keywords = ["모집", "신청", "프로그램", "멘토", "검정고시", "직업체험", "꿈드림", "교육", "상담"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "상담원", "채용"]


class ChangwonVolunteerCenterAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_volunteer_center_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11067/14173/14188.web?gcode=1386"
    default_location = "창원시종합자원봉사센터"
    default_category = "공익활동"
    tags_extra = ["자원봉사", "봉사교육"]
    include_keywords = ["모집", "참여", "자원봉사", "봉사자", "봉사단", "교육", "체험", "프로그램", "신청"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "센터 휴관", "1365"]


class ChangwonMasanWomenHallAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_masan_women_hall_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11061/11076/11325.web?gcode=1274"
    default_location = "창원시 여성회관 마산관"
    default_category = "교육"
    tags_extra = ["여성회관", "마산관", "평생교육"]
    include_keywords = ["수강생", "모집", "교육", "프로그램", "은빛대학", "강좌", "특강", "신청"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "개강연기", "취소", "환불"]


class ChangwonHealthCenterNewsAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_health_center_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11066/14416/13302.web?gcode=1009"
    default_location = "창원보건소"
    default_category = "복지건강"
    tags_extra = ["보건소", "건강교육"]
    include_keywords = ["모집", "참여", "신청", "건강", "운동", "프로그램", "교실", "교육", "마음건강", "헬스케어"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "채용", "의료기관", "진료시간", "예방접종 일정"]

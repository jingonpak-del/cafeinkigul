from __future__ import annotations

import re
from html import unescape
from urllib.parse import quote, urljoin

from .base import AdapterBase, ListingItem
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class CwsisulFacilitySectionAdapter(AdapterBase):
    """Source-specific parser base for one 창원시설공단 facility notice section.

    The public board is shared by all facilities (`sub06_04_01`) and separated by
    the `sca` category parameter. Subclasses pin one facility name/category so the
    crawler produces institution-specific output instead of broad generic scraping.
    """

    parser_version = "cwsisul_facility_section_v1"
    base = "https://www.cwsisul.or.kr"
    board_url = "https://www.cwsisul.or.kr/bbs/board.php?bo_table=sub06_04_01"
    facility_name = ""
    default_location = "창원시설공단"
    apply_url = "https://reserve.cwsisul.or.kr/"
    include_keywords = [
        "프로그램", "운영", "모집", "수강", "강좌", "교육", "행사", "체험", "무료입장",
        "진로박람회", "잼월드", "평생학습", "대관", "추첨",
    ]
    negative_keywords = [
        "채용", "합격", "입찰", "계약", "공사", "휴관", "정기휴관", "휴장", "점검", "수질검사",
        "유충검사", "CCTV", "행정예고", "미운영", "제한", "분실물", "사물함", "브레이크 타임",
        "개인정보", "결과 안내", "당첨자 안내", "주간행사일정", "주간 행사 일정", "폭염", "운영 중단",
    ]
    tags_extra: list[str] = []

    @property
    def list_url(self) -> str:
        return f"{self.board_url}&sca={quote(self.facility_name)}"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, 5):
            if len(items) >= limit:
                break
            url = self.list_url if page == 1 else f"{self.list_url}&page={page}"
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
                items.append(item)
                seen.add(item.url)
                added += 1
                if len(items) >= limit:
                    break
            if added == 0 and page > 1:
                break
        return items

    def parse_list_html(self, html: str) -> list[ListingItem]:
        items: list[ListingItem] = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I):
            if "wr_id=" not in row:
                continue
            row_text = strip_tags(row)
            if self.facility_name and self.facility_name not in row_text and f"sca={quote(self.facility_name)}" not in row:
                continue
            href = first_match(r'href=["\']([^"\']*board\.php\?bo_table=sub06_04_01[^"\']*wr_id=\d+[^"\']*)["\']', row)
            if not href:
                continue
            title_html = first_match(r'<div[^>]+class=["\'][^"\']*bo_tit[^"\']*["\'][^>]*>(.*?)</div>', row)
            title = strip_tags(first_match(r"<a[^>]*>(.*?)</a>", title_html))
            if not title:
                title = strip_tags(first_match(r'<a[^>]+href=["\'][^"\']*wr_id=\d+[^"\']*["\'][^>]*>(.*?)</a>', row))
            title = re.sub(r"\s+", " ", title).strip()
            published_at = self._parse_date(strip_tags(first_match(r'<td[^>]*class=["\'][^"\']*td_datetime[^"\']*["\'][^>]*>(.*?)</td>', row)))
            if title:
                full_url = urljoin(self.base, unescape(href))
                items.append(ListingItem(title=title, url=full_url, status=self.facility_name, department=self.facility_name, published_at=published_at))
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
        title = strip_tags(first_match(r'<span[^>]+class=["\'][^"\']*bo_v_tit[^"\']*["\'][^>]*>(.*?)</span>', html)) or (fallback.title if fallback else "")
        title = re.sub(r"\s+", " ", title).strip()
        facility = strip_tags(first_match(r'<span[^>]+class=["\'][^"\']*bo_v_cate[^"\']*["\'][^>]*>(.*?)</span>', html)) or self.facility_name
        published_at = self._parse_date(first_match(r'<strong[^>]+class=["\'][^"\']*if_date[^"\']*["\'][^>]*>(.*?)</strong>', html)) or (fallback.published_at if fallback else None)
        body_html = first_match(r'<div[^>]+id=["\']bo_v_con["\'][^>]*>(.*?)(?:</div>\s*<!-- } 본문 내용 끝|</section>)', html)
        if not body_html:
            body_html = first_match(r'<div[^>]+id=["\']bo_v_con["\'][^>]*>(.*?)</div>', html)
        body_text = strip_tags(body_html)
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        image_alts = [strip_tags(alt) for alt in re.findall(r'<img[^>]+alt=["\']([^"\']*)["\']', body_html or "", re.I) if alt]
        attachment_urls = []
        attachment_names = []
        for text, link in all_links(html, url):
            if "download.php" in link:
                if link not in attachment_urls:
                    attachment_urls.append(link)
                if text:
                    attachment_names.append(text)
        if len(body_text) < 30:
            body_text = "\n".join(x for x in [body_text, *image_alts, *attachment_names, title] if x).strip()
        body_text = append_attachment_text(body_text or title, extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes))
        app_rng = self._extract_range(body_text, ["모집기간", "접수기간", "신청기간", "접수", "온라인 접수"])
        event_rng = self._extract_range(body_text, ["운영기간", "강습기간", "교육기간", "행사기간", "이용기간", "일시", "기간"])
        location = self._extract_labeled_value(body_text, ["교육장소", "행사장소", "운영장소", "장소", "강의실"])
        target = self._extract_labeled_value(body_text, ["교육대상", "모집대상", "참여대상", "대상", "지원자격"])
        text = title + " " + body_text
        category = classify_category(text, self.source.get("category_hint", "교육"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text), location_name=location or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=facility or (fallback.status if fallback else self.facility_name),
            published_at=published_at, apply_url=url if "신청" in text or "접수" in text else self.apply_url,
            attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [category, "창원시", facility, *self.tags_extra] if t], parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        if any(k in text for k in self.negative_keywords):
            return False
        return any(k in text for k in self.include_keywords)

    @staticmethod
    def _parse_date(text: str) -> str | None:
        m = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text or "")
        if not m:
            return None
        y, mo, d = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|[\n\r\s•○▶-])" + re.escape(label) + r"(?![가-힣A-Za-z0-9])\s*[:：-]?\s*([^\n\r]{2,100})", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

    @staticmethod
    def _extract_range(text: str, labels: list[str]) -> DateRange:
        for label in labels:
            m = re.search(re.escape(label) + r"\s*[:：-]?\s*([^\n\r]{0,160})", text or "")
            if m:
                rng = parse_date_range(m.group(0))
                if rng.start:
                    return rng
        return extract_labeled_range(text, labels) or DateRange()


class UrinuriYouthCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "urinuri_youth_center_v1"
    facility_name = "우리누리청소년문화센터"
    default_location = "우리누리청소년문화센터"
    apply_url = "https://reserve.cwsisul.or.kr/ollec/cwsisul/lec_list.do?sisul_idx=20"
    tags_extra = ["우리누리", "청소년"]


class GreenhallYouthCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "greenhall_youth_center_v1"
    facility_name = "늘푸른전당"
    default_location = "늘푸른전당"
    apply_url = "https://reserve.cwsisul.or.kr/ollec/cwsisul/lec_list.do?sisul_idx=2"
    tags_extra = ["늘푸른전당", "청소년"]


class JindongWelfareCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "jindong_welfare_center_v1"
    facility_name = "진동종합복지관"
    default_location = "진동종합복지관"
    apply_url = "https://www.cwsisul.or.kr/_jdswc/"
    tags_extra = ["진동", "평생학습"]


class GamgyeWelfareCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "gamgye_welfare_center_v1"
    facility_name = "감계복지센터"
    default_location = "감계복지센터"
    apply_url = "https://www.cwsisul.or.kr/_ggswc/"
    tags_extra = ["감계", "복지센터"]


class CitizenSportsCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "citizen_sports_center_v1"
    facility_name = "시민생활체육관"
    default_location = "시민생활체육관"
    apply_url = "https://www.cwsisul.or.kr/"
    tags_extra = ["시민생활체육관", "체육"]


class NaeseoSportsCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "naeseo_sports_center_v1"
    facility_name = "내서스포츠센터"
    default_location = "내서스포츠센터"
    apply_url = "https://www.cwsisul.or.kr/"
    tags_extra = ["내서", "스포츠센터", "체육"]


class MasanhappoSportsCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "masanhappo_sports_center_v1"
    facility_name = "마산합포스포츠센터"
    default_location = "마산합포스포츠센터"
    apply_url = "https://www.cwsisul.or.kr/"
    tags_extra = ["마산합포", "스포츠센터", "체육"]


class SeongsanSportsCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "seongsan_sports_center_v1"
    facility_name = "성산스포츠센터"
    default_location = "성산스포츠센터"
    apply_url = "https://www.cwsisul.or.kr/"
    tags_extra = ["성산", "스포츠센터", "체육"]


class YongwonSportsCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "yongwon_sports_center_v1"
    facility_name = "용원국민체육센터"
    default_location = "용원국민체육센터"
    apply_url = "https://www.cwsisul.or.kr/"
    tags_extra = ["용원", "국민체육센터", "체육"]


class JinhaeSportsCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "jinhae_sports_center_v1"
    facility_name = "진해국민체육센터"
    default_location = "진해국민체육센터"
    apply_url = "https://www.cwsisul.or.kr/"
    tags_extra = ["진해", "국민체육센터", "체육"]


class MarineLeportsCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "marine_leports_center_v1"
    facility_name = "해양레포츠센터"
    default_location = "해양레포츠센터"
    apply_url = "https://www.cwsisul.or.kr/"
    tags_extra = ["해양레포츠", "체험", "체육"]


class MasanMemberSportsCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "masan_member_sports_center_v1"
    facility_name = "마산회원체육센터"
    default_location = "마산회원체육센터"
    apply_url = "https://www.cwsisul.or.kr/"
    tags_extra = ["마산회원", "체육센터", "체육"]


class JinhaeYeojwaSportsCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "jinhae_yeojwa_sports_center_v1"
    facility_name = "진해여좌국민체육센터"
    default_location = "진해여좌국민체육센터"
    apply_url = "https://www.cwsisul.or.kr/"
    tags_extra = ["진해여좌", "국민체육센터", "체육"]


class ChangwonFootballCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "changwon_football_center_v1"
    facility_name = "창원축구센터"
    default_location = "창원축구센터"
    apply_url = "https://www.cwsisul.or.kr/"
    tags_extra = ["창원축구센터", "축구", "체육"]


class UichangSportsCenterAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "uichang_sports_center_v1"
    facility_name = "의창스포츠센터"
    default_location = "의창스포츠센터"
    apply_url = "https://www.cwsisul.or.kr/"
    tags_extra = ["의창", "스포츠센터", "체육"]


class ChangwonSportsParkAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "changwon_sports_park_v1"
    facility_name = "창원종합운동장"
    default_location = "창원종합운동장"
    apply_url = "https://www.cwsisul.or.kr/"
    include_keywords = [*CwsisulFacilitySectionAdapter.include_keywords, "스포츠", "체육", "대회"]
    negative_keywords = [*CwsisulFacilitySectionAdapter.negative_keywords, "주차", "교통", "보수"]
    tags_extra = ["창원종합운동장", "스포츠파크", "체육"]


class ChangwonIndoorSwimmingPoolAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "changwon_indoor_swimming_pool_v1"
    facility_name = "창원실내수영장"
    default_location = "창원실내수영장"
    apply_url = "https://www.cwsisul.or.kr/"
    include_keywords = [*CwsisulFacilitySectionAdapter.include_keywords, "수영", "강습", "아쿠아", "수상"]
    negative_keywords = [*CwsisulFacilitySectionAdapter.negative_keywords, "수질검사", "수질 검사", "유충", "휴장"]
    tags_extra = ["창원실내수영장", "수영", "체육"]


class DeokdongTennisCourtAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "deokdong_tennis_court_v1"
    facility_name = "덕동테니스장"
    default_location = "덕동테니스장"
    apply_url = "https://www.cwsisul.or.kr/"
    include_keywords = [*CwsisulFacilitySectionAdapter.include_keywords, "테니스", "강습", "회원모집", "레슨"]
    negative_keywords = [*CwsisulFacilitySectionAdapter.negative_keywords, "대회일정", "운영 안내", "이용제한"]
    tags_extra = ["덕동테니스장", "테니스", "체육"]


class JinhaeMarineParkAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "jinhae_marine_park_v1"
    facility_name = "진해해양공원"
    default_location = "진해해양공원"
    apply_url = "https://www.cwsisul.or.kr/"
    include_keywords = [*CwsisulFacilitySectionAdapter.include_keywords, "해양공원", "전시", "체험", "행사", "교육"]
    negative_keywords = [*CwsisulFacilitySectionAdapter.negative_keywords, "휴장", "시설물", "입장료 안내"]
    tags_extra = ["진해해양공원", "체험", "문화"]


class JinhaeYouthCampAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "jinhae_youth_camp_v1"
    facility_name = "진해청소년야영장"
    default_location = "진해청소년야영장"
    apply_url = "https://www.cwsisul.or.kr/"
    include_keywords = [*CwsisulFacilitySectionAdapter.include_keywords, "청소년", "야영", "캠프", "체험", "프로그램"]
    negative_keywords = [*CwsisulFacilitySectionAdapter.negative_keywords, "시설 점검", "예약 안내", "이용수칙"]
    tags_extra = ["진해청소년야영장", "청소년", "캠프"]


class BukmyeonDisabledParkgolfAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "bukmyeon_disabled_parkgolf_v1"
    facility_name = "북면장애인파크골프장"
    default_location = "북면장애인파크골프장"
    apply_url = "https://www.cwsisul.or.kr/"
    include_keywords = [*CwsisulFacilitySectionAdapter.include_keywords, "파크골프", "장애인", "강습", "대회", "체험", "이용"]
    negative_keywords = [*CwsisulFacilitySectionAdapter.negative_keywords, "잔디", "예초", "방역", "이용 제한", "임시폐쇄"]
    tags_extra = ["북면", "장애인파크골프", "체육"]


class DaesanParkgolfAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "daesan_parkgolf_v1"
    facility_name = "대산파크골프장"
    default_location = "대산파크골프장"
    apply_url = "https://www.cwsisul.or.kr/"
    include_keywords = [*CwsisulFacilitySectionAdapter.include_keywords, "파크골프", "강습", "대회", "체험", "이용", "접수"]
    negative_keywords = [*CwsisulFacilitySectionAdapter.negative_keywords, "잔디", "예초", "방역", "이용 제한", "임시폐쇄"]
    tags_extra = ["대산", "파크골프", "체육"]


class ChangwonInternationalShootingRangeAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "changwon_international_shooting_range_v1"
    facility_name = "창원국제사격장"
    default_location = "창원국제사격장"
    apply_url = "https://www.cwsisul.or.kr/"
    include_keywords = [*CwsisulFacilitySectionAdapter.include_keywords, "사격", "클레이", "공기소총", "체험", "대회", "강습", "접수"]
    negative_keywords = [*CwsisulFacilitySectionAdapter.negative_keywords, "탄약", "안전점검", "이용 제한", "임시휴장", "운영 일정", "체험 불가"]
    tags_extra = ["창원국제사격장", "사격", "체육"]


class BukmyeonGolfRangeAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "bukmyeon_golf_range_v1"
    facility_name = "북면골프연습장"
    default_location = "북면골프연습장"
    apply_url = "https://www.cwsisul.or.kr/"
    include_keywords = [*CwsisulFacilitySectionAdapter.include_keywords, "골프", "연습장", "강습", "레슨", "회원", "접수"]
    negative_keywords = [*CwsisulFacilitySectionAdapter.negative_keywords, "타석 점검", "시설 점검", "이용 제한", "임시휴장"]
    tags_extra = ["북면", "골프연습장", "체육"]


class SpecialTransportServiceAdapter(CwsisulFacilitySectionAdapter):
    parser_version = "special_transport_service_v1"
    facility_name = "교통약자특별교통수단"
    default_location = "창원시설공단 교통약자특별교통수단"
    apply_url = "https://www.cwsisul.or.kr/"
    include_keywords = ["모집", "신청", "교육", "참여", "체험", "이용", "교통약자", "특별교통수단", "바우처", "등록", "접수"]
    negative_keywords = [*CwsisulFacilitySectionAdapter.negative_keywords, "운행시간", "전화번호", "요금 안내", "개인정보", "시스템 점검", "운행결과", "결과 보고", "결과보고"]
    tags_extra = ["교통약자", "이동지원", "복지"]

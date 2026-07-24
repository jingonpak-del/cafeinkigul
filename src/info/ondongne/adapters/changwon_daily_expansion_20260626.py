from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from .changwon_city_public_boards_20260620 import ChangwonCityPublicBoardAdapter
from ..classify import classify_category, detect_price_type
from ..date_parser import DateRange, is_within_days, parse_date_range
from ..html_utils import all_links, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class ChangwonArboretumAdapter(ChangwonCityPublicBoardAdapter):
    """창원수목원 공지사항: 숲해설/수목원 체험 프로그램."""

    parser_version = "changwon_arboretum_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/11346/11356.web?gcode=1275"
    default_location = "창원수목원"
    default_category = "문화"
    tags_extra = ["창원수목원", "숲해설", "생태체험"]
    include_keywords = ["모집", "신청", "프로그램", "숲해설", "수목원", "체험", "교육", "탐방", "해설", "운영"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "휴무", "휴관", "임시휴장", "공사", "점검", "분실물"]


class UngcheonCeramicsMuseumAdapter(ChangwonCityPublicBoardAdapter):
    """웅천도요지전시관 공지사항: 도자기/차문화/디지털 체험교육."""

    parser_version = "ungcheon_ceramics_museum_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/12457/12803.web?gcode=1310"
    default_location = "웅천도요지전시관"
    default_category = "문화"
    tags_extra = ["웅천도요지", "도자기체험", "전시관"]
    include_keywords = ["모집", "신청", "예약", "마감", "행사", "체험", "교육", "강연", "특강", "도자기", "차문화", "디지털", "전시"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "주차 안내", "휴관", "휴무", "시설점검", "관람 안내"]


class JinhaeModernHistoryTourAdapter(ChangwonCityPublicBoardAdapter):
    """진해근대문화투어 공지사항: 군항문화탐방/근대문화역사길."""

    parser_version = "jinhae_modern_history_tour_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/12458/12812.web?gcode=1312"
    default_location = "진해근대문화투어"
    default_category = "문화"
    tags_extra = ["진해", "근대문화", "투어"]
    include_keywords = ["모집", "신청", "참가", "탐방", "투어", "문화", "역사길", "군항", "해설", "운영", "체험"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "휴무", "휴관", "운영 중단", "취소", "교통통제"]


class ChangwonEnvironmentEducationAdapter(ChangwonCityPublicBoardAdapter):
    """창원시 환경교육 공지사항."""

    parser_version = "changwon_environment_education_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11065/11083/13061.web?gcode=1344"
    default_location = "창원시 환경교육"
    default_category = "문화"
    tags_extra = ["환경교육", "탄소중립", "생태"]
    include_keywords = ["모집", "신청", "교육", "환경교육", "프로그램", "체험", "탄소중립", "생태", "기후", "참여", "공모"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "환경백서", "환경지표", "배출원조사", "법정교육", "제출 안내", "점검"]


class ChangwonVolunteerRecruitmentAdapter(AdapterBase):
    """창원시 자원봉사모집 표 전용 어댑터.

    이 페이지는 창원시 포털 내부 상세가 아니라 1365 신청 상세 링크를 표 행에 직접 노출한다.
    따라서 list row 자체를 안정 URL/본문 소스로 사용하고, 신청 링크는 1365 원문을 유지한다.
    """

    parser_version = "changwon_volunteer_recruitment_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11067/14173/14194.web"
    default_location = "창원시"
    include_keywords = ["모집", "봉사", "자원봉사", "교육", "청소년", "체험", "도서관", "센터"]
    negative_keywords = ["취소", "마감", "점검", "휴관", "휴무", "행정", "공사", "채용", "합격", "결과"]

    def _page_url(self, page: int) -> str:
        return self.list_url if page == 1 else f"{self.list_url}?cpage={page}"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, 4):
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
            cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
            link_match = re.search(r'<a[^>]+href=["\']([^"\']*progrmRegistNo=\d+[^"\']*)["\'][^>]*>(.*?)</a>', row, re.S | re.I)
            if not link_match or len(cells) < 9:
                continue
            href, inner = link_match.groups()
            title = self._clean_title(strip_tags(inner))
            apply_url = unescape(href).replace("&amp;", "&")
            stable = self._canonical_url(apply_url)
            body = "\n".join([
                f"모집상태: {cells[2]}", f"모집기관: {cells[3]}", f"청소년 가능여부: {cells[4]}",
                f"성인 가능여부: {cells[5]}", f"봉사기간: {cells[6]}", f"봉사장소: {cells[7]}", f"모집일: {cells[8]}",
            ])
            item = ListingItem(title=title, url=stable, status=cells[2] or "자원봉사모집", published_at=self._range_end_or_start(cells[8]))
            item.extra = {"body_text": body, "apply_url": apply_url, "volunteer_period": cells[6], "recruit_period": cells[8], "location": cells[7], "organization": cells[3]}  # type: ignore[attr-defined]
            items.append(item)
        return items

    def parse_detail(self, item: ListingItem) -> Event:
        extra = getattr(item, "extra", {}) or {}
        body_text = extra.get("body_text") or item.title
        app_rng = parse_date_range(extra.get("recruit_period", "")) or DateRange()
        event_rng = parse_date_range(extra.get("volunteer_period", "")) or DateRange()
        target = "청소년/성인 자원봉사자" if "Y" in body_text else "성인 자원봉사자"
        text = f"{item.title} {body_text}"
        category = classify_category(text, "공익활동")
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=item.title, source_url=item.url, category=category, summary=summarize_event(item.title, body_text), body_text=body_text,
            target_audience=target, location_name=extra.get("location") or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=item.status, published_at=item.published_at,
            apply_url=extra.get("apply_url") or item.url, tags=[category, "창원시", "자원봉사"], parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _canonical_url(url: str) -> str:
        m = re.search(r"progrmRegistNo=(\d+)", url)
        return f"https://1365.go.kr/vols/P9210/partcptn/timeCptn.do?type=show&progrmRegistNo={m.group(1)}" if m else url

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:180].rstrip() + ("…" if len(text) > 180 else "")

    @staticmethod
    def _range_end_or_start(text: str) -> str | None:
        rng = parse_date_range(text or "")
        return rng.start or rng.end

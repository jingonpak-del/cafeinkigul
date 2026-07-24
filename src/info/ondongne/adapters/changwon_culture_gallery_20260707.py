from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import ListingItem
from .changwon_city_public_boards_20260620 import ChangwonCityPublicBoardAdapter
from ..date_parser import parse_first_date
from ..html_utils import first_match, strip_tags


class ChangwonCultureGalleryBoardAdapter(ChangwonCityPublicBoardAdapter):
    """Changwon portal gallery/list boards for museum and literature programs.

    These official portal sections share the same detail view as the city public
    board (`*.web?gcode=...&idx=...&amode=view`) but list items are rendered as
    gallery `<li>` cards instead of table rows. Subclasses pin one precise section
    and relevance vocabulary.
    """

    parser_version = "changwon_culture_gallery_board_v1"
    max_pages = 2
    default_category = "문화"
    include_keywords = [
        "전시", "교육", "행사", "강좌", "문예", "문학", "박물관", "어린이", "체험",
        "모집", "신청", "운영", "특별전", "수강", "참가", "시민",
    ]
    negative_keywords = [
        *ChangwonCityPublicBoardAdapter.negative_keywords,
        "사진자료", "소장자료", "풍경", "언론보도", "보도자료", "대관", "휴관", "점검",
        "게시판으로 이동", "이 게시글은", "지난 전시", "지난전시",
    ]
    tags_extra = ["문화", "창원시"]

    def parse_list_html(self, html: str) -> list[ListingItem]:
        items = super().parse_list_html(html)
        if items:
            return items
        found: list[ListingItem] = []
        for block in re.findall(r"<li[^>]*class=[\"'][^\"']*li1[^\"']*[\"'][^>]*>(.*?)</li>", html or "", re.S | re.I):
            match = re.search(r'<a[^>]+href=["\']([^"\']*amode=view[^"\']*)["\'][^>]*>(.*?)</a>', block, re.S | re.I)
            if not match:
                continue
            href, inner = match.groups()
            title = strip_tags(first_match(r'<strong[^>]+class=["\'][^"\']*t1[^"\']*["\'][^>]*>(.*?)</strong>', inner))
            if not title:
                title = strip_tags(inner)
            title = self._clean_title(title)
            text = strip_tags(block)
            date_text = first_match(r'(20\d{2}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}|\d{2}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2})', text)
            url = self._canonical_url(urljoin(self.list_url, unescape(href).replace("&amp;", "&")))
            if title:
                found.append(ListingItem(title=title, url=url, status="문화행사", published_at=self._parse_card_date(date_text)))
        deduped: list[ListingItem] = []
        seen: set[str] = set()
        for item in found:
            if item.url not in seen:
                deduped.append(item)
                seen.add(item.url)
        return deduped

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _parse_card_date(text: str) -> str | None:
        text = re.sub(r"\s+", "", text or "")
        parsed = parse_first_date(text)
        if parsed:
            return parsed
        m = re.search(r"(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
        if m:
            yy, mm, dd = map(int, m.groups())
            return f"20{yy:02d}-{mm:02d}-{dd:02d}"
        return None


class MasanMuseumEducationAdapter(ChangwonCultureGalleryBoardAdapter):
    parser_version = "masan_museum_education_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/11381/11417.web"
    default_location = "창원시립마산박물관"
    tags_extra = ["마산박물관", "박물관교육", "문화교육"]


class MasanMuseumSpecialExhibitionAdapter(ChangwonCultureGalleryBoardAdapter):
    parser_version = "masan_museum_special_exhibition_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/11381/11410.web"
    default_location = "창원시립마산박물관"
    tags_extra = ["마산박물관", "특별전", "전시"]
    include_keywords = [*ChangwonCultureGalleryBoardAdapter.include_keywords, "기획전", "특별전"]


class MasanLiteratureSpecialExhibitionAdapter(ChangwonCultureGalleryBoardAdapter):
    parser_version = "masan_literature_special_exhibition_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/12453/12473.web"
    default_location = "창원시립마산문학관"
    tags_extra = ["마산문학관", "문학전시", "문화"]
    include_keywords = [*ChangwonCultureGalleryBoardAdapter.include_keywords, "야외문학전시회", "문학전시"]


class MasanLiteratureLectureAdapter(ChangwonCultureGalleryBoardAdapter):
    parser_version = "masan_literature_lecture_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/12453/12474.web"
    default_location = "창원시립마산문학관"
    tags_extra = ["마산문학관", "문예강좌", "시민문예대학"]
    include_keywords = [*ChangwonCultureGalleryBoardAdapter.include_keywords, "문예대학", "수강", "강좌"]


class MasanLiteratureEventsAdapter(ChangwonCultureGalleryBoardAdapter):
    parser_version = "masan_literature_events_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/12453/12475.web"
    default_location = "창원시립마산문학관"
    tags_extra = ["마산문학관", "문학행사", "청소년문학교실"]
    include_keywords = [*ChangwonCultureGalleryBoardAdapter.include_keywords, "문학교실", "문학행사", "낭송", "백일장"]

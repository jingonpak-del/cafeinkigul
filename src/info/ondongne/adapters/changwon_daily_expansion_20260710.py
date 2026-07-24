from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from .changwon_family_center import ChangwonFamilyCenterAdapter
from .generic_gnuboard import GenericGnuboardAdapter
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class RobotLandExperienceAdapter(GenericGnuboardAdapter):
    parser_version = "robot_land_experience_v1"
    # The top menu says 체험/행사, but recent user-facing campaign rows live on bo_table=event.
    board_url = "https://robot-land.co.kr/bbs/board.php?bo_table=event"
    allowed_boards = ["event", "experience", "notice"]
    default_location = "마산로봇랜드"
    default_category = "체험"
    tags_extra = ["마산로봇랜드", "체험", "가족"]
    include_keywords = ["체험", "행사", "이벤트", "프로그램", "프로모션", "할인", "축제", "운영", "참여", "신청", "공연"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "운휴", "휴장", "정기점검", "시스템 점검", "요금 안내"]


class JinhaeDreamParkNoticeAdapter(GenericGnuboardAdapter):
    parser_version = "jinhae_dreampark_notice_v1"
    board_url = "https://jhdreampark.com/bri/board.php?bo_table=notice"
    allowed_boards = ["notice"]
    default_location = "진해드림파크"
    default_category = "체험"
    tags_extra = ["진해드림파크", "숲체험", "환경교육"]
    include_keywords = ["체험", "프로그램", "모집", "신청", "교육", "숲", "참가", "예약", "가족"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "휴무", "휴장", "점검", "공사", "분실물"]

    def _canonical_url(self, url: str) -> str:
        m_board = re.search(r"bo_table=([^&]+)", url)
        m_id = re.search(r"wr_id=(\d+)", url)
        if m_board and m_id:
            return f"https://jhdreampark.com/bri/board.php?bo_table={m_board.group(1)}&wr_id={m_id.group(1)}"
        return url


class MasanFamilyCenterAdapter(ChangwonFamilyCenterAdapter):
    parser_version = "masan_family_center_v1"
    base = "https://masan.familynet.or.kr"


class ChangdongBurimBoardAdapter(AdapterBase):
    parser_version = "changdong_burim_board_v1"
    list_url = ""
    default_location = "창원시"
    default_category = "문화"
    tags_extra: list[str] = []
    max_pages = 2
    include_keywords = ["모집", "신청", "교육", "원데이", "클래스", "행사", "전시", "프로그램", "체험", "공예", "입주", "페스티벌"]
    negative_keywords = ["채용", "입찰", "계약", "점검", "휴관", "휴무", "공사", "선정결과", "결과발표", "보도자료"]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            sep = "&" if "?" in self.list_url else "?"
            url = self.list_url if page == 1 else f"{self.list_url}{sep}page={page}"
            html = self.fetch_html(url)
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
        items: list[ListingItem] = []
        for href, inner in re.findall(r'<a[^>]+href=["\']([^"\']*(?:bseq|YnNlcT0|ic2VxPT)[^"\']*)["\'][^>]*>(.*?)</a>', html or "", re.S | re.I):
            title = self._clean_title(strip_tags(inner))
            if not title or title in {"보기", "자세히"}:
                continue
            row = self._near_row(html, href)
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{4}-\d{2}-\d{2}|\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', row)
            items.append(ListingItem(title=title, url=self._canonical_url(urljoin(self.list_url, unescape(href).replace("&amp;", "&"))), status="공지사항", published_at=parse_first_date(date_text)))
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
        title = self._clean_title(strip_tags(first_match(r'<h[123][^>]*>(.*?)</h[123]>', html))) or (fallback.title if fallback else "")
        body_html = first_match(r'<div[^>]+class=["\'][^"\']*contBody[^"\']*["\'][^>]*>(.*?)</div>', html)
        if not body_html:
            body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:board_view|view|content|contents|substance)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\'][^"\']*(?:btn|reply|list)|<ul[^>]+class=["\'][^"\']*btn)', html)
        if not body_html:
            body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:board|bbs)[^"\']*["\'][^>]*>(.*?)</div>\s*</div>', html)
        body_text = strip_tags(body_html) or strip_tags(first_match(r'<body[^>]*>(.*?)</body>', html))
        body_text = re.sub(r"\s+", " ", body_text).strip()
        body_text = re.sub(r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)\s+[\d,]+(\s|$)", r"\1 ", body_text)
        body_text = re.sub(r"\[?\s*download\s*:\s*\d+\]?", " ", body_text, flags=re.I)
        body_text = re.sub(r"조회수\s*[:：]?\s*[\d,]+", " ", body_text)
        body_text = re.sub(r"\s+", " ", body_text).strip()
        if len(body_text) > 7000:
            body_text = body_text[:7000]
        if fallback and (not title or title in {"공지사항", "Notification"}):
            title = fallback.title
        if not body_text or len(body_text) < 30:
            body_text = f"{title}\n{strip_tags(html)[:1000]}"
        attachment_urls = [link for _, link in all_links(html, url) if any(k in link.lower() for k in ["download", "file", "upload", "down"])]
        body_text = append_attachment_text(body_text, extract_many_attachment_texts(attachment_urls[:3], max_files=2, fetcher=self.fetch_bytes))
        body_text = re.sub(r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)\s+[\d,]+(\s|$)", r"\1 ", body_text)
        body_text = re.sub(r"\[?\s*download\s*:\s*\d+\]?", " ", body_text, flags=re.I)
        body_text = re.sub(r"조회수\s*[:：]?\s*[\d,]+", " ", body_text)
        body_text = re.sub(r"\s+", " ", body_text).strip()
        app_rng = self._extract_range(body_text, ["신청기간", "접수기간", "모집기간", "접수", "신청"])
        event_rng = self._extract_range(body_text, ["행사기간", "교육기간", "운영기간", "일시", "일정", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "참여대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소", "위치"])
        text = f"{title} {body_text}"
        category = classify_category(text, self.source.get("category_hint", self.default_category))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text), location_name=location or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=(fallback.published_at if fallback else parse_first_date(body_text)),
            apply_url=url, attachment_urls=attachment_urls[:5], tags=[t for t in [category, "창원시", *self.tags_extra] if t], parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    def _canonical_url(self, url: str) -> str:
        # The site uses base64-like query blobs. Preserve the blob as stable traceable detail URL.
        return url.split("#")[0]

    @staticmethod
    def _near_row(html: str, href: str) -> str:
        idx = (html or "").find(href)
        if idx < 0:
            return ""
        return (html or "")[max(0, idx - 800): idx + 800]

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\b\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}\b", " ", text)
        text = re.sub(r"조회수\s*[:：]?\s*[\d,]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:180].rstrip()

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


class ChangdongArtVillageNoticeAdapter(ChangdongBurimBoardAdapter):
    parser_version = "changdong_art_village_notice_v1"
    list_url = "http://changdongartvillage.kr/sub/community/?cGNvZGU9MQ=="
    default_location = "창동예술촌"
    tags_extra = ["창동예술촌", "원데이클래스", "문화예술"]


class BurimCraftVillageNoticeAdapter(ChangdongBurimBoardAdapter):
    parser_version = "burim_craft_village_notice_v1"
    list_url = "http://www.artburim.kr/sub/notice/?cGNvZGU9MQ=="
    default_location = "부림창작공예촌"
    tags_extra = ["부림창작공예촌", "공예", "문화예술"]

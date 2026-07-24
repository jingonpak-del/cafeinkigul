from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from .generic_gnuboard import GenericGnuboardAdapter
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class RhymixBoardAdapter(AdapterBase):
    """Source-specific base for Rhymix/XE boards using /module/document_id URLs."""

    parser_version = "rhymix_board_v1"
    list_url = ""
    default_location = "창원시"
    default_category = "복지건강"
    tags_extra: list[str] = []
    max_pages = 2
    include_keywords = [
        "모집", "신청", "참여", "교육", "프로그램", "강좌", "상담", "지원", "체험", "행사", "특강", "공간",
    ]
    negative_keywords = [
        "채용", "합격", "면접", "직원", "입찰", "계약", "공사", "휴관", "점검", "보도자료", "언론보도",
        "선정 결과", "선정결과", "납품 업체", "물품 납품", "실습", "사회복지현장실습", "결과",
    ]

    def _page_url(self, page: int) -> str:
        return self.list_url if page == 1 else f"{self.list_url}?page={page}"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            try:
                html = self.fetch_html(self._page_url(page))
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
            if len(items) >= limit or (page > 1 and added == 0):
                break
        return items

    def parse_list_html(self, html: str) -> list[ListingItem]:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I)
        items: list[ListingItem] = []
        for row in rows:
            m = re.search(r'<a[^>]+href=["\']([^"\']*/xe/board_cbSK71/\d+[^"\']*)["\'][^>]*>(.*?)</a>', row, re.S | re.I)
            if not m:
                continue
            href, inner = m.groups()
            title = self._clean_title(strip_tags(inner))
            if not title or title in {"댓글", "첨부"}:
                continue
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', row)
            items.append(ListingItem(title=title, url=self._canonical_url(urljoin(self.list_url, unescape(href).replace("&amp;", "&"))), status="공지사항", published_at=parse_first_date(date_text)))
        return self._dedupe(items)

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = self._clean_title(strip_tags(first_match(r'<h[123][^>]+class=["\'][^"\']*(?:title|read_header|document_title)[^"\']*["\'][^>]*>(.*?)</h[123]>', html)))
        if not title:
            title = self._clean_title(strip_tags(first_match(r'<title[^>]*>(.*?)</title>', html)))
        if (not title or "창원종합사회복지관" in title) and fallback:
            title = fallback.title
        info = strip_tags(first_match(r'<(?:div|span)[^>]+class=["\'][^"\']*(?:date|time|info)[^"\']*["\'][^>]*>(.*?)</(?:div|span)>', html))
        published_at = parse_first_date(info) or (fallback.published_at if fallback else None)
        body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:xe_content|document_content|read_body)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\'][^"\']*(?:btn|comment|reply|read_footer)|</article>)', html)
        if not body_html:
            body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:xe_content|document_content|read_body)[^"\']*["\'][^>]*>(.*?)</div>', html)
        return self._event_from_parts(title, body_html, html, url, published_at, fallback)

    def _event_from_parts(self, title: str, body_html: str, full_html: str, url: str, published_at: str | None, fallback: ListingItem | None = None) -> Event:
        body_html = re.sub(r'<script\b.*?</script>|<style\b.*?</style>', ' ', body_html or '', flags=re.S | re.I)
        body_text = strip_tags(body_html) or title
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        image_alts = [strip_tags(x) for x in re.findall(r'<img[^>]+(?:alt|title)=["\']([^"\']*)["\']', body_html or "", re.I) if x]
        if len(body_text) < 40 and image_alts:
            body_text = "\n".join([body_text, *image_alts]).strip()
        attachment_urls = [link for _, link in all_links(full_html, url) if any(k in link.lower() for k in ["download", "file", "attach", "kboard_file"])]
        body_text = append_attachment_text(body_text, extract_many_attachment_texts(attachment_urls[:4], max_files=2, fetcher=self.fetch_bytes))
        app_rng = self._extract_range(body_text, ["신청기간", "접수기간", "모집기간", "신청", "접수", "모집"])
        event_rng = self._extract_range(body_text, ["교육기간", "운영기간", "행사기간", "활동기간", "일시", "일정", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "참여대상", "신청대상"])
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

    def _canonical_url(self, url: str) -> str:
        m = re.search(r"/xe/board_cbSK71/(\d+)", url)
        return f"http://cs.cathms.kr/xe/board_cbSK71/{m.group(1)}" if m else url

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"댓글\s*\d+|조회수\s*[:：]?\s*[\d,]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:180].rstrip() + ("…" if len(text) > 180 else "")

    @staticmethod
    def _dedupe(items: list[ListingItem]) -> list[ListingItem]:
        seen: set[str] = set(); out: list[ListingItem] = []
        for item in items:
            if item.url not in seen:
                out.append(item); seen.add(item.url)
        return out

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


class KboardNoticeAdapter(RhymixBoardAdapter):
    """Source-specific base for WordPress KBoard notice lists using uid/mod=document links."""

    parser_version = "kboard_notice_v1"
    uid_param = "uid"

    def parse_list_html(self, html: str) -> list[ListingItem]:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I)
        if not rows:
            rows = re.findall(r"<div[^>]+class=[" + '"\'' + r"][^" + '"\'' + r"]*(?:kboard-list|kboard-default|kboard-post)[^" + '"\'' + r"]*[" + '"\'' + r"][^>]*>(.*?)</div>", html or "", re.S | re.I)
        items: list[ListingItem] = []
        for row in rows:
            m = re.search(r'<a[^>]+href=["\']([^"\']*(?:uid=\d+[^"\']*mod=document|mod=document[^"\']*uid=\d+)[^"\']*)["\'][^>]*>(.*?)</a>', row, re.S | re.I)
            if not m:
                continue
            href, inner = m.groups()
            title = self._clean_title(strip_tags(inner))
            if not title or title in {"다운로드", "첨부파일"}:
                continue
            row_text = strip_tags(row)
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', row_text)
            items.append(ListingItem(title=title, url=self._canonical_url(urljoin(self.list_url, unescape(href).replace("&#038;", "&").replace("&amp;", "&"))), status="공지사항", published_at=parse_first_date(date_text)))
        return self._dedupe(items)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = self._clean_title(strip_tags(first_match(r'<(?:h[123]|div)[^>]+class=["\'][^"\']*(?:kboard-title|entry-title|title)[^"\']*["\'][^>]*>(.*?)</(?:h[123]|div)>', html)))
        if (not title or title in {"공지사항"}) and fallback:
            title = fallback.title
        info = strip_tags(first_match(r'<div[^>]+class=["\'][^"\']*(?:kboard-document-info|kboard-date|date)[^"\']*["\'][^>]*>(.*?)</div>', html))
        published_at = parse_first_date(info) or (fallback.published_at if fallback else None)
        body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:kboard-content|kboard-document-wrap|entry-content)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\'][^"\']*(?:kboard-control|comments|comment|wp-block)|</article>)', html)
        if not body_html:
            body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:kboard-content|entry-content)[^"\']*["\'][^>]*>(.*?)</div>', html)
        return self._event_from_parts(title, body_html, html, url, published_at, fallback)

    def _canonical_url(self, url: str) -> str:
        m = re.search(r"uid=(\d+)", url)
        if m:
            return f"{self.list_url}?uid={m.group(1)}&mod=document"
        return url


class ChangwonCraftOpenStudioNoticeAdapter(RhymixBoardAdapter):
    parser_version = "changwon_craft_open_studio_notice_v1"
    list_url = "https://cwcraft.or.kr/00019/00033.web"
    default_location = "창원공예오픈스튜디오"
    default_category = "문화"
    tags_extra = ["공예", "문화예술", "창원공예오픈스튜디오"]
    include_keywords = ["프로그램", "신청", "모집", "공예", "체험", "교육", "강좌", "행사", "운영", "참가"]
    negative_keywords = [*RhymixBoardAdapter.negative_keywords, "채용공고", "강사 모집", "강사모집", "기간제 근로자"]

    def _page_url(self, page: int) -> str:
        return self.list_url if page == 1 else f"{self.list_url}?page={page}"

    def parse_list_html(self, html: str) -> list[ListingItem]:
        items: list[ListingItem] = []
        for href, inner in re.findall(r'<a[^>]+href=["\']([^"\']*gcode=1002[^"\']*idx=\d+[^"\']*amode=view[^"\']*)["\'][^>]*>(.*?)</a>', html or "", re.S | re.I):
            title = self._clean_title(strip_tags(inner))
            if not title or title.startswith("<img"):
                alt = first_match(r'(?:alt|name)=["\']([^"\']+)["\']', inner + href)
                title = self._clean_title(alt)
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', strip_tags(inner))
            items.append(ListingItem(title=title, url=self._canonical_url(urljoin(self.list_url, unescape(href).replace("&amp;", "&"))), status="공지사항", published_at=parse_first_date(date_text)))
        return self._dedupe([i for i in items if i.title])

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = self._clean_title(strip_tags(first_match(r'<h[123][^>]*>(.*?)</h[123]>', html)) or (fallback.title if fallback else ""))
        body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:board_view|view_cont|view_content|content)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\'][^"\']*(?:btn|board_btn)|</article>)', html)
        if not body_html:
            body_html = first_match(r'<body[^>]*>(.*?)</body>', html)
        published_at = parse_first_date(strip_tags(first_match(r'(?:등록일|작성일|기간)[^<]{0,80}(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', html))) or (fallback.published_at if fallback else None)
        return self._event_from_parts(title or (fallback.title if fallback else "공지사항"), body_html, html, url, published_at, fallback)

    def _canonical_url(self, url: str) -> str:
        m = re.search(r"idx=(\d+)", url)
        return f"https://cwcraft.or.kr/00019/00033.web?gcode=1002&idx={m.group(1)}&amode=view" if m else url


class ChangwonGeneralSocialWelfareNoticeAdapter(RhymixBoardAdapter):
    parser_version = "changwon_general_social_welfare_notice_v1"
    list_url = "http://cs.cathms.kr/xe/board_cbSK71"
    default_location = "창원종합사회복지관"
    default_category = "복지건강"
    tags_extra = ["종합사회복지관", "복지", "창원"]
    include_keywords = ["모집", "신청", "참여", "교육", "프로그램", "상담", "강좌", "체험", "공간", "대관", "지원"]
    negative_keywords = [*RhymixBoardAdapter.negative_keywords, "현장실습", "실습생", "납품 업체", "업체 모집", "결과", "푸드마켓"]


class JinhaeGeneralSocialWelfareNoticeAdapter(KboardNoticeAdapter):
    parser_version = "jinhae_general_social_welfare_notice_v1"
    list_url = "https://jh1004.or.kr/sub05-2/"
    default_location = "창원시진해종합사회복지관"
    default_category = "복지건강"
    tags_extra = ["진해", "종합사회복지관", "복지"]
    include_keywords = ["모집", "신청", "참여", "교육", "프로그램", "강좌", "상담", "체육", "수강", "행사", "지원"]
    negative_keywords = [*KboardNoticeAdapter.negative_keywords, "채용공고", "실습생", "사회복지실습", "유충검사", "사칭", "체육센터 전용 홈페이지"]


class JinhaeCultureCenterNoticeAdapter(KboardNoticeAdapter):
    parser_version = "jinhae_culture_center_notice_v1"
    list_url = "https://jinhaeculture.or.kr/%EC%B0%B8%EC%97%AC%EB%A7%88%EB%8B%B9/%EA%B3%B5%EC%A7%80%EC%82%AC%ED%95%AD/"
    default_location = "진해문화원"
    default_category = "문화"
    tags_extra = ["진해", "문화원", "문화예술"]
    include_keywords = ["모집", "신청", "참가", "참여", "문화", "강좌", "특강", "교육", "프로그램", "합창단", "수강"]
    negative_keywords = [*KboardNoticeAdapter.negative_keywords, "채용", "공시", "결산", "기부금", "활용실적"]


class MasanCultureCenterNoticeAdapter(GenericGnuboardAdapter):
    parser_version = "masan_culture_center_notice_v1"
    board_url = "http://masanculture.or.kr/m/g5/bbs/board.php?bo_table=notice_a"
    allowed_boards = ["notice_a"]
    default_location = "마산문화원"
    default_category = "문화"
    tags_extra = ["마산", "문화원", "문화강좌"]
    include_keywords = ["모집", "신청", "수강", "문화대학", "문화강좌", "강의", "교육", "프로그램", "특강", "행사"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "강사모집", "강사 모집", "마감"]

    def _canonical_url(self, url: str) -> str:
        m_board = re.search(r"bo_table=([^&]+)", url)
        m_id = re.search(r"wr_id=(\d+)", url)
        if m_board and m_id:
            return f"http://masanculture.or.kr/m/g5/bbs/board.php?bo_table={m_board.group(1)}&wr_id={m_id.group(1)}"
        return url


class JinhaeYouthCenterHallNoticeAdapter(GenericGnuboardAdapter):
    parser_version = "jinhae_youth_center_hall_notice_v1"
    board_url = "https://www.jinhaeyouth.or.kr/bbs/board.php?bo_table=06_01"
    allowed_boards = ["06_01"]
    default_location = "진해청소년전당"
    default_category = "아동청소년"
    tags_extra = ["진해", "청소년", "문화활동"]
    include_keywords = ["모집", "신청", "참가", "참여", "청소년", "프로그램", "문화", "체험", "드론", "꿈다락", "봉사단", "교육"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "합격", "대관 공지", "대관 신청", "야간체육관"]

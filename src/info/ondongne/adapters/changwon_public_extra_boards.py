from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from .generic_gnuboard import GenericGnuboardAdapter
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import extract_labeled_range, is_within_days, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class PublicSimpleBoardAdapter(AdapterBase):
    """Small source-specific base for WordPress/KBoard/XE-style public boards.

    Subclasses still pin one institution and selectors/URLs. This base only shares
    the hardened mechanics for list/detail parsing, labels, attachments and event
    construction.
    """

    parser_version = "public_simple_board_v1"
    board_url = ""
    page_param = "pageid"
    max_pages = 2
    url_pattern = r""
    title_patterns = [
        r'<div[^>]+class=["\'][^"\']*kboard-title[^"\']*["\'][^>]*>\s*<h1[^>]*>(.*?)</h1>',
        r'<h1[^>]+class=["\'][^"\']*(?:title|entry-title|np_18px_span)[^"\']*["\'][^>]*>(.*?)</h1>',
        r'<h[123][^>]*>(.*?)</h[123]>',
    ]
    body_patterns = [
        r'<div[^>]+class=["\'][^"\']*kboard-content[^"\']*["\'][^>]*>\s*<div[^>]+class=["\'][^"\']*content-view[^"\']*["\'][^>]*>(.*?)</div>\s*</div>',
        r'<div[^>]+class=["\'][^"\']*xe_content[^"\']*["\'][^>]*>(.*?)</div>\s*(?:</div>\s*){0,3}<div[^>]+class=["\'][^"\']*(?:feedback|btn|comment)',
        r'<div[^>]+class=["\'][^"\']*(?:entry-content|content-view|board-content|read_body|document_content)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div|</article|<footer)',
    ]
    default_location = "창원시"
    default_category = "기타"
    tags_extra: list[str] = []
    include_keywords = ["모집", "신청", "교육", "프로그램", "참여", "행사", "공모", "접수", "특강", "상담", "봉사", "일자리"]
    negative_keywords = ["채용", "합격", "면접", "직원", "입찰", "계약", "공사", "점검", "휴관", "결산", "예산", "보도자료", "선정 결과", "선정결과"]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            url = self.board_url if page == 1 else self._page_url(page)
            try:
                html = self.fetch_html(url)
            except Exception:
                break
            added = 0
            for item in self.parse_list_html(html, url):
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

    def _page_url(self, page: int) -> str:
        if self.page_param == "path":
            return self.board_url.rstrip("/") + f"/page/{page}"
        sep = "&" if "?" in self.board_url else "?"
        return f"{self.board_url}{sep}{self.page_param}={page}"

    def parse_list_html(self, html: str, base_url: str | None = None) -> list[ListingItem]:
        base_url = base_url or self.board_url
        items: list[ListingItem] = []
        blocks = re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I)
        if not blocks:
            blocks = re.findall(r"<li[^>]*>(.*?)</li>", html or "", re.S | re.I)
        if not blocks:
            blocks = re.findall(r"<div[^>]+class=[\"'][^\"']*(?:post|item|list|document)[^\"']*[\"'][^>]*>(.*?)</div>", html or "", re.S | re.I)
        link_re = self.url_pattern or r"[^'\"]*(?:uid=\d+|/notice/\d+|document_srl=\d+)[^'\"]*"
        for block in blocks:
            m = re.search(r'<a[^>]+href=["\'](' + link_re + r')["\'][^>]*>(.*?)</a>', block, re.S | re.I)
            if not m:
                continue
            href, inner = m.groups()
            title = strip_tags(first_match(r'<div[^>]+class=["\'][^"\']*(?:kboard-default-cut-strings|title|subject)[^"\']*["\'][^>]*>(.*?)</div>', block))
            if not title:
                title = strip_tags(inner)
            title = self._clean_title(title)
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', block)
            if title and title not in {"이전글", "다음글", "공지사항"}:
                items.append(ListingItem(title=title, url=urljoin(base_url, unescape(href).replace("&amp;", "&")), status="공지사항", published_at=parse_first_date(date_text) or GenericGnuboardAdapter._parse_date(date_text)))
        if not items:
            for href, inner in re.findall(r'<a[^>]+href=["\'](' + link_re + r')["\'][^>]*>(.*?)</a>', html or "", re.S | re.I):
                title = self._clean_title(strip_tags(inner))
                if title and title not in {"이전글", "다음글", "공지사항"}:
                    items.append(ListingItem(title=title, url=urljoin(base_url, unescape(href).replace("&amp;", "&")), status="공지사항"))
        deduped: list[ListingItem] = []
        seen: set[str] = set()
        for item in items:
            stable = self._canonical_url(item.url)
            if stable not in seen:
                item.url = stable
                deduped.append(item)
                seen.add(stable)
        return deduped

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = ""
        for pat in self.title_patterns:
            title = strip_tags(first_match(pat, html))
            if title:
                break
        title = self._clean_title(title or (fallback.title if fallback else ""))
        published_at = parse_first_date(strip_tags(first_match(r'(?:작성일|Date|날짜|등록일)[^<]{0,40}(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', html)) or "") or (fallback.published_at if fallback else None)
        body_html = ""
        for pat in self.body_patterns:
            body_html = first_match(pat, html)
            if body_html:
                break
        if not body_html:
            body_html = first_match(r'<body[^>]*>(.*?)</body>', html)
        body_text = strip_tags(body_html) or title
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        image_alts = [strip_tags(x) for x in re.findall(r'<img[^>]+(?:alt|title)=["\']([^"\']*)["\']', body_html or "", re.I) if x]
        if len(body_text) < 30 and image_alts:
            body_text = "\n".join([body_text, *image_alts]).strip()
        attachment_urls: list[str] = []
        for _, link in all_links(html, url):
            if any(k in link.lower() for k in ["kboard_file_download", "download", "file", "attach"]):
                if link not in attachment_urls:
                    attachment_urls.append(link)
        body_text = append_attachment_text(body_text or title, extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes))
        app_rng = extract_labeled_range(body_text, ["신청기간", "접수기간", "모집기간", "접수", "신청"])
        event_rng = extract_labeled_range(body_text, ["활동기간", "교육기간", "행사기간", "운영기간", "일시", "일정", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "신청대상", "참여대상", "지원대상"])
        location = self._extract_labeled_value(body_text, ["장소", "활동장소", "교육장소", "행사장소"])
        text = title + " " + body_text
        category = classify_category(text, self.source.get("category_hint", self.default_category))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text), location_name=location or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end,
            event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=published_at,
            apply_url=url, attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [category, "창원시", *self.tags_extra] if t], parser_version=self.parser_version,
        ).finalize()

    def _canonical_url(self, url: str) -> str:
        for pat in [r"uid=(\d+)", r"/notice/(\d+)", r"document_srl=(\d+)"]:
            m = re.search(pat, url)
            if m:
                if "uid=" in pat:
                    return urljoin(self.board_url, f"?uid={m.group(1)}&mod=document")
                if "/notice/" in pat:
                    return urljoin(self.board_url, f"/notice/{m.group(1)}")
                return urljoin(self.board_url, f"?document_srl={m.group(1)}")
        return url

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"^(공지|알림)\s*", "", text).strip()
        return text

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|[\n\r\s▶□○-])" + re.escape(label) + r"(?![가-힣A-Za-z0-9])\s*[:：-]?\s*([^\n\r]{2,100})", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""


class ChangwonSeniorClubAdapter(GenericGnuboardAdapter):
    """창원시니어클럽 공지사항."""

    parser_version = "changwon_senior_club_v1"
    board_url = "http://www.cwsenior.or.kr/bbs/board.php?bo_table=notice"
    allowed_boards = ["notice"]
    default_location = "창원시니어클럽"
    default_category = "복지건강"
    tags_extra = ["노인일자리", "시니어", "복지"]
    include_keywords = ["모집", "참여자", "노인일자리", "사회활동", "교육", "참여", "신청", "실습"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "합격자", "서류전형", "후원금"]


class MasanYwcaWomenCenterAdapter(GenericGnuboardAdapter):
    """마산여성인력개발센터/마산YWCA 공지사항."""

    parser_version = "masan_ywca_women_center_v1"
    board_url = "http://www.masanywca.or.kr/bbs/board.php?bo_table=notice"
    allowed_boards = ["notice"]
    default_location = "마산여성인력개발센터"
    default_category = "취업창업"
    tags_extra = ["여성", "직업교육", "취업"]
    include_keywords = ["모집", "교육", "훈련", "수강", "취업", "창업", "내일배움", "프로그램", "신청", "참여"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "합격", "인사"]


class GyeongnamVolunteerCenterAdapter(PublicSimpleBoardAdapter):
    """경상남도자원봉사센터 공지사항 KBoard."""

    parser_version = "gyeongnam_volunteer_center_v1"
    board_url = "https://www.gnbongsa.net/info/"
    url_pattern = r"[^'\"]*uid=\d+[^'\"]*"
    default_location = "경상남도자원봉사센터"
    default_category = "공익활동"
    tags_extra = ["자원봉사", "공익", "경남"]
    include_keywords = ["모집", "자원봉사", "봉사자", "교육", "온라인교육", "공모전", "신청", "참가", "청년봉사단", "이벤트"]
    negative_keywords = [*PublicSimpleBoardAdapter.negative_keywords, "직원채용", "입찰", "합격자", "서류전형"]


class JinhaeSeniorClubAdapter(PublicSimpleBoardAdapter):
    """진해시니어클럽 KBoard 공지사항."""

    parser_version = "jinhae_senior_club_v1"
    board_url = "http://jhcsc.or.kr/sub06-1/"
    url_pattern = r"[^'\"]*uid=\d+[^'\"]*"
    default_location = "진해시니어클럽"
    default_category = "복지건강"
    tags_extra = ["진해", "시니어", "노인일자리"]
    include_keywords = ["모집", "참여자", "노인일자리", "사회활동", "교육", "신청", "실습"]
    negative_keywords = [*PublicSimpleBoardAdapter.negative_keywords, "채용공고", "합격자", "서류전형"]


class SeongsanSeniorClubAdapter(PublicSimpleBoardAdapter):
    """성산시니어클럽 XE 공지사항."""

    parser_version = "seongsan_senior_club_v1"
    board_url = "http://cwssclub.or.kr/notice"
    page_param = "path"
    url_pattern = r"/notice/\d+"
    default_location = "성산시니어클럽"
    default_category = "복지건강"
    tags_extra = ["성산", "시니어", "노인일자리"]
    include_keywords = ["모집", "참여자", "노인일자리", "사회활동", "교육", "신청", "실습"]
    negative_keywords = [*PublicSimpleBoardAdapter.negative_keywords, "채용", "합격", "후원", "기부"]

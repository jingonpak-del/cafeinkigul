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


class GenericGnuboardAdapter(AdapterBase):
    """Configurable source-specific adapter base for Korean Gnuboard public notice boards.

    Subclasses are intentionally tiny but source-specific: each pins the institution,
    board URL, include/exclude vocabulary, location and tags while reusing the same
    hardened Gnuboard list/detail parsing logic.
    """

    parser_version = "generic_gnuboard_v1"
    board_url = ""
    allowed_boards: list[str] = []
    default_location = "창원시"
    default_category = "기타"
    tags_extra: list[str] = []
    max_pages = 3
    include_keywords = [
        "모집", "신청", "참여", "교육", "프로그램", "행사", "공모", "공모전", "지원사업",
        "상담", "강좌", "체험", "특강", "설명회", "멘토링", "컨설팅", "워크숍", "세미나",
        "입주", "참가", "수강", "접수", "운영", "공연", "전시",
    ]
    negative_keywords = [
        "채용", "합격", "서류전형", "면접", "직원", "인사", "입찰", "계약", "용역",
        "휴관", "휴무", "점검", "공사", "결산", "예산", "후원금", "회의 결과", "회의결과",
        "선정결과", "선정 결과", "수상자", "보도자료", "언론보도", "당선인", "선거", "대관",
    ]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            if len(items) >= limit:
                break
            sep = "&" if "?" in self.board_url else "?"
            url = self.board_url if page == 1 else f"{self.board_url}{sep}page={page}"
            try:
                html = self.fetch_html(url)
            except Exception:
                break
            added = 0
            for item in self.parse_list_html(html):
                stable = self._canonical_url(item.url)
                if stable in seen or not self._is_relevant(item.title):
                    continue
                if item.published_at and not is_within_days(item.published_at, since_days):
                    continue
                item.url = stable
                items.append(item)
                seen.add(stable)
                added += 1
                if len(items) >= limit:
                    break
            if added == 0 and page > 1:
                break
        return items

    def parse_list_html(self, html: str) -> list[ListingItem]:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I)
        if not rows:
            rows = re.findall(r"<li[^>]*>(.*?)</li>", html or "", re.S | re.I)
        items: list[ListingItem] = []
        board_pat = "|".join(re.escape(b) for b in (self.allowed_boards or [self._board_name(self.board_url)]))
        href_re = rf'<a[^>]+href=["\']([^"\']*(?:bo_table=(?:{board_pat})[^"\']*)?wr_id=\d+[^"\']*)["\'][^>]*>(.*?)</a>'
        for row in rows:
            match = re.search(href_re, row, re.S | re.I)
            if not match:
                continue
            href, inner = match.groups()
            title = self._clean_title(strip_tags(inner))
            subj = strip_tags(first_match(r'<td[^>]+class=["\'][^"\']*(?:td_subject|subject|title)[^"\']*["\'][^>]*>(.*?)</td>', row))
            if subj and len(subj) > len(title):
                title = self._clean_title(subj)
            date_text = strip_tags(first_match(r'<td[^>]+class=["\'][^"\']*(?:td_datetime|date|time)[^"\']*["\'][^>]*>(.*?)</td>', row))
            if not date_text:
                date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', row)
            if title:
                items.append(ListingItem(title=title, url=urljoin(self.board_url, unescape(href).replace("&amp;", "&")), status="공지사항", published_at=self._parse_date(date_text)))
        if not items:
            for href, inner in re.findall(href_re, html or "", re.S | re.I):
                title = self._clean_title(strip_tags(inner))
                if title:
                    items.append(ListingItem(title=title, url=urljoin(self.board_url, unescape(href).replace("&amp;", "&")), status="공지사항"))
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
        title = strip_tags(first_match(r'<[^>]+class=["\'][^"\']*bo_v_(?:tit|title)[^"\']*["\'][^>]*>(.*?)</[^>]+>\s*(?:<|$)', html))
        if not title:
            title = strip_tags(first_match(r'<span[^>]+class=["\'][^"\']*bo_v_tit[^"\']*["\'][^>]*>(.*?)</span>', html))
        if not title:
            title = strip_tags(first_match(r'<h[1234][^>]*>(.*?)</h[1234]>', html))
        if not title:
            title = strip_tags(first_match(r'<title[^>]*>\s*(?:게시판\s*>\s*)?(?:[^>]+>\s*)?(.*?)</title>', html))
        title = self._clean_title(title or "")
        if (not title or len(title) <= 3 or title in {"공지사항", "지원센터 알림", "상세정보", "센터알림", "GSAT", "사항 읽기"}) and fallback:
            title = self._clean_title(fallback.title)
        info = strip_tags(first_match(r'<section[^>]+id=["\']bo_v_info["\'][^>]*>(.*?)</section>', html))
        published_at = parse_first_date(info) or (fallback.published_at if fallback else None)
        body_html = first_match(r'<div[^>]+id=["\']bo_v_con["\'][^>]*>(.*?)</div>\s*(?:<script|<section|</article|<div[^>]+id=["\']bo_v_share)', html)
        if not body_html:
            body_html = first_match(r'<div[^>]+id=["\']bo_v_con["\'][^>]*>(.*?)</div>', html)
        if not body_html:
            body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:view|content|board_view)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\'][^"\']*(?:btn|reply|comment)|</article>)', html)
        if not body_html:
            body_html = first_match(r'<span[^>]+id=["\']writeContents["\'][^>]*>(.*?)</span>', html)
        body_text = strip_tags(body_html) or title
        if fallback and len(body_text) < 30 and len(fallback.title) > len(body_text):
            body_text = fallback.title
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        image_alts = [strip_tags(x) for x in re.findall(r'<img[^>]+(?:alt|title)=["\']([^"\']*)["\']', body_html or "", re.I) if x]
        if len(body_text) < 30 and image_alts:
            body_text = "\n".join([body_text, *image_alts]).strip()
        attachment_urls = [link for _, link in all_links(html, url) if any(k in link.lower() for k in ["download.php", "bbs/download", "file", "down"])]
        body_text = append_attachment_text(body_text or title, extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes))
        app_rng = self._extract_range(body_text, ["신청기간", "접수기간", "모집기간", "공모기간", "신청", "접수", "모집"])
        event_rng = self._extract_range(body_text, ["행사기간", "교육기간", "운영기간", "활동기간", "일시", "일정", "기간"])
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

    def _canonical_url(self, url: str) -> str:
        m_board = re.search(r"bo_table=([^&]+)", url)
        m_id = re.search(r"wr_id=(\d+)", url)
        if m_board and m_id:
            return urljoin(self.board_url, f"/bbs/board.php?bo_table={m_board.group(1)}&wr_id={m_id.group(1)}")
        return url

    @staticmethod
    def _board_name(url: str) -> str:
        return first_match(r"bo_table=([^&]+)", url) or "notice"

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\b\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}\b", " ", text)
        text = re.sub(r"조회수\s*[:：]?\s*\d+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"^(공지|알림)\s*", "", text).strip()
        if len(text) > 180:
            text = text[:180].rstrip() + "…"
        return text

    @staticmethod
    def _parse_date(text: str) -> str | None:
        full = parse_first_date(text)
        if full:
            return full
        m = re.search(r"(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text or "")
        if m:
            y, mo, d = map(int, m.groups())
            return f"20{y:02d}-{mo:02d}-{d:02d}"
        return None

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

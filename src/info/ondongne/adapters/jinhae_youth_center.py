from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import extract_labeled_range, is_within_days, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class JinhaeYouthCenterAdapter(AdapterBase):
    """Parser for 진해청소년수련관 KBoard notices/program recruitments."""

    parser_version = "jinhae_youth_center_v1"
    base = "https://jhyouth.kr"
    boards = [
        ("공지사항", "https://jhyouth.kr/community/information/"),
        ("청소년동아리", "https://jhyouth.kr/community/groupbbs/"),
        ("프로그램", "https://jhyouth.kr/community/event/"),
    ]
    include_keywords = ["모집", "신청", "프로그램", "교육", "참가", "참여", "동아리 모집", "포럼", "아동의회"]
    negative_keywords = ["휴관", "대관", "공사", "채용", "합격", "결과", "입찰", "공고", "식단표", "활동실 대관", "선도기관 선정"]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for board_name, board_url in self.boards:
            page = 1
            while len(items) < limit and page <= 3:
                url = board_url if page == 1 else f"{board_url}?pageid={page}"
                try:
                    html = self.fetch_html(url)
                except Exception:
                    break
                added = 0
                for item in self.parse_list_html(html, board_name=board_name, board_url=board_url):
                    if item.url in seen or not self._is_relevant(item.title):
                        continue
                    if item.published_at and not is_within_days(item.published_at, since_days):
                        continue
                    items.append(item)
                    seen.add(item.url)
                    added += 1
                    if len(items) >= limit:
                        break
                if added == 0:
                    break
                page += 1
            if len(items) >= limit:
                break
        return items

    def parse_list_html(self, html: str, board_name: str = "공지사항", board_url: str | None = None) -> list[ListingItem]:
        items: list[ListingItem] = []
        board_url = board_url or self.base
        row_blocks = re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I)
        if row_blocks:
            for row in row_blocks:
                href = first_match(r'<a[^>]+href=["\']([^"\']*\?uid=\d+[^"\']*)["\']', row)
                if not href:
                    continue
                title = strip_tags(first_match(r'<div[^>]+class=["\']kboard-default-cut-strings["\'][^>]*>(.*?)</div>', row))
                if not title:
                    title = strip_tags(first_match(r'<a[^>]+href=["\'][^"\']*\?uid=\d+[^"\']*["\'][^>]*>(.*?)</a>', row))
                title = re.sub(r"\s+", " ", title).strip()
                published_at = parse_first_date(strip_tags(first_match(r'<td[^>]+class=["\']kboard-list-date["\'][^>]*>(.*?)</td>', row)))
                if title and title not in {"이전글", "다음글"}:
                    items.append(ListingItem(title=title, url=urljoin(board_url, unescape(href)), status=board_name, published_at=published_at))
        else:
            for href, inner in re.findall(r'<a[^>]+href=["\']([^"\']*\?uid=\d+[^"\']*)["\'][^>]*>(.*?)</a>', html or "", re.S | re.I):
                title = re.sub(r"\s+", " ", strip_tags(inner)).strip()
                if not title or title in {"이전글", "다음글"}:
                    continue
                items.append(ListingItem(title=title, url=urljoin(board_url, unescape(href)), status=board_name))
        deduped: list[ListingItem] = []
        seen: set[str] = set()
        for item in items:
            if item.url not in seen:
                deduped.append(item)
                seen.add(item.url)
        return deduped

    def parse_detail(self, item: ListingItem) -> Event:
        html = self.fetch_html(item.url)
        return self.parse_detail_html(html, item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = strip_tags(first_match(r'<div[^>]+class=["\']kboard-title["\'][^>]*>\s*<h1[^>]*>(.*?)</h1>', html)) or (fallback.title if fallback else "")
        title = re.sub(r"\s+", " ", title).strip()
        published_at = parse_first_date(first_match(r'<div[^>]+class=["\']detail-attr detail-date["\'][^>]*>.*?<div[^>]+class=["\']detail-value["\'][^>]*>(.*?)</div>', html))
        body_html = first_match(r'<div[^>]+class=["\']kboard-content["\'][^>]*>\s*<div[^>]+class=["\']content-view["\'][^>]*>(.*?)</div>\s*</div>', html)
        body_text = strip_tags(body_html)
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        image_alts = [strip_tags(alt) for alt in re.findall(r'<img[^>]+alt=["\']([^"\']*)["\']', body_html or "", re.I) if alt]
        if len(body_text) < 20 and image_alts:
            body_text = "\n".join([body_text, *image_alts]).strip()
        attachment_urls: list[str] = []
        for link in re.findall(r"window\.location\.href=['\"]([^'\"]+action=kboard_file_download[^'\"]+)['\"]", html or "", re.I):
            full = urljoin(url, unescape(link))
            if full not in attachment_urls:
                attachment_urls.append(full)
        for _, link in all_links(html, url):
            if "kboard_file_download" in link and link not in attachment_urls:
                attachment_urls.append(link)
        extracted = extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes)
        body_text = append_attachment_text(body_text or title, extracted)
        app_rng = extract_labeled_range(body_text, ["신청기간", "접수기간", "모집기간", "기간"])
        event_rng = extract_labeled_range(body_text, ["활동기간", "교육기간", "행사기간", "일시", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "신청대상", "참가대상"])
        location = self._extract_labeled_value(body_text, ["장소", "활동장소", "교육장소"])
        category = classify_category(title + " " + body_text, self.source.get("category_hint", "아동청소년"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(title + " " + body_text), location_name=location,
            application_start_date=app_rng.start, application_end_date=app_rng.end,
            event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=published_at, apply_url=url,
            attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [category, "창원시", "진해", "청소년"] if t], parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        if any(k in text for k in self.negative_keywords):
            return False
        return any(k in text for k in self.include_keywords)

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|[\n\r\s])" + re.escape(label) + r"\s*[:：-]?\s*([^\n\r]{2,90})", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

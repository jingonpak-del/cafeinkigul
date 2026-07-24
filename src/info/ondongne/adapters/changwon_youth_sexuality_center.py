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


class ChangwonYouthSexualityCenterAdapter(AdapterBase):
    """Parser for 창원시청소년성문화센터 Gnuboard notices."""

    parser_version = "changwon_youth_sexuality_center_v1"
    base = "http://www.cwsay.net"
    list_url = "http://www.cwsay.net/bbs/board.php?bo_table=say51&sca=&sfl=mb_id,1&stx=admin"
    include_keywords = ["신청", "모집", "프로그램", "교육", "체험", "캠프", "와글와글", "도담도담", "사춘기"]
    negative_keywords = ["채용", "합격", "결과", "직원", "공고", "휴관", "점검", "입찰", "계약"]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, 5):
            url = self.list_url + (f"&page={page}" if page > 1 else "")
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
                    return items
            if page > 1 and added == 0:
                break
        return items

    def parse_list_html(self, html: str, page_url: str | None = None) -> list[ListingItem]:
        page_url = page_url or self.list_url
        items: list[ListingItem] = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I):
            href = first_match(r'<a[^>]+href=["\']([^"\']*bo_table=say51[^"\']*wr_id=\d+[^"\']*)["\']', row)
            if not href:
                continue
            title = strip_tags(first_match(r'<div[^>]+class=["\'][^"\']*td-subject[^"\']*["\'][^>]*>(.*?)</div>', row))
            if not title:
                title = strip_tags(first_match(r'<a[^>]+href=["\'][^"\']*wr_id=\d+[^"\']*["\'][^>]*>(.*?)</a>', row))
            title = re.sub(r"\s+", " ", title).replace("공지", "", 1).strip()
            date_text = strip_tags(first_match(r'<td[^>]+class=["\'][^"\']*td-date[^"\']*["\'][^>]*>(.*?)</td>', row))
            published_at = self._parse_date(date_text)
            if title:
                items.append(ListingItem(title=title, url=urljoin(page_url, unescape(href)), status="공지사항", published_at=published_at))
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
        title = strip_tags(first_match(r'<article[^>]+class=["\'][^"\']*board-view[^"\']*["\'][^>]*>.*?<h4>\s*<strong>(.*?)</strong>', html))
        title = title or strip_tags(first_match(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html))
        title = re.sub(r"\s*>\s*공지사항.*$", "", title or (fallback.title if fallback else "")).strip()
        title = re.sub(r"\s+", " ", title)
        info = strip_tags(first_match(r'<section[^>]+class=["\'][^"\']*board-view-info[^"\']*["\'][^>]*>(.*?)</section>', html))
        published_at = parse_first_date(info) or (fallback.published_at if fallback else None)
        body_html = first_match(r'<div[^>]+class=["\'][^"\']*view-content[^"\']*["\'][^>]*>(.*?)</div>\s*</section>', html)
        body_text = strip_tags(body_html)
        og_desc = strip_tags(first_match(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']', html))
        if len(body_text) < 30 and og_desc:
            body_text = og_desc
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        image_alts = [strip_tags(alt) for alt in re.findall(r'<img[^>]+alt=["\']([^"\']*)["\']', body_html or "", re.I) if alt]
        if len(body_text) < 30 and image_alts:
            body_text = "\n".join([body_text, *image_alts]).strip()
        attachment_urls = [link for _, link in all_links(html, url) if "download.php" in link or "file" in link.lower()]
        body_text = append_attachment_text(body_text or title, extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes))
        app_rng = extract_labeled_range(body_text, ["신청기간", "접수기간", "모집기간"])
        event_rng = extract_labeled_range(body_text, ["교육기간", "운영기간", "행사기간", "일시", "일정"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "참가대상", "신청대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "진행장소"])
        text = title + " " + body_text
        category = classify_category(text, self.source.get("category_hint", "아동청소년"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text) or "창원시 청소년/가족", location_name=location or "창원시청소년성문화센터",
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=published_at,
            apply_url=url, attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [category, "창원시", "청소년", "성교육"] if t], parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        return bool(text) and not any(k in text for k in self.negative_keywords) and any(k in text for k in self.include_keywords)

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
            m = re.search(r"(?:^|[\n\r\s■□-])" + re.escape(label) + r"\s*[:：-]?\s*([^\n\r■□]{2,90})", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

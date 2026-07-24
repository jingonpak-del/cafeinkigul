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


class SeongsanSeniorWelfareAdapter(AdapterBase):
    """Parser for 성산노인종합복지관 notice board."""

    parser_version = "seongsan_senior_welfare_v1"
    base = "https://ssswc.cwwf.or.kr"
    list_url = "https://ssswc.cwwf.or.kr/sub/board_01.php?code=notice"
    include_keywords = ["모집", "신청", "교육", "프로그램", "강좌", "행사", "상담", "음악회", "참여", "수강"]
    negative_keywords = ["채용", "입찰", "계약", "공사", "휴관", "식단", "수질검사", "결산", "추경", "합격", "실습생"]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, 6):
            url = self.list_url + f"&page={page}"
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
        for li in re.findall(r"<li>\s*<a\s+href=[\"']([^\"']*board_01\.php[^\"']*bbsData=[^\"']*mode=view[^\"']*)[\"'][^>]*>(.*?)</a>\s*</li>", html or "", re.S | re.I):
            href, inner = li
            title = strip_tags(first_match(r'<span[^>]+class=["\']title["\'][^>]*>(.*?)</span>', inner))
            date_text = strip_tags(first_match(r'<span[^>]+class=["\']date["\'][^>]*>(.*?)</span>', inner))
            published_at = self._parse_date(date_text)
            title = re.sub(r"\s+", " ", title).strip()
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
        title = strip_tags(first_match(r'<div[^>]+class=["\']viewTop["\'][^>]*>\s*<h4>(.*?)</h4>', html))
        if not title:
            title = strip_tags(first_match(r'<dt[^>]*class=["\']subject["\'][^>]*>(.*?)</dt>', html))
        if not title:
            title = strip_tags(first_match(r'<p[^>]*class=["\']subject["\'][^>]*>(.*?)</p>', html))
        if not title:
            title = strip_tags(first_match(r'<span[^>]+class=["\']title["\'][^>]*>(.*?)</span>', html))
        title = re.sub(r"\s+", " ", title or (fallback.title if fallback else "")).strip()
        info_text = strip_tags(first_match(r'<div[^>]+class=["\']viewTop["\'][^>]*>(.*?)</div>', html))
        if not info_text:
            info_text = strip_tags(first_match(r'<div[^>]+class=["\'][^"\']*board_view[^"\']*["\'][^>]*>(.*?)</div>', html))
        published_at = parse_first_date(info_text) or (fallback.published_at if fallback else None)
        body_html = first_match(r'<div[^>]+class=["\']v_contents["\'][^>]*>(.*?)</div>\s*<!--', html)
        if not body_html:
            body_html = first_match(r'<dd[^>]*class=["\']content["\'][^>]*>(.*?)</dd>', html)
        if not body_html:
            body_html = first_match(r'<div[^>]+class=["\'][^"\']*view_cont[^"\']*["\'][^>]*>(.*?)</div>', html)
        if not body_html:
            body_html = first_match(r'<td[^>]+class=["\'][^"\']*content[^"\']*["\'][^>]*>(.*?)</td>', html)
        body_text = strip_tags(body_html or info_text)
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        image_alts = [strip_tags(alt) for alt in re.findall(r'<img[^>]+alt=["\']([^"\']*)["\']', body_html or "", re.I) if alt]
        if len(body_text) < 30 and image_alts:
            body_text = "\n".join([body_text, *image_alts]).strip()
        attachment_urls = [link for _, link in all_links(html, url) if "download" in link.lower() or "file" in link.lower()]
        body_text = append_attachment_text(body_text or title, extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes))
        app_rng = extract_labeled_range(body_text, ["신청기간", "접수기간", "모집기간", "접수"])
        event_rng = extract_labeled_range(body_text, ["교육기간", "운영기간", "행사기간", "일시", "일정", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "참가대상", "신청대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "진행장소"])
        text = title + " " + body_text
        category = classify_category(text, self.source.get("category_hint", "복지건강"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text) or "창원시 어르신", location_name=location or "성산노인종합복지관",
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=published_at,
            apply_url=url, attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [category, "창원시", "성산", "노인복지"] if t], parser_version=self.parser_version,
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
            m = re.search(r"(?:^|[\n\r\s○●■□-])" + re.escape(label) + r"\s*[:：-]?\s*([^\n\r○●■□]{2,90})", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

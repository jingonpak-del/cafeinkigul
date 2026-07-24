from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from ..classify import classify_category, classify_audience, detect_price_type
from ..date_parser import extract_labeled_range, is_within_days, parse_date_range
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class ChangwonCityCalendarAdapter(AdapterBase):
    """Precise parser for 창원특례시 캘린더로 보는 소식."""

    parser_version = "changwon_city_calendar_v1"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        html = self.fetch_html(self.source["base_url"])
        details = first_match(r'<div class="schedule2list1" id="details">(.*?)(?:</div>\s*</div>\s*<!-- schedule2|</form>)', html)
        if not details:
            details = html
        items: list[ListingItem] = []
        current_category = self.source.get("category_hint", "행사")
        for part in re.split(r'(<h4[^>]*class="hb1 h2"[^>]*>.*?</h4>)', details, flags=re.S | re.I):
            if part.startswith("<h4"):
                current_category = strip_tags(part).replace(" 일정", "").strip() or current_category
                continue
            for li in re.findall(r"<li[^>]*>(.*?)</li>", part, re.S | re.I):
                href = first_match(r'<a[^>]+href="([^"]+)"[^>]*class="[^"]*btn-view', li)
                title = strip_tags(first_match(r'<strong[^>]*class="h3"[^>]*>(.*?)</strong>', li))
                period = strip_tags(first_match(r'<span[^>]*class="date"[^>]*>(.*?)</span>', li))
                department = strip_tags(first_match(r'<span[^>]*class="t1"[^>]*>(.*?)</span>', li))
                published_at = strip_tags(first_match(r'<span[^>]*class="t2"[^>]*>(.*?)</span>', li))
                rng = parse_date_range(period)
                # Calendar items are relevant while their event/application period is still recent or active.
                if rng.end and not is_within_days(rng.end, since_days):
                    continue
                if not href or not title:
                    continue
                items.append(
                    ListingItem(
                        title=title,
                        url=urljoin("https://www.changwon.go.kr", unescape(href)),
                        status=current_category,
                        application_period_text=period,
                        department=department,
                        published_at=published_at or None,
                    )
                )
                if len(items) >= limit:
                    return items
        return items

    def parse_detail(self, item: ListingItem) -> Event:
        html = self.fetch_html(item.url)
        if "booking1view" in html:
            return self._parse_booking_detail(html, item)
        return self._parse_bbs_detail(html, item)

    def _parse_booking_detail(self, html: str, item: ListingItem) -> Event:
        view_html = first_match(r'<div class="booking1view">(.*?)(?:<script>|<div id="body_foot")', html) or html
        title_html = first_match(r'<h2 class="h1">(.*?)</h2>', view_html)
        title = strip_tags(re.sub(r'<span class="cate1">.*?</span>', '', title_html, flags=re.S | re.I)) or item.title
        status = strip_tags(first_match(r'<span class="cate1">(.*?)</span>', title_html)) or item.status
        info_text = strip_tags(first_match(r'<ul class="info1">(.*?)</ul>', view_html))
        body_html = first_match(r'<div class="substance">(.*?)</div>', view_html)
        body_text = strip_tags(body_html) or f"{title}\n기간: {item.application_period_text}\n담당부서: {item.department}"
        app_range = extract_labeled_range(info_text, ["접수 기간", "접수기간", "신청기간"])
        event_range = extract_labeled_range(body_text, ["일 시", "일시", "교육기간", "행사기간", "기간"])
        if not event_range.start:
            event_range = parse_date_range(item.application_period_text)
        department = self._extract_info_value(info_text, "담당 부서") or item.department
        location = self._extract_labeled_value(body_text, ["장 소", "장소"])
        target = self._extract_labeled_value(body_text, ["대 상", "대상"])
        apply_href = first_match(r'<a href="([^"]+)" class="button submit">접수</a>', view_html)
        category = classify_category(title + " " + body_text + " " + item.status, item.status or self.source.get("category_hint", "행사"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=item.url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(title + " " + body_text), location_name=location,
            application_start_date=app_range.start, application_end_date=app_range.end,
            event_start_date=event_range.start, event_end_date=event_range.end,
            price_type=detect_price_type(body_text), status=status, published_at=item.published_at,
            apply_url=urljoin(item.url, unescape(apply_href)) if apply_href else item.url,
            attachment_urls=[u for _, u in all_links(view_html, item.url) if "download" in u.lower() or "cmsfile" in u.lower()],
            image_urls=self._image_urls(body_html, item.url),
            tags=[t for t in [category, self.source.get("region_level2", ""), department] if t], parser_version=self.parser_version,
        ).finalize()

    def _parse_bbs_detail(self, html: str, item: ListingItem) -> Event:
        view_html = first_match(r'<div class="bbs1view1">(.*?)(?:<div class="btn1s"|<div id="body_foot")', html) or html
        title = strip_tags(first_match(r'<h1[^>]*id="sns_bbs_title"[^>]*>(.*?)</h1>', view_html)) or item.title
        info_text = strip_tags(first_match(r'<div class="info1">(.*?)</div>', view_html))
        published_at = self._parse_date(self._extract_info_value(info_text, "등록일")) or self._parse_date(info_text) or item.published_at
        department = self._extract_info_value(info_text, "담당부서") or item.department
        body_html = first_match(r'<div class="substance">(.*?)(?:</div>\s*<!-- //substance|<div class="btn1s"|</div>\s*</div>)', view_html)
        body_text = strip_tags(body_html)
        if not body_text or len(body_text) < 20:
            body_text = f"{title}\n기간: {item.application_period_text}\n담당부서: {department}"
        event_range = extract_labeled_range(body_text, ["교육기간", "행사기간", "일시", "기간"])
        if not event_range.start:
            event_range = parse_date_range(item.application_period_text)
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소"])
        target = self._extract_labeled_value(body_text, ["대상", "교육대상", "모집대상"])
        category = classify_category(title + " " + body_text + " " + item.status, item.status or self.source.get("category_hint", "행사"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=item.url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(title + " " + body_text), location_name=location,
            event_start_date=event_range.start, event_end_date=event_range.end,
            price_type=detect_price_type(body_text), status=item.status, published_at=published_at, apply_url=item.url,
            attachment_urls=[u for _, u in all_links(view_html, item.url) if "download" in u.lower() or "cmsfile" in u.lower()],
            image_urls=self._image_urls(body_html, item.url),
            tags=[t for t in [category, self.source.get("region_level2", ""), department] if t], parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _extract_info_value(info_text: str, label: str) -> str:
        text = re.sub(r"\s+", " ", info_text or "")
        m = re.search(re.escape(label) + r"\s*:?\s*([^:]+?)(?=등록일|담당부서|조회수|$)", text)
        return m.group(1).strip(" -") if m else ""

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|\n)\s*[■○]?\s*" + re.escape(label) + r"\s*[:：]?\s*([^\n■]+)", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

    @staticmethod
    def _parse_date(text: str) -> str | None:
        m = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", text or "")
        if not m:
            return None
        y, mo, d = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"

    @staticmethod
    def _image_urls(html: str, base: str) -> list[str]:
        urls = []
        for img in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html or "", re.I):
            full = urljoin(base, unescape(img))
            if full not in urls:
                urls.append(full)
        return urls

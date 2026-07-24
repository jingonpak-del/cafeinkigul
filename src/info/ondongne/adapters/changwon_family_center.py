from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import extract_labeled_range, is_within_days, parse_date_range
from ..html_utils import first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class ChangwonFamilyCenterAdapter(AdapterBase):
    """Parser for 창원시 가족센터 familynet program recruitment cards."""

    parser_version = "changwon_family_center_v1"
    base = "https://changwon.familynet.or.kr"
    list_path = "/center/lay1/program/S295T322C451/recruitReceipt/list.do"

    negative_keywords = ["채용", "입찰", "계약", "합격자", "결과발표", "강사 모집"]

    @property
    def list_url(self) -> str:
        return urljoin(self.base, self.list_path)

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        page = 1
        while len(items) < limit and page <= 5:
            url = self.list_url if page == 1 else f"{self.list_url}?rows=5&cpage={page}"
            try:
                html = self.fetch_html(url)
            except Exception:
                break
            added = 0
            for item in self.parse_list_html(html, source_url=url):
                if item.url in seen:
                    continue
                if not self._is_relevant(item.title + " " + item.application_period_text + " " + item.department):
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
        return items

    def parse_list_html(self, html: str, source_url: str | None = None) -> list[ListingItem]:
        items: list[ListingItem] = []
        for block in re.findall(r'<li class=["\']clearfix["\']>(.*?)</li>\s*(?=<li class=["\']clearfix["\']>|</ul>)', html or "", re.S | re.I):
            title = strip_tags(first_match(r'<p[^>]+class=["\']tit["\'][^>]*>\s*<a[^>]+onclick=["\']send\([^,]+,\s*["\'](.*?)["\']\s*,', block))
            if not title:
                title = strip_tags(first_match(r'<p[^>]+class=["\']tit["\'][^>]*>(.*?)</p>', block))
            title = unescape(title).replace("&#039;", "'").strip()
            program_id = first_match(r"send\(['\"](\d+)['\"]", block)
            if not title or not program_id:
                continue
            alt_text = strip_tags(first_match(r'<img[^>]+alt=["\']([^"\']*)["\']', block))
            card_text = strip_tags(block)
            event_period = self._field_after_label(card_text, "행사기간")
            app_period = self._field_after_label(card_text, "접수기간")
            location = self._field_after_label(card_text, "진행장소")
            status = strip_tags(first_match(r'<span[^>]+class=["\']c\d+["\'][^>]*>(.*?)</span>', block))
            body = "\n".join(x for x in [title, card_text, alt_text] if x)
            url = f"{self.list_url}?program_id={program_id}#program_{program_id}"
            item = ListingItem(title=title, url=url, status=status or "프로그램신청", application_period_text=app_period, department=location)
            # ListingItem has fixed fields, so preserve rich list body in an attribute for parse_detail/tests.
            item.body_text = body  # type: ignore[attr-defined]
            item.event_period_text = event_period  # type: ignore[attr-defined]
            item.location = location  # type: ignore[attr-defined]
            items.append(item)
        return items

    def parse_detail(self, item: ListingItem) -> Event:
        body_text = getattr(item, "body_text", "")
        if not body_text:
            # Synthetic URL points back to the list card; refetch list and find matching id.
            program_id = first_match(r"program_id=(\d+)", item.url)
            try:
                for parsed in self.parse_list_html(self.fetch_html(self.list_url)):
                    if program_id and program_id in parsed.url:
                        item = parsed
                        body_text = getattr(parsed, "body_text", "")
                        break
            except Exception:
                body_text = item.title
        app_rng = parse_date_range(item.application_period_text) or extract_labeled_range(body_text, ["접수기간", "모집기간", "신청기간"])
        event_rng = parse_date_range(getattr(item, "event_period_text", ""))
        if not event_rng.start:
            event_rng = extract_labeled_range(body_text, ["행사기간", "교육기간", "운영기간", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "인원", "모집대상"])
        location = getattr(item, "location", "") or item.department or self._extract_labeled_value(body_text, ["진행장소", "장소"])
        category = classify_category(item.title + " " + body_text, self.source.get("category_hint", "가족"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=item.title, source_url=item.url, category=category, summary=summarize_event(item.title, body_text), body_text=body_text,
            target_audience=target or classify_audience(item.title + " " + body_text), location_name=location,
            application_start_date=app_rng.start, application_end_date=app_rng.end,
            event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=item.status or "프로그램신청", apply_url=self.list_url,
            tags=[t for t in [category, "창원시", "가족센터", "프로그램"] if t], parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        if any(k in text for k in self.negative_keywords):
            return False
        include = self.source.get("include_keywords", [])
        return not include or any(k in text for k in include)

    @staticmethod
    def _field_after_label(text: str, label: str) -> str:
        m = re.search(re.escape(label) + r"\s*([^\n]+)", text or "")
        return re.sub(r"\s+", " ", m.group(1)).strip(" -") if m else ""

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|[\n\r\s])" + re.escape(label) + r"\s*[:：-]?\s*([^\n\r]{2,80})", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

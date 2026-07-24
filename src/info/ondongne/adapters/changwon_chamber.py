from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .base import AdapterBase, ListingItem
from ..classify import classify_category, classify_audience, detect_price_type
from ..date_parser import extract_labeled_range, is_within_days, parse_date_range
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class ChangwonChamberAdapter(AdapterBase):
    """Precise parser for 창원상공회의소 행사/교육 AJAX board."""

    parser_version = "changwon_chamber_v1"
    base = "https://changwon.korcham.net"
    list_url = base + "/front/event/eventListPage.do?menuId="
    view_url = base + "/front/event/eventView.do?menuId="

    def fetch_post(self, url: str, data: dict[str, str], timeout: int = 20) -> str:
        payload = urlencode(data).encode()
        req = Request(
            url,
            data=payload,
            headers={
                "User-Agent": "Mozilla/5.0 OndongneBot/0.2",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": self.base + "/front/event/eventList.do",
            },
        )
        raw = urlopen(req, timeout=timeout).read()
        return raw.decode("utf-8", errors="ignore")

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        include_keywords = self.source.get("include_keywords", [])
        exclude_keywords = self.source.get("exclude_keywords", [])
        page = 1
        while len(items) < limit and page <= 10:
            html = self.fetch_post(
                self.list_url,
                {"miv_pageNo": str(page), "miv_pageSize": "15", "mode": "W", "state": ""},
            )
            added = 0
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
                if "eventView" not in row:
                    continue
                event_id = first_match(r"eventView\(['\"]([^'\"]+)['\"]\)", row)
                title = strip_tags(first_match(r'<td[^>]*class=["\']title[^"\']*["\'][^>]*>(.*?)</td>', row))
                cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
                period_text = cells[1] if len(cells) > 1 else ""
                status = cells[2] if len(cells) > 2 else ""
                haystack = title + " " + period_text + " " + status
                if exclude_keywords and any(k in haystack for k in exclude_keywords):
                    continue
                if include_keywords and not any(k in haystack for k in include_keywords):
                    continue
                rng = parse_date_range(period_text)
                if not is_within_days(rng.end or rng.start, since_days):
                    continue
                if event_id and title and event_id not in seen:
                    state = first_match(r"eventState" + re.escape(event_id) + r"[^>]+value=['\"]([^'\"]+)['\"]", row)
                    items.append(
                        ListingItem(
                            title=title,
                            url=self.view_url + "&eventId=" + event_id,
                            status=status,
                            application_period_text=period_text,
                            department=state,
                        )
                    )
                    seen.add(event_id)
                    added += 1
                    if len(items) >= limit:
                        break
            if added == 0:
                break
            page += 1
        return items

    def parse_detail(self, item: ListingItem) -> Event:
        event_id = first_match(r"eventId=([^&]+)", item.url)
        html = self.fetch_post(
            self.view_url,
            {"eventId": event_id, "state": item.department or "", "miv_pageNo": "1", "miv_pageSize": "15", "mode": "W"},
        )
        return self.parse_detail_html(html, item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        fields = self._table_fields(html)
        title = fields.get("제목", "") or (fallback.title if fallback else "")
        event_period = fields.get("행사/교육 일자", "") or (fallback.application_period_text if fallback else "")
        department = fields.get("담당부서", "")
        manager = fields.get("담당자", "")
        method = fields.get("참가신청방법", "")
        body_html = first_match(r'<td[^>]*class=["\']td_p["\'][^>]*>(.*?)</td>', html)
        body_text = strip_tags(body_html)
        if not body_text or len(body_text) < 20:
            body_text = "\n".join(f"{k}: {v}" for k, v in fields.items() if v)
        else:
            prefix = "\n".join(f"{k}: {v}" for k, v in fields.items() if k != "제목" and v)
            body_text = "\n".join(x for x in [prefix, body_text] if x)
        event_rng = parse_date_range(event_period)
        app_rng = extract_labeled_range(body_text, ["접수기간", "신청기간", "모집기간"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소", "강의장소"])
        target = self._extract_labeled_value(body_text, ["대상", "교육대상", "참석대상", "수강대상"])
        attachment_urls = []
        image_urls = []
        for text, link in all_links(html, self.base):
            if "/file/" in link and link not in attachment_urls:
                attachment_urls.append(link)
        for img in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I):
            full = urljoin(self.base, unescape(img))
            if full not in image_urls:
                image_urls.append(full)
        category = classify_category(title + " " + body_text, self.source.get("category_hint", "취업창업"))
        status = (fallback.status if fallback else "") or method
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(title + " " + body_text), location_name=location,
            application_start_date=app_rng.start, application_end_date=app_rng.end,
            event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=status, apply_url=url,
            attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [category, self.source.get("region_level2", ""), department, manager] if t],
            parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _table_fields(html: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I):
            cells = re.findall(r"<(?:th|td)[^>]*>(.*?)</(?:th|td)>", row, re.S | re.I)
            clean = [strip_tags(c).strip() for c in cells]
            clean = [re.sub(r"\s+", " ", c).strip() for c in clean]
            for i in range(0, len(clean) - 1, 2):
                label = clean[i].strip()
                value = clean[i + 1].strip()
                if label and value and len(label) <= 20:
                    fields[label] = value
        return fields

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|\n|\s|[·∙-])" + re.escape(label) + r"\s*[:：]\s*([^\n]+)", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

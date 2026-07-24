from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from ..classify import classify_category, classify_audience, detect_price_type
from ..date_parser import extract_labeled_range, is_within_days
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class ChangwonRehabCenterAdapter(AdapterBase):
    """Precise parser for 창원시장애인종합복지관 공지사항 모집/교육/행사 글."""

    parser_version = "changwon_rehab_center_v1"
    list_url = "https://www.cwrehab.or.kr/bbs/board.php?bo_table=board_customer1"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        page = 1
        include_keywords = self.source.get("include_keywords", [])
        exclude_keywords = self.source.get("exclude_keywords", [])
        while len(items) < limit and page <= 10:
            url = self.list_url if page == 1 else f"{self.list_url}&page={page}"
            html = self.fetch_html(url)
            added = 0
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
                if "wr_id=" not in row or "bo_tit" not in row:
                    continue
                href = first_match(r'href=["\']([^"\']*board\.php\?bo_table=board_customer1[^"\']*wr_id=\d+[^"\']*)["\']', row)
                title_html = first_match(r'<div class=["\']bo_tit["\'][^>]*>(.*?)</div>', row)
                title = strip_tags(first_match(r"<a[^>]*>(.*?)</a>", title_html)).strip()
                title = re.sub(r"^(H\s*인기글|인기글|공지)\s*", "", title).strip()
                published_at = self._parse_list_date(strip_tags(first_match(r'<td[^>]*class=["\'][^"\']*td_datetime[^"\']*["\'][^>]*>(.*?)</td>', row)))
                haystack = title + " " + strip_tags(row)
                if exclude_keywords and any(k in haystack for k in exclude_keywords):
                    continue
                if include_keywords and not any(k in haystack for k in include_keywords):
                    continue
                if published_at and not is_within_days(published_at, since_days):
                    continue
                if href and title:
                    items.append(ListingItem(title=title, url=urljoin("https://www.cwrehab.or.kr", unescape(href)), status="공지사항", published_at=published_at))
                    added += 1
                    if len(items) >= limit:
                        break
            if added == 0:
                break
            page += 1
        return items

    def parse_detail(self, item: ListingItem) -> Event:
        html = self.fetch_html(item.url)
        return self.parse_detail_html(html, item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = strip_tags(first_match(r'<span class=["\']bo_v_tit["\'][^>]*>(.*?)</span>', html)) or (fallback.title if fallback else "")
        body_html = first_match(r'<div id=["\']bo_v_con["\'][^>]*>(.*?)(?:</div>\s*</section>|<div id=["\']bo_v_share)', html)
        body_text = strip_tags(body_html) or title
        published_at = self._parse_detail_date(html) or (fallback.published_at if fallback else None)
        app_rng = extract_labeled_range(body_text, ["모집기간", "접수기간", "신청기간", "접수"])
        event_rng = extract_labeled_range(body_text, ["교육기간", "행사기간", "프로그램기간", "일시", "기간"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소"])
        target = self._extract_labeled_value(body_text, ["대상", "교육대상", "모집대상", "참여대상"])
        attachment_urls = []
        for _, link in all_links(html, url):
            if any(token in link for token in ["download.php", "download", "view_image.php", "/data/file/"]) and link not in attachment_urls:
                attachment_urls.append(link)
        image_urls = []
        for img in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html, re.I):
            full = urljoin(url, unescape(img))
            if full not in image_urls:
                image_urls.append(full)
        category = classify_category(title + " " + body_text, self.source.get("category_hint", "복지건강"))
        audience = target or classify_audience(title + " " + body_text)
        return Event(
            source_id=self.source["id"],
            source_name=self.source["name"],
            organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""),
            region_level2=self.source.get("region_level2", ""),
            title=title,
            source_url=url,
            category=category,
            summary=summarize_event(title, body_text),
            body_text=body_text,
            target_audience=audience,
            location_name=location,
            application_start_date=app_rng.start,
            application_end_date=app_rng.end,
            event_start_date=event_rng.start,
            event_end_date=event_rng.end,
            price_type=detect_price_type(body_text),
            status=(fallback.status if fallback else "공지사항"),
            published_at=published_at,
            apply_url=url,
            attachment_urls=attachment_urls,
            image_urls=image_urls,
            tags=[t for t in [category, self.source.get("region_level2", ""), "창원시장애인종합복지관"] if t],
            parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _parse_list_date(text: str) -> str | None:
        text = (text or "").strip()
        m = re.search(r"(\d{2})-(\d{1,2})", text)
        if m:
            mo, d = map(int, m.groups())
            return f"{datetime.now().year:04d}-{mo:02d}-{d:02d}"
        return ChangwonRehabCenterAdapter._parse_detail_date(text)

    @staticmethod
    def _parse_detail_date(text: str) -> str | None:
        m = re.search(r"(\d{2,4})[./-](\d{1,2})[./-](\d{1,2})", text or "")
        if not m:
            return None
        y, mo, d = map(int, m.groups())
        if y < 100:
            y += 2000
        return f"{y:04d}-{mo:02d}-{d:02d}"

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|\n|\s)" + re.escape(label) + r"\s*[:：]\s*([^\n]+)", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

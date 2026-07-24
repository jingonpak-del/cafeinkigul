from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from ..classify import classify_category, classify_audience, detect_price_type
from ..date_parser import extract_labeled_range, parse_date_range, is_within_days
from ..html_utils import first_match, strip_tags, all_links
from ..models import Event
from ..summarizer import summarize_event


class ChangwonBookingAdapter(AdapterBase):
    """Precise parser for 창원시 일상플러스 통합예약 교육강좌.

    List/detail path: /booking/10030/10039/10327.web
    """

    parser_version = "changwon_booking_v1"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        page = 1
        while len(items) < limit and page <= 20:
            sep = "&" if "?" in self.source["base_url"] else "?"
            url = self.source["base_url"] if page == 1 else f"{self.source['base_url']}{sep}cpage={page}"
            html = self.fetch_html(url)
            blocks = re.findall(r'<li class="li1">(.*?)</li>\s*(?=<li class="li1">|</ul>)', html, re.S | re.I)
            if not blocks:
                # fallback for nested li parsing: take each list card up to next card marker
                section = first_match(r'<div class="cp31edu1list1">(.*?)(?:<div class="infomenu1">|</div>\s*<!-- /#body_content)', html)
                blocks = re.split(r'(?=<li class="li1">)', section)[1:]
            added = 0
            for block in blocks:
                item = self.parse_list_block(block)
                if not item:
                    continue
                app_rng = parse_date_range(item.application_period_text)
                # 통합예약은 장기 접수도 현재 신청 가능하면 가치가 있어 마감일 기준으로 필터링한다.
                if app_rng.end and not is_within_days(app_rng.end, since_days):
                    continue
                items.append(item)
                added += 1
                if len(items) >= limit:
                    break
            if added == 0:
                break
            page_count_text = strip_tags(first_match(r'<div class="info1">(.*?)</div>', html))
            m_page = re.search(r'\((\d+)\s*/\s*(\d+)\s*페이지\)', page_count_text)
            if m_page and int(m_page.group(1)) >= int(m_page.group(2)):
                break
            if f"cpage={page + 1}" not in html and f"cpage={page+1}" not in html:
                break
            page += 1
        return items

    def parse_list_block(self, block: str) -> ListingItem | None:
        href = first_match(r'<a[^>]+href="([^"]*amode=view[^"]*)"', block)
        if not href:
            return None
        title = strip_tags(first_match(r'<span class="h1">(.*?)</span>', block))
        if not title:
            title = strip_tags(first_match(r'<a[^>]+class="tg1"[^>]*>(.*?)</a>', block))
        status = strip_tags(first_match(r'<em class="g1[^"]*">(.*?)</em>', block))
        app_period = self._extract_card_value(block, "접수일시")
        detail_url = urljoin(self.source["base_url"], unescape(href))
        return ListingItem(title=title, url=detail_url, status=status, application_period_text=app_period)

    def parse_detail(self, item: ListingItem) -> Event:
        html = self.fetch_html(item.url)
        return self.parse_detail_html(html, item.url, fallback=item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        view_html = first_match(r'<div class="cp31edu1view1">(.*?)(?:<!-- cp31edu1view1 //-->|<div id="tabs1")', html) or html
        tabs_html = first_match(r'<div id="tabs1pane1" class="tabs1pane">(.*?)(?:<div id="tabs1pane2"|</div>\s*</div>\s*<!-- /#body_content)', html) or ""
        if not tabs_html and 'id="tabs1pane1"' in html:
            tabs_html = html.split('id="tabs1pane1"', 1)[1]
        title = strip_tags(first_match(r'<h3 class="h1">(.*?)</h3>', view_html)) or (fallback.title if fallback else "")
        status = strip_tags(first_match(r'<em class="g1[^"]*">(.*?)</em>', view_html)) or (fallback.status if fallback else "")
        info = self._extract_detail_map(view_html)
        body_text = strip_tags(tabs_html)
        app_rng = parse_date_range(info.get("접수일시", ""))
        event_rng = parse_date_range(info.get("교육기간", ""))
        apply_href = first_match(r'<a href="([^"]*amode=agree[^"]*)"[^>]*>', view_html)
        apply_url = urljoin(url, unescape(apply_href)) if apply_href else url
        attachment_urls = []
        for text, link in all_links(tabs_html, url):
            if "download.do" in link and link not in attachment_urls:
                attachment_urls.append(link)
        image_urls = []
        for img in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I):
            if "cmsfile/image.do" in img:
                full = urljoin(url, unescape(img))
                if full not in image_urls:
                    image_urls.append(full)
        target = info.get("교육대상", "")
        category_seed = " ".join([title, info.get("시설구분", ""), info.get("교육과정", ""), body_text])
        category = classify_category(category_seed, self.source.get("category_hint", "교육"))
        audience = classify_audience(title + " " + target + " " + body_text)
        if target and audience == "전체":
            audience = target[:60]
        price_text = " ".join([info.get("수강료", ""), info.get("재료비", ""), body_text])
        summary = summarize_event(title, body_text or self._info_to_body(info))
        return Event(
            source_id=self.source["id"],
            source_name=self.source["name"],
            organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""),
            region_level2=self.source.get("region_level2", ""),
            title=title,
            source_url=url,
            category=category,
            summary=summary,
            body_text=body_text or self._info_to_body(info),
            target_audience=audience,
            event_start_date=event_rng.start,
            event_end_date=event_rng.end,
            application_start_date=app_rng.start,
            application_end_date=app_rng.end,
            location_name=info.get("교육장소", ""),
            price_type=detect_price_type(price_text),
            status=status or "검수필요",
            apply_url=apply_url,
            attachment_urls=attachment_urls,
            image_urls=image_urls,
            tags=[t for t in [category, self.source.get("region_level2", ""), info.get("시설구분", ""), target] if t],
            parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _extract_card_value(block: str, label: str) -> str:
        pattern = r'<span class="t1">\s*' + re.escape(label) + r'\s*:?\s*</span>\s*</b>\s*<span class="dd">(.*?)</span>'
        return re.sub(r"\s+", " ", strip_tags(first_match(pattern, block))).strip()

    @staticmethod
    def _extract_detail_map(view_html: str) -> dict[str, str]:
        pairs: dict[str, str] = {}
        for label, value in re.findall(r'<span class="dt">(.*?)</span>\s*<span class="dd">(.*?)</span>', view_html, re.S | re.I):
            key = re.sub(r"\s+", " ", strip_tags(label)).strip().rstrip(":")
            val = re.sub(r"\s+", " ", strip_tags(value)).strip()
            pairs[key] = val
        return pairs

    @staticmethod
    def _info_to_body(info: dict[str, str]) -> str:
        return "\n".join(f"{k}: {v}" for k, v in info.items() if v)

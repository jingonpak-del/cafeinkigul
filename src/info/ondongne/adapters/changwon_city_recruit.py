from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from ..classify import classify_category, classify_audience, detect_price_type
from ..date_parser import extract_labeled_range, is_within_days
from ..html_utils import first_match, strip_tags, all_links
from ..models import Event
from ..summarizer import summarize_event


class ChangwonCityRecruitAdapter(AdapterBase):
    """Precise parser for 창원특례시 모집신청접수.

    List page: /cwportal/10311/10486.web
    Detail page: /cwportal/10311/10486/10487.web?amode=view&idx={id}
    """

    parser_version = "changwon_city_recruit_v1"
    detail_base_url = "https://www.changwon.go.kr/cwportal/10311/10486/10487.web"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        page = 1
        while len(items) < limit and page <= 20:
            url = self.source["base_url"] if page == 1 else f"{self.source['base_url']}?cpage={page}"
            html = self.fetch_html(url)
            blocks = re.findall(r'<li class="list">(.*?)</li>', html, re.S | re.I)
            if not blocks:
                break
            added_on_page = 0
            for block in blocks:
                href = first_match(r'<a[^>]+href="([^"]+)"', block)
                if "amode=view" not in href or "idx=" not in href:
                    continue
                status = strip_tags(first_match(r'<span class="cate1">(.*?)</span>', block))
                title_html = first_match(r'<strong class="h1">(.*?)</strong>', block)
                title = strip_tags(re.sub(r'<span class="cate1">.*?</span>', '', title_html, flags=re.S | re.I))
                app_period = strip_tags(first_match(r'<div class="n1"><span class="t1">접수 기간</span><span class="t2">(.*?)</span></div>', block))
                department = strip_tags(first_match(r'<div class="n4"><span class="t1">담당 부서</span><span class="t2">(.*?)</span></div>', block))
                app_rng = extract_labeled_range("접수 기간 " + app_period, ["접수 기간"])
                # For recruitments, keep long-running open applications if the application end is not old.
                if app_rng.end and not is_within_days(app_rng.end, since_days):
                    continue
                detail_url = urljoin(self.detail_base_url, unescape(href))
                items.append(ListingItem(title=title, url=detail_url, status=status, application_period_text=app_period, department=department))
                added_on_page += 1
                if len(items) >= limit:
                    break
            if added_on_page == 0 and page > 1:
                break
            page += 1
        return items

    def parse_detail(self, item: ListingItem) -> Event:
        html = self.fetch_html(item.url)
        view_html = first_match(r'<div class="booking1view">(.*?)(?:<script>|<div id="body_foot")', html)
        if not view_html:
            view_html = html
        title_html = first_match(r'<h2 class="h1">(.*?)</h2>', view_html)
        title = strip_tags(re.sub(r'<span class="cate1">.*?</span>', '', title_html, flags=re.S | re.I)) or item.title
        status = strip_tags(first_match(r'<span class="cate1">(.*?)</span>', title_html)) or item.status
        info_text = strip_tags(first_match(r'<ul class="info1">(.*?)</ul>', view_html))
        body_html = first_match(r'<div class="substance">(.*?)</div>', view_html)
        body_text = strip_tags(body_html)
        app_range = extract_labeled_range(info_text, ["접수 기간"])
        event_range = extract_labeled_range(body_text, ["일 시", "일시", "교육기간", "행사기간", "기간"])
        department = self._extract_info_value(info_text, "담당 부서") or item.department
        contact = self._extract_info_value(info_text, "문 의 처")
        location = self._extract_body_label(body_text, ["장 소", "장소"])
        target = self._extract_body_label(body_text, ["대 상", "대상"])
        attachment_urls = [url for text, url in all_links(view_html, item.url) if "download" in url.lower() or "file" in url.lower()]
        apply_href = first_match(r'<a href="([^"]+)" class="button submit">접수</a>', view_html)
        apply_url = urljoin(item.url, unescape(apply_href)) if apply_href else item.url
        category = classify_category(title + " " + body_text, self.source.get("category_hint", "모집공모"))
        audience = classify_audience(title + " " + target + " " + body_text)
        if target and audience == "전체":
            audience = target[:60]
        summary = summarize_event(title, body_text)
        tags = [category, self.source.get("region_level2", ""), department]
        if target:
            tags.append(target)
        return Event(
            source_id=self.source["id"],
            source_name=self.source["name"],
            organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""),
            region_level2=self.source.get("region_level2", ""),
            title=title,
            source_url=item.url,
            category=category,
            summary=summary,
            body_text=body_text,
            target_audience=audience,
            event_start_date=event_range.start,
            event_end_date=event_range.end,
            application_start_date=app_range.start,
            application_end_date=app_range.end,
            location_name=location,
            price_type=detect_price_type(title + " " + body_text),
            status=status or "검수필요",
            apply_url=apply_url,
            attachment_urls=attachment_urls,
            tags=[t for t in tags if t],
            parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _extract_info_value(info_text: str, label: str) -> str:
        text = re.sub(r"\s+", " ", info_text or "")
        m = re.search(re.escape(label) + r"\s+([^\n]+?)(?=접수 기간|모집 인원|신청 현황|담당 부서|문 의 처|$)", text)
        return m.group(1).strip(" -") if m else ""

    @staticmethod
    def _extract_body_label(body_text: str, labels: list[str]) -> str:
        for label in labels:
            # Match public notice labels at line/bullet boundaries, not words like "대상으로".
            pattern = r"(?:^|\n)\s*[■○]?\s*(?:[가-힣]\.\s*)?" + re.escape(label) + r"\s*[:：]?\s*([^\n■]+)"
            m = re.search(pattern, body_text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

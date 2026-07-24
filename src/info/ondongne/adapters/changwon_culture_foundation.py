from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from urllib.parse import quote, urljoin

from .base import AdapterBase, ListingItem
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_category, classify_audience, detect_price_type
from ..date_parser import parse_date_range, extract_labeled_range, is_within_days
from ..html_utils import first_match, strip_tags, all_links
from ..models import Event
from ..summarizer import summarize_event


class ChangwonCultureFoundationAdapter(AdapterBase):
    """Precise parser for 창원문화재단 열린마당 > 공지사항 > 모집 및 행사."""

    parser_version = "changwon_culture_foundation_v1"

    def fetch_html(self, url: str) -> str:
        from urllib.request import Request, urlopen

        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urlopen(req, timeout=20).read()
        return raw.decode("cp949", errors="ignore")

    def _list_url(self) -> str:
        if "notice_list.asp" in self.source.get("base_url", ""):
            return "https://www.cwcf.or.kr/commu/notice_list.asp?BCATE=BD00001&BSUBCATE=%B8%F0%C1%FD%20%B9%D7%20%C7%E0%BB%E7&place_idx="
        return self.source["base_url"]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        page = 1
        base_url = self._list_url()
        include_keywords = self.source.get("include_keywords", [])
        exclude_keywords = self.source.get("exclude_keywords", [])
        while len(items) < limit and page <= 20:
            sep = "&" if "?" in base_url else "?"
            url = base_url if page == 1 else f"{base_url}{sep}page={page}"
            html = self.fetch_html(url)
            added = 0
            seen_urls = {item.url for item in items}
            for row in re.findall(r"<tr>(.*?)</tr>", html, re.S | re.I):
                item = self.parse_list_row(row)
                if not item:
                    continue
                haystack = item.title + " " + item.status
                if exclude_keywords and any(k in haystack for k in exclude_keywords):
                    continue
                if include_keywords and not any(k in haystack for k in include_keywords):
                    continue
                if item.url in seen_urls:
                    continue
                if item.published_at and not is_within_days(item.published_at, since_days):
                    continue
                items.append(item)
                seen_urls.add(item.url)
                added += 1
                if len(items) >= limit:
                    break
            if added == 0:
                break
            if f"page={page + 1}" not in html and f"page={page+1}" not in html:
                break
            page += 1
        return items

    def parse_list_row(self, row: str) -> ListingItem | None:
        if "notice_view.asp" not in row:
            return None
        href = first_match(r'href="([^"]*notice_view\.asp[^"]*)"', row)
        title = strip_tags(first_match(r"<a[^>]*>(.*?)</a>", row))
        if not href or not title:
            return None
        cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
        status = ""
        published_at = None
        if len(cells) >= 2:
            status = cells[1]
        for cell in cells:
            parsed = self._parse_short_date(cell)
            if parsed:
                published_at = parsed
                break
        href = unescape(href)
        href = re.sub(r"BSUBCATE=[^&]*", "BSUBCATE=%B8%F0%C1%FD%20%B9%D7%20%C7%E0%BB%E7", href)
        href = re.sub(r"page=\d+", "page=1", href)
        href = quote(href, safe="/:?=&%")
        return ListingItem(
            title=title,
            url=urljoin("https://www.cwcf.or.kr", href),
            status=status,
            published_at=published_at,
        )

    def parse_detail(self, item: ListingItem) -> Event:
        html = self.fetch_html(item.url)
        return self.parse_detail_html(html, item.url, fallback=item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = strip_tags(first_match(r'<span class="m-board-title">(.*?)</span>', html))
        title = re.sub(r"^\[[^\]]+\]\s*", "", title).strip() or (fallback.title if fallback else "")
        published_at = self._extract_published_at(html) or (fallback.published_at if fallback else None)
        content_html = first_match(r'<div class="Detail-content">(.*?)(?:<div class="m-boardDetail-prev">|<div class="m-boards-btns)', html) or ""
        body_text = strip_tags(content_html)
        if not body_text:
            attachment_names = [strip_tags(t) for t, _ in all_links(html, url) if "download_file.asp" in _]
            body_text = "\n".join([title, *attachment_names]).strip()
        app_rng = extract_labeled_range(body_text, ["모집기간", "접수기간", "신청기간", "접수"])
        event_rng = extract_labeled_range(body_text, ["교육기간", "행사기간", "공연일자", "일시", "기간"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "공연장소"])
        target = self._extract_labeled_value(body_text, ["대상", "교육대상", "모집대상"])
        price_text = self._extract_labeled_value(body_text, ["참가비", "입장료", "수강료", "비용"]) or body_text
        attachment_urls = []
        file_html = first_match(r'<div class="Detail-subHeader[^>]*>(.*?)</div>\s*</div>', html) or first_match(r'<div class="Detail-subHeader[^>]*>(.*?)</div>', html) or html
        for _, link in all_links(file_html, url):
            if "download_file.asp" in link and link not in attachment_urls:
                attachment_urls.append(link)
        image_urls = []
        for img in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', content_html, re.I):
            full = self._abs_url(url, unescape(img))
            if full not in image_urls:
                image_urls.append(full)
        extracted = extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes)
        body_text = append_attachment_text(body_text, extracted)
        app_rng = extract_labeled_range(body_text, ["모집기간", "접수기간", "신청기간", "접수"])
        event_rng = extract_labeled_range(body_text, ["교육기간", "행사기간", "공연일자", "일시", "기간"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "공연장소"])
        target = self._extract_labeled_value(body_text, ["대상", "교육대상", "모집대상"])
        price_text = self._extract_labeled_value(body_text, ["참가비", "입장료", "수강료", "비용"]) or body_text
        category = classify_category(title + " " + body_text, self.source.get("category_hint", "문화"))
        audience = classify_audience(title + " " + target + " " + body_text)
        if any(k in target for k in ["초등", "아동", "청소년", "어린이", "유아", "학생"]):
            audience = "아동/청소년"
        elif target and audience == "전체":
            audience = target[:60]
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
            price_type=detect_price_type(price_text),
            status=(fallback.status if fallback else "모집 및 행사"),
            published_at=published_at,
            apply_url=url,
            attachment_urls=attachment_urls,
            image_urls=image_urls,
            tags=[t for t in [category, self.source.get("region_level2", ""), "창원문화재단"] if t],
            parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _parse_short_date(text: str) -> str | None:
        m = re.search(r"(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
        if m:
            y, mo, d = map(int, m.groups())
            return f"20{y:02d}-{mo:02d}-{d:02d}"
        m = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
        if m:
            y, mo, d = map(int, m.groups())
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return None

    @classmethod
    def _extract_published_at(cls, html: str) -> str | None:
        block = first_match(r"작성일.*?<span class=\"Detail-info-body\">(.*?)</span>", html)
        return cls._parse_short_date(strip_tags(block))

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|\n|\s)" + re.escape(label) + r"\s*[:：]\s*([^\n]+)", text)
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

    @staticmethod
    def _abs_url(base: str, url: str) -> str:
        if url.startswith("//"):
            return "https:" + url
        return urljoin(base, url)

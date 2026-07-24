from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_category, classify_audience, detect_price_type
from ..date_parser import extract_labeled_range, is_within_days
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class ChangwonFacilitiesAdapter(AdapterBase):
    """Precise parser for 창원시설공단 알림마당 공지/행사/프로그램 notices."""

    parser_version = "changwon_facilities_v1"
    board_urls = [
        "https://www.cwsisul.or.kr/bbs/board.php?bo_table=sub06_04_01",  # 알림마당/공지사항
        "https://www.cwsisul.or.kr/bbs/board.php?bo_table=sub06_04_04",  # 채용/강사 모집 등
    ]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        include_keywords = self.source.get("include_keywords", [])
        exclude_keywords = [*self.source.get("exclude_keywords", []), "수질검사", "유충검사", "휴관", "제한", "점검", "공사"]
        for base_url in self.board_urls:
            page = 1
            while len(items) < limit and page <= 5:
                url = base_url if page == 1 else f"{base_url}&page={page}"
                html = self.fetch_html(url)
                added = 0
                for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
                    if "wr_id=" not in row or "bo_tit" not in row:
                        continue
                    href = first_match(r'href=["\']([^"\']*board\.php\?bo_table=[^"\']+wr_id=\d+[^"\']*)["\']', row)
                    title_html = first_match(r'<div class=["\']bo_tit["\'][^>]*>(.*?)</div>', row)
                    title = strip_tags(first_match(r"<a[^>]*>(.*?)</a>", title_html)).strip()
                    category_cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
                    department = strip_tags(category_cells[1]) if len(category_cells) > 1 else ""
                    published_at = self._parse_date(strip_tags(first_match(r'<td[^>]*class=["\'][^"\']*td_datetime[^"\']*["\'][^>]*>(.*?)</td>', row)))
                    haystack = title + " " + department
                    if exclude_keywords and any(k in haystack for k in exclude_keywords):
                        continue
                    if include_keywords and not any(k in haystack for k in include_keywords):
                        continue
                    if published_at and not is_within_days(published_at, since_days):
                        continue
                    full_url = urljoin("https://www.cwsisul.or.kr", unescape(href))
                    if href and title and full_url not in seen:
                        items.append(ListingItem(title=title, url=full_url, status="알림마당", department=department, published_at=published_at))
                        seen.add(full_url)
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
        category = strip_tags(first_match(r'<span class=["\']bo_v_cate["\'][^>]*>(.*?)</span>', html)) or (fallback.department if fallback else "")
        published_at = self._parse_date(first_match(r'<strong class=["\']if_date["\'][^>]*>(.*?)</strong>', html)) or (fallback.published_at if fallback else None)
        body_html = first_match(r'<div id=["\']bo_v_con["\'][^>]*>(.*?)(?:</div>\s*<!-- } 본문 내용 끝|</div>\s*\r?\n\s*<!-- } 본문 내용 끝|</section>)', html)
        body_text = strip_tags(body_html)
        attachment_names = [strip_tags(name) for name in re.findall(r'<a[^>]+class=["\']view_file_download["\'][^>]*>\s*<strong>(.*?)</strong>', html, re.S | re.I)]
        if not body_text or len(body_text) < 20:
            extra = "\n".join(attachment_names)
            body_text = "\n".join(x for x in [title, category, extra] if x)
        app_rng = extract_labeled_range(body_text, ["모집기간", "접수기간", "신청기간", "접수"])
        event_rng = extract_labeled_range(body_text, ["행사기간", "교육기간", "운영기간", "일시", "기간"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소"])
        target = self._extract_labeled_value(body_text, ["대상", "교육대상", "모집대상", "참여대상"])
        attachment_urls = []
        for _, link in all_links(html, url):
            if "download.php" in link and link not in attachment_urls:
                attachment_urls.append(link)
        image_urls = []
        for img in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I):
            full = urljoin(url, unescape(img))
            if full not in image_urls:
                image_urls.append(full)
        extracted = extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes)
        body_text = append_attachment_text(body_text, extracted)
        app_rng = extract_labeled_range(body_text, ["모집기간", "접수기간", "신청기간", "접수"])
        event_rng = extract_labeled_range(body_text, ["행사기간", "교육기간", "운영기간", "일시", "기간"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소"])
        target = self._extract_labeled_value(body_text, ["대상", "교육대상", "모집대상", "참여대상"])
        event_category = classify_category(title + " " + body_text, self.source.get("category_hint", "복지건강"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=event_category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(title + " " + body_text), location_name=location,
            application_start_date=app_rng.start, application_end_date=app_rng.end,
            event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=category or (fallback.status if fallback else "알림마당"),
            published_at=published_at, apply_url=url, attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [event_category, self.source.get("region_level2", ""), category] if t], parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _parse_date(text: str) -> str | None:
        m = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", text or "")
        if not m:
            return None
        y, mo, d = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|\n|\s)" + re.escape(label) + r"\s*[:：]\s*([^\n]+)", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

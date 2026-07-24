from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class CwwfSeniorBoardAdapter(AdapterBase):
    """Shared parser for 창원복지재단 산하 노인종합복지관 basicList boards."""

    parser_version = "cwwf_senior_board_v1"
    base = ""
    board_url = ""
    org_label = ""
    default_location = ""
    tags_extra: list[str] = []

    include_keywords = [
        "모집", "신청", "참여", "상담", "교육", "강좌", "프로그램", "교실", "특강",
        "건강", "디지털", "문화", "행사", "수강", "운영 일정", "의료상담",
    ]
    negative_keywords = [
        "채용", "합격", "서류", "면접", "공고문", "입찰", "계약", "공사", "휴관", "점검",
        "후원금", "후원현황", "회의결과", "운영위원회", "사칭", "이용자수칙", "식단",
        "결산", "추경", "강사 모집", "실습생 합격", "최종 합격", "보도자료", "언론보도",
    ]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, 5):
            if len(items) >= limit:
                break
            url = f"{self.board_url}&page={page}"
            try:
                html = self.fetch_html(url)
            except Exception:
                break
            added = 0
            for item in self.parse_list_html(html):
                if item.url in seen or not self._is_relevant(item.title):
                    continue
                if item.published_at and not is_within_days(item.published_at, since_days):
                    continue
                items.append(item)
                seen.add(item.url)
                added += 1
                if len(items) >= limit:
                    break
            if added == 0 and page > 1:
                break
        return items

    def parse_list_html(self, html: str) -> list[ListingItem]:
        items: list[ListingItem] = []
        block = first_match(r'<div[^>]+class=["\']basicList["\'][^>]*>(.*?)</div>\s*(?:<div class="page|</form>)', html)
        if not block:
            block = html or ""
        for li in re.findall(r"<li(?:\s[^>]*)?>(.*?)</li>", block, re.S | re.I):
            href = first_match(r'<a[^>]+href=["\']([^"\']*board_01\.php[^"\']*mode=view[^"\']*)["\']', li)
            title = strip_tags(first_match(r'<span[^>]+class=["\']title["\'][^>]*>(.*?)</span>', li))
            if not href or not title or title == "제목":
                continue
            date_text = strip_tags(first_match(r'<span[^>]+class=["\']date["\'][^>]*>(.*?)</span>', li))
            item_url = urljoin(self.board_url, unescape(href)).replace("&amp;", "&")
            item_url = item_url.replace("||", "%7C%7C")
            items.append(ListingItem(title=re.sub(r"\s+", " ", title).strip(), url=item_url, status="공지사항", published_at=self._parse_date(date_text)))
        return items

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = strip_tags(first_match(r'<div[^>]+class=["\']viewTop["\'][^>]*>\s*<h4[^>]*>(.*?)</h4>', html)) or (fallback.title if fallback else "")
        title = re.sub(r"\s+", " ", title).strip()
        top_text = strip_tags(first_match(r'<div[^>]+class=["\']viewTop["\'][^>]*>(.*?)</div>', html))
        published_at = parse_first_date(top_text) or (fallback.published_at if fallback else None)
        body_html = first_match(r'<div[^>]+class=["\']v_contents["\'][^>]*>(.*?)</div>\s*(?:<div class="v_bottom|<div class="boardButton)', html)
        body_text = strip_tags(body_html) or title
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        image_titles = [strip_tags(x) for x in re.findall(r'<img[^>]+(?:alt|title)=["\']([^"\']*)["\']', body_html or "", re.I) if x]
        if len(body_text) < 30:
            fallback_parts = [title, *[x for x in image_titles if x and not x.lower().endswith((".png", ".jpg", ".jpeg"))]]
            body_text = "\n".join(dict.fromkeys(fallback_parts)).strip()
        attachment_urls = [link for text, link in all_links(html, url) if any(k in link.lower() for k in ["bbsdown", "download", "file", "down.php"])]
        body_text = append_attachment_text(body_text, extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes))
        app_rng = self._extract_line_range(body_text, ["신청기간", "접수기간", "모집기간", "접수", "신청"])
        event_rng = self._extract_line_range(body_text, ["일시", "운영일정", "운영 일정", "교육기간", "행사기간", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "참여대상", "모집대상", "신청대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "상담장소", "강의장소"])
        text = title + " " + body_text
        category = classify_category(text, self.source.get("category_hint", "복지건강"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text), location_name=location or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=published_at,
            apply_url=url, attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [category, "창원시", "노인복지", self.org_label, *self.tags_extra] if t], parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

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
            m = re.search(r"(?:^|[\n\r\s])" + re.escape(label) + r"(?![가-힣A-Za-z0-9])\s*[:：-]?\s*([^\n\r]{2,90})", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

    @staticmethod
    def _extract_line_range(text: str, labels: list[str]) -> DateRange:
        for label in labels:
            m = re.search(re.escape(label) + r"\s*[:：-]?\s*([^\n\r]{0,160})", text or "")
            if m:
                rng = parse_date_range(m.group(0))
                if rng.start:
                    return rng
        return extract_labeled_range(text, labels) or DateRange()

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .base import AdapterBase, ListingItem
from ..classify import classify_category, classify_audience, detect_price_type
from ..date_parser import extract_labeled_range, is_within_days
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class GyeongnamChangwonLibraryAdapter(AdapterBase):
    """Precise parser for 경상남도교육청 창원도서관 행사공지 + 평생학습 프로그램 신청."""

    parser_version = "gyeongnam_changwon_library_v1"
    board_list_url = "https://cwlib.gne.go.kr/board.es?mid=a20610000000&bid=A2_NEW3"
    program_list_url = "https://cwlib.gne.go.kr/usr_gne/lec_list.es?mid=a20810000000&cate_no=79"

    def fetch_html(self, url: str, timeout: int = 20, referer: str | None = None) -> str:
        headers = {"User-Agent": "Mozilla/5.0 OndongneBot/0.2"}
        if referer:
            headers["Referer"] = referer
        req = Request(url, headers=headers)
        raw = urlopen(req, timeout=timeout).read()
        return raw.decode("utf-8", errors="ignore")

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for item in self._list_program_items(since_days=since_days, limit=limit):
            if item.url not in seen:
                items.append(item)
                seen.add(item.url)
            if len(items) >= limit:
                return items
        for item in self._list_board_items(since_days=since_days, limit=limit - len(items)):
            if item.url not in seen:
                items.append(item)
                seen.add(item.url)
            if len(items) >= limit:
                break
        return items

    def _list_program_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        html = self.fetch_html(self.program_list_url)
        items: list[ListingItem] = []
        # One row per course. The list page already exposes the important dates and status.
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
            if "lec_v.es" not in row:
                continue
            href = first_match(r'href=["\']([^"\']*lec_v\.es[^"\']+)["\']', row)
            title = strip_tags(first_match(r"<span[^>]*font-size:\s*15px[^>]*>(.*?)</span>", row))
            if not title:
                title = strip_tags(first_match(r"<a[^>]*>(.*?)</a>", row))
                title = re.split(r"ㆍ|\n", title)[0].strip()
            title = re.sub(r"^\s+|\s+$", "", title)
            if not href or not title:
                continue
            row_text = strip_tags(row)
            app_text = self._extract_inline_field(row_text, "모집기간")
            event_text = self._extract_inline_field(row_text, "학습기간")
            freshness_range = extract_labeled_range(row_text, ["모집기간", "학습기간"])
            if not is_within_days(freshness_range.end or freshness_range.start, since_days):
                continue
            cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
            audience = cells[1] if len(cells) > 1 else ""
            status = self._extract_img_alt(row) or (cells[-1] if cells else "")
            items.append(
                ListingItem(
                    title=title,
                    url=urljoin("https://cwlib.gne.go.kr", unescape(href)),
                    status=status,
                    application_period_text=app_text or event_text,
                    department=audience,
                )
            )
            if len(items) >= limit:
                break
        return items

    def _list_board_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        page = 1
        include_keywords = self.source.get("include_keywords", [])
        exclude_keywords = self.source.get("exclude_keywords", [])
        while len(items) < limit and page <= 10:
            sep = "&" if "?" in self.board_list_url else "?"
            url = self.board_list_url if page == 1 else f"{self.board_list_url}{sep}nPage={page}"
            html = self.fetch_html(url)
            added = 0
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
                if "list_no=" not in row or "act=view" not in row:
                    continue
                href = first_match(r'href=["\']([^"\']*board\.es[^"\']*act=view[^"\']*)["\']', row)
                title = strip_tags(first_match(r"<td[^>]*class=[\"']subject[^\"']*[\"'][^>]*>(.*?)</td>", row))
                title = re.sub(r"\s*new\s*", " ", title, flags=re.I).strip()
                if not title:
                    title = strip_tags(first_match(r"<a[^>]*>(.*?)</a>", row)).strip()
                cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
                published_at = None
                for cell in cells:
                    published_at = self._parse_date(cell)
                    if published_at:
                        break
                haystack = title + " " + strip_tags(row)
                if exclude_keywords and any(k in haystack for k in exclude_keywords):
                    continue
                if include_keywords and not any(k in haystack for k in include_keywords):
                    continue
                if published_at and not is_within_days(published_at, since_days):
                    continue
                if href and title:
                    items.append(
                        ListingItem(
                            title=title,
                            url=urljoin("https://cwlib.gne.go.kr", unescape(href)),
                            status="행사공지",
                            published_at=published_at,
                        )
                    )
                    added += 1
                    if len(items) >= limit:
                        break
            if added == 0:
                break
            page += 1
        return items

    def parse_detail(self, item: ListingItem) -> Event:
        if "/usr_gne/lec_v.es" in item.url:
            html = self.fetch_html(item.url, referer=self.program_list_url)
            return self.parse_program_detail_html(html, item.url, item)
        html = self.fetch_html(item.url, referer=self.board_list_url)
        return self.parse_board_detail_html(html, item.url, item)

    def parse_program_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        fields = self._table_fields(html)
        title = fields.get("강좌명", "") or (fallback.title if fallback else "")
        body_text = strip_tags(first_match(r"<table[^>]*class=[\"']tstyle_view[\"'][^>]*>(.*?)(?:<form|<h4|</table>\s*<script>)", html))
        if not body_text:
            body_text = "\n".join(f"{k}: {v}" for k, v in fields.items())
        app_rng = extract_labeled_range(body_text, ["모집기간", "접수기간", "신청기간"])
        event_rng = extract_labeled_range(body_text, ["교육기간", "학습기간", "운영기간"])
        target = fields.get("교육대상", "") or (fallback.department if fallback else "")
        status = fields.get("진행상태", "") or (fallback.status if fallback else "")
        location = fields.get("강의실", "") or fields.get("강의장소", "") or fields.get("장소", "")
        # cwlib's program detail endpoint rejects normal browser clicks unless the
        # request carries the program-list Referer header.  The crawler can fetch
        # the detail URL with that header and keeps it as source_url for stable
        # dedupe, but user-facing digests should use the accessible list page as
        # apply_url instead of a detail URL that shows "비정상적인 접근입니다."
        # when opened directly.
        user_facing_url = self.program_list_url if "/usr_gne/lec_v.es" in url else url
        category = classify_category(title + " " + body_text, self.source.get("category_hint", "도서문화"))
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
            target_audience=classify_audience(title + " " + target + " " + body_text) if not target else target,
            location_name=location,
            application_start_date=app_rng.start,
            application_end_date=app_rng.end,
            event_start_date=event_rng.start,
            event_end_date=event_rng.end,
            price_type=detect_price_type(body_text),
            status=status,
            apply_url=user_facing_url,
            tags=[t for t in [category, self.source.get("region_level2", ""), "창원도서관", "평생학습"] if t],
            parser_version=self.parser_version,
        ).finalize()

    def parse_board_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = strip_tags(first_match(r'<p[^>]*class=["\']title["\'][^>]*>(.*?)</p>', html)) or (fallback.title if fallback else "")
        content_html = first_match(r'<td[^>]*class=["\']tb_contents["\'][^>]*>(.*?)</td>', html)
        body_text = strip_tags(content_html) or title
        fields = self._table_fields(html)
        published_at = self._parse_date(fields.get("작성일시", "")) or (fallback.published_at if fallback else None)
        app_rng = extract_labeled_range(body_text, ["모집기간", "접수기간", "신청기간", "접수"])
        event_rng = extract_labeled_range(body_text, ["교육기간", "행사기간", "학습기간", "일시", "기간"])
        attachment_urls = []
        for _, link in all_links(html, url):
            if "download.es" in link and link not in attachment_urls:
                attachment_urls.append(link)
        image_urls = []
        for img in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', content_html, re.I):
            full = urljoin(url, unescape(img))
            if full not in image_urls:
                image_urls.append(full)
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소"])
        target = self._extract_labeled_value(body_text, ["대상", "교육대상", "모집대상"])
        category = classify_category(title + " " + body_text, self.source.get("category_hint", "도서문화"))
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
            target_audience=classify_audience(title + " " + target + " " + body_text) if not target else target,
            location_name=location,
            application_start_date=app_rng.start,
            application_end_date=app_rng.end,
            event_start_date=event_rng.start,
            event_end_date=event_rng.end,
            price_type=detect_price_type(body_text),
            status=(fallback.status if fallback else "행사공지"),
            published_at=published_at,
            apply_url=url,
            attachment_urls=attachment_urls,
            image_urls=image_urls,
            tags=[t for t in [category, self.source.get("region_level2", ""), "창원도서관", "행사공지"] if t],
            parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _extract_inline_field(text: str, label: str) -> str:
        m = re.search(re.escape(label) + r"\s*[:：]\s*([^ㆍ\n]+(?:\n?\s*\d{4}[-./]\d{1,2}[-./]\d{1,2}[^ㆍ\n]*)?)", text or "")
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    @staticmethod
    def _extract_img_alt(html: str) -> str:
        alts = [strip_tags(a) for a in re.findall(r'<img[^>]+alt=["\']([^"\']+)["\']', html or "", re.I)]
        for alt in alts:
            if alt and alt not in {"온라인접수", "방문접수", "전화접수"}:
                return alt
        return ""

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

    @staticmethod
    def _table_fields(html: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I):
            cells = re.findall(r"<(?:th|td)[^>]*>(.*?)</(?:th|td)>", row, re.S | re.I)
            clean = [strip_tags(c).strip(" *\u00a0\n\t") for c in cells]
            clean = [re.sub(r"\s+", " ", c).strip() for c in clean]
            for i in range(0, len(clean) - 1, 2):
                label = clean[i].strip("* ")
                value = clean[i + 1].strip()
                if label and value and len(label) <= 20:
                    fields[label] = value
        return fields

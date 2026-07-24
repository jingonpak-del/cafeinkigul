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


class ChangwonWelfareFoundationAdapter(AdapterBase):
    """Precise parser for 창원복지재단 public welfare notices and city-promotion programs."""

    parser_version = "changwon_welfare_foundation_v1"
    base = "https://www.cwwf.or.kr"
    board_urls = [
        ("사업소식", "https://www.cwwf.or.kr/talk/sub_01_01.php", "cw_notice"),
        ("시정홍보", "https://www.cwwf.or.kr/talk/sub_09_01.php", "talk09"),
    ]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        include_keywords = self.source.get("include_keywords", [])
        exclude_keywords = [
            *self.source.get("exclude_keywords", []),
            "채용", "합격자", "서류전형", "면접", "임용", "수의계약", "견적서", "입찰", "공사", "계약", "사칭", "주의",
        ]
        for board_name, list_url, code in self.board_urls:
            page = 1
            while len(items) < limit and page <= 5:
                url = f"{list_url}?code={code}&page={page}"
                html = self.fetch_html(url)
                added = 0
                for block in re.findall(r"<li>\s*<a\s+href=[\"']([^\"']*bbsData=[^\"']*mode=view[^\"']*)[\"'][^>]*>(.*?)</a>\s*</li>", html, re.S | re.I):
                    href, inner = block
                    title = strip_tags(first_match(r'<span[^>]*class=["\']title["\'][^>]*>(.*?)</span>', inner))
                    published_at = self._parse_short_date(strip_tags(first_match(r'<span[^>]*class=["\']date["\'][^>]*>(.*?)</span>', inner)))
                    number = strip_tags(first_match(r'<span[^>]*class=["\'][^"\']*(?:notice|num)[^"\']*["\'][^>]*>(.*?)</span>', inner))
                    haystack = title + " " + board_name
                    if exclude_keywords and any(k in haystack for k in exclude_keywords):
                        continue
                    if include_keywords and not any(k in haystack for k in include_keywords):
                        continue
                    if published_at and not is_within_days(published_at, since_days):
                        continue
                    full_url = urljoin(self.base, unescape(href).replace("&amp;", "&"))
                    if title and full_url not in seen:
                        items.append(ListingItem(title=title, url=full_url, status=board_name, department=number, published_at=published_at))
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
        title = strip_tags(first_match(r'<div[^>]*class=["\']viewTop["\'][^>]*>.*?<h4[^>]*>(.*?)</h4>', html)) or (fallback.title if fallback else "")
        published_at = self._parse_full_date(first_match(r'<span[^>]*class=["\']date["\'][^>]*>(.*?)</span>', html)) or (fallback.published_at if fallback else None)
        body_html = first_match(r'<div[^>]*class=["\']v_contents["\'][^>]*>(.*?)</div>\s*(?:<div class=["\']v_bottom|<div class=["\']boardButton)', html)
        body_text = strip_tags(body_html)
        attachment_names = [strip_tags(name) for name in re.findall(r'class=["\']attem["\'][^>]*>.*?<a[^>]*>(.*?)</a>', html, re.S | re.I)]
        if not body_text or len(body_text) < 20:
            image_alts = [strip_tags(a) for a in re.findall(r'<img[^>]+alt=["\']([^"\']+)["\']', body_html or "", re.I)]
            body_text = "\n".join(x for x in [title, *image_alts, *attachment_names] if x)
        else:
            body_text = "\n".join(x for x in [body_text, *attachment_names] if x)
        app_rng = extract_labeled_range(body_text, ["신청기간", "접수기간", "모집기간", "신청"])
        event_rng = extract_labeled_range(body_text, ["일시", "일 시", "교육기간", "행사기간", "운영기간", "기간"])
        location = self._extract_labeled_value(body_text, ["장소", "장 소", "교육장소", "행사장소"])
        target = self._extract_labeled_value(body_text, ["대상", "참여대상", "모집대상", "교육대상"])
        attachment_urls = []
        image_urls = []
        apply_url = url
        for text, link in all_links(html, url):
            if "bbs_download.php" in link or "/bbsDown/" in link:
                if link not in attachment_urls:
                    attachment_urls.append(link)
            elif any(host in link for host in ["form.naver.com", "forms.gle", "docs.google.com/forms"]):
                apply_url = link
        for img in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I):
            full = urljoin(url, unescape(img))
            if full not in image_urls:
                image_urls.append(full)
        extracted = extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes)
        body_text = append_attachment_text(body_text, extracted)
        app_rng = extract_labeled_range(body_text, ["신청기간", "접수기간", "모집기간", "신청"])
        event_rng = extract_labeled_range(body_text, ["일시", "일 시", "교육기간", "행사기간", "운영기간", "기간"])
        location = self._extract_labeled_value(body_text, ["장소", "장 소", "교육장소", "행사장소"])
        target = self._extract_labeled_value(body_text, ["대상", "참여대상", "모집대상", "교육대상"])
        category = classify_category(title + " " + body_text, self.source.get("category_hint", "복지건강"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(title + " " + body_text), location_name=location,
            application_start_date=app_rng.start, application_end_date=app_rng.end,
            event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "복지소식"), published_at=published_at,
            apply_url=apply_url, attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [category, self.source.get("region_level2", ""), (fallback.status if fallback else "")] if t],
            parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _parse_short_date(text: str) -> str | None:
        m = re.search(r"(\d{2})[./-](\d{1,2})[./-](\d{1,2})", text or "")
        if not m:
            return None
        y, mo, d = map(int, m.groups())
        return f"20{y:02d}-{mo:02d}-{d:02d}"

    @staticmethod
    def _parse_full_date(text: str) -> str | None:
        m = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", text or "")
        if not m:
            return None
        y, mo, d = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|\n|\s|[·∙-])" + re.escape(label) + r"\s*[:：]\s*([^\n]+)", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

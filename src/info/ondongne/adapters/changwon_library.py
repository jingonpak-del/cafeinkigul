from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_category, classify_audience, detect_price_type
from ..date_parser import extract_labeled_range, is_within_days, parse_date_range
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class ChangwonLibraryAdapter(AdapterBase):
    """Precise parser for 창원시립도서관 multi-branch notices and online classes."""

    parser_version = "changwon_library_v2_multibranch_attachments"
    base = "https://lib.changwon.go.kr"
    # 창원시립도서관 권역별/분관 코드. cl is the umbrella site and has no class page.
    branches = {
        "uc": "창원중앙도서관",
        "mg": "명곡도서관",
        "db": "동부도서관",
        "hp": "마산합포도서관",
        "hw": "마산회원도서관",
        "jh": "진해도서관",
        "jr": "중리초등도서관",
        "bm": "최윤덕도서관",
        "gh": "고향의봄도서관",
    }

    def class_url_for(self, code: str) -> str:
        return f"{self.base}/{code}/culture/applyclass.html?lib_code={code}"

    def notice_url_for(self, code: str) -> str:
        return f"{self.base}/board/bbs/board.php?bo_table=notice&ic={code}&sca={code}"

    @property
    def class_url(self) -> str:
        return self.class_url_for("uc")

    @property
    def notice_url(self) -> str:
        return self.notice_url_for("uc")

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        branch_codes = self.source.get("branch_codes") or list(self.branches)
        per_branch_limit = max(5, limit)
        for code in branch_codes:
            for item in self._list_class_items_for_branch(code, since_days, per_branch_limit):
                if item.url not in seen:
                    items.append(item)
                    seen.add(item.url)
                if len(items) >= limit:
                    return items
            for item in self._list_notice_items_for_branch(code, since_days, per_branch_limit):
                if item.url not in seen:
                    items.append(item)
                    seen.add(item.url)
                if len(items) >= limit:
                    return items
        return items

    def _list_class_items(self, since_days: int, limit: int) -> list[ListingItem]:
        return self._list_class_items_for_branch("uc", since_days, limit)

    def _list_class_items_for_branch(self, code: str, since_days: int, limit: int) -> list[ListingItem]:
        class_url = self.class_url_for(code)
        try:
            html = self.fetch_html(class_url)
        except Exception:
            return []
        items: list[ListingItem] = []
        branch_name = self.branches.get(code, code)
        for m in re.finditer(r'<tr[^>]+id=["\']detail_(\d+)["\'][^>]*>(.*?)</tr>\s*</table>\s*</td>\s*</tr>', html, re.S | re.I):
            detail_no, block = m.group(1), m.group(2)
            fields = self._table_fields(block)
            desc = fields.get("강좌설명", "")
            title = self._class_title_from_description(desc) or f"{branch_name} 문화강좌 {detail_no}"
            event_period = fields.get("강좌기간", "") or fields.get("강의기간", "")
            rng = parse_date_range(event_period)
            if not is_within_days(rng.end or rng.start, since_days):
                continue
            target = fields.get("모집대상", "")
            status = "온라인수강신청"
            url = f"{class_url}#detail_{detail_no}"
            items.append(ListingItem(title=f"[{branch_name}] {title}", url=url, status=status, application_period_text=event_period, department=target))
            if len(items) >= limit:
                break
        return items

    def _list_notice_items(self, since_days: int, limit: int) -> list[ListingItem]:
        return self._list_notice_items_for_branch("uc", since_days, limit)

    def _list_notice_items_for_branch(self, code: str, since_days: int, limit: int) -> list[ListingItem]:
        items: list[ListingItem] = []
        branch_name = self.branches.get(code, code)
        include_keywords = self.source.get("include_keywords", [])
        exclude_keywords = [*self.source.get("exclude_keywords", []), "휴실", "장서점검", "대출", "반납", "추천도서", "개관시간", "자료실 휴실"]
        page = 1
        seen: set[str] = set()
        while len(items) < limit and page <= 3:
            base_url = self.notice_url_for(code)
            url = base_url if page == 1 else f"{base_url}&page={page}"
            try:
                html = self.fetch_html(url)
            except Exception:
                break
            added = 0
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
                if "wr_id=" not in row:
                    continue
                href = first_match(r'href=["\']([^"\']*board\.php\?bo_table=notice[^"\']*wr_id=\d+[^"\']*)["\']', row)
                title = strip_tags(first_match(r'<td[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>(.*?)</td>', row))
                published_at = self._parse_date(strip_tags(first_match(r'<td[^>]*data-name=["\']작성일["\'][^>]*>(.*?)</td>', row)))
                haystack = title + " " + strip_tags(row)
                if exclude_keywords and any(k in haystack for k in exclude_keywords):
                    continue
                if include_keywords and not any(k in haystack for k in include_keywords):
                    continue
                if published_at and not is_within_days(published_at, since_days):
                    continue
                full_url = urljoin(self.base, unescape(href))
                if href and title and full_url not in seen:
                    items.append(ListingItem(title=f"[{branch_name}] {title}", url=full_url, status="공지사항", published_at=published_at))
                    seen.add(full_url)
                    added += 1
                    if len(items) >= limit:
                        break
            if added == 0:
                break
            page += 1
        return items

    def parse_detail(self, item: ListingItem) -> Event:
        if "applyclass.html" in item.url:
            code = first_match(r"lib_code=([A-Za-z0-9]+)", item.url) or "uc"
            class_url = self.class_url_for(code)
            html = self.fetch_html(class_url)
            detail_no = first_match(r"#detail_(\d+)", item.url)
            block = first_match(r'<tr[^>]+id=["\']detail_' + re.escape(detail_no) + r'["\'][^>]*>(.*?)</tr>\s*</table>\s*</td>\s*</tr>', html)
            return self.parse_class_detail_html(block, item.url, item)
        html = self.fetch_html(item.url)
        return self.parse_notice_detail_html(html, item.url, item)

    def parse_class_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        fields = self._table_fields(html)
        code = first_match(r"lib_code=([A-Za-z0-9]+)", url) or "uc"
        branch_name = self.branches.get(code, "창원중앙도서관")
        desc = fields.get("강좌설명", "")
        title = self._class_title_from_description(desc) or self._strip_branch_prefix(fallback.title if fallback else "")
        body_text = "\n".join(f"{k}: {v}" for k, v in fields.items() if v)
        app_rng = extract_labeled_range(body_text, ["모집기간", "접수기간", "신청기간"])
        event_rng = parse_date_range(fields.get("강좌기간", "") or fields.get("강의기간", ""))
        target = fields.get("모집대상", "") or (fallback.department if fallback else "")
        location = fields.get("강의실", "") or self._extract_labeled_value(desc, ["장소"])
        category = classify_category(title + " " + body_text, self.source.get("category_hint", "도서문화"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(title + " " + body_text), location_name=location,
            application_start_date=app_rng.start, application_end_date=app_rng.end,
            event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "온라인수강신청"), apply_url=url.split("#", 1)[0],
            tags=[t for t in [category, self.source.get("region_level2", ""), branch_name, "문화강좌"] if t],
            parser_version=self.parser_version,
        ).finalize()

    def parse_notice_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = strip_tags(first_match(r'<span[^>]*class=["\']bo_v_tit["\'][^>]*>(.*?)</span>', html)) or (fallback.title if fallback else "")
        title = self._strip_branch_prefix(re.sub(r"\s+", " ", title).strip())
        body_html = first_match(r'<div[^>]*id=["\']bo_v_con["\'][^>]*>(.*?)</div>\s*(?:<!-- } 본문 내용 끝|<!--)', html)
        if not body_html:
            body_html = first_match(r'<div[^>]*id=["\']bo_v_con["\'][^>]*>(.*?)</div>', html)
        body_text = strip_tags(body_html)
        if not body_text or len(body_text) < 20:
            image_alts = [strip_tags(a) for a in re.findall(r'<img[^>]+alt=["\']([^"\']+)["\']', body_html or "", re.I)]
            body_text = "\n".join(x for x in [title, *image_alts] if x)
        published_at = self._parse_date(first_match(r"작성일\s*</strong>\s*([^<]+)", html)) or (fallback.published_at if fallback else None)
        attachment_urls = []
        image_urls = []
        for _, link in all_links(html, url):
            if "/data/file/" in link or "download" in link:
                if link not in attachment_urls:
                    attachment_urls.append(link)
        for img in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I):
            full = urljoin(url, unescape(img))
            if full not in image_urls:
                image_urls.append(full)
        extracted = extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes)
        body_text = append_attachment_text(body_text, extracted)
        app_rng = extract_labeled_range(body_text, ["모집기간", "접수기간", "신청기간", "운영기간"])
        event_rng = extract_labeled_range(body_text, ["행사기간", "운영기간", "일시", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "참여대상"])
        location = self._extract_labeled_value(body_text, ["장소", "행사장소"])
        code = first_match(r"[?&]ic=([A-Za-z0-9]+)", url) or first_match(r"[?&]sca=([A-Za-z0-9]+)", url) or "uc"
        branch_name = self.branches.get(code, "창원중앙도서관")
        category = classify_category(title + " " + body_text, self.source.get("category_hint", "도서문화"))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(title + " " + body_text), location_name=location,
            application_start_date=app_rng.start, application_end_date=app_rng.end,
            event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=published_at, apply_url=url,
            attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [category, self.source.get("region_level2", ""), branch_name, "공지사항"] if t],
            parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _table_fields(html: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I):
            cells = re.findall(r"<(?:th|td)[^>]*>(.*?)</(?:th|td)>", row, re.S | re.I)
            clean = [strip_tags(c).strip(" *\u00a0\n\t") for c in cells]
            clean = [re.sub(r"\s+", " ", c).strip() for c in clean]
            if len(clean) >= 2:
                label = re.sub(r"\s+", "", clean[0]).strip()
                value = clean[1].strip()
                if label and value and len(label) <= 20:
                    fields[label] = value
        for label, value in re.findall(r'data-name=["\']([^"\']+)["\'][^>]*>(.*?)</td>', html or "", re.S | re.I):
            label = re.sub(r"\s+", "", strip_tags(label)).strip()
            value = re.sub(r"\s+", " ", strip_tags(value)).strip()
            if label and value and label not in fields:
                fields[label] = value
        return fields

    @staticmethod
    def _class_title_from_description(text: str) -> str:
        text = strip_tags(text or "")
        text = re.sub(r"\s+", " ", text).strip()
        content = re.search(r"(?:내용|강좌내용)\s*[:：]\s*([^∙\n-]+(?:\s+[^∙\n-]+)?)", text)
        if content:
            return re.sub(r"\s+", " ", content.group(1)).strip(" -")[:80]
        first_line = re.split(r"\n|∙|※|준비물\s*:", text)[0]
        first_line = re.sub(r"^[-\s]*(대상|일시|장소)\s*[:：]\s*[^-]+-\s*", "", first_line).strip()
        if not first_line or first_line.startswith(("대상", "일시", "장소")):
            target = re.search(r"대상\s*[:：]\s*([^∙\n-]+)", text)
            return ((target.group(1).strip() + " 대상 도서관 문화강좌") if target else "").strip()[:80]
        return first_line.strip(" -")[:80]

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
            m = re.search(r"(?:^|\n|\s|[·∙-])" + re.escape(label) + r"\s*[:：]\s*([^\n]+)", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

    @staticmethod
    def _strip_branch_prefix(title: str) -> str:
        return re.sub(r"^\[[^\]]+\]\s*", "", title or "").strip()

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin, urlencode

from .base import AdapterBase, ListingItem
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class RegionalSimpleBoardAdapter(AdapterBase):
    """Small source-specific base for 2026-06-30 regional Changwon-area public boards."""

    parser_version = "regional_simple_board_v1"
    list_url = ""
    base_url = ""
    default_location = "창원시/경남"
    default_category = "공익활동"
    tags_extra: list[str] = []
    include_keywords = ["모집", "신청", "접수", "교육", "지원", "사업", "프로그램", "행사", "공고", "공모", "입주", "보증", "자금"]
    negative_keywords = ["채용", "합격", "입찰", "계약", "용역", "공사", "보도자료", "결과", "선정결과", "회의", "휴관", "점검"]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        html = self.fetch_html(self.list_url)
        items = []
        seen = set()
        for item in self.parse_list_html(html):
            if item.url in seen or not self._is_relevant(item.title):
                continue
            if item.published_at and not is_within_days(item.published_at, since_days):
                continue
            items.append(item)
            seen.add(item.url)
            if len(items) >= limit:
                break
        return items

    def parse_list_html(self, html: str) -> list[ListingItem]:
        raise NotImplementedError

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = self._clean_title(strip_tags(first_match(r'<span[^>]+class=["\'][^"\']*bo_v_tit[^"\']*["\'][^>]*>(.*?)</span>', html)))
        if not title:
            title = self._clean_title(strip_tags(first_match(r'<[^>]+class=["\'][^"\']*(?:title|subject|bo_v_tit)[^"\']*["\'][^>]*>(.*?)</[^>]+>', html)))
        if not title:
            title = self._clean_title(strip_tags(first_match(r'<h[1234][^>]*>(.*?)</h[1234]>', html)))
        if (not title or len(title) < 4 or "게시판" in title or title in {"알림마당", "공지사항"}) and fallback:
            title = fallback.title
        body_html = first_match(r'<div[^>]+class=["\'][^"\']*(?:board_view|view|content|cont|contents|bo_v_con)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\'][^"\']*(?:btn|reply|comment)|</section>|</article>)', html)
        if not body_html:
            body_html = first_match(r'<div[^>]+id=["\']bo_v_con["\'][^>]*>(.*?)</div>\s*(?:<script|<section|</article)', html)
        if not body_html:
            body_html = first_match(r'<body[^>]*>(.*?)</body>', html)
        body_text = re.sub(r"\s+", " ", strip_tags(body_html) or title).strip()[:7000]
        published_at = parse_first_date(body_text) or (fallback.published_at if fallback else None)
        return self._make_event(title, body_text, url, published_at, html, fallback)

    def _make_event(self, title: str, body_text: str, url: str, published_at: str | None, html: str, fallback: ListingItem | None = None) -> Event:
        app_rng = self._extract_range(body_text, ["접수기간", "신청기간", "모집기간", "공고기간", "지원기간", "접수", "신청", "모집"])
        event_rng = self._extract_range(body_text, ["교육기간", "사업기간", "운영기간", "행사기간", "일시", "일정", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "지원대상", "신청대상", "모집대상", "참여대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소", "소재지", "위치"])
        text = f"{title} {body_text}"
        category = classify_category(text, self.source.get("category_hint", self.default_category))
        attachment_urls = [link for _, link in all_links(html, url) if any(k in link.lower() for k in ["download", "file", "attach"])]
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", "경상남도"), region_level2=self.source.get("region_level2", "창원시"),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text), location_name=location or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=published_at,
            apply_url=url, attachment_urls=attachment_urls[:5], tags=[t for t in [category, "창원시", "경남", *self.tags_extra] if t],
            parser_version=self.parser_version,
        ).finalize()

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\b\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}\b", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:180].rstrip() + ("…" if len(text) > 180 else "")

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|[\n\r\s▶□○\-])" + re.escape(label) + r"(?![가-힣A-Za-z0-9])\s*[:：-]?\s*([^\n\r]{2,100})", text or "")
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

    @staticmethod
    def _extract_range(text: str, labels: list[str]) -> DateRange:
        for label in labels:
            m = re.search(re.escape(label) + r"\s*[:：-]?\s*([^\n\r]{0,180})", text or "")
            if m:
                rng = parse_date_range(m.group(0))
                if rng.start:
                    return rng
        return extract_labeled_range(text, labels) or DateRange()


class GndamoaRecruitAdapter(RegionalSimpleBoardAdapter):
    parser_version = "gndamoa_recruit_v1"
    list_url = "https://www.gndamoa.or.kr/01328/01330.web"
    base_url = "https://www.gndamoa.or.kr"
    default_location = "경상남도인재평생교육진흥원/경남 일원"
    default_category = "교육"
    tags_extra = ["평생교육", "모집접수"]
    negative_keywords = [*RegionalSimpleBoardAdapter.negative_keywords, "보도", "자료"]

    def parse_list_html(self, html: str) -> list[ListingItem]:
        out = []
        for href, inner in re.findall(r'<a[^>]+href=["\']([^"\']*(?:amode=view[^"\']*idx=\d+|idx=\d+[^"\']*amode=view)[^"\']*)["\'][^>]*>(.*?)</a>', html or "", re.S | re.I):
            title = self._clean_title(strip_tags(inner))
            around = html[max(0, html.find(href) - 300):html.find(href) + 700]
            out.append(ListingItem(title=title, url=urljoin(self.base_url, unescape(href)), status="모집접수", published_at=parse_first_date(around)))
        return self._dedupe(out)

    @staticmethod
    def _dedupe(items: list[ListingItem]) -> list[ListingItem]:
        seen, out = set(), []
        for item in items:
            if item.url not in seen:
                out.append(item); seen.add(item.url)
        return out


class GndamoaNoticeAdapter(GndamoaRecruitAdapter):
    parser_version = "gndamoa_notice_v1"
    list_url = "https://www.gndamoa.or.kr/01328/01329.web"
    default_category = "교육"
    tags_extra = ["평생교육", "공지공고"]
    negative_keywords = [*RegionalSimpleBoardAdapter.negative_keywords, "나라장터", "용역사", "입찰"]


class GntpNoticeAdapter(RegionalSimpleBoardAdapter):
    parser_version = "gntp_notice_v1"
    list_url = "https://www.gntp.or.kr/board/list"
    base_url = "https://www.gntp.or.kr"
    default_location = "경남테크노파크"
    default_category = "취업창업"
    tags_extra = ["경남테크노파크", "기업지원"]
    include_keywords = ["모집", "지원", "사업", "공고", "입주", "교육", "참가", "수혜기업", "기업지원"]
    negative_keywords = [*RegionalSimpleBoardAdapter.negative_keywords, "채용", "입찰"]

    def parse_list_html(self, html: str) -> list[ListingItem]:
        out = []
        for path, inner in re.findall(r'onclick=["\']goPage\([^\)]*?["\'](/board/detail/[^"\']+/\d+)["\'][^\)]*\)["\'][^>]*>(.*?)</a>', html or "", re.S | re.I):
            title = self._clean_title(strip_tags(inner))
            pos = html.find(path)
            around = html[max(0, pos - 500):pos + 800]
            out.append(ListingItem(title=title, url=urljoin(self.base_url, path), status="공지사항", published_at=parse_first_date(around)))
        return GndamoaRecruitAdapter._dedupe(out)


class GnsinboSupportAdapter(RegionalSimpleBoardAdapter):
    parser_version = "gnsinbo_support_v1"
    list_url = "https://gcgf.gnsinbo.or.kr/bbs/board.php?bo_table=02_01"
    base_url = "https://gcgf.gnsinbo.or.kr"
    default_location = "경남신용보증재단"
    default_category = "취업창업"
    tags_extra = ["소상공인", "보증지원", "정책자금"]
    include_keywords = ["지원가능", "자금", "보증", "지원", "창업", "소상공인", "기업"]
    negative_keywords = ["지원종료", "종료", "채용", "입찰", "계약"]

    def parse_list_html(self, html: str) -> list[ListingItem]:
        out = []
        chunks = re.split(r'<li[^>]+class=["\'][^"\']*gall_li[^"\']*["\'][^>]*>', html or "", flags=re.I)[1:]
        rows = [chunk.split('<li class="gall_li')[0] for chunk in chunks]
        rows += re.findall(r'<tr[^>]*>(.*?)</tr>', html or "", re.S | re.I)
        for row in rows:
            m = re.search(r'<a[^>]+href=["\']([^"\']*bo_table=02_01[^"\']*wr_id=\d+[^"\']*)["\'][^>]*>(.*?)</a>', row, re.S | re.I)
            if not m:
                continue
            href, inner = m.groups()
            status = strip_tags(first_match(r'<span[^>]+class=["\'][^"\']*bo_state[^"\']*["\'][^>]*>(.*?)</span>', row))
            title_part = strip_tags(first_match(r'<div[^>]+class=["\'][^"\']*bo_tit[^"\']*["\'][^>]*>(.*?)</div>', row))
            info = strip_tags(first_match(r'<div[^>]+class=["\'][^"\']*gall_info[^"\']*["\'][^>]*>(.*?)</div>', row))
            title = self._clean_title(" ".join(x for x in [status, title_part, info] if x)) or self._clean_title(strip_tags(inner))
            out.append(ListingItem(title=title, url=urljoin(self.base_url, unescape(href).replace("&amp;", "&")), status="지원사업", published_at=parse_first_date(row)))
        return GndamoaRecruitAdapter._dedupe(out)
    def parse_detail(self, item: ListingItem) -> Event:
        # Product detail pages include dynamic site chrome; listing cards contain the stable support summary.
        return self._make_event(item.title, item.title, item.url, item.published_at, "", item)


class GndcNoticeAdapter(RegionalSimpleBoardAdapter):
    parser_version = "gndc_notice_v1"
    list_url = "https://www.gndc.co.kr/boardlist.do?seqId=0000000047"
    base_url = "https://www.gndc.co.kr"
    default_location = "경남개발공사"
    default_category = "공익활동"
    tags_extra = ["경남개발공사", "공지"]
    include_keywords = ["공고", "신청", "모집", "지원", "분양", "임대", "입주", "주거"]
    negative_keywords = [*RegionalSimpleBoardAdapter.negative_keywords, "채용", "입찰"]
    bbs_id = "33914CF6F52E4DAC821501F91CA8AC89"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        from urllib.request import Request, urlopen

        api = "https://www.gndc.co.kr/getBbsArticleList.do?" + urlencode({"BBS_ID": self.bbs_id, "PAGE_UNIT": str(limit), "PAGE_INDEX": "1"})
        try:
            with urlopen(Request(api, headers={"User-Agent": "Mozilla/5.0 OndongneBot/0.2", "X-Requested-With": "XMLHttpRequest"}), timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
        except Exception:
            # The GNDc board API occasionally returns transient 404/HTML errors; do not break the full daily run.
            return []
        out = []
        for obj in data.get("articallist", []):
            title = self._clean_title(obj.get("CPDS_SUBJECT") or "")
            if not title or not self._is_relevant(title):
                continue
            published = parse_first_date(obj.get("CPDS_WDATE") or "")
            if published and not is_within_days(published, since_days):
                continue
            url = f"https://www.gndc.co.kr/boardview.do?seqId=0000000047&BBS_ID={self.bbs_id}&IPDS_IDX={obj.get('IPDS_IDX')}"
            out.append(ListingItem(title=title, url=url, status="공지사항", published_at=published))
        return out[:limit]

    def parse_list_html(self, html: str) -> list[ListingItem]:
        return []

    def parse_detail(self, item: ListingItem) -> Event:
        # API list already carries lossy server text on this EUC-KR/JSON endpoint; use clickable detail URL for audit.
        return self._make_event(item.title, item.title, item.url, item.published_at, "", item)

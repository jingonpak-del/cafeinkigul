from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from .base import AdapterBase, ListingItem
from .generic_gnuboard import GenericGnuboardAdapter
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class StableGnuboardAdapter(GenericGnuboardAdapter):
    """Gnuboard variant that preserves non-root board prefixes such as /gnuboard4."""

    def _canonical_url(self, url: str) -> str:
        m_board = re.search(r"bo_table=([^&]+)", url)
        m_id = re.search(r"wr_id=(\d+)", url)
        if m_board and m_id:
            parts = urlsplit(self.board_url)
            path = parts.path if parts.path.endswith("/board.php") else "/bbs/board.php"
            return urlunsplit((parts.scheme, parts.netloc, path, urlencode({"bo_table": m_board.group(1), "wr_id": m_id.group(1)}), ""))
        return url


class ChangwonIndustryPromotionAdapter(GenericGnuboardAdapter):
    """창원산업진흥원 공지사항 Gnuboard."""

    parser_version = "changwon_industry_promotion_v1"
    board_url = "https://cwip.or.kr/bbs/board.php?bo_table=b0501"
    allowed_boards = ["b0501"]
    default_location = "창원산업진흥원"
    default_category = "취업창업"
    tags_extra = ["산업", "기업지원", "창업"]
    include_keywords = ["모집", "신청", "지원사업", "교육", "컨설팅", "멘토링", "설명회", "창업", "기업", "투자", "일경험", "참여"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "합격", "입찰", "용역", "수의계약", "결과", "선정 결과"]


class BonglimYouthTrainingCenterAdapter(StableGnuboardAdapter):
    """창원시봉림청소년수련관 청소년 모집 게시판."""

    parser_version = "bonglim_youth_training_center_v1"
    board_url = "http://www.cbyc.or.kr/gnuboard4/bbs/board.php?bo_table=board3"
    allowed_boards = ["board3"]
    default_location = "창원시봉림청소년수련관"
    default_category = "아동청소년"
    tags_extra = ["청소년", "봉림", "수련관"]
    include_keywords = ["모집", "신청", "청소년", "프로그램", "교육", "캠프", "체험", "축제", "동아리", "참여", "리더십"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "합격", "보도자료", "언론", "결과", "마감"]


class EncodedSimpleBoardAdapter(AdapterBase):
    """Legacy public board using bbsData=...&mode=view links."""

    parser_version = "encoded_simple_board_v1"
    board_url = ""
    max_pages = 2
    default_location = "창원시"
    default_category = "기타"
    tags_extra: list[str] = []
    include_keywords = ["모집", "신청", "교육", "프로그램", "참여", "행사", "수강", "상담", "무료진료", "강습", "특강", "축제"]
    negative_keywords = ["채용", "합격", "면접", "직원", "입찰", "계약", "공사", "점검", "휴관", "휴무", "보도자료", "결과", "선정", "식단", "인사", "안내사항"]

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            url = self._page_url(page)
            try:
                html = self.fetch_html(url)
            except Exception:
                break
            added = 0
            for item in self.parse_list_html(html, url):
                if item.url in seen or not self._is_relevant(item.title):
                    continue
                if item.published_at and not is_within_days(item.published_at, since_days):
                    continue
                items.append(item)
                seen.add(item.url)
                added += 1
                if len(items) >= limit:
                    break
            if len(items) >= limit or (page > 1 and added == 0):
                break
        return items

    def _page_url(self, page: int) -> str:
        sep = "&" if "?" in self.board_url else "?"
        return self.board_url if page == 1 else f"{self.board_url}{sep}page={page}"

    def parse_list_html(self, html: str, base_url: str | None = None) -> list[ListingItem]:
        base_url = base_url or self.board_url
        items: list[ListingItem] = []
        href_re = r'<a[^>]+href=["\']((?=[^"\']*(?:bbsData=|o_seq=))(?=[^"\']*(?:o_)?mode=view)[^"\']+)["\'][^>]*>(.*?)</a>'
        for href, inner in re.findall(href_re, html or "", re.S | re.I):
            raw_text = strip_tags(inner)
            title = self._clean_title(raw_text)
            if not title or title in {"공지사항", "목록"}:
                continue
            block = self._surrounding_row(html, href)
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', block or raw_text)
            full = urljoin(base_url, unescape(href).replace("&amp;", "&"))
            items.append(ListingItem(title=title, url=self._canonical_url(full), status="공지사항", published_at=parse_first_date(date_text) or GenericGnuboardAdapter._parse_date(date_text)))
        deduped: list[ListingItem] = []
        seen: set[str] = set()
        for item in items:
            if item.url not in seen:
                deduped.append(item)
                seen.add(item.url)
        return deduped

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = ""
        for pat in [
            r'<h[123][^>]*>(.*?)</h[123]>',
            r'<[^>]+class=["\'][^"\']*(?:view_title|bbs_head_top|subject|title)[^"\']*["\'][^>]*>(.*?)</[^>]+>',
        ]:
            title = strip_tags(first_match(pat, html))
            if title:
                break
        if not title and fallback:
            title = fallback.title
        title = self._clean_title(title)
        if fallback and (not title or title in {"창원시 농촌 활성화 지원센터", "창원외국인근로자지원센터", "진해노인종합복지관", "공지사항", "메인메뉴"}):
            title = self._clean_title(fallback.title)
        published_at = parse_first_date(strip_tags(first_match(r'(?:등록일|작성일|날짜|DATE)[^<]{0,80}(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', html)) or "") or (fallback.published_at if fallback else None)
        body_html = ""
        for pat in [
            r'<div[^>]+class=["\'][^"\']*(?:bbs_content|board_view_con|view_content|content|substance)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div|<table|</section|</article)',
            r'<td[^>]+class=["\'][^"\']*(?:content|view_cont|board_content)[^"\']*["\'][^>]*>(.*?)</td>',
            r'<body[^>]*>(.*?)</body>',
        ]:
            body_html = first_match(pat, html)
            if body_html:
                break
        body_text = strip_tags(body_html) or title
        body_text = re.sub(r"PHPSESSID=[A-Za-z0-9]+", "PHPSESSID=", body_text)
        body_text = re.sub(r"조회\s*[:：]?\s*[\d,]+", "조회", body_text)
        body_text = re.sub(r"조회수\s*[\d,]+", "조회수", body_text)
        if len(body_text) > 8000:
            idx = body_text.find(title)
            if idx >= 0:
                body_text = body_text[idx: idx + 5000]
            else:
                body_text = body_text[:5000]
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        image_alts = [strip_tags(x) for x in re.findall(r'<img[^>]+(?:alt|title)=["\']([^"\']*)["\']', body_html or "", re.I) if x]
        if len(body_text) < 40 and image_alts:
            body_text = "\n".join([body_text, *image_alts]).strip()
        attachment_urls = [link for _, link in all_links(html, url) if any(k in link.lower() for k in ["download", "file", "bbsdown", "down"])][:5]
        body_text = append_attachment_text(body_text or title, extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes))
        app_rng = self._extract_range(body_text, ["신청기간", "접수기간", "모집기간", "접수", "신청"])
        event_rng = self._extract_range(body_text, ["교육기간", "운영기간", "행사기간", "활동기간", "강습기간", "일시", "일정", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "참여대상", "신청대상", "지원대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소", "운영장소", "강습장소"])
        text = f"{title} {body_text}"
        category = classify_category(text, self.source.get("category_hint", self.default_category))
        return Event(
            source_id=self.source["id"], source_name=self.source["name"], organization_name=self.source["organization_name"],
            region_level1=self.source.get("region_level1", ""), region_level2=self.source.get("region_level2", ""),
            title=title, source_url=url, category=category, summary=summarize_event(title, body_text), body_text=body_text,
            target_audience=target or classify_audience(text), location_name=location or self.default_location,
            application_start_date=app_rng.start, application_end_date=app_rng.end, event_start_date=event_rng.start, event_end_date=event_rng.end,
            price_type=detect_price_type(body_text), status=(fallback.status if fallback else "공지사항"), published_at=published_at,
            apply_url=url, attachment_urls=attachment_urls, image_urls=image_urls,
            tags=[t for t in [category, "창원시", *self.tags_extra] if t], parser_version=self.parser_version,
        ).finalize()

    def _canonical_url(self, url: str) -> str:
        parts = urlsplit(url)
        qs = parse_qs(parts.query, keep_blank_values=True)
        bbs = (qs.get("bbsData") or [""])[0]
        code = (qs.get("code") or [""])[0]
        page = (qs.get("page") or ["1"])[0]
        clean_qs = {"code": code, "page": page, "bbsData": bbs, "mode": "view"}
        if qs.get("id"):
            clean_qs = {"id": qs["id"][0], **clean_qs}
        if qs.get("o_seq"):
            clean_qs.pop("bbsData", None)
            clean_qs["o_mode"] = clean_qs.pop("mode")
            clean_qs["o_seq"] = qs["o_seq"][0]
            if qs.get("o_list_no"):
                clean_qs["o_list_no"] = qs["o_list_no"][0]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(clean_qs), ""))

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\b\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}\b", " ", text)
        text = re.sub(r"조회\s*[:：]?\s*[\d,]+", " ", text)
        text = re.sub(r"^\d+\s+", "", text)
        text = re.sub(r"\s+[\d,]{1,6}$", "", text)
        text = re.sub(r"^(공지|알림)\s*", "", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _surrounding_row(html: str, href: str) -> str:
        idx = (html or "").find(href)
        if idx < 0:
            return ""
        start = max((html or "").rfind("<tr", 0, idx), (html or "").rfind("<li", 0, idx), 0)
        end_candidates = [p for p in [(html or "").find("</tr>", idx), (html or "").find("</li>", idx)] if p >= 0]
        end = min(end_candidates) + 5 if end_candidates else idx + 500
        return html[start:end]

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            m = re.search(r"(?:^|[\n\r\s▶□○-])" + re.escape(label) + r"(?![가-힣A-Za-z0-9])\s*[:：-]?\s*([^\n\r]{2,100})", text or "")
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


class JinhaeSeniorWelfareCenterAdapter(EncodedSimpleBoardAdapter):
    """진해노인종합복지관 공지사항."""

    parser_version = "jinhae_senior_welfare_center_v1"
    board_url = "http://jhsw.or.kr/sub.html?id=jhsw&code=20180228_145712_38084"
    default_location = "진해노인종합복지관"
    default_category = "복지건강"
    tags_extra = ["진해", "노인복지", "평생교육"]
    include_keywords = ["모집", "수강생", "참여자", "교육", "프로그램", "강습", "노년사회화", "특강", "바리스타", "상담"]
    negative_keywords = [*EncodedSimpleBoardAdapter.negative_keywords, "채용", "합격", "서류", "면접", "생활지원사", "실습 최종", "휴관", "강사 모집"]


class ChangwonRuralCommunityCenterAdapter(EncodedSimpleBoardAdapter):
    """창원시농촌활성화지원센터 공지/수강신청 게시판."""

    parser_version = "changwon_rural_community_center_v1"
    board_url = "http://www.xn--980bq01a7a978bo3dw8feuiy4k9b.org/sub07/sub01_01.php?code=030101"
    default_location = "창원시농촌활성화지원센터"
    default_category = "교육"
    tags_extra = ["농촌", "마을공동체", "교육"]
    include_keywords = ["모집", "수강생", "교육", "공동체", "문화예술", "체험", "투어", "페스티벌", "마을만들기", "참여"]
    negative_keywords = [*EncodedSimpleBoardAdapter.negative_keywords, "결과", "선정", "합격", "취소", "정정"]


class ChangwonMigrantWorkerCenterAdapter(EncodedSimpleBoardAdapter):
    """창원외국인근로자지원센터 공지사항."""

    parser_version = "changwon_migrant_worker_center_v1"
    board_url = "https://www.mfwc.or.kr/2023/sub05/sub05_01.php?code=notice"
    default_location = "창원외국인근로자지원센터"
    default_category = "복지건강"
    tags_extra = ["외국인근로자", "이주민", "상담"]
    include_keywords = ["모집", "교육", "한국어", "상담", "무료진료", "인권리더", "자격증", "문화행사", "지원", "안내"]
    negative_keywords = [*EncodedSimpleBoardAdapter.negative_keywords, "채용", "합격", "입찰", "계약", "유투브", "운영 시간 변경", "윤리강령"]

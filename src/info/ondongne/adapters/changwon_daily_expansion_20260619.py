from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlencode, urljoin

from .base import AdapterBase, ListingItem
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class PublicEducationBoardAdapter(AdapterBase):
    """Reusable source-specific base for non-Gnuboard lifelong-learning boards."""

    parser_version = "public_education_board_v1"
    list_url = ""
    default_location = "창원시"
    default_category = "교육"
    tags_extra: list[str] = []
    max_pages = 2
    include_keywords = ["모집", "신청", "수강", "교육", "강좌", "프로그램", "특강", "학습", "공모", "접수", "강사", "아카데미"]
    negative_keywords = [
        "채용", "합격", "입찰", "계약", "공사", "휴관", "휴무", "점검", "주차", "폐강", "환불", "영수증", "일시 중단", "홈페이지",
        "자료집", "회의", "보도자료", "선정결과", "결과", "개인정보", "정전", "규정", "5부제",
    ]

    def _page_url(self, page: int) -> str:
        sep = "&" if "?" in self.list_url else "?"
        return self.list_url if page == 1 else f"{self.list_url}{sep}page={page}"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            html = self.fetch_html(self._page_url(page))
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
            if len(items) >= limit or (page > 1 and added == 0):
                break
        return items

    def parse_list_html(self, html: str) -> list[ListingItem]:
        raise NotImplementedError

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = ""
        for pat in [
            r'<h[123][^>]*class=["\'][^"\']*(?:tit|title|subject)[^"\']*["\'][^>]*>(.*?)</h[123]>',
            r'<[^>]+class=["\'][^"\']*(?:view_title|board_title|bbs_tit|title|subject)[^"\']*["\'][^>]*>(.*?)</[^>]+>',
            r'<h[123][^>]*>(.*?)</h[123]>',
            r'<title[^>]*>(.*?)</title>',
        ]:
            title = self._clean_title(strip_tags(first_match(pat, html)))
            if title:
                break
        if fallback and (not title or len(title) < 4 or any(x in title for x in ["내용보기", "게시물 내용보기", "공지사항", "마산대학교", "창원대학교"])):
            title = fallback.title
        meta_text = strip_tags(first_match(r'(?:작성일|등록일|작성일자|등록일자)[^<]{0,120}(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', html))
        published_at = parse_first_date(meta_text) or (fallback.published_at if fallback else None)
        body_html = ""
        for pat in [
            r'<div[^>]+class=["\'][^"\']*BD_table[^"\']*["\'][^>]*>\s*<table[^>]*>(.*?)</table>',
            r'<div[^>]+class=["\'][^"\']*board-view-cont[^"\']*["\'][^>]*>(.*?)</div>\s*<div[^>]+class=["\'][^"\']*board-bottom',
            r'<div[^>]+class=["\'][^"\']*(?:board_view_cont|view_cont|view_con|bbs_view|bbs_content|content|contents|nttCn|fr-view)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\'][^"\']*(?:btn|file|reply|comment)|<ul[^>]+class=["\'][^"\']*(?:file)|</article|</section)',
            r'<td[^>]+class=["\'][^"\']*(?:content|view_cont|board_content)[^"\']*["\'][^>]*>(.*?)</td>',
            r'<body[^>]*>(.*?)</body>',
        ]:
            body_html = first_match(pat, html)
            if body_html:
                break
        body_text = strip_tags(body_html) or title
        if len(body_text) > 7000:
            idx = body_text.find(title)
            body_text = body_text[idx: idx + 5000] if idx >= 0 else body_text[:5000]
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        alts = [strip_tags(a) for a in re.findall(r'<img[^>]+(?:alt|title)=["\']([^"\']*)["\']', body_html or "", re.I) if a]
        if len(body_text) < 40 and alts:
            body_text = "\n".join([body_text, *alts]).strip()
        attachment_urls = [link for _, link in all_links(html, url) if any(k in link.lower() for k in ["download", "file", "atch", "attach", "down"])][:5]
        body_text = append_attachment_text(body_text or title, extract_many_attachment_texts(attachment_urls, max_files=2, fetcher=self.fetch_bytes))
        app_rng = self._extract_range(body_text, ["신청기간", "접수기간", "모집기간", "등록기간", "추가접수", "접수", "신청"])
        event_rng = self._extract_range(body_text, ["교육기간", "운영기간", "강의기간", "강좌기간", "행사기간", "일시", "일정", "기간"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "수강대상", "교육대상", "참여대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "강의장소", "운영장소", "접수장소"])
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

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\b\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}\b", " ", text)
        text = re.sub(r"^(공지|알림|전체)\s*[-:：>]*\s*", "", text)
        text = re.sub(r"조회수?\s*[:：]?\s*[\d,]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

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


class ChangwonLifelongLearningNoticeAdapter(PublicEducationBoardAdapter):
    parser_version = "changwon_lifelong_learning_notice_v1"
    list_url = "https://www.changwon.go.kr/lll/portal/bbs/list.do?mId=0601000000&ptIdx=112"
    default_location = "창원시 평생학습관"
    tags_extra = ["평생학습", "창원시"]
    negative_keywords = [*PublicEducationBoardAdapter.negative_keywords, "강사 모집", "강사 모"]

    def parse_list_html(self, html: str) -> list[ListingItem]:
        items = []
        for block in re.findall(r'<tr[^>]*>(.*?)</tr>', html or "", re.S | re.I):
            m = re.search(r"goTo\.view\('list','(\d+)','(\d+)','(\d+)'\)", block)
            if not m:
                continue
            bidx, ptidx, mid = m.groups()
            title = self._clean_title(strip_tags(first_match(r'<a[^>]+onclick=["\'][^"\']*goTo\.view[^"\']*["\'][^>]*>(.*?)</a>', block) or block))
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', block)
            url = f"https://www.changwon.go.kr/lll/portal/bbs/view.do?{urlencode({'mId': mid, 'ptIdx': ptidx, 'bIdx': bidx})}"
            if title:
                items.append(ListingItem(title=title, url=url, status="공지사항", published_at=parse_first_date(date_text)))
        if not items:
            for bidx, ptidx, mid in re.findall(r"goTo\.view\('list','(\d+)','(\d+)','(\d+)'\)", html or ""):
                start = max(0, html.find(bidx) - 500); end = html.find(bidx) + 500
                block = html[start:end]
                title = self._clean_title(strip_tags(block))
                url = f"https://www.changwon.go.kr/lll/portal/bbs/view.do?{urlencode({'mId': mid, 'ptIdx': ptidx, 'bIdx': bidx})}"
                items.append(ListingItem(title=title, url=url, status="공지사항"))
        return items


class ChangwonLifelongLearningOrgNewsAdapter(ChangwonLifelongLearningNoticeAdapter):
    parser_version = "changwon_lifelong_learning_org_news_v1"
    list_url = "https://www.changwon.go.kr/lll/portal/bbs/list.do?mId=0603000000&ptIdx=114"
    default_location = "창원시 평생학습 기관"
    tags_extra = ["평생학습", "기관소식"]


class ChangwonUniversityLifelongAdapter(PublicEducationBoardAdapter):
    parser_version = "changwon_univ_lifelong_v1"
    list_url = "https://www.changwon.ac.kr/lifelong/na/ntt/selectNttList.do?mi=4774&bbsId=1787"
    default_location = "국립창원대학교 평생교육원"
    tags_extra = ["평생교육원", "국립창원대학교"]
    negative_keywords = [*PublicEducationBoardAdapter.negative_keywords, "주차불가", "납입영수증"]

    def parse_list_html(self, html: str) -> list[ListingItem]:
        items = []
        for block in re.findall(r'<tr[^>]*>(.*?)</tr>', html or "", re.S | re.I):
            m = re.search(r'data-id=["\'](\d+)["\']', block)
            if not m:
                continue
            ntt = m.group(1)
            title = self._clean_title(strip_tags(first_match(r'<a[^>]+data-id=["\']\d+["\'][^>]*>(.*?)</a>', block) or block))
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', block)
            url = f"https://www.changwon.ac.kr/lifelong/na/ntt/selectNttInfo.do?mi=4774&nttSn={ntt}"
            if title:
                items.append(ListingItem(title=title, url=url, status="공지사항", published_at=parse_first_date(date_text)))
        return items


class MasanUniversityLifelongAdapter(PublicEducationBoardAdapter):
    parser_version = "masan_univ_lifelong_v1"
    list_url = "https://lifelong.masan.ac.kr/board/000001"
    default_location = "마산대학교 평생교육원"
    tags_extra = ["평생교육원", "마산대학교"]
    negative_keywords = [*PublicEducationBoardAdapter.negative_keywords, "휴관 안내"]

    def parse_list_html(self, html: str) -> list[ListingItem]:
        items = []
        for href, inner in re.findall(r'<a[^>]+href=["\'](/boardview/000001/\d+)["\'][^>]*>(.*?)</a>', html or "", re.S | re.I):
            text = self._clean_title(strip_tags(inner))
            if not text or text == "바로가기":
                continue
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', inner)
            items.append(ListingItem(title=text, url=urljoin(self.list_url, href), status="공지사항", published_at=parse_first_date(date_text)))
        deduped, seen = [], set()
        for item in items:
            if item.url not in seen:
                deduped.append(item); seen.add(item.url)
        return deduped


class MasanUniversityOpenCourseAdapter(MasanUniversityLifelongAdapter):
    parser_version = "masan_univ_open_course_v1"
    list_url = "https://lifelong.masan.ac.kr/main"
    default_location = "마산대학교 평생교육원"
    tags_extra = ["강좌개설", "평생교육", "마산대학교"]
    include_keywords = ["강좌 개설", "개설 제안", "신규강좌", "공모", "제안", "강사", "모집", "평생교육과정"]
    negative_keywords = [*PublicEducationBoardAdapter.negative_keywords, "휴관", "갤러리"]

    def parse_list_html(self, html: str) -> list[ListingItem]:
        items = []
        for href, inner in re.findall(r'<a[^>]+href=["\'](/lectopen/view/[^"\']+)["\'][^>]*>(.*?)</a>', html or "", re.S | re.I):
            text = self._clean_title(strip_tags(inner))
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', inner)
            if text:
                items.append(ListingItem(title=text, url=urljoin(self.list_url, href), status="강좌개설", published_at=parse_first_date(date_text)))
        return items

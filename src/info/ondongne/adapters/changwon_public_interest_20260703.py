from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from .base import AdapterBase, ListingItem
from .generic_gnuboard import GenericGnuboardAdapter
from ..attachment_extractor import append_attachment_text, extract_many_attachment_texts
from ..classify import classify_audience, classify_category, detect_price_type
from ..date_parser import DateRange, extract_labeled_range, is_within_days, parse_date_range, parse_first_date
from ..html_utils import all_links, first_match, strip_tags
from ..models import Event
from ..summarizer import summarize_event


class EncodedPublicBoardAdapter(AdapterBase):
    """Source-specific base for bbsData/mode=view PHP boards in local public institutions."""

    parser_version = "encoded_public_board_v1"
    list_url = ""
    default_location = "창원시"
    default_category = "공익활동"
    tags_extra: list[str] = []
    max_pages = 2
    include_keywords = [
        "모집", "신청", "참여", "교육", "프로그램", "행사", "이벤트", "상담", "검진", "특강",
        "강좌", "수강", "운동", "캠페인", "공모", "대회", "포인트", "워크숍", "지원",
    ]
    negative_keywords = [
        "채용", "합격", "면접", "서류", "직원", "입찰", "계약", "공사", "휴관", "휴무", "점검",
        "보도자료", "언론보도", "결과", "당첨자 발표", "당첨안내", "정기총회", "회장선거",
        "사칭", "기부행위", "구입 공고", "기증 안내",
    ]

    def _page_url(self, page: int) -> str:
        if page == 1:
            return self.list_url
        sep = "&" if "?" in self.list_url else "?"
        return f"{self.list_url}{sep}page={page}"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ListingItem]:
        items: list[ListingItem] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            try:
                html = self.fetch_html(self._page_url(page))
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
            if len(items) >= limit or (page > 1 and added == 0):
                break
        return items

    def parse_list_html(self, html: str) -> list[ListingItem]:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I)
        if not rows:
            rows = re.findall(r"<li[^>]*>(.*?)</li>", html or "", re.S | re.I)
        items: list[ListingItem] = []
        for row in rows:
            m = re.search(r'<a[^>]+href=["\']([^"\']*(?:bbsData=[^"\']+mode=view|mode=view[^"\']*bbsData=)[^"\']*)["\'][^>]*>(.*?)</a>', row, re.S | re.I)
            if not m:
                continue
            href, inner = m.groups()
            title = self._clean_title(strip_tags(inner))
            if not title or title in {"이전글", "다음글", "목록"}:
                continue
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', row)
            url = self._canonical_url(urljoin(self.list_url, unescape(href).replace("&amp;", "&")))
            items.append(ListingItem(title=title, url=url, status="공지사항", published_at=parse_first_date(date_text) or GenericGnuboardAdapter._parse_date(date_text)))
        return self._dedupe(items)

    def parse_detail(self, item: ListingItem) -> Event:
        return self.parse_detail_html(self.fetch_html(item.url), item.url, item)

    def parse_detail_html(self, html: str, url: str, fallback: ListingItem | None = None) -> Event:
        title = ""
        for pat in [
            r'<h[123][^>]+class=["\'][^"\']*(?:title|tit|view_tit|np_18px_span)[^"\']*["\'][^>]*>(.*?)</h[123]>',
            r'<div[^>]+class=["\'][^"\']*(?:title|view_tit|bbs_title)[^"\']*["\'][^>]*>(.*?)</div>',
            r'<th[^>]*>\s*제목\s*</th>\s*<td[^>]*>(.*?)</td>',
            r'<title[^>]*>(.*?)</title>',
        ]:
            title = self._clean_title(strip_tags(first_match(pat, html)))
            if title:
                break
        if fallback and (
            not title
            or len(title) < 6
            or title in {"공지사항", "이벤트", "진해정신건강복지센터", "창원시체육회", "창원박물관"}
            or "공지사항" in title
        ):
            title = fallback.title
        published_at = parse_first_date(strip_tags(first_match(r'(?:작성일|등록일|날짜|기간)[^<]{0,80}(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', html)) or "") or (fallback.published_at if fallback else None)
        body_html = ""
        for pat in [
            r'<div[^>]+class=["\'][^"\']*(?:editor_view|board_view_con|bbs_content|bbs_view|view_cont|view_content|board_cont|content-view|read_body|document_content|xe_content)[^"\']*["\'][^>]*>(.*?)</div>\s*(?:<div[^>]+class=["\'][^"\']*(?:board_view_file|board_view_link|bbs_buttons|btn|reply|comment|boardBtn|read_footer)|</article|<ul[^>]+class=["\'](?:prev|next))',
            r'<td[^>]+class=["\'][^"\']*(?:content|view)[^"\']*["\'][^>]*>(.*?)</td>',
            r'<div[^>]+id=["\'](?:bbs_view|bo_v_con|view_content)["\'][^>]*>(.*?)</div>',
            r'<body[^>]*>(.*?)</body>',
        ]:
            body_html = first_match(pat, html)
            if body_html:
                break
        body_html = re.sub(r'<script\b.*?</script>|<style\b.*?</style>', ' ', body_html or '', flags=re.S | re.I)
        body_text = strip_tags(body_html) or title
        body_text = re.sub(r"조회수\s*[:：]?\s*[\d,]+", "조회수", body_text)
        body_text = re.sub(r"Download\s*:\s*[\d,]+", "Download", body_text, flags=re.I)
        body_text = re.sub(r"\[File Size:[^\]]+\]", "", body_text, flags=re.I)
        if len(body_text) > 7000:
            body_text = body_text[:7000]
        image_urls = [urljoin(url, unescape(src)) for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html or "", re.I)]
        image_alts = [strip_tags(x) for x in re.findall(r'<img[^>]+(?:alt|title)=["\']([^"\']*)["\']', body_html or "", re.I) if x]
        if len(body_text) < 40 and image_alts:
            body_text = "\n".join([body_text, *image_alts]).strip()
        attachment_urls = []
        for _, link in all_links(html, url):
            if any(k in link.lower() for k in ["download", "bbsdown", "file", "attach"]):
                if link not in attachment_urls:
                    attachment_urls.append(link)
        body_text = append_attachment_text(body_text or title, extract_many_attachment_texts(attachment_urls[:4], max_files=2, fetcher=self.fetch_bytes))
        app_rng = self._extract_range(body_text, ["신청기간", "접수기간", "모집기간", "공모기간", "신청", "접수", "모집"])
        event_rng = self._extract_range(body_text, ["교육기간", "운영기간", "행사기간", "활동기간", "기간", "일시", "일정"])
        target = self._extract_labeled_value(body_text, ["대상", "모집대상", "참여대상", "신청대상", "지원대상"])
        location = self._extract_labeled_value(body_text, ["장소", "교육장소", "행사장소", "운영장소", "위치"])
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
        m = re.search(r"bbsData=([^&]+)", url)
        if m:
            return urljoin(self.list_url, f"?bbsData={m.group(1)}&mode=view")
        return url

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\[[^\]]*(?:공지|종료|마감)[^\]]*\]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"^\d+\s+(?:진행중|마감|공지|당첨자 발표)\s+", "", text).strip()
        return text[:180].rstrip() + ("…" if len(text) > 180 else "")

    @staticmethod
    def _dedupe(items: list[ListingItem]) -> list[ListingItem]:
        seen: set[str] = set()
        out: list[ListingItem] = []
        for item in items:
            if item.url not in seen:
                out.append(item)
                seen.add(item.url)
        return out

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


class XeDocumentBoardAdapter(EncodedPublicBoardAdapter):
    """Source-specific base for XE document_srl notice boards."""

    parser_version = "xe_document_board_v1"

    def parse_list_html(self, html: str) -> list[ListingItem]:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I)
        items: list[ListingItem] = []
        for row in rows:
            m = re.search(r'<a[^>]+href=["\']([^"\']*document_srl=\d+[^"\']*)["\'][^>]*>(.*?)</a>', row, re.S | re.I)
            if not m:
                continue
            href, inner = m.groups()
            title = self._clean_title(strip_tags(inner))
            date_text = first_match(r'(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})', row)
            if title:
                items.append(ListingItem(title=title, url=self._canonical_url(urljoin(self.list_url, unescape(href).replace("&amp;", "&"))), status="공지사항", published_at=parse_first_date(date_text) or GenericGnuboardAdapter._parse_date(date_text)))
        return self._dedupe(items)

    def _canonical_url(self, url: str) -> str:
        m = re.search(r"document_srl=(\d+)", url)
        if m:
            return urljoin(self.list_url, f"/index.php?mid=notice_01&document_srl={m.group(1)}")
        return url


class JinhaeMentalHealthEventAdapter(EncodedPublicBoardAdapter):
    parser_version = "jinhae_mental_health_event_v1"
    list_url = "https://www.jhmhc.or.kr/sub06/sub04_01.php"
    default_location = "진해정신건강복지센터"
    default_category = "복지건강"
    tags_extra = ["정신건강", "진해", "상담"]
    include_keywords = ["이벤트", "교육", "프로그램", "검진", "상담", "마음", "자조모임", "공모전", "참여", "신청", "캠페인"]
    negative_keywords = [*EncodedPublicBoardAdapter.negative_keywords, "당첨자", "당첨자 발표", "채용", "합격"]


class JinhaeWomenWorkCenterNoticeAdapter(EncodedPublicBoardAdapter):
    parser_version = "jinhae_women_work_center_notice_v1"
    list_url = "http://www.jhwoman.or.kr/kor/community/notice.html?code=notice"
    default_location = "진해여성인력개발센터"
    default_category = "교육"
    tags_extra = ["여성", "직업교육", "진해"]
    include_keywords = ["수강생", "모집", "교육", "무료", "프로그램", "강좌", "훈련", "창업", "취업", "신청", "접수", "특강"]
    negative_keywords = [*EncodedPublicBoardAdapter.negative_keywords, "강사모집", "강사 모집", "채용", "합격", "마감"]


class GyeongnamMigrantSupportNoticeAdapter(XeDocumentBoardAdapter):
    parser_version = "gyeongnam_migrant_support_notice_v1"
    list_url = "https://www.gnmigrant.or.kr/notice_01?l=ko"
    default_location = "경상남도외국인주민지원센터(창원시 의창구)"
    default_category = "복지건강"
    tags_extra = ["외국인주민", "이주민", "교육"]
    include_keywords = ["교육", "신청", "지원", "상담", "외국인", "주민", "참여", "워크숍", "비자", "주거환경", "기술교육"]
    negative_keywords = [*EncodedPublicBoardAdapter.negative_keywords, "채용정보", "언론보도"]


class ChangwonMuseumNoticeAdapter(EncodedPublicBoardAdapter):
    parser_version = "changwon_museum_notice_v1"
    list_url = "https://cwmuseum.or.kr/sub/sub04_01.php?code=cw_notice"
    default_location = "창원박물관"
    default_category = "문화"
    tags_extra = ["박물관", "문화", "시민참여"]
    include_keywords = ["모집", "신청", "토론회", "이벤트", "교육", "프로그램", "전시", "체험", "참여", "강좌"]
    negative_keywords = [*EncodedPublicBoardAdapter.negative_keywords, "유물기증", "소장품 기증", "유물 구입", "건립"]


class ChangwonSportsCouncilNoticeAdapter(EncodedPublicBoardAdapter):
    parser_version = "changwon_sports_council_notice_v1"
    list_url = "http://www.cwsports.or.kr/sub02/sub01_01.php?code=sub0201"
    default_location = "창원시체육회"
    default_category = "복지건강"
    tags_extra = ["체육", "생활체육", "건강"]
    include_keywords = ["대회", "모집", "신청", "참여", "스포츠", "체육", "생활체육", "운동", "튼튼머니", "교육", "포인트", "프로그램"]
    negative_keywords = [*EncodedPublicBoardAdapter.negative_keywords, "직원사칭", "선거", "총회", "채용", "합격", "의무교육"]

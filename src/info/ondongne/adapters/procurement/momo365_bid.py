from __future__ import annotations

from html import unescape
from datetime import datetime, timedelta
import re
from urllib.parse import urlencode, urljoin

from .base import ProcurementAdapterBase, ProcurementListingItem
from ...date_parser import is_within_days
from ...html_utils import first_match, strip_tags
from ...procurement_classifier import score_procurement_text
from ...procurement_models import ProcurementNotice
from ...summarizer import summarize_event


class Momo365BidAdapter(ProcurementAdapterBase):
    """문화사업지원플랫폼 모모365 입찰 공고 조회 parser.

    Momo365 mirrors cultural/event-related public bids and exposes plain HTML
    list/detail pages, so it is a practical first-phase alternative while full
    G2B OpenAPI integration is handled separately.
    """

    parser_version = "momo365_bid_v1"
    base = "https://www.momo365.net/BidInfo"

    def _list_url(self, page: int, since_days: int) -> str:
        # Keep the site defaults, but force 경남(AreaCode=23), list view, and page.
        today = datetime.now().date()
        start = today - timedelta(days=since_days)
        params = {
            "excel_table": "",
            "keyword": "",
            "ViewType": "list",
            "AreaCode": self.source.get("area_code", "23"),
            "BidState": "0",
            "OrderBy": "RegDTime",
            "iPageNum": str(page),
            "StartNum": str(max(0, (page - 1) * int(self.source.get("page_size", 10)))),
            "isLike": "",
            "lstSearchDate": "RegDTime",
            "SDate": self.source.get("start_date") or start.isoformat(),
            "EDate": self.source.get("end_date") or today.isoformat(),
            "lstSearchMoney": "BasicPrice",
            "SMoney": "",
            "EMoney": "",
            "lstNum": str(self.source.get("page_size", 10)),
            "lstSearchType": "BidName",
            "SearchWord": "",
        }
        return f"{self.base}?{urlencode(params)}"

    def list_items(self, since_days: int = 30, limit: int = 100) -> list[ProcurementListingItem]:
        items: list[ProcurementListingItem] = []
        seen: set[str] = set()
        page = 1
        while len(items) < limit and page <= 80:
            html = self.fetch_html(self._list_url(page, since_days))
            rows = re.findall(r"<tr[^>]*id=\"tr_([^\"]+)\"[^>]*>(.*?)</tr>", html, re.S | re.I)
            added = 0
            for row_id, row in rows:
                href = first_match(r'<a[^>]+href="([^"]*ViewType=detail[^"]*)"', row)
                title = strip_tags(first_match(r'<a[^>]+href="[^"]*ViewType=detail[^"]*"[^>]*>(.*?)</a>', row))
                cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
                dates = re.findall(r"20\d{2}-\d{2}-\d{2}", " ".join(cells))
                published_at = dates[1] if len(dates) >= 2 else (dates[0] if dates else None)
                if published_at and not is_within_days(published_at, since_days):
                    continue
                if not href or not title:
                    continue
                url = urljoin(self.base, unescape(href))
                if url in seen:
                    continue
                seen.add(url)
                items.append(
                    ProcurementListingItem(
                        title=title,
                        url=url,
                        notice_number=row_id.replace("_", "-"),
                        published_at=published_at,
                        application_period_text=" / ".join(dates),
                    )
                )
                added += 1
                if len(items) >= limit:
                    break
            if added == 0:
                break
            page += 1
        return items

    def crawl(self, since_days: int = 30, limit: int = 100) -> list[ProcurementNotice]:
        notices: list[ProcurementNotice] = []
        for item in self.list_items(since_days=since_days, limit=limit):
            scored_title = score_procurement_text(item.title)
            if scored_title["decision"] == "exclude":
                continue
            notice = self.parse_detail(item)
            scored = score_procurement_text(" ".join([notice.title, notice.body_text, notice.budget, notice.organization_name]))
            if scored["decision"] != "collect":
                continue
            notice.relevance_score = scored["score"]
            notice.matched_keywords = scored["matched_keywords"]
            notices.append(notice.finalize())
        return notices

    def parse_detail(self, item: ProcurementListingItem) -> ProcurementNotice:
        html = self.fetch_html(item.url)
        title = strip_tags(first_match(r"<th[^>]*>공고명</th>\s*<td[^>]*[^>]*>(.*?)</td>", html)) or item.title
        pairs = self._parse_th_td(html)
        body = strip_tags(first_match(r'<div[^>]+id="balju"[^>]*>(.*?)</div>\s*</div>', html)) or strip_tags(html)
        dates = re.findall(r"20\d{2}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?", html)
        published_at = pairs.get("공고게시일") or item.published_at
        end_date = pairs.get("투찰마감일") or pairs.get("참가등록마감일") or (dates[-2] if len(dates) >= 2 else None)
        org = pairs.get("발주기관") or pairs.get("발주(공고)기관") or pairs.get("수요기관") or self.source.get("organization_name", "모모365")
        budget = pairs.get("추정금액") or pairs.get("기초금액")
        return ProcurementNotice(
            source_id=self.source["id"],
            source_name=self.source["name"],
            organization_name=org,
            region_level1=self.source.get("region_level1", "경상남도"),
            region_level2=self.source.get("region_level2", "경남"),
            title=title,
            source_url=item.url,
            notice_type="입찰공고",
            summary=summarize_event(title, body),
            body_text=body,
            published_at=published_at[:10] if published_at else None,
            application_end_date=end_date[:10] if end_date else None,
            budget=budget,
            location_name=pairs.get("지역제한", ""),
            apply_url=item.url,
            notice_number=pairs.get("공고번호") or item.notice_number,
            status="수집완료",
            parser_version=self.parser_version,
        ).finalize()

    @staticmethod
    def _parse_th_td(html: str) -> dict[str, str]:
        pairs: dict[str, str] = {}
        for key, value in re.findall(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", html, re.S | re.I):
            k = strip_tags(key).strip(" :")
            v = strip_tags(value).strip()
            if k and v and k not in pairs:
                pairs[k] = v
        return pairs

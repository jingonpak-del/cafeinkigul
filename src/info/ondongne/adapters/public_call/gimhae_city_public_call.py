from __future__ import annotations

from ...procurement_models import ProcurementNotice
from ...public_call_classifier import has_public_call_prefilter, score_public_call_text
from ...summarizer import summarize_event
from ..procurement.gimhae_city_notice import GimhaeCityNoticeAdapter


class GimhaeCityPublicCallAdapter(GimhaeCityNoticeAdapter):
    """김해시 고시공고 중 행사·교육·공모·참여자 모집 public-call parser."""

    parser_version = "gimhae_city_public_call_v1"

    def crawl(self, since_days: int = 30, limit: int = 100) -> list[ProcurementNotice]:
        notices: list[ProcurementNotice] = []
        for item in self.list_items(since_days=since_days, limit=limit):
            if not has_public_call_prefilter(item.title):
                continue
            notice = self.parse_detail(item)
            text = " ".join([notice.title, notice.body_text, " ".join(a.name for a in notice.attachments)])
            scored = score_public_call_text(text)
            if scored["decision"] == "exclude":
                continue
            notice.notice_type = "공모·모집"
            notice.summary = summarize_event(notice.title, notice.body_text)
            notice.relevance_score = scored["score"]
            notice.matched_keywords = scored["matched_keywords"]
            notice.status = "수집완료" if scored["decision"] == "collect" else "검수필요"
            notice.parser_version = self.parser_version
            notices.append(notice.finalize())
        return notices

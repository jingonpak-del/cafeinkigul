from __future__ import annotations

import re
from html import unescape

from .changwon_ward_news_20260706 import ChangwonWardNewsAdapter


class UichangSubdistrictNewsAdapter(ChangwonWardNewsAdapter):
    """Changwon 읍면동 새소식 boards under the official ward portal.

    Each subclass pins one 읍/면/동 list URL while reusing the hardened official
    Changwon portal list/detail parser.  These boards are noisy 주민등록/행정공지
    streams, so the negative filter is intentionally stricter than ward-level news.
    """

    parser_version = "uichang_subdistrict_news_v1"
    default_category = "공익활동"
    max_pages = 3
    include_keywords = [
        "모집", "신청", "참여", "교육", "프로그램", "공모", "지원사업", "융자",
        "보조금", "상담", "체험", "특강", "행사", "수강", "접수", "주민자치",
        "봉사", "복지", "농어촌", "농업", "청년", "가족", "바우처", "문화누리",
    ]
    negative_keywords = [
        *ChangwonWardNewsAdapter.negative_keywords,
        "주민등록", "무단전출", "직권조치", "최고공고", "사실통지", "이장회의",
        "통장회의", "회의자료", "회의 자료", "민방위", "지방세", "체납", "공시송달",
        "폐기물", "쓰레기", "불법투기", "주정차", "영업신고", "위반", "행정처분",
        "장마", "폭염", "호우", "태풍", "재난", "안전점검", "도로명주소", "정정공고",
    ]
    tags_extra = ["의창구", "읍면동", "생활정보"]

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\b새\s*글\b", " ", text)
        text = re.sub(r"\[[^\]]*공지[^\]]*\]", " ", text)
        text = re.sub(r"\b\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}\b", " ", text)
        text = re.sub(r"조회수\s*[:：]?\s*[\d,]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()


class UichangDongeupNewsAdapter(UichangSubdistrictNewsAdapter):
    parser_version = "uichang_dongeup_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11094/11464/11496.web?gcode=1417"
    default_location = "창원시 의창구 동읍"
    tags_extra = ["의창구", "동읍", "읍면동", "생활정보"]


class UichangBukmyeonNewsAdapter(UichangSubdistrictNewsAdapter):
    parser_version = "uichang_bukmyeon_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11094/11465/11510.web?gcode=1417"
    default_location = "창원시 의창구 북면"
    tags_extra = ["의창구", "북면", "읍면동", "생활정보"]


class UichangDaesanNewsAdapter(UichangSubdistrictNewsAdapter):
    parser_version = "uichang_daesan_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11094/11466/11536.web?gcode=1417"
    default_location = "창원시 의창구 대산면"
    tags_extra = ["의창구", "대산면", "읍면동", "생활정보"]


class UichangUichangdongNewsAdapter(UichangSubdistrictNewsAdapter):
    parser_version = "uichang_uichangdong_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11094/11467/11552.web?gcode=1417"
    default_location = "창원시 의창구 의창동"
    tags_extra = ["의창구", "의창동", "읍면동", "생활정보"]


class UichangPallyongNewsAdapter(UichangSubdistrictNewsAdapter):
    parser_version = "uichang_pallyong_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11094/11468/11566.web?gcode=1417"
    default_location = "창원시 의창구 팔룡동"
    tags_extra = ["의창구", "팔룡동", "읍면동", "생활정보"]

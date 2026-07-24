from __future__ import annotations

import re
from html import unescape

from .changwon_city_public_boards_20260620 import ChangwonCityPublicBoardAdapter


class ChangwonWardNewsAdapter(ChangwonCityPublicBoardAdapter):
    """Changwon ward-office public notice boards.

    The five ward main news pages share the official Changwon portal board renderer
    and `gcode=1417`, but each ward has a distinct menu path.  Subclasses pin the
    menu URL, ward name, location/tags, and a ward-specific relevance vocabulary.
    """

    parser_version = "changwon_ward_news_v1"
    default_category = "공익활동"
    max_pages = 3
    include_keywords = [
        "모집", "신청", "참여", "교육", "프로그램", "공모", "공모전", "지원사업",
        "무료", "상담", "체험", "특강", "행사", "수강", "접수", "청년", "가족",
        "한부모", "스포츠패스", "주민자치", "봉사", "복지", "건강검진",
    ]
    negative_keywords = [
        *ChangwonCityPublicBoardAdapter.negative_keywords,
        "주간일정", "주간 일정", "주민등록", "무단전출", "최고공고", "최고장",
        "채용", "최종합격", "합격자", "기간제", "노동자", "공고", "고시",
        "입찰", "계약", "공사", "점검", "CCTV", "영상정보", "운영관리 방침",
        "지방세", "세무", "체납", "부과", "단속", "교통유발부담금", "운임",
        "불법", "행정처분", "영업정지", "여권", "민방위", "쓰레기", "폐기물",
        "결과 안내", "실시 결과", "회의", "통장 선정", "반송",
    ]
    tags_extra = ["구청", "생활정보"]

    @staticmethod
    def _clean_title(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"\b새\s*글\b", " ", text)
        text = re.sub(r"\[[^\]]*공지[^\]]*\]", " ", text)
        text = re.sub(r"\b\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}\b", " ", text)
        text = re.sub(r"조회수\s*[:：]?\s*[\d,]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 180:
            text = text[:180].rstrip() + "…"
        return text

    def _is_relevant(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "")
        if any(k.replace(" ", "") in normalized for k in self.negative_keywords):
            return False
        return any(k in (text or "") for k in self.include_keywords)


class UichangWardNewsAdapter(ChangwonWardNewsAdapter):
    parser_version = "uichang_ward_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11094/11462/11475.web?gcode=1417"
    default_location = "창원시 의창구"
    tags_extra = ["의창구", "구청", "생활정보"]


class SeongsanWardNewsAdapter(ChangwonWardNewsAdapter):
    parser_version = "seongsan_ward_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11098/11607/11639.web?gcode=1417"
    default_location = "창원시 성산구"
    tags_extra = ["성산구", "구청", "생활정보"]


class MasanhappoWardNewsAdapter(ChangwonWardNewsAdapter):
    parser_version = "masanhappo_ward_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11099/11806/11849.web?gcode=1417"
    default_location = "창원시 마산합포구"
    tags_extra = ["마산합포구", "구청", "생활정보"]


class MasanmemberWardNewsAdapter(ChangwonWardNewsAdapter):
    parser_version = "masanmember_ward_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12100/12137.web?gcode=1417"
    default_location = "창원시 마산회원구"
    tags_extra = ["마산회원구", "구청", "생활정보"]


class JinhaeWardNewsAdapter(ChangwonWardNewsAdapter):
    parser_version = "jinhae_ward_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11101/12355/12399.web?gcode=1417"
    default_location = "창원시 진해구"
    tags_extra = ["진해구", "구청", "생활정보"]

from __future__ import annotations

import re

from .changwon_city_public_boards_20260620 import ChangwonCityPublicBoardAdapter
from .changwon_culture_foundation import ChangwonCultureFoundationAdapter


class ChangwonVehicleRegistrationNewsAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_vehicle_registration_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11064/13615/13678.web?gcode=1009"
    default_location = "창원시 차량등록사업소"
    default_category = "공익활동"
    tags_extra = ["차량등록", "교통", "시민안내"]
    include_keywords = ["교육", "신청", "모집", "지원", "안내", "캠페인", "검사", "자동차", "민원", "운영"]
    negative_keywords = [
        *ChangwonCityPublicBoardAdapter.negative_keywords,
        "채용", "입찰", "계약", "공사", "점검", "장애", "중단", "과태료", "처분", "압류", "번호판", "단속",
    ]


class JinhaePortManagementNoticeAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "jinhae_port_management_notice_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11064/13691/13702.web?gcode=1009"
    default_location = "창원시 진해항"
    default_category = "공익활동"
    tags_extra = ["진해항", "해양", "항만"]
    include_keywords = ["교육", "신청", "모집", "지원", "안내", "체험", "행사", "항만", "해양", "운영"]
    negative_keywords = [
        *ChangwonCityPublicBoardAdapter.negative_keywords,
        "채용", "입찰", "계약", "공사", "점검", "사용료", "고시", "공고", "단속", "정비", "폐기물",
    ]


class ChangwonCovidNewsAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_covid_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11066/13228/14476.web?gcode=1009"
    default_location = "창원시 보건소"
    default_category = "복지건강"
    tags_extra = ["감염병", "보건", "건강안내"]
    include_keywords = ["교육", "신청", "모집", "지원", "안내", "접종", "검사", "예방", "건강", "상담"]
    negative_keywords = [
        *ChangwonCityPublicBoardAdapter.negative_keywords,
        "채용", "입찰", "계약", "현황", "확진자", "방역수칙", "행정명령", "중단", "점검",
    ]


class CwcfVenueNoticeAdapter(ChangwonCultureFoundationAdapter):
    venue_keywords: list[str] = []
    extra_negative_keywords = [
        "채용", "합격", "서류전형", "면접", "입찰", "계약", "용역", "평가위원", "심의 결과", "심의결과", "대관 심의", "사칭",
    ]
    extra_include_keywords = ["모집", "신청", "참여", "관람", "교육", "프로그램", "행사", "공연", "전시", "체험", "수강"]

    def list_items(self, since_days: int = 30, limit: int = 100):
        # Reuse the verified CWCF list/detail parser, then narrow it to one venue/facility.
        original_include = self.source.get("include_keywords", [])
        original_exclude = self.source.get("exclude_keywords", [])
        self.source["include_keywords"] = self.extra_include_keywords
        self.source["exclude_keywords"] = self.extra_negative_keywords
        try:
            items = super().list_items(since_days=since_days, limit=max(limit, 30))
        finally:
            self.source["include_keywords"] = original_include
            self.source["exclude_keywords"] = original_exclude
        out = []
        for item in items:
            normalized = re.sub(r"\s+", "", item.title)
            if self.venue_keywords and not any(k.replace(" ", "") in normalized for k in self.venue_keywords):
                continue
            if any(k.replace(" ", "") in normalized for k in self.extra_negative_keywords):
                continue
            out.append(item)
            if len(out) >= limit:
                break
        return out


class SeongsanArtHallNoticeAdapter(CwcfVenueNoticeAdapter):
    parser_version = "seongsan_art_hall_notice_v1"
    venue_keywords = ["성산아트홀"]


class Masan315ArtHallNoticeAdapter(CwcfVenueNoticeAdapter):
    parser_version = "masan_315_art_hall_notice_v1"
    venue_keywords = ["3·15아트홀", "315아트홀", "3ㆍ15아트홀"]

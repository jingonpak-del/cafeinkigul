from __future__ import annotations

from .changwon_city_public_boards_20260620 import ChangwonCityPublicBoardAdapter


class ChangwonTransportPolicyNewsAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_transport_policy_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11064/13466/13579.web?gcode=1335"
    default_location = "창원시 교통정책/버스운영"
    default_category = "행사"
    tags_extra = ["교통", "시민행사", "대중교통"]
    include_keywords = ["행사", "축제", "투르", "마라톤", "대회", "참여", "교통"]
    negative_keywords = [
        *ChangwonCityPublicBoardAdapter.negative_keywords,
        "채용", "입찰", "계약", "공사", "고장", "연료부족", "수리", "품질", "검사", "번호판",
        "노선 조정", "운행계통", "집회", "시내버스 시간표", "수소충전소",
    ]


class ChangwonSelfSufficiencyNewsAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_self_sufficiency_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11067/14103/14150.web?gcode=1378"
    default_location = "창원시 지역자활센터"
    default_category = "복지건강"
    tags_extra = ["자활", "일자리", "복지"]
    include_keywords = ["모집", "신청", "참여", "자활", "사업", "교육", "프로그램", "인턴", "참가"]
    negative_keywords = [
        *ChangwonCityPublicBoardAdapter.negative_keywords,
        "결산", "예산", "감사", "회의", "운영위원", "공시", "채용", "합격",
    ]


class ChangwonFoodSafetyNoticeAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_food_safety_notice_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11068/11091/13532.web?gcode=1391"
    default_location = "창원시 보건위생과"
    default_category = "복지건강"
    tags_extra = ["식품안전", "위생교육", "소상공인"]
    include_keywords = ["교육", "신청", "모집", "지원", "위생", "식품", "안전", "영업자", "업소", "컨설팅"]
    negative_keywords = [
        *ChangwonCityPublicBoardAdapter.negative_keywords,
        "사칭", "사기", "주의", "결과", "평가", "현황", "매뉴얼", "의무대상 확대 안내",
    ]


class ChangwonPublicHygieneNoticeAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_public_hygiene_notice_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11068/11091/13537.web?gcode=1395"
    default_location = "창원시 보건위생과"
    default_category = "복지건강"
    tags_extra = ["공중위생", "위생교육", "소상공인"]
    include_keywords = ["교육", "신청", "모집", "지원", "위생", "숙박", "목욕", "미용", "세탁", "업소"]
    negative_keywords = [
        *ChangwonCityPublicBoardAdapter.negative_keywords,
        "평가 결과", "최우수", "현황", "신고방법", "재난 원인조사", "불법사항",
    ]


class ChangwonWaterSewerNewsAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_water_sewer_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11065/11086/13192.web?gcode=1009"
    default_location = "창원시 하수도사업소"
    default_category = "공익활동"
    tags_extra = ["환경", "하수도", "시민안내"]
    include_keywords = ["교육", "신청", "모집", "참여", "실천", "캠페인", "안내", "환경", "하수", "빗물받이"]
    negative_keywords = [
        *ChangwonCityPublicBoardAdapter.negative_keywords,
        "요금 인상", "원가", "정보공개", "업무상황", "인상 및 개편", "공시", "결산",
    ]

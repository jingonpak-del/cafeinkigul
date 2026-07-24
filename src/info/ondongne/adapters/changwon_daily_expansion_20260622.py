from __future__ import annotations

from .changwon_city_public_boards_20260620 import ChangwonCityPublicBoardAdapter


class MasanHealthCenterNewsAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "masan_health_center_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11066/14417/13390.web?gcode=1009"
    default_location = "마산보건소"
    default_category = "복지건강"
    tags_extra = ["마산보건소", "건강교육", "운동교실"]
    include_keywords = ["모집", "참여", "신청", "건강", "운동", "프로그램", "교실", "교육", "헬스케어", "치매", "비만", "실버체조"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "강사 공개모집", "운영강사", "의료기관", "예방접종", "진료", "감염병", "방역", "검사 안내"]


class JinhaeHealthCenterNewsAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "jinhae_health_center_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11066/14418/13745.web?gcode=1009"
    default_location = "진해보건소"
    default_category = "복지건강"
    tags_extra = ["진해보건소", "건강교육", "동부건강생활지원센터"]
    include_keywords = ["모집", "참여", "신청", "건강", "운동", "프로그램", "교실", "교육", "걷기", "건강해GYM", "치매"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "강사 공개모집", "운영강사", "의료기관", "예방접종", "진료", "감염병", "방역", "검사 안내"]


class ChangwonAgricultureEducationAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_agriculture_education_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11071/11079/13519.web?gcode=1009"
    default_location = "창원시농업기술센터"
    default_category = "교육"
    tags_extra = ["농업기술센터", "농업교육", "도시농업"]
    include_keywords = ["교육생", "모집", "신청", "교육", "농업", "도시농업", "품목별", "농업대학", "아카데미", "귀농", "농심대학"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "주간농사정보", "병해충", "방제", "강사 모집", "채용", "농업기계 임대", "가격동향"]


class JinhaeGunhangjeCultureAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "jinhae_gunhangje_culture_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11063/11090/13030.web?gcode=1329"
    default_location = "진해군항제/진해구 일원"
    default_category = "문화"
    tags_extra = ["진해군항제", "축제", "문화행사"]
    include_keywords = ["군항제", "문화행사", "참여자", "모집", "신청", "공연", "전시", "체험", "행사", "축제", "가요제"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "교통통제", "주차", "안전관리", "보도자료", "결과", "정산", "용역", "입찰"]


class MasanChrysanthemumFestivalAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "masan_chrysanthemum_festival_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11063/14383/14393.web?gcode=1432"
    default_location = "마산가고파국화축제/마산 일원"
    default_category = "문화"
    tags_extra = ["마산국화축제", "축제", "문화행사"]
    include_keywords = ["국화축제", "마산국화", "가고파국화", "참여자", "모집", "신청", "공연", "전시", "체험", "행사", "축제", "가요제", "캐리커처"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "교통통제", "주차", "안전관리", "보도자료", "결과", "정산", "용역", "입찰"]

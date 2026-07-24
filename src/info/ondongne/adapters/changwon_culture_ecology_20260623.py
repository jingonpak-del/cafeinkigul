from __future__ import annotations

from .changwon_city_public_boards_20260620 import ChangwonCityPublicBoardAdapter


class ChangwonForestHealingAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "changwon_forest_healing_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/11362/11375.web?gcode=1276"
    default_location = "창원 편백 치유의 숲"
    default_category = "문화"
    tags_extra = ["산림휴양", "치유의숲", "체험프로그램"]
    include_keywords = ["모집", "참가자", "신청", "프로그램", "치유", "숲", "체험", "교육", "운영", "특별프로그램", "산림"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "휴무", "휴관", "임시휴장", "근로자의 날", "설날", "추석", "시설 점검", "시설물 보수"]


class JunamReservoirEcologyAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "junam_reservoir_ecology_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/12459/12819.web?gcode=1321"
    default_location = "주남저수지"
    default_category = "문화"
    tags_extra = ["주남저수지", "생태교육", "탐방"]
    include_keywords = ["모집", "참가자", "수강생", "신청", "프로그램", "생태", "탐방", "체험", "교육", "해설", "전시", "개최"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "출입통제", "개방 안내", "폐쇄", "조류인플루엔자", "AI 발생", "공사", "점검", "단순 안내"]


class MasanMuseumProgramAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "masan_museum_program_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/11381/11424.web?gcode=1283"
    default_location = "창원시립마산박물관"
    default_category = "문화"
    tags_extra = ["마산박물관", "역사교육", "전시해설"]
    include_keywords = ["모집", "참가자", "수강생", "신청", "교육", "박물관학교", "시민박물관대학", "전시", "전시해설", "기획전", "체험", "문화행사", "운영"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "운영 안내", "휴관", "휴무", "관람 안내", "유물 구입", "소장품", "입찰", "채용"]


class MasanMusicHallProgramAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "masan_music_hall_program_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/12455/12787.web?gcode=1293"
    default_location = "창원시립마산음악관"
    default_category = "문화"
    tags_extra = ["마산음악관", "음악교육", "공연"]
    include_keywords = ["모집", "수강생", "신청", "음악교양대학", "교육", "강좌", "공연", "음악회", "프로그램", "공모", "지원사업자"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "채용", "입찰", "계약", "점검", "휴관", "운영 안내", "보도자료"]


class MasanLiteratureMuseumProgramAdapter(ChangwonCityPublicBoardAdapter):
    parser_version = "masan_literature_museum_program_v1"
    list_url = "https://www.changwon.go.kr/cwportal/depart/11062/12453/12478.web?gcode=1289"
    default_location = "창원시립마산문학관"
    default_category = "문화"
    tags_extra = ["마산문학관", "문예대학", "인문교육"]
    include_keywords = ["모집", "수강생", "신청", "문예대학", "문학", "아카데미", "교육", "강좌", "프로그램", "문예", "시민문예대학"]
    negative_keywords = [*ChangwonCityPublicBoardAdapter.negative_keywords, "채용", "입찰", "계약", "휴관", "운영 안내", "야외음악회 지방보조금"]

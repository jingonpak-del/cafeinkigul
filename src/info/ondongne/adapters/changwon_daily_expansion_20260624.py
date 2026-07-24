from __future__ import annotations

from .generic_gnuboard import GenericGnuboardAdapter


class ChangwonCommunitySecurityCouncilAdapter(GenericGnuboardAdapter):
    """창원시 지역사회보장협의체 공지사항."""

    parser_version = "changwon_community_security_council_v1"
    board_url = "https://www.cwwelfare.or.kr/bbs/board.php?bo_table=05_01"
    allowed_boards = ["05_01"]
    default_location = "창원시 지역사회보장협의체"
    default_category = "복지건강"
    tags_extra = ["지역사회보장", "복지", "협의체"]
    include_keywords = ["모집", "신청", "참석", "교육", "복지박람회", "지역사회보장", "워크숍", "세미나", "간담회", "사업 안내", "지원사업"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "용역", "제안서", "평가 결과", "위원회 결과", "회의록"]


class GyeongnamStartupTechAdapter(GenericGnuboardAdapter):
    """GSAT(경남 스타트업/창업 지원) 공지사항."""

    parser_version = "gyeongnam_startup_tech_v1"
    board_url = "https://gsat.or.kr/bbs/board.php?bo_table=news"
    allowed_boards = ["news"]
    default_location = "경남/창원"
    default_category = "취업창업"
    tags_extra = ["창업", "스타트업", "교육"]
    include_keywords = ["모집", "신청", "프로그램", "창업", "스타트업", "교육", "멘토링", "컨설팅", "지원사업", "사업화", "입주", "참가"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "용역", "선정결과", "결과 발표"]


class ChangwonNationalUniversitySwAdapter(GenericGnuboardAdapter):
    """국립창원대학교 SW중심대학사업단 공지사항."""

    parser_version = "changwon_national_university_sw_v1"
    board_url = "https://sw.changwon.ac.kr/bbs/board.php?bo_table=notice"
    allowed_boards = ["notice"]
    default_location = "국립창원대학교"
    default_category = "교육"
    tags_extra = ["SW", "AI", "대학", "청년"]
    include_keywords = ["모집", "신청", "프로그램", "교육", "AI", "SW", "해커톤", "경진대회", "캠프", "특강", "오픈소스", "프로젝트"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "비공개 글", "합격", "결과", "수상자"]


class MasanDisabledWelfareCenterAdapter(GenericGnuboardAdapter):
    """마산장애인복지관 공지사항."""

    parser_version = "masan_disabled_welfare_center_v1"
    board_url = "https://www.mscrc.or.kr/bbs/board.php?bo_table=03_01"
    allowed_boards = ["03_01"]
    default_location = "마산장애인복지관"
    default_category = "복지건강"
    tags_extra = ["장애인", "복지", "마산"]
    include_keywords = ["모집", "신청", "참여", "프로그램", "교육", "여성장애인", "시민옹호인", "주거환경", "이용자", "걷기대회", "상담", "체험"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "합격", "운영위원회", "회의결과", "후원금"]


class JinhaeDisabledSportsCenterAdapter(GenericGnuboardAdapter):
    """창원시진해종합사회복지관/장애인체육 공지사항."""

    parser_version = "jinhae_disabled_sports_center_v1"
    board_url = "https://jh1004sports.or.kr/bbs/board.php?bo_table=03_01"
    allowed_boards = ["03_01"]
    default_location = "창원시진해종합사회복지관 체육시설"
    default_category = "복지건강"
    tags_extra = ["진해", "장애인체육", "수영", "체육"]
    include_keywords = ["모집", "회원접수", "접수", "강습", "수영", "특강", "체육", "프로그램", "이용", "신청"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "휴관", "공사", "업무시간 변경", "환불방법", "운영 안내", "공지"]

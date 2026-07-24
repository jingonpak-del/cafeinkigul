from __future__ import annotations

from .generic_gnuboard import GenericGnuboardAdapter


class MasanSocialWelfareCenterAdapter(GenericGnuboardAdapter):
    """마산종합사회복지관 새소식."""

    parser_version = "masan_social_welfare_center_v1"
    board_url = "http://www.youngsin.or.kr/bbs/board.php?bo_table=news"
    allowed_boards = ["news"]
    default_location = "마산종합사회복지관"
    default_category = "복지건강"
    tags_extra = ["마산", "종합사회복지관", "복지"]
    include_keywords = ["모집", "신청", "참여", "프로그램", "교육", "느린학습자", "다다름", "가족", "상담", "강좌", "체험", "행사"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "합격", "실습생", "후원금", "식단", "공고", "결과보고"]


class ChangwonAddictionCenterAdapter(GenericGnuboardAdapter):
    """창원중독관리통합지원센터 공지사항."""

    parser_version = "changwon_addiction_center_v1"
    board_url = "https://www.cwacc.or.kr/bbs/board.php?bo_table=K060100"
    allowed_boards = ["K060100"]
    default_location = "창원중독관리통합지원센터"
    default_category = "복지건강"
    tags_extra = ["중독관리", "정신건강", "절주"]
    include_keywords = ["모집", "신청", "참여", "프로그램", "교육", "절주", "회복", "캠페인", "상담", "사업장", "강좌", "행사"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "직원", "합격", "결산", "공고", "의뢰서 양식", "개인정보"]


class ChangwonDevelopmentDisabilityCenterAdapter(GenericGnuboardAdapter):
    """창원발달장애인가활센터 공지사항."""

    parser_version = "changwon_development_disability_center_v1"
    board_url = "https://www.gahwal.or.kr/bbs/board.php?bo_table=sub03_01"
    allowed_boards = ["sub03_01"]
    default_location = "창원발달장애인가활센터"
    default_category = "복지건강"
    tags_extra = ["발달장애", "AAC", "가활"]
    include_keywords = ["모집", "신청", "참여", "프로그램", "교육", "발달재활", "AAC", "부모", "보호자", "이용자", "지원사업", "상담"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "합격", "직원", "회계", "결산", "후원", "운영위원회"]


class GyeongnamGlobalGameCenterAdapter(GenericGnuboardAdapter):
    """경남글로벌게임센터 공지사항."""

    parser_version = "gyeongnam_global_game_center_v1"
    board_url = "https://www.gngc.or.kr/bbs/board.php?bo_table=04_01"
    allowed_boards = ["04_01"]
    default_location = "경남글로벌게임센터/창원"
    default_category = "취업창업"
    tags_extra = ["게임", "콘텐츠", "창업", "기업지원"]
    include_keywords = ["모집", "신청", "참여기업", "지원사업", "교육", "프로그램", "멘토링", "컨설팅", "전시", "박람회", "이스포츠", "창업"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "합격", "용역", "입찰", "선정결과", "결과 발표", "평가 결과"]


class ChangwonTennisCenterAdapter(GenericGnuboardAdapter):
    """창원시립테니스장 공지사항."""

    parser_version = "changwon_tennis_center_v1"
    board_url = "https://www.cwsisul.or.kr/bbs/board.php?bo_table=sub06_04_01&sca=%EC%B0%BD%EC%9B%90%EC%8B%9C%EB%A6%BD%ED%85%8C%EB%8B%88%EC%8A%A4%EC%9E%A5"
    allowed_boards = ["sub06_04_01"]
    default_location = "창원시립테니스장"
    default_category = "복지건강"
    tags_extra = ["체육", "테니스", "시설공단"]
    include_keywords = ["모집", "신청", "회원모집", "프로그램", "강습", "수강", "테니스", "대회", "체험", "이용", "접수"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "채용", "입찰", "공사", "휴관", "휴장", "점검", "수질검사", "CCTV", "분실물", "개인정보", "이용 제한", "운영일정", "운영 일정"]

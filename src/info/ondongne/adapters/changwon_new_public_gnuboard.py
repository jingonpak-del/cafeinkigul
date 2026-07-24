from __future__ import annotations

from .generic_gnuboard import GenericGnuboardAdapter


class ChangwonJinroCenterAdapter(GenericGnuboardAdapter):
    """창원진로교육지원센터 공지사항."""

    parser_version = "changwon_jinro_center_v1"
    board_url = "https://www.cwjinro.kr/bbs/board.php?bo_table=notice"
    allowed_boards = ["notice"]
    default_location = "창원진로교육지원센터"
    default_category = "교육"
    tags_extra = ["진로", "청소년", "교육"]
    max_pages = 1
    include_keywords = ["진로", "진학", "멘토링", "체험", "특강", "상담", "공모전", "신청", "접수", "모집", "교육", "프로그램"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "보도자료", "완료"]


class ChangwonSocialEconomyCenterAdapter(GenericGnuboardAdapter):
    """창원시사회적경제지원센터 지원센터 알림."""

    parser_version = "changwon_social_economy_center_v1"
    board_url = "https://cwsec.or.kr/bbs/board.php?bo_table=B01"
    allowed_boards = ["B01"]
    default_location = "창원시사회적경제지원센터"
    default_category = "취업창업"
    tags_extra = ["사회적경제", "창업", "기업지원"]
    include_keywords = ["모집", "지원사업", "교육", "컨설팅", "멘토링", "설명회", "참여", "신청", "공모", "스케일업", "창업", "입주", "상담"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "휴무", "채용", "결과"]


class ModucoopAdapter(GenericGnuboardAdapter):
    """모두의경제 사회적협동조합 공지사항."""

    parser_version = "moducoop_v1"
    board_url = "http://www.moducoop.com/bbs/board.php?bo_table=notice"
    allowed_boards = ["notice"]
    default_location = "경남/창원 사회적경제 지원기관"
    default_category = "취업창업"
    tags_extra = ["사회적경제", "협동조합", "기업지원"]
    include_keywords = ["모집", "교육", "멘토링", "컨설팅", "지원사업", "참가", "참여", "신청", "공모", "설립인가", "상담", "입주", "소셜"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "직원채용", "최종합격자", "용역 공고", "선정 공고"]


class JinhaeDisabilityWelfareCenterAdapter(GenericGnuboardAdapter):
    """진해장애인복지관 공지사항."""

    parser_version = "jinhae_disability_welfare_center_v1"
    board_url = "https://jcrc.or.kr/bbs/board.php?bo_table=notice"
    allowed_boards = ["notice"]
    default_location = "진해장애인복지관"
    default_category = "복지건강"
    tags_extra = ["진해", "장애인복지", "복지관"]
    include_keywords = ["모집", "신청", "프로그램", "교육", "평생교육", "공연", "행사", "참여", "바우처", "상담", "동아리", "체험"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "휴관", "운영위원회", "회의", "수상자", "선정결과"]


class GyeongnamContentKoreaLabAdapter(GenericGnuboardAdapter):
    """경남콘텐츠코리아랩 공지사항."""

    parser_version = "gyeongnam_content_korea_lab_v1"
    board_url = "https://www.gnckl.or.kr/bbs/board.php?bo_table=notice"
    allowed_boards = ["notice"]
    default_location = "경남콘텐츠코리아랩(창원시 성산구 창원대로 524)"
    default_category = "문화"
    tags_extra = ["콘텐츠", "창작", "창업", "교육"]
    include_keywords = ["모집", "교육", "창작", "콘텐츠", "지원사업", "참가", "신청", "공모", "스타트업", "창업", "프로그램", "페어"]
    negative_keywords = [*GenericGnuboardAdapter.negative_keywords, "웹진", "취재", "결과"]

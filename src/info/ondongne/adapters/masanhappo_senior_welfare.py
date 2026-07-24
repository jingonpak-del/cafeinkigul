from __future__ import annotations

from .cwwf_senior_board import CwwfSeniorBoardAdapter


class MasanHappoSeniorWelfareAdapter(CwwfSeniorBoardAdapter):
    """Parser for 마산합포노인종합복지관 공지사항."""

    parser_version = "masanhappo_senior_welfare_v1"
    base = "https://mshpswc.cwwf.or.kr"
    board_url = "https://mshpswc.cwwf.or.kr/sub/board_01.php?code=notice"
    org_label = "마산합포노인종합복지관"
    default_location = "마산합포노인종합복지관"
    tags_extra = ["마산합포구"]

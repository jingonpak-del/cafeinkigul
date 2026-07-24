from __future__ import annotations

from .cwwf_senior_board import CwwfSeniorBoardAdapter


class UichangSeniorWelfareAdapter(CwwfSeniorBoardAdapter):
    """Parser for 의창노인종합복지관 공지사항."""

    parser_version = "uichang_senior_welfare_v1"
    base = "https://chswc.cwwf.or.kr"
    board_url = "https://chswc.cwwf.or.kr/sub/board_01.php?code=notice"
    org_label = "의창노인종합복지관"
    default_location = "의창노인종합복지관"
    tags_extra = ["의창구"]

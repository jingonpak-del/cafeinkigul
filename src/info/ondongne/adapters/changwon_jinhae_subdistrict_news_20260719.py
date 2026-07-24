from __future__ import annotations

from .changwon_jinhae_subdistrict_news_20260718 import JinhaeSubdistrictNewsAdapter


class JinhaeIdongNewsAdapter(JinhaeSubdistrictNewsAdapter):
    """Official Changwon portal: Jinhae-gu Idong public-interest news."""

    parser_version = "jinhae_idong_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11101/12362/12519.web?gcode=1417"
    default_location = "창원시 진해구 이동"
    tags_extra = ["진해구", "이동", "읍면동", "생활정보"]


class JinhaeJaeunNewsAdapter(JinhaeSubdistrictNewsAdapter):
    """Official Changwon portal: Jinhae-gu Jaeun-dong public-interest news."""

    parser_version = "jinhae_jaeun_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11101/12363/12533.web?gcode=1417"
    default_location = "창원시 진해구 자은동"
    tags_extra = ["진해구", "자은동", "읍면동", "생활정보"]


class JinhaeDeoksanNewsAdapter(JinhaeSubdistrictNewsAdapter):
    """Official Changwon portal: Jinhae-gu Deoksan-dong public-interest news."""

    parser_version = "jinhae_deoksan_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11101/12365/12567.web?gcode=1417"
    default_location = "창원시 진해구 덕산동"
    tags_extra = ["진해구", "덕산동", "읍면동", "생활정보"]


class JinhaePunghoNewsAdapter(JinhaeSubdistrictNewsAdapter):
    """Official Changwon portal: Jinhae-gu Pungho-dong public-interest news."""

    parser_version = "jinhae_pungho_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11101/12366/12586.web?gcode=1417"
    default_location = "창원시 진해구 풍호동"
    tags_extra = ["진해구", "풍호동", "읍면동", "생활정보"]


class JinhaeUngcheonNewsAdapter(JinhaeSubdistrictNewsAdapter):
    """Official Changwon portal: Jinhae-gu Ungcheon-dong public-interest news."""

    parser_version = "jinhae_ungcheon_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11101/12367/12603.web?gcode=1417"
    default_location = "창원시 진해구 웅천동"
    tags_extra = ["진해구", "웅천동", "읍면동", "생활정보"]

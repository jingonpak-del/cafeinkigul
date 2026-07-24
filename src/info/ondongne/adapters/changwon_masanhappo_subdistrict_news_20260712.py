from __future__ import annotations

from .changwon_subdistrict_news_20260711 import UichangSubdistrictNewsAdapter


class MasanhappoSubdistrictNewsAdapter(UichangSubdistrictNewsAdapter):
    """Masan Happo-gu 읍면동 새소식 boards on the official Changwon portal.

    The Masan Happo subdistrict boards reuse the same `gcode=1417` official
    board renderer hardened for ward/subdistrict news.  This base pins a stricter
    Happo-gu administrative-noise filter while subclasses pin each menu path.
    """

    parser_version = "masanhappo_subdistrict_news_v1"
    default_category = "공익활동"
    tags_extra = ["마산합포구", "읍면동", "생활정보"]
    negative_keywords = [
        *UichangSubdistrictNewsAdapter.negative_keywords,
        "어선", "어업허가", "수산", "농지처분", "산불", "방역", "소독", "적치물",
        "불법광고물", "자동차세", "개별공시지가", "건축신고", "도로점용", "가로등",
    ]


class MasanhappoGusanNewsAdapter(MasanhappoSubdistrictNewsAdapter):
    parser_version = "masanhappo_gusan_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11099/11808/11872.web?gcode=1417"
    default_location = "창원시 마산합포구 구산면"
    tags_extra = ["마산합포구", "구산면", "읍면동", "생활정보"]


class MasanhappoJindongNewsAdapter(MasanhappoSubdistrictNewsAdapter):
    parser_version = "masanhappo_jindong_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11099/11809/11892.web?gcode=1417"
    default_location = "창원시 마산합포구 진동면"
    tags_extra = ["마산합포구", "진동면", "읍면동", "생활정보"]


class MasanhappoJinbukNewsAdapter(MasanhappoSubdistrictNewsAdapter):
    parser_version = "masanhappo_jinbuk_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11099/11810/11907.web?gcode=1417"
    default_location = "창원시 마산합포구 진북면"
    tags_extra = ["마산합포구", "진북면", "읍면동", "생활정보"]


class MasanhappoJinjeonNewsAdapter(MasanhappoSubdistrictNewsAdapter):
    parser_version = "masanhappo_jinjeon_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11099/11811/11924.web?gcode=1417"
    default_location = "창원시 마산합포구 진전면"
    tags_extra = ["마산합포구", "진전면", "읍면동", "생활정보"]


class MasanhappoHyeondongNewsAdapter(MasanhappoSubdistrictNewsAdapter):
    parser_version = "masanhappo_hyeondong_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11099/11812/11940.web?gcode=1417"
    default_location = "창원시 마산합포구 현동"
    tags_extra = ["마산합포구", "현동", "읍면동", "생활정보"]

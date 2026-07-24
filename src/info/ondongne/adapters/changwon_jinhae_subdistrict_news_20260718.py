from __future__ import annotations

from .changwon_subdistrict_news_20260711 import UichangSubdistrictNewsAdapter


class JinhaeSubdistrictNewsAdapter(UichangSubdistrictNewsAdapter):
    """Jinhae-gu 읍면동 새소식 boards on the official Changwon portal."""

    parser_version = "jinhae_subdistrict_news_v1"
    default_category = "공익활동"
    tags_extra = ["진해구", "읍면동", "생활정보"]
    negative_keywords = [
        *UichangSubdistrictNewsAdapter.negative_keywords,
        "통장 공개모집", "통장 공개 모집", "통장 선정", "주민자치센터 수강료",
        "수강료 수입 및 지출", "자동차 과태료", "고지서 반송", "공시송달",
        "주정차", "불법광고물", "도로점용", "가로등", "보안등", "방역", "소독",
        "공사", "휴관", "휴장", "정기점검", "정기 점검", "청소년지도위원회",
    ]


class JinhaeChungmuNewsAdapter(JinhaeSubdistrictNewsAdapter):
    parser_version = "jinhae_chungmu_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11101/12357/12422.web?gcode=1417"
    default_location = "창원시 진해구 충무동"
    tags_extra = ["진해구", "충무동", "읍면동", "생활정보"]


class JinhaeYeojaNewsAdapter(JinhaeSubdistrictNewsAdapter):
    parser_version = "jinhae_yeoja_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11101/12358/12436.web?gcode=1417"
    default_location = "창원시 진해구 여좌동"
    tags_extra = ["진해구", "여좌동", "읍면동", "생활정보"]


class JinhaeTaebaekNewsAdapter(JinhaeSubdistrictNewsAdapter):
    parser_version = "jinhae_taebaek_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11101/12359/12450.web?gcode=1417"
    default_location = "창원시 진해구 태백동"
    tags_extra = ["진해구", "태백동", "읍면동", "생활정보"]


class JinhaeGyeonghwaNewsAdapter(JinhaeSubdistrictNewsAdapter):
    parser_version = "jinhae_gyeonghwa_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11101/12360/12489.web?gcode=1417"
    default_location = "창원시 진해구 경화동"
    tags_extra = ["진해구", "경화동", "읍면동", "생활정보"]


class JinhaeByeongamNewsAdapter(JinhaeSubdistrictNewsAdapter):
    parser_version = "jinhae_byeongam_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11101/12361/12505.web?gcode=1417"
    default_location = "창원시 진해구 병암동"
    tags_extra = ["진해구", "병암동", "읍면동", "생활정보"]

from __future__ import annotations

from .changwon_subdistrict_news_20260711 import UichangSubdistrictNewsAdapter


class SeongsanSubdistrictNewsAdapter(UichangSubdistrictNewsAdapter):
    """Seongsan-gu 읍면동 새소식 boards on the official Changwon portal.

    These five boards reuse Changwon's official `gcode=1417` board renderer.
    The subclasses pin distinct Seongsan-gu menu paths while this base adds
    district-specific administrative-noise exclusions discovered from live lists.
    """

    parser_version = "seongsan_subdistrict_news_v1"
    default_category = "공익활동"
    tags_extra = ["성산구", "읍면동", "생활정보"]
    negative_keywords = [
        *UichangSubdistrictNewsAdapter.negative_keywords,
        "자동차관리법", "이륜자동차", "과태료", "고지서 반송", "반송분",
        "공시송달", "민방위 사이버교육", "청소년지도위원회 순찰 결과",
        "야간순찰 실시 결과", "수강료 수입 및 지출내역", "주민자치센터 수강료",
        "통장 공개모집", "통장 공개 모집", "통장 선정", "방역", "소독",
        "도로점용", "불법광고물", "가로등", "보안등", "지방세", "자동차세",
    ]


class SeongsanBansongNewsAdapter(SeongsanSubdistrictNewsAdapter):
    parser_version = "seongsan_bansong_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11098/11609/11666.web?gcode=1417"
    default_location = "창원시 성산구 반송동"
    tags_extra = ["성산구", "반송동", "읍면동", "생활정보"]


class SeongsanJungangNewsAdapter(SeongsanSubdistrictNewsAdapter):
    parser_version = "seongsan_jungang_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11098/11610/11682.web?gcode=1417"
    default_location = "창원시 성산구 중앙동"
    tags_extra = ["성산구", "중앙동", "읍면동", "생활정보"]


class SeongsanSangnamNewsAdapter(SeongsanSubdistrictNewsAdapter):
    parser_version = "seongsan_sangnam_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11098/11612/11719.web?gcode=1417"
    default_location = "창원시 성산구 상남동"
    tags_extra = ["성산구", "상남동", "읍면동", "생활정보"]


class SeongsanSapaNewsAdapter(SeongsanSubdistrictNewsAdapter):
    parser_version = "seongsan_sapa_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11098/11613/11733.web?gcode=1417"
    default_location = "창원시 성산구 사파동"
    tags_extra = ["성산구", "사파동", "읍면동", "생활정보"]


class SeongsanGaeumjeongNewsAdapter(SeongsanSubdistrictNewsAdapter):
    parser_version = "seongsan_gaeumjeong_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11098/11614/11761.web?gcode=1417"
    default_location = "창원시 성산구 가음정동"
    tags_extra = ["성산구", "가음정동", "읍면동", "생활정보"]

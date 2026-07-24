from __future__ import annotations

from .changwon_masanhappo_subdistrict_news_20260712 import MasanhappoSubdistrictNewsAdapter


class MasanhappoNeighborhoodNewsAdapter(MasanhappoSubdistrictNewsAdapter):
    """Later Masan Happo-gu neighborhood news boards on Changwon's official portal.

    The five pinned menu paths share the official ``gcode=1417`` list/detail
    renderer, but local lists contain frequent administrative notices.  Keep the
    parser source-specific and reject those notices before detail requests.
    """

    parser_version = "masanhappo_neighborhood_news_v1"
    tags_extra = ["마산합포구", "읍면동", "생활정보"]
    negative_keywords = [
        *MasanhappoSubdistrictNewsAdapter.negative_keywords,
        "통장 공개모집", "통장 공개 모집", "통장 선정", "주민자치회 위원 모집",
        "주민자치회 위원 위촉", "주민자치센터 수강료", "수강료 수입 및 지출",
        "쓰레기 불법투기", "불법 주정차", "세외수입", "과태료", "공시송달",
        "도로굴착", "공사 안내", "정비공사", "하수관", "보안등",
    ]


class MasanhappoGapoNewsAdapter(MasanhappoNeighborhoodNewsAdapter):
    parser_version = "masanhappo_gapo_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11099/11813/11954.web?gcode=1417"
    default_location = "창원시 마산합포구 가포동"
    tags_extra = ["마산합포구", "가포동", "읍면동", "생활정보"]


class MasanhappoWolyeongNewsAdapter(MasanhappoNeighborhoodNewsAdapter):
    parser_version = "masanhappo_wolyeong_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11099/11814/11968.web?gcode=1417"
    default_location = "창원시 마산합포구 월영동"
    tags_extra = ["마산합포구", "월영동", "읍면동", "생활정보"]


class MasanhappoMunhwaNewsAdapter(MasanhappoNeighborhoodNewsAdapter):
    parser_version = "masanhappo_munhwa_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11099/11815/11981.web?gcode=1417"
    default_location = "창원시 마산합포구 문화동"
    tags_extra = ["마산합포구", "문화동", "읍면동", "생활정보"]


class MasanhappoBanwolJungangNewsAdapter(MasanhappoNeighborhoodNewsAdapter):
    parser_version = "masanhappo_banwoljungang_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11099/11816/11995.web?gcode=1417"
    default_location = "창원시 마산합포구 반월중앙동"
    tags_extra = ["마산합포구", "반월중앙동", "읍면동", "생활정보"]


class MasanhappoWanwolNewsAdapter(MasanhappoNeighborhoodNewsAdapter):
    parser_version = "masanhappo_wanwol_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11099/11817/12009.web?gcode=1417"
    default_location = "창원시 마산합포구 완월동"
    tags_extra = ["마산합포구", "완월동", "읍면동", "생활정보"]

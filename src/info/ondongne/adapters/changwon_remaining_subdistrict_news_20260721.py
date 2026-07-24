from __future__ import annotations

from .changwon_masanmember_subdistrict_news_20260713 import MasanmemberSubdistrictNewsAdapter
from .changwon_seongsan_subdistrict_news_20260714 import SeongsanSubdistrictNewsAdapter


class MasanmemberGuam2NewsAdapter(MasanmemberSubdistrictNewsAdapter):
    """Official Changwon portal: Masan Hoewon-gu Guam 2-dong news."""

    parser_version = "masanmember_guam2_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12112/12321.web?gcode=1417"
    default_location = "창원시 마산회원구 구암2동"
    tags_extra = ["마산회원구", "구암2동", "읍면동", "생활정보"]


class MasanmemberBongamNewsAdapter(MasanmemberSubdistrictNewsAdapter):
    """Official Changwon portal: Masan Hoewon-gu Bongam-dong news."""

    parser_version = "masanmember_bongam_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12113/12339.web?gcode=1417"
    default_location = "창원시 마산회원구 봉암동"
    tags_extra = ["마산회원구", "봉암동", "읍면동", "생활정보"]


class SeongsanYongjiNewsAdapter(SeongsanSubdistrictNewsAdapter):
    """Official Changwon portal: Seongsan-gu Yongji-dong news."""

    parser_version = "seongsan_yongji_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11098/11611/11696.web?gcode=1417"
    default_location = "창원시 성산구 용지동"
    tags_extra = ["성산구", "용지동", "읍면동", "생활정보"]


class SeongsanSeongjuNewsAdapter(SeongsanSubdistrictNewsAdapter):
    """Official Changwon portal: Seongsan-gu Seongju-dong news."""

    parser_version = "seongsan_seongju_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11098/11615/11779.web?gcode=1417"
    default_location = "창원시 성산구 성주동"
    tags_extra = ["성산구", "성주동", "읍면동", "생활정보"]


class SeongsanUngnamNewsAdapter(SeongsanSubdistrictNewsAdapter):
    """Official Changwon portal: Seongsan-gu Ungnam-dong news."""

    parser_version = "seongsan_ungnam_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11098/11616/11793.web?gcode=1417"
    default_location = "창원시 성산구 웅남동"
    tags_extra = ["성산구", "웅남동", "읍면동", "생활정보"]

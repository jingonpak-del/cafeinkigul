from __future__ import annotations

from .changwon_subdistrict_news_20260711 import UichangSubdistrictNewsAdapter


class MasanmemberSubdistrictNewsAdapter(UichangSubdistrictNewsAdapter):
    """Masan Hoewon-gu 읍면동 새소식 boards on the official Changwon portal.

    These boards reuse Changwon's official `gcode=1417` board renderer.  The
    subclasses below pin five not-yet-registered Masan Hoewon-gu menu paths while
    this base adds district-specific administrative-noise exclusions.
    """

    parser_version = "masanmember_subdistrict_news_v1"
    default_category = "공익활동"
    tags_extra = ["마산회원구", "읍면동", "생활정보"]
    negative_keywords = [
        *UichangSubdistrictNewsAdapter.negative_keywords,
        "자동차세", "개별공시지가", "건축신고", "도로점용", "가로등", "불법광고물",
        "방역", "소독", "적치물", "공유수면", "농지", "산불", "기초번호", "보안등",
        "통장 공개모집", "통장 공개 모집", "통장 선정",
    ]


class MasanmemberNaeseoNewsAdapter(MasanmemberSubdistrictNewsAdapter):
    parser_version = "masanmember_naeseo_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12102/12159.web?gcode=1417"
    default_location = "창원시 마산회원구 내서읍"
    tags_extra = ["마산회원구", "내서읍", "읍면동", "생활정보"]


class MasanmemberHoewon1NewsAdapter(MasanmemberSubdistrictNewsAdapter):
    parser_version = "masanmember_hoewon1_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12103/12179.web?gcode=1417"
    default_location = "창원시 마산회원구 회원1동"
    tags_extra = ["마산회원구", "회원1동", "읍면동", "생활정보"]


class MasanmemberHoewon2NewsAdapter(MasanmemberSubdistrictNewsAdapter):
    parser_version = "masanmember_hoewon2_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12104/12193.web?gcode=1417"
    default_location = "창원시 마산회원구 회원2동"
    tags_extra = ["마산회원구", "회원2동", "읍면동", "생활정보"]


class MasanmemberSeokjeonNewsAdapter(MasanmemberSubdistrictNewsAdapter):
    parser_version = "masanmember_seokjeon_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12105/12208.web?gcode=1417"
    default_location = "창원시 마산회원구 석전동"
    tags_extra = ["마산회원구", "석전동", "읍면동", "생활정보"]


class MasanmemberHoeseongNewsAdapter(MasanmemberSubdistrictNewsAdapter):
    parser_version = "masanmember_hoeseong_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12106/12222.web?gcode=1417"
    default_location = "창원시 마산회원구 회성동"
    tags_extra = ["마산회원구", "회성동", "읍면동", "생활정보"]


class MasanmemberYangdeok1NewsAdapter(MasanmemberSubdistrictNewsAdapter):
    """Official Changwon portal: Masan Hoewon-gu Yangdeok 1-dong news."""

    parser_version = "masanmember_yangdeok1_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12107/12238.web?gcode=1417"
    default_location = "창원시 마산회원구 양덕1동"
    tags_extra = ["마산회원구", "양덕1동", "읍면동", "생활정보"]


class MasanmemberYangdeok2NewsAdapter(MasanmemberSubdistrictNewsAdapter):
    """Official Changwon portal: Masan Hoewon-gu Yangdeok 2-dong news."""

    parser_version = "masanmember_yangdeok2_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12108/12255.web?gcode=1417"
    default_location = "창원시 마산회원구 양덕2동"
    tags_extra = ["마산회원구", "양덕2동", "읍면동", "생활정보"]


class MasanmemberHapseong1NewsAdapter(MasanmemberSubdistrictNewsAdapter):
    """Official Changwon portal: Masan Hoewon-gu Hapseong 1-dong news."""

    parser_version = "masanmember_hapseong1_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12109/12269.web?gcode=1417"
    default_location = "창원시 마산회원구 합성1동"
    tags_extra = ["마산회원구", "합성1동", "읍면동", "생활정보"]


class MasanmemberHapseong2NewsAdapter(MasanmemberSubdistrictNewsAdapter):
    """Official Changwon portal: Masan Hoewon-gu Hapseong 2-dong news."""

    parser_version = "masanmember_hapseong2_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12110/12283.web?gcode=1417"
    default_location = "창원시 마산회원구 합성2동"
    tags_extra = ["마산회원구", "합성2동", "읍면동", "생활정보"]


class MasanmemberGuam1NewsAdapter(MasanmemberSubdistrictNewsAdapter):
    """Official Changwon portal: Masan Hoewon-gu Guam 1-dong news."""

    parser_version = "masanmember_guam1_news_v1"
    list_url = "https://www.changwon.go.kr/cwportal/gu/11100/12111/12297.web?gcode=1417"
    default_location = "창원시 마산회원구 구암1동"
    tags_extra = ["마산회원구", "구암1동", "읍면동", "생활정보"]

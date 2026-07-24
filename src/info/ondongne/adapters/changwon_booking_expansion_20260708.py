from __future__ import annotations

from .changwon_booking import ChangwonBookingAdapter


class MasanLiteratureBookingAdapter(ChangwonBookingAdapter):
    """창원시 일상플러스 통합예약 - 마산문학관 문예강좌."""

    parser_version = "masan_literature_booking_v1"


class MasanMusicHallBookingAdapter(ChangwonBookingAdapter):
    """창원시 일상플러스 통합예약 - 마산음악관 음악교양대학."""

    parser_version = "masan_music_hall_booking_v1"


class ChangwonHumanitiesBookingAdapter(ChangwonBookingAdapter):
    """창원시 일상플러스 통합예약 - 인문도시지원사업 강연/탐방."""

    parser_version = "changwon_humanities_booking_v1"


class ChangwonCitizenExperienceBookingAdapter(ChangwonBookingAdapter):
    """창원시 일상플러스 통합예약 - 시민체험프로그램."""

    parser_version = "changwon_citizen_experience_booking_v1"


class HaengamArtBookingAdapter(ChangwonBookingAdapter):
    """창원시 일상플러스 통합예약 - 행암문예마루 프로그램."""

    parser_version = "haengam_art_booking_v1"

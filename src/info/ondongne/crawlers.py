from .crawler_base import GenericBoardCrawler


class ChangwonCityRecruitCrawler(GenericBoardCrawler):
    pass


class ChangwonCityCalendarCrawler(GenericBoardCrawler):
    pass


class ChangwonBookingCrawler(GenericBoardCrawler):
    pass


class ChangwonCultureFoundationCrawler(GenericBoardCrawler):
    pass


class ChangwonFacilitiesCrawler(GenericBoardCrawler):
    pass


class ChangwonChamberCrawler(GenericBoardCrawler):
    pass


class ChangwonLibraryCrawler(GenericBoardCrawler):
    pass


class GyeongnamChangwonLibraryCrawler(GenericBoardCrawler):
    pass


class ChangwonWelfareFoundationCrawler(GenericBoardCrawler):
    pass


class ChangwonRehabCenterCrawler(GenericBoardCrawler):
    pass


CRAWLER_CLASS_BY_SOURCE_ID = {
    "changwon_city_recruit": ChangwonCityRecruitCrawler,
    "changwon_city_calendar": ChangwonCityCalendarCrawler,
    "changwon_booking": ChangwonBookingCrawler,
    "changwon_culture_foundation": ChangwonCultureFoundationCrawler,
    "changwon_facilities": ChangwonFacilitiesCrawler,
    "changwon_chamber": ChangwonChamberCrawler,
    "changwon_library": ChangwonLibraryCrawler,
    "gyeongnam_changwon_library": GyeongnamChangwonLibraryCrawler,
    "changwon_welfare_foundation": ChangwonWelfareFoundationCrawler,
    "changwon_rehab_center": ChangwonRehabCenterCrawler,
}

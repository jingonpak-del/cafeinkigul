from __future__ import annotations

import argparse
from pathlib import Path

from .adapters.bonglim_youth_center import BonglimYouthCenterAdapter
from .adapters.changwon_booking import ChangwonBookingAdapter
from .adapters.changwon_booking_expansion_20260708 import (
    ChangwonCitizenExperienceBookingAdapter,
    ChangwonHumanitiesBookingAdapter,
    HaengamArtBookingAdapter,
    MasanLiteratureBookingAdapter,
    MasanMusicHallBookingAdapter,
)
from .adapters.changwon_daily_expansion_20260710 import (
    BurimCraftVillageNoticeAdapter,
    ChangdongArtVillageNoticeAdapter,
    JinhaeDreamParkNoticeAdapter,
    MasanFamilyCenterAdapter,
    RobotLandExperienceAdapter,
)
from .adapters.changwon_subdistrict_news_20260711 import (
    UichangBukmyeonNewsAdapter,
    UichangDaesanNewsAdapter,
    UichangDongeupNewsAdapter,
    UichangPallyongNewsAdapter,
    UichangUichangdongNewsAdapter,
)
from .adapters.changwon_masanhappo_subdistrict_news_20260712 import (
    MasanhappoGusanNewsAdapter,
    MasanhappoHyeondongNewsAdapter,
    MasanhappoJinbukNewsAdapter,
    MasanhappoJindongNewsAdapter,
    MasanhappoJinjeonNewsAdapter,
)
from .adapters.changwon_masanhappo_subdistrict_news_20260717 import (
    MasanhappoBanwolJungangNewsAdapter,
    MasanhappoGapoNewsAdapter,
    MasanhappoMunhwaNewsAdapter,
    MasanhappoWanwolNewsAdapter,
    MasanhappoWolyeongNewsAdapter,
)
from .adapters.changwon_jinhae_subdistrict_news_20260718 import (
    JinhaeByeongamNewsAdapter,
    JinhaeChungmuNewsAdapter,
    JinhaeGyeonghwaNewsAdapter,
    JinhaeTaebaekNewsAdapter,
    JinhaeYeojaNewsAdapter,
)
from .adapters.changwon_jinhae_subdistrict_news_20260719 import (
    JinhaeDeoksanNewsAdapter,
    JinhaeIdongNewsAdapter,
    JinhaeJaeunNewsAdapter,
    JinhaePunghoNewsAdapter,
    JinhaeUngcheonNewsAdapter,
)
from .adapters.changwon_masanmember_subdistrict_news_20260713 import (
    MasanmemberGuam1NewsAdapter,
    MasanmemberHapseong1NewsAdapter,
    MasanmemberHapseong2NewsAdapter,
    MasanmemberHoeseongNewsAdapter,
    MasanmemberHoewon1NewsAdapter,
    MasanmemberHoewon2NewsAdapter,
    MasanmemberNaeseoNewsAdapter,
    MasanmemberSeokjeonNewsAdapter,
    MasanmemberYangdeok1NewsAdapter,
    MasanmemberYangdeok2NewsAdapter,
)
from .adapters.changwon_remaining_subdistrict_news_20260721 import (
    MasanmemberBongamNewsAdapter,
    MasanmemberGuam2NewsAdapter,
    SeongsanSeongjuNewsAdapter,
    SeongsanUngnamNewsAdapter,
    SeongsanYongjiNewsAdapter,
)
from .adapters.changwon_seongsan_subdistrict_news_20260714 import (
    SeongsanBansongNewsAdapter,
    SeongsanGaeumjeongNewsAdapter,
    SeongsanJungangNewsAdapter,
    SeongsanSangnamNewsAdapter,
    SeongsanSapaNewsAdapter,
)
from .adapters.changwon_chamber import ChangwonChamberAdapter
from .adapters.changwon_city_calendar import ChangwonCityCalendarAdapter
from .adapters.changwon_city_recruit import ChangwonCityRecruitAdapter
from .adapters.changwon_culture_foundation import ChangwonCultureFoundationAdapter
from .adapters.changwon_facilities import ChangwonFacilitiesAdapter
from .adapters.changwon_family_center import ChangwonFamilyCenterAdapter
from .adapters.changwon_library import ChangwonLibraryAdapter
from .adapters.changwon_daily_expansion_20260616 import (
    ChangwonDisabledParentsAssociationAdapter,
    ChangwonIndependentLivingCenterAdapter,
    ChangwonScienceGiftedEducationCenterAdapter,
    ChangwonSocialWelfareCenterAdapter,
    ChangwonWomenWorkCenterAdapter,
    JinhaeWestSeniorWelfareCenterAdapter,
)
from .adapters.changwon_daily_expansion_20260617 import (
    BonglimYouthTrainingCenterAdapter,
    ChangwonIndustryPromotionAdapter,
    ChangwonMigrantWorkerCenterAdapter,
    ChangwonRuralCommunityCenterAdapter,
    JinhaeSeniorWelfareCenterAdapter,
)
from .adapters.changwon_daily_expansion_20260619 import (
    ChangwonLifelongLearningNoticeAdapter,
    ChangwonLifelongLearningOrgNewsAdapter,
    ChangwonUniversityLifelongAdapter,
    MasanUniversityLifelongAdapter,
    MasanUniversityOpenCourseAdapter,
)
from .adapters.changwon_city_public_boards_20260620 import (
    ChangwonHealthCenterNewsAdapter,
    ChangwonMasanWomenHallAdapter,
    ChangwonOutOfSchoolYouthCenterAdapter,
    ChangwonVolunteerCenterAdapter,
    ChangwonYouthCounselingCenterAdapter,
)
from .adapters.changwon_culture_ecology_20260623 import (
    ChangwonForestHealingAdapter,
    JunamReservoirEcologyAdapter,
    MasanLiteratureMuseumProgramAdapter,
    MasanMuseumProgramAdapter,
    MasanMusicHallProgramAdapter,
)
from .adapters.changwon_daily_expansion_20260622 import (
    ChangwonAgricultureEducationAdapter,
    JinhaeGunhangjeCultureAdapter,
    JinhaeHealthCenterNewsAdapter,
    MasanChrysanthemumFestivalAdapter,
    MasanHealthCenterNewsAdapter,
)
from .adapters.changwon_daily_expansion_20260624 import (
    ChangwonCommunitySecurityCouncilAdapter,
    ChangwonNationalUniversitySwAdapter,
    GyeongnamStartupTechAdapter,
    JinhaeDisabledSportsCenterAdapter,
    MasanDisabledWelfareCenterAdapter,
)
from .adapters.changwon_daily_expansion_20260625 import (
    ChangwonAddictionCenterAdapter,
    ChangwonDevelopmentDisabilityCenterAdapter,
    ChangwonTennisCenterAdapter,
    GyeongnamGlobalGameCenterAdapter,
    MasanSocialWelfareCenterAdapter,
)
from .adapters.changwon_daily_expansion_20260626 import (
    ChangwonArboretumAdapter,
    ChangwonEnvironmentEducationAdapter,
    ChangwonVolunteerRecruitmentAdapter,
    JinhaeModernHistoryTourAdapter,
    UngcheonCeramicsMuseumAdapter,
)
from .adapters.changwon_daily_expansion_20260627 import (
    ChangwonDemocracyNoticeAdapter,
    ChangwonMilitaryBandFestivalAdapter,
    ChangwonYmcaNoticeAdapter,
    ChangwonYwcaNoticeAdapter,
    GyeongnamCultureArtsNoticeAdapter,
)
from .adapters.changwon_regional_expansion_20260630 import (
    GndamoaNoticeAdapter,
    GndamoaRecruitAdapter,
    GndcNoticeAdapter,
    GnsinboSupportAdapter,
    GntpNoticeAdapter,
)
from .adapters.changwon_public_boards_20260701 import (
    ChangwonFoodSafetyNoticeAdapter,
    ChangwonPublicHygieneNoticeAdapter,
    ChangwonSelfSufficiencyNewsAdapter,
    ChangwonTransportPolicyNewsAdapter,
    ChangwonWaterSewerNewsAdapter,
)
from .adapters.changwon_social_support_20260702 import (
    ChangwonChildcareSupportCenterNoticeAdapter,
    ChangwonDisabledFamilySupportNoticeAdapter,
    ChangwonDisabledRightsCenterNoticeAdapter,
    ChangwonWomenAssociationNoticeAdapter,
    GyeongnamRegionalChildCenterNoticeAdapter,
)
from .adapters.changwon_public_interest_20260703 import (
    ChangwonMuseumNoticeAdapter,
    ChangwonSportsCouncilNoticeAdapter,
    GyeongnamMigrantSupportNoticeAdapter,
    JinhaeMentalHealthEventAdapter,
    JinhaeWomenWorkCenterNoticeAdapter,
)
from .adapters.changwon_culture_welfare_20260704 import (
    ChangwonGeneralSocialWelfareNoticeAdapter,
    JinhaeCultureCenterNoticeAdapter,
    JinhaeGeneralSocialWelfareNoticeAdapter,
    JinhaeYouthCenterHallNoticeAdapter,
    MasanCultureCenterNoticeAdapter,
)
from .adapters.changwon_culture_gallery_20260707 import (
    MasanLiteratureEventsAdapter,
    MasanLiteratureLectureAdapter,
    MasanLiteratureSpecialExhibitionAdapter,
    MasanMuseumEducationAdapter,
    MasanMuseumSpecialExhibitionAdapter,
)
from .adapters.changwon_daily_expansion_20260705 import (
    ChangwonCovidNewsAdapter,
    ChangwonVehicleRegistrationNewsAdapter,
    JinhaePortManagementNoticeAdapter,
    Masan315ArtHallNoticeAdapter,
    SeongsanArtHallNoticeAdapter,
)
from .adapters.changwon_ward_news_20260706 import (
    JinhaeWardNewsAdapter,
    MasanhappoWardNewsAdapter,
    MasanmemberWardNewsAdapter,
    SeongsanWardNewsAdapter,
    UichangWardNewsAdapter,
)
from .adapters.changwon_new_public_gnuboard import (
    ChangwonJinroCenterAdapter,
    ChangwonSocialEconomyCenterAdapter,
    GyeongnamContentKoreaLabAdapter,
    JinhaeDisabilityWelfareCenterAdapter,
    ModucoopAdapter,
)
from .adapters.changwon_public_extra_boards import (
    ChangwonSeniorClubAdapter,
    GyeongnamVolunteerCenterAdapter,
    JinhaeSeniorClubAdapter,
    MasanYwcaWomenCenterAdapter,
    SeongsanSeniorClubAdapter,
)
from .adapters.changwon_rehab_center import ChangwonRehabCenterAdapter
from .adapters.changwon_youth_sexuality_center import ChangwonYouthSexualityCenterAdapter
from .adapters.changwon_welfare_foundation import ChangwonWelfareFoundationAdapter
from .adapters.cwsisul_facility_sections import (
    BukmyeonDisabledParkgolfAdapter,
    BukmyeonGolfRangeAdapter,
    ChangwonFootballCenterAdapter,
    ChangwonIndoorSwimmingPoolAdapter,
    ChangwonInternationalShootingRangeAdapter,
    ChangwonSportsParkAdapter,
    CitizenSportsCenterAdapter,
    DaesanParkgolfAdapter,
    DeokdongTennisCourtAdapter,
    GamgyeWelfareCenterAdapter,
    GreenhallYouthCenterAdapter,
    JinhaeMarineParkAdapter,
    JinhaeSportsCenterAdapter,
    JinhaeYeojwaSportsCenterAdapter,
    JinhaeYouthCampAdapter,
    JindongWelfareCenterAdapter,
    MarineLeportsCenterAdapter,
    MasanMemberSportsCenterAdapter,
    MasanhappoSportsCenterAdapter,
    NaeseoSportsCenterAdapter,
    SeongsanSportsCenterAdapter,
    SpecialTransportServiceAdapter,
    UichangSportsCenterAdapter,
    UrinuriYouthCenterAdapter,
    YongwonSportsCenterAdapter,
)
from .adapters.gyeongnam_changwon_library import GyeongnamChangwonLibraryAdapter
from .adapters.gyeongnam_disabled_welfare import GyeongnamDisabledWelfareAdapter
from .adapters.gyeongnam_social_welfare import GyeongnamSocialWelfareAdapter
from .adapters.jinhae_youth_center import JinhaeYouthCenterAdapter
from .adapters.masanhappo_senior_welfare import MasanHappoSeniorWelfareAdapter
from .adapters.masan_senior_welfare import MasanSeniorWelfareAdapter
from .adapters.seongsan_senior_welfare import SeongsanSeniorWelfareAdapter
from .adapters.uichang_senior_welfare import UichangSeniorWelfareAdapter
from .crawlers import CRAWLER_CLASS_BY_SOURCE_ID
from .adapters.procurement.changwon_city_bid import ChangwonCityBidAdapter
from .adapters.procurement.cwcf_bid import ChangwonCultureFoundationBidAdapter
from .adapters.procurement.gimhae_city_notice import GimhaeCityNoticeAdapter
from .adapters.procurement.haman_county_notice import HamanCountyNoticeAdapter
from .adapters.procurement.momo365_bid import Momo365BidAdapter
from .adapters.public_call.gimhae_city_public_call import GimhaeCityPublicCallAdapter
from .discovery.institution_discovery import (
    make_seed_institutions,
    write_institutions_csv,
    write_institutions_json,
)
from .io_utils import load_sources, dedupe_events, write_json, write_csv
from .naver_cafe import make_daily_post
from .procurement_store import InstitutionStore, ProcurementStore
from .public_call_store import PublicCallStore
from .source_registry import build_registry, write_inventory
from .store import EventStore

ADAPTER_BY_SOURCE_ID = {
    "changwon_city_recruit": ChangwonCityRecruitAdapter,
    "changwon_city_calendar": ChangwonCityCalendarAdapter,
    "changwon_booking": ChangwonBookingAdapter,
    "changwon_culture_foundation": ChangwonCultureFoundationAdapter,
    "changwon_facilities": ChangwonFacilitiesAdapter,
    "changwon_family_center": ChangwonFamilyCenterAdapter,
    "changwon_chamber": ChangwonChamberAdapter,
    "changwon_library": ChangwonLibraryAdapter,
    "changwon_welfare_foundation": ChangwonWelfareFoundationAdapter,
    "gyeongnam_changwon_library": GyeongnamChangwonLibraryAdapter,
    "gyeongnam_social_welfare": GyeongnamSocialWelfareAdapter,
    "gyeongnam_disabled_welfare": GyeongnamDisabledWelfareAdapter,
    "changwon_rehab_center": ChangwonRehabCenterAdapter,
    "jinhae_youth_center": JinhaeYouthCenterAdapter,
    "bonglim_youth_center": BonglimYouthCenterAdapter,
    "masan_senior_welfare": MasanSeniorWelfareAdapter,
    "changwon_youth_sexuality_center": ChangwonYouthSexualityCenterAdapter,
    "seongsan_senior_welfare": SeongsanSeniorWelfareAdapter,
    "uichang_senior_welfare": UichangSeniorWelfareAdapter,
    "masanhappo_senior_welfare": MasanHappoSeniorWelfareAdapter,
    "urinuri_youth_center": UrinuriYouthCenterAdapter,
    "greenhall_youth_center": GreenhallYouthCenterAdapter,
    "jindong_welfare_center": JindongWelfareCenterAdapter,
    "gamgye_welfare_center": GamgyeWelfareCenterAdapter,
    "citizen_sports_center": CitizenSportsCenterAdapter,
    "naeseo_sports_center": NaeseoSportsCenterAdapter,
    "masanhappo_sports_center": MasanhappoSportsCenterAdapter,
    "seongsan_sports_center": SeongsanSportsCenterAdapter,
    "yongwon_sports_center": YongwonSportsCenterAdapter,
    "jinhae_sports_center": JinhaeSportsCenterAdapter,
    "marine_leports_center": MarineLeportsCenterAdapter,
    "masan_member_sports_center": MasanMemberSportsCenterAdapter,
    "jinhae_yeojwa_sports_center": JinhaeYeojwaSportsCenterAdapter,
    "changwon_football_center": ChangwonFootballCenterAdapter,
    "uichang_sports_center": UichangSportsCenterAdapter,
    "changwon_sports_park": ChangwonSportsParkAdapter,
    "changwon_indoor_swimming_pool": ChangwonIndoorSwimmingPoolAdapter,
    "deokdong_tennis_court": DeokdongTennisCourtAdapter,
    "jinhae_marine_park": JinhaeMarineParkAdapter,
    "jinhae_youth_camp": JinhaeYouthCampAdapter,
    "bukmyeon_disabled_parkgolf": BukmyeonDisabledParkgolfAdapter,
    "daesan_parkgolf": DaesanParkgolfAdapter,
    "changwon_international_shooting_range": ChangwonInternationalShootingRangeAdapter,
    "bukmyeon_golf_range": BukmyeonGolfRangeAdapter,
    "special_transport_service": SpecialTransportServiceAdapter,
    "changwon_jinro_center": ChangwonJinroCenterAdapter,
    "changwon_social_economy_center": ChangwonSocialEconomyCenterAdapter,
    "moducoop": ModucoopAdapter,
    "jinhae_disability_welfare_center": JinhaeDisabilityWelfareCenterAdapter,
    "gyeongnam_content_korea_lab": GyeongnamContentKoreaLabAdapter,
    "changwon_senior_club": ChangwonSeniorClubAdapter,
    "masan_ywca_women_center": MasanYwcaWomenCenterAdapter,
    "gyeongnam_volunteer_center": GyeongnamVolunteerCenterAdapter,
    "jinhae_senior_club": JinhaeSeniorClubAdapter,
    "seongsan_senior_club": SeongsanSeniorClubAdapter,
    "changwon_disabled_parents_association": ChangwonDisabledParentsAssociationAdapter,
    "changwon_independent_living_center": ChangwonIndependentLivingCenterAdapter,
    "changwon_science_gifted_education_center": ChangwonScienceGiftedEducationCenterAdapter,
    "jinhae_west_senior_welfare_center": JinhaeWestSeniorWelfareCenterAdapter,
    "changwon_women_work_center": ChangwonWomenWorkCenterAdapter,
    "changwon_industry_promotion": ChangwonIndustryPromotionAdapter,
    "bonglim_youth_training_center": BonglimYouthTrainingCenterAdapter,
    "jinhae_senior_welfare_center": JinhaeSeniorWelfareCenterAdapter,
    "changwon_rural_community_center": ChangwonRuralCommunityCenterAdapter,
    "changwon_migrant_worker_center": ChangwonMigrantWorkerCenterAdapter,
    "changwon_lifelong_learning_notice": ChangwonLifelongLearningNoticeAdapter,
    "changwon_lifelong_learning_org_news": ChangwonLifelongLearningOrgNewsAdapter,
    "changwon_univ_lifelong": ChangwonUniversityLifelongAdapter,
    "masan_univ_lifelong": MasanUniversityLifelongAdapter,
    "masan_univ_open_course": MasanUniversityOpenCourseAdapter,
    "changwon_youth_counseling_center": ChangwonYouthCounselingCenterAdapter,
    "changwon_out_of_school_youth_center": ChangwonOutOfSchoolYouthCenterAdapter,
    "changwon_volunteer_center": ChangwonVolunteerCenterAdapter,
    "changwon_masan_women_hall": ChangwonMasanWomenHallAdapter,
    "changwon_health_center_news": ChangwonHealthCenterNewsAdapter,
    "masan_health_center_news": MasanHealthCenterNewsAdapter,
    "jinhae_health_center_news": JinhaeHealthCenterNewsAdapter,
    "changwon_agriculture_education": ChangwonAgricultureEducationAdapter,
    "jinhae_gunhangje_culture": JinhaeGunhangjeCultureAdapter,
    "masan_chrysanthemum_festival": MasanChrysanthemumFestivalAdapter,
    "changwon_forest_healing": ChangwonForestHealingAdapter,
    "junam_reservoir_ecology": JunamReservoirEcologyAdapter,
    "masan_museum_program": MasanMuseumProgramAdapter,
    "masan_music_hall_program": MasanMusicHallProgramAdapter,
    "masan_literature_museum_program": MasanLiteratureMuseumProgramAdapter,
    "changwon_community_security_council": ChangwonCommunitySecurityCouncilAdapter,
    "gyeongnam_startup_tech": GyeongnamStartupTechAdapter,
    "changwon_national_university_sw": ChangwonNationalUniversitySwAdapter,
    "masan_disabled_welfare_center": MasanDisabledWelfareCenterAdapter,
    "jinhae_disabled_sports_center": JinhaeDisabledSportsCenterAdapter,
    "masan_social_welfare_center": MasanSocialWelfareCenterAdapter,
    "changwon_addiction_center": ChangwonAddictionCenterAdapter,
    "changwon_development_disability_center": ChangwonDevelopmentDisabilityCenterAdapter,
    "gyeongnam_global_game_center": GyeongnamGlobalGameCenterAdapter,
    "changwon_tennis_center": ChangwonTennisCenterAdapter,
    "changwon_arboretum": ChangwonArboretumAdapter,
    "ungcheon_ceramics_museum": UngcheonCeramicsMuseumAdapter,
    "jinhae_modern_history_tour": JinhaeModernHistoryTourAdapter,
    "changwon_environment_education": ChangwonEnvironmentEducationAdapter,
    "changwon_volunteer_recruitment": ChangwonVolunteerRecruitmentAdapter,
    "changwon_military_band_festival": ChangwonMilitaryBandFestivalAdapter,
    "changwon_democracy_notice": ChangwonDemocracyNoticeAdapter,
    "changwon_ymca_notice": ChangwonYmcaNoticeAdapter,
    "changwon_ywca_notice": ChangwonYwcaNoticeAdapter,
    "gyeongnam_culture_arts_notice": GyeongnamCultureArtsNoticeAdapter,
    "gndamoa_recruit": GndamoaRecruitAdapter,
    "gndamoa_notice": GndamoaNoticeAdapter,
    "gntp_notice": GntpNoticeAdapter,
    "gnsinbo_support": GnsinboSupportAdapter,
    "gndc_notice": GndcNoticeAdapter,
    "changwon_transport_policy_news": ChangwonTransportPolicyNewsAdapter,
    "changwon_self_sufficiency_news": ChangwonSelfSufficiencyNewsAdapter,
    "changwon_food_safety_notice": ChangwonFoodSafetyNoticeAdapter,
    "changwon_public_hygiene_notice": ChangwonPublicHygieneNoticeAdapter,
    "changwon_water_sewer_news": ChangwonWaterSewerNewsAdapter,
    "changwon_women_association_notice": ChangwonWomenAssociationNoticeAdapter,
    "changwon_disabled_family_support_notice": ChangwonDisabledFamilySupportNoticeAdapter,
    "changwon_disabled_rights_center_notice": ChangwonDisabledRightsCenterNoticeAdapter,
    "gyeongnam_regional_child_center_notice": GyeongnamRegionalChildCenterNoticeAdapter,
    "changwon_childcare_support_center_notice": ChangwonChildcareSupportCenterNoticeAdapter,
    "jinhae_mental_health_event": JinhaeMentalHealthEventAdapter,
    "jinhae_women_work_center_notice": JinhaeWomenWorkCenterNoticeAdapter,
    "gyeongnam_migrant_support_notice": GyeongnamMigrantSupportNoticeAdapter,
    "changwon_museum_notice": ChangwonMuseumNoticeAdapter,
    "changwon_sports_council_notice": ChangwonSportsCouncilNoticeAdapter,
    "changwon_general_social_welfare_notice": ChangwonGeneralSocialWelfareNoticeAdapter,
    "jinhae_general_social_welfare_notice": JinhaeGeneralSocialWelfareNoticeAdapter,
    "jinhae_culture_center_notice": JinhaeCultureCenterNoticeAdapter,
    "masan_culture_center_notice": MasanCultureCenterNoticeAdapter,
    "jinhae_youth_center_hall_notice": JinhaeYouthCenterHallNoticeAdapter,
    "changwon_vehicle_registration_news": ChangwonVehicleRegistrationNewsAdapter,
    "jinhae_port_management_notice": JinhaePortManagementNoticeAdapter,
    "changwon_covid_news": ChangwonCovidNewsAdapter,
    "seongsan_art_hall_notice": SeongsanArtHallNoticeAdapter,
    "masan_315_art_hall_notice": Masan315ArtHallNoticeAdapter,
    "uichang_ward_news": UichangWardNewsAdapter,
    "seongsan_ward_news": SeongsanWardNewsAdapter,
    "masanhappo_ward_news": MasanhappoWardNewsAdapter,
    "masanmember_ward_news": MasanmemberWardNewsAdapter,
    "jinhae_ward_news": JinhaeWardNewsAdapter,
    "masan_museum_education": MasanMuseumEducationAdapter,
    "masan_museum_special_exhibition": MasanMuseumSpecialExhibitionAdapter,
    "masan_literature_special_exhibition": MasanLiteratureSpecialExhibitionAdapter,
    "masan_literature_lecture": MasanLiteratureLectureAdapter,
    "masan_literature_events": MasanLiteratureEventsAdapter,
    "masan_literature_booking": MasanLiteratureBookingAdapter,
    "masan_music_hall_booking": MasanMusicHallBookingAdapter,
    "changwon_humanities_booking": ChangwonHumanitiesBookingAdapter,
    "changwon_citizen_experience_booking": ChangwonCitizenExperienceBookingAdapter,
    "haengam_art_booking": HaengamArtBookingAdapter,
    "robot_land_experience": RobotLandExperienceAdapter,
    "jinhae_dreampark_notice": JinhaeDreamParkNoticeAdapter,
    "masan_family_center": MasanFamilyCenterAdapter,
    "changdong_art_village_notice": ChangdongArtVillageNoticeAdapter,
    "burim_craft_village_notice": BurimCraftVillageNoticeAdapter,
    "uichang_dongeup_news": UichangDongeupNewsAdapter,
    "uichang_bukmyeon_news": UichangBukmyeonNewsAdapter,
    "uichang_daesan_news": UichangDaesanNewsAdapter,
    "uichang_uichangdong_news": UichangUichangdongNewsAdapter,
    "uichang_pallyong_news": UichangPallyongNewsAdapter,
    "masanhappo_gusan_news": MasanhappoGusanNewsAdapter,
    "masanhappo_jindong_news": MasanhappoJindongNewsAdapter,
    "masanhappo_jinbuk_news": MasanhappoJinbukNewsAdapter,
    "masanhappo_jinjeon_news": MasanhappoJinjeonNewsAdapter,
    "masanhappo_hyeondong_news": MasanhappoHyeondongNewsAdapter,
    "masanhappo_gapo_news": MasanhappoGapoNewsAdapter,
    "masanhappo_wolyeong_news": MasanhappoWolyeongNewsAdapter,
    "masanhappo_munhwa_news": MasanhappoMunhwaNewsAdapter,
    "masanhappo_banwoljungang_news": MasanhappoBanwolJungangNewsAdapter,
    "masanhappo_wanwol_news": MasanhappoWanwolNewsAdapter,
    "jinhae_chungmu_news": JinhaeChungmuNewsAdapter,
    "jinhae_yeoja_news": JinhaeYeojaNewsAdapter,
    "jinhae_taebaek_news": JinhaeTaebaekNewsAdapter,
    "jinhae_gyeonghwa_news": JinhaeGyeonghwaNewsAdapter,
    "jinhae_byeongam_news": JinhaeByeongamNewsAdapter,
    "jinhae_idong_news": JinhaeIdongNewsAdapter,
    "jinhae_jaeun_news": JinhaeJaeunNewsAdapter,
    "jinhae_deoksan_news": JinhaeDeoksanNewsAdapter,
    "jinhae_pungho_news": JinhaePunghoNewsAdapter,
    "jinhae_ungcheon_news": JinhaeUngcheonNewsAdapter,
    "masanmember_naeseo_news": MasanmemberNaeseoNewsAdapter,
    "masanmember_hoewon1_news": MasanmemberHoewon1NewsAdapter,
    "masanmember_hoewon2_news": MasanmemberHoewon2NewsAdapter,
    "masanmember_seokjeon_news": MasanmemberSeokjeonNewsAdapter,
    "masanmember_hoeseong_news": MasanmemberHoeseongNewsAdapter,
    "masanmember_yangdeok1_news": MasanmemberYangdeok1NewsAdapter,
    "masanmember_yangdeok2_news": MasanmemberYangdeok2NewsAdapter,
    "masanmember_hapseong1_news": MasanmemberHapseong1NewsAdapter,
    "masanmember_hapseong2_news": MasanmemberHapseong2NewsAdapter,
    "masanmember_guam1_news": MasanmemberGuam1NewsAdapter,
    "masanmember_guam2_news": MasanmemberGuam2NewsAdapter,
    "masanmember_bongam_news": MasanmemberBongamNewsAdapter,
    "seongsan_bansong_news": SeongsanBansongNewsAdapter,
    "seongsan_jungang_news": SeongsanJungangNewsAdapter,
    "seongsan_sangnam_news": SeongsanSangnamNewsAdapter,
    "seongsan_sapa_news": SeongsanSapaNewsAdapter,
    "seongsan_gaeumjeong_news": SeongsanGaeumjeongNewsAdapter,
    "seongsan_yongji_news": SeongsanYongjiNewsAdapter,
    "seongsan_seongju_news": SeongsanSeongjuNewsAdapter,
    "seongsan_ungnam_news": SeongsanUngnamNewsAdapter,
}


PROCUREMENT_ADAPTER_BY_SOURCE_ID = {
    "changwon_city_bid": ChangwonCityBidAdapter,
    "changwon_city_bid_candidates": ChangwonCityBidAdapter,
    "changwon_culture_foundation_bid": ChangwonCultureFoundationBidAdapter,
    "gimhae_city_notice": GimhaeCityNoticeAdapter,
    "gimhae_city_bid_candidates": GimhaeCityNoticeAdapter,
    "haman_county_notice": HamanCountyNoticeAdapter,
    "haman_county_bid_candidates": HamanCountyNoticeAdapter,
    "momo365_gyeongnam_bid": Momo365BidAdapter,
}


PUBLIC_CALL_ADAPTER_BY_SOURCE_ID = {
    "gimhae_city_public_call": GimhaeCityPublicCallAdapter,
}


def _load_source(root: Path, source_id: str | None):
    sources = load_sources(root / "data/sources.json")
    if not source_id:
        return sources
    for source in sources:
        if source["id"] == source_id:
            return source
    raise SystemExit(f"Unknown source id: {source_id}")


def _crawl_source(source: dict, since_days: int = 30, limit: int = 100):
    adapter_cls = ADAPTER_BY_SOURCE_ID.get(source["id"])
    if adapter_cls:
        return adapter_cls(source).crawl(since_days=since_days, limit=limit)
    cls = CRAWLER_CLASS_BY_SOURCE_ID.get(source["id"])
    if not cls:
        print(f"WARN no crawler for {source['id']}")
        return []
    return cls(source).crawl(limit=limit)


def run_legacy(args):
    root = Path.cwd()
    sources = load_sources(root / args.sources)
    all_events = []

    for source in sources:
        events = _crawl_source(source, since_days=30, limit=args.limit)
        print(f"{source['id']}: {len(events)} events")
        all_events.extend(events)

    events = dedupe_events(all_events)
    out = root / args.output
    write_json(events, out / "events_latest.json")
    write_csv(events, out / "events_latest.csv")
    title, body = make_daily_post(events, args.region_name)
    (out / "naver_cafe_daily_post.md").write_text(f"# {title}\n\n{body}", encoding="utf-8")

    print(f"saved {len(events)} deduped events to {out}")
    print(f"naver cafe title: {title}")


def run_crawl(args):
    root = Path.cwd()
    source = _load_source(root, args.source)
    events = _crawl_source(source, since_days=args.since_days, limit=args.limit)
    out = root / args.output
    filename_base = f"{source['id']}_last_{args.since_days}_days"
    write_json(events, out / f"{filename_base}.json")
    write_csv(events, out / f"{filename_base}.csv")
    print(f"{source['id']}: saved {len(events)} events")
    if args.debug:
        for event in events[:10]:
            print(f"- {event.title} | app={event.application_start_date}~{event.application_end_date} | body={len(event.body_text)} | q={event.quality_score:.2f}")


def run_daily(args):
    root = Path.cwd()
    sources = _load_source(root, args.source) if args.source else _load_source(root, None)
    if isinstance(sources, dict):
        sources = [sources]
    all_events = []
    for source in sources:
        events = _crawl_source(source, since_days=args.since_days, limit=args.limit)
        print(f"{source['id']}: {len(events)} candidates")
        all_events.extend(events)
    events = dedupe_events(all_events)
    store = EventStore(root / "data/store/events_master.jsonl")
    result = store.upsert_many(events)
    daily = result.new_or_updated
    out = root / args.output
    write_json(daily, out / "events_daily_new.json")
    write_csv(daily, out / "events_daily_new.csv")
    write_json(events, out / "events_latest.json")
    write_csv(events, out / "events_latest.csv")
    title, body = make_daily_post(daily, args.region_name)
    (out / "naver_cafe_daily_post.md").write_text(f"# {title}\n\n{body}", encoding="utf-8")
    print(f"daily: candidates={len(events)} new={result.new_count} updated={result.updated_count} skipped={result.skipped_count}")


def _load_procurement_sources(root: Path, source_id: str | None):
    sources = load_sources(root / "data/procurement_sources.json")
    if not source_id:
        return sources
    for source in sources:
        if source["id"] == source_id:
            return source
    raise SystemExit(f"Unknown procurement source id: {source_id}")


def _load_public_call_sources(root: Path, source_id: str | None):
    sources = load_sources(root / "data/public_call_sources.json")
    if not source_id:
        return sources
    for source in sources:
        if source["id"] == source_id:
            return source
    raise SystemExit(f"Unknown public-call source id: {source_id}")


def _crawl_procurement_source(source: dict, since_days: int = 30, limit: int = 100):
    adapter_cls = PROCUREMENT_ADAPTER_BY_SOURCE_ID.get(source["id"])
    if adapter_cls:
        return adapter_cls(source).crawl(since_days=since_days, limit=limit)
    # Procurement source-specific adapters are added incrementally after discovery.
    # Sources marked candidate_only document institutions that still need hardening.
    print(f"WARN no procurement crawler for {source['id']} (status={source.get('status', 'unknown')})")
    return []


def _crawl_public_call_source(source: dict, since_days: int = 30, limit: int = 100):
    adapter_cls = PUBLIC_CALL_ADAPTER_BY_SOURCE_ID.get(source["id"])
    if adapter_cls:
        return adapter_cls(source).crawl(since_days=since_days, limit=limit)
    print(f"WARN no public-call crawler for {source['id']} (status={source.get('status', 'unknown')})")
    return []


def _write_procurement_digest(notices, path: Path, region_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {region_name} 행사 관련 입찰·공모·모집공고 일일 리포트", ""]
    if not notices:
        lines.append("신규/변경 공고가 없습니다.")
    for idx, notice in enumerate(notices, start=1):
        lines.extend([
            f"{idx}. [{notice.organization_name}] {notice.title}",
            f"   - 유형: {notice.notice_type}",
            f"   - 점수: {notice.relevance_score}",
            f"   - 마감: {notice.application_end_date or '미확인'}",
            f"   - 예산: {notice.budget or '미확인'}",
            f"   - 원문: {notice.source_url}",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def run_procurement_daily(args):
    root = Path.cwd()
    sources = _load_procurement_sources(root, args.source) if args.source else _load_procurement_sources(root, None)
    if isinstance(sources, dict):
        sources = [sources]
    all_notices = []
    for source in sources:
        notices = _crawl_procurement_source(source, since_days=args.since_days, limit=args.limit)
        print(f"{source['id']}: {len(notices)} procurement candidates")
        all_notices.extend(notices)
    store = ProcurementStore(root / "data/store/procurement_master.jsonl")
    result = store.upsert_many(all_notices)
    daily = result.new_or_updated
    out = root / args.output
    write_json(daily, out / "procurement_daily_new.json")
    write_csv(daily, out / "procurement_daily_new.csv")
    write_json(all_notices, out / "procurement_latest.json")
    write_csv(all_notices, out / "procurement_latest.csv")
    _write_procurement_digest(daily, out / "procurement_daily_digest.md", args.region_name)
    print(f"procurement daily: candidates={len(all_notices)} new={result.new_count} updated={result.updated_count} skipped={result.skipped_count}")


def run_public_call_daily(args):
    root = Path.cwd()
    sources = _load_public_call_sources(root, args.source) if args.source else _load_public_call_sources(root, None)
    if isinstance(sources, dict):
        sources = [sources]
    all_notices = []
    for source in sources:
        notices = _crawl_public_call_source(source, since_days=args.since_days, limit=args.limit)
        print(f"{source['id']}: {len(notices)} public-call candidates")
        all_notices.extend(notices)
    store = PublicCallStore(root / "data/store/public_call_master.jsonl")
    result = store.upsert_many(all_notices)
    daily = result.new_or_updated
    out = root / args.output
    write_json(daily, out / "public_call_daily_new.json")
    write_csv(daily, out / "public_call_daily_new.csv")
    write_json(all_notices, out / "public_call_latest.json")
    write_csv(all_notices, out / "public_call_latest.csv")
    _write_procurement_digest(daily, out / "public_call_daily_digest.md", args.region_name)
    print(f"public-call daily: candidates={len(all_notices)} new={result.new_count} updated={result.updated_count} skipped={result.skipped_count}")


def run_discover_institutions(args):
    root = Path.cwd()
    institutions = make_seed_institutions(args.regions, years=args.years)
    store = InstitutionStore(root / "data/store/institutions_master.jsonl")
    changed = store.upsert_many(institutions)
    out = root / args.output
    write_institutions_json(institutions, out / "institutions_discovered.json")
    write_institutions_csv(institutions, out / "institutions_discovered.csv")
    print(f"discover-institutions: candidates={len(institutions)} changed={len(changed)} output={out}")


def run_inventory_sources(args):
    """Export a read-only source-registry v2 inventory.

    This command deliberately does not alter existing source JSON files or daily
    crawling behavior.  It provides the audited baseline required before moving
    legacy sources onto the national-scale operational registry.
    """
    root = Path.cwd()
    records = build_registry(root)
    paths, summary = write_inventory(records, root / args.output)
    print(
        "inventory-sources: "
        f"sources={summary['total_sources']} "
        f"institutions={summary['total_institutions']} "
        f"stable={summary['by_lifecycle'].get('stable', 0)} "
        f"candidate={summary['by_lifecycle'].get('candidate', 0)}"
    )
    print(f"inventory json: {paths['json']}")
    print(f"inventory csv: {paths['csv']}")
    print(f"inventory summary: {paths['summary']}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    crawl = sub.add_parser("crawl")
    crawl.add_argument("--source", required=True)
    crawl.add_argument("--since-days", type=int, default=30)
    crawl.add_argument("--limit", type=int, default=100)
    crawl.add_argument("--output", default="output")
    crawl.add_argument("--debug", action="store_true")
    crawl.set_defaults(func=run_crawl)

    daily = sub.add_parser("daily")
    daily.add_argument("--source")
    daily.add_argument("--since-days", type=int, default=2)
    daily.add_argument("--limit", type=int, default=100)
    daily.add_argument("--output", default="output")
    daily.add_argument("--region-name", default="창원")
    daily.set_defaults(func=run_daily)

    procurement_daily = sub.add_parser("procurement-daily")
    procurement_daily.add_argument("--source")
    procurement_daily.add_argument("--since-days", type=int, default=2)
    procurement_daily.add_argument("--limit", type=int, default=100)
    procurement_daily.add_argument("--output", default="output")
    procurement_daily.add_argument("--region-name", default="창원·마산·진해·김해·함안")
    procurement_daily.set_defaults(func=run_procurement_daily)

    procurement_crawl = sub.add_parser("procurement-crawl")
    procurement_crawl.add_argument("--source", required=True)
    procurement_crawl.add_argument("--since-days", type=int, default=30)
    procurement_crawl.add_argument("--limit", type=int, default=100)
    procurement_crawl.add_argument("--output", default="output")
    procurement_crawl.add_argument("--region-name", default="창원·마산·진해·김해·함안")
    procurement_crawl.add_argument("--debug", action="store_true")
    procurement_crawl.set_defaults(func=run_procurement_daily)

    public_call_daily = sub.add_parser("public-call-daily")
    public_call_daily.add_argument("--source")
    public_call_daily.add_argument("--since-days", type=int, default=2)
    public_call_daily.add_argument("--limit", type=int, default=100)
    public_call_daily.add_argument("--output", default="output")
    public_call_daily.add_argument("--region-name", default="창원·마산·진해·김해·함안")
    public_call_daily.set_defaults(func=run_public_call_daily)

    discover = sub.add_parser("discover-institutions")
    discover.add_argument("--years", type=int, default=2)
    discover.add_argument("--regions", nargs="+", default=["창원", "마산", "진해", "김해", "함안"])
    discover.add_argument("--output", default="output")
    discover.set_defaults(func=run_discover_institutions)

    inventory = sub.add_parser("inventory-sources")
    inventory.add_argument("--output", default="output")
    inventory.set_defaults(func=run_inventory_sources)

    parser.add_argument("--sources", default="data/sources.json")
    parser.add_argument("--output", default="output")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--region-name", default="창원")
    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        run_legacy(args)


if __name__ == "__main__":
    main()

import re

CATEGORY_RULES = [
    ("취업창업", ["창업", "소상공", "기업", "상공", "취업", "일자리", "CEO", "실무"]),
    ("아동청소년", ["아동", "어린이", "초등", "청소년", "학부모", "가족", "동화"]),
    ("도서문화", ["도서", "독서", "책", "강연", "작가"]),
    ("문화", ["공연", "전시", "예술", "문화", "축제"]),
    ("복지건강", ["복지", "건강", "장애", "어르신", "노인", "가족휴식"]),
    ("교육", ["교육", "강좌", "수강", "특강", "평생학습", "세미나"]),
    ("모집공모", ["모집", "공모", "참여자", "신청"]),
]

AUDIENCE_RULES = [
    ("유아", ["유아", "미취학"]),
    ("초등", ["초등", "어린이"]),
    ("청소년", ["청소년", "중학생", "고등학생"]),
    ("청년", ["청년", "대학생"]),
    ("어르신", ["어르신", "노인", "시니어"]),
    ("가족", ["가족", "부모", "학부모"]),
    ("기업", ["기업", "소상공", "사업자", "CEO"]),
]

DATE_PATTERN = re.compile(r"(20\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})")


def classify_category(text: str, default: str = "기타") -> str:
    lower = text.lower()
    for category, words in CATEGORY_RULES:
        if any(w.lower() in lower for w in words):
            return category
    return default


def classify_audience(text: str) -> str:
    lower = text.lower()
    for audience, words in AUDIENCE_RULES:
        if any(w.lower() in lower for w in words):
            return audience
    return "전체"


def detect_price_type(text: str) -> str:
    if "무료" in text or "참가비 없음" in text or "수강료 없음" in text:
        return "무료"
    # Avoid treating place names such as 창원 as a price. Require a numeric amount or explicit paid wording.
    if "유료" in text or "수강료" in text or "참가비" in text or re.search(r"\d[\d,]*\s*원", text or ""):
        return "유료"
    return "미확인"


def extract_first_date(text: str):
    m = DATE_PATTERN.search(text)
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}"


def make_summary(title: str, source_name: str, category: str) -> str:
    return f"{source_name}에서 등록된 {category} 정보입니다. 자세한 일정과 신청 가능 여부는 원문을 확인하세요: {title}"

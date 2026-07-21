"""내용 기반 자동 분류 (온동네 플랫폼에서 이식).

출처 유형(정부/지자체/비영리 등)과는 다른 축인 **내용 주제**(topic)를 분류한다:
교육·문화·복지건강·모집공모·행사 등. 대상(audience)·가격유형도 추정.
config의 category(출처유형)는 그대로 두고, 자동분류 결과는 topic 필드로 채운다.
"""
from __future__ import annotations

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

# 행사·모집성 글(신청기간·대상이 의미있는 kind='event') 판별 키워드
EVENT_KEYWORDS = [
    "모집", "신청", "접수", "공모", "참가", "참여", "수강", "강좌", "교육", "프로그램",
    "행사", "축제", "공연", "전시", "체험", "특강", "설명회", "멘토링", "워크숍", "세미나",
]


def classify_category(text: str, default: str = "기타") -> str:
    lower = (text or "").lower()
    for category, words in CATEGORY_RULES:
        if any(w.lower() in lower for w in words):
            return category
    return default


def classify_audience(text: str) -> str:
    lower = (text or "").lower()
    for audience, words in AUDIENCE_RULES:
        if any(w.lower() in lower for w in words):
            return audience
    return "전체"


def detect_price_type(text: str) -> str:
    text = text or ""
    if "무료" in text or "참가비 없음" in text or "수강료 없음" in text:
        return "무료"
    # 지명(창원 등)을 가격으로 오인하지 않게 금액/유료 표현이 있을 때만 유료.
    if "유료" in text or "수강료" in text or "참가비" in text or re.search(r"\d[\d,]*\s*원", text):
        return "유료"
    return "미확인"


def is_event_like(text: str) -> bool:
    """제목/본문이 행사·모집성이면 True (kind 판별용)."""
    t = text or ""
    return any(k in t for k in EVENT_KEYWORDS)

"""내용 기반 자동 주제 분류.

출처 유형(정부/지자체/비영리 등)과는 다른 축인 **주제(topic)**를 8개로 분류한다.
행사·이벤트·교육은 필수 항목. 규칙은 위에서부터 검사하고 첫 매치가 이긴다(단일 라벨).
어디에도 안 맞으면 '기타'.
"""
from __future__ import annotations

import re

# 순서 = 우선순위. 내용형(교육) 이 행동형(모집)보다 앞 → "교육 수강생 모집"=교육.
TOPIC_RULES = [
    ("교육", ["교육", "강좌", "수강", "특강", "아카데미", "평생학습", "세미나", "워크숍",
             "워크샵", "연수", "클래스", "교실", "강습", "배움", "코딩", "체험학습"]),
    ("이벤트", ["이벤트", "경품", "추첨", "응모", "투표", "챌린지", "프로모션", "인증샷",
              "event", "사은", "룰렛", "퀴즈"]),
    ("행사", ["행사", "축제", "공연", "전시", "박람회", "설명회", "기념식", "페스티벌",
             "콘서트", "개막", "한마당", "대회", "공모전", "발표회", "품평회", "장터"]),
    ("모집·채용", ["채용", "구인", "모집", "공모", "참가자", "지원사업", "봉사자", "신청자",
                "선발", "입주", "구직", "일자리", "인턴", "수강생 모집", "위촉"]),
    ("복지·건강", ["복지", "건강", "의료", "병원", "보건", "방역", "감염병", "백신", "접종",
                "돌봄", "장애", "어르신", "노인", "임산부", "아동", "청소년", "상담",
                "급여", "수당", "바우처", "요양", "재활", "심리"]),
    ("문화·관광", ["문화", "예술", "미술", "음악", "관광", "여행", "여행지", "가볼만", "명소",
                "박물관", "도서관", "독서", "작가", "맛집", "둘레길", "생태", "숲"]),
    ("정책·경제", ["정책", "보도자료", "브리핑", "해명", "경제", "금융", "세금", "국세", "국채",
                "부동산", "창업", "기업", "산업", "예산", "투자", "수출", "통상", "고용",
                "농업", "환경", "기후", "에너지", "안전", "재난", "교통", "통계", "행정"]),
]

# 행사·모집성 주제(kind='event'로 취급) — '행사·모집만' 필터용
EVENT_TOPICS = {"교육", "이벤트", "행사", "모집·채용"}

AUDIENCE_RULES = [
    ("유아", ["유아", "미취학"]),
    ("초등", ["초등", "어린이"]),
    ("청소년", ["청소년", "중학생", "고등학생"]),
    ("청년", ["청년", "대학생"]),
    ("어르신", ["어르신", "노인", "시니어"]),
    ("가족", ["가족", "부모", "학부모"]),
    ("기업", ["기업", "소상공", "사업자", "CEO"]),
]


def classify_topic(text: str) -> str:
    """8개 주제 중 하나로 분류. 미매칭은 '기타'."""
    lower = (text or "").lower()
    for topic, words in TOPIC_RULES:
        if any(w.lower() in lower for w in words):
            return topic
    return "기타"


# 하위호환 별칭(기존 호출부)
def classify_category(text: str, default: str = "기타") -> str:
    t = classify_topic(text)
    return t if t != "기타" else default


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
    if "유료" in text or "수강료" in text or "참가비" in text or re.search(r"\d[\d,]*\s*원", text):
        return "유료"
    return "미확인"


def is_event_topic(topic: str) -> bool:
    return topic in EVENT_TOPICS


# 하위호환: 제목만으로 행사성 여부(주제 기반으로 판정)
def is_event_like(text: str) -> bool:
    return classify_topic(text) in EVENT_TOPICS

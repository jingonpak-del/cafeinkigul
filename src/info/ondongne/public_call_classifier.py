from __future__ import annotations

import re

POSITIVE_GROUPS = {
    "strong_public_call": {
        "score": 5,
        "terms": ["참가자 모집", "참여자 모집", "수강생 모집", "공모전", "작품공모", "부스 모집", "셀러 모집", "입주기업 모집"],
    },
    "program": {
        "score": 3,
        "terms": ["프로그램", "강좌", "교육", "아카데미", "체험", "특강", "워크숍", "행사", "축제", "공연", "전시"],
    },
    "support": {
        "score": 3,
        "terms": ["모집", "공모", "지원사업", "참여기업", "참여 단체", "제공기관", "대상자", "신청", "접수"],
    },
}

NEGATIVE_TERMS = [
    "채용", "최종합격", "서류 합격", "면접시험", "이장 모집", "통장 모집", "위원 모집", "선거관리위원",
    "도로", "하천", "CCTV", "원상회복", "공시송달", "자동차", "과태료", "의무보험", "도시계획시설",
    "농기계 임대료", "보청기", "청력검사", "산업단지 개발사업", "공유재산", "입찰", "용역", "제안서 평가위원",
]


def _contains(text: str, term: str) -> bool:
    return re.sub(r"\s+", "", term.lower()) in re.sub(r"\s+", "", (text or "").lower())


def score_public_call_text(text: str) -> dict:
    score = 0
    matched: list[str] = []
    negative: list[str] = []
    for group in POSITIVE_GROUPS.values():
        for term in group["terms"]:
            if _contains(text, term):
                score += int(group["score"])
                matched.append(term)
    for term in NEGATIVE_TERMS:
        if _contains(text, term):
            score -= 5 if term in {"채용", "최종합격", "이장 모집", "통장 모집", "공시송달", "자동차", "입찰", "용역"} else 3
            negative.append(term)
    decision = "collect" if score >= 5 else "candidate" if score >= 3 else "exclude"
    return {"score": score, "decision": decision, "matched_keywords": matched, "negative_keywords": negative}


def has_public_call_prefilter(text: str) -> bool:
    text = text or ""
    include = ["모집", "공모", "수강생", "참여자", "참가자", "지원사업", "아카데미", "강좌", "프로그램", "공모전", "입주기업"]
    return any(term in text for term in include)

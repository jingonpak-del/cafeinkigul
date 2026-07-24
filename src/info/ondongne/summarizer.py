from __future__ import annotations

import re

IMPORTANT_LABELS = ["일 시", "일시", "접수", "기간", "장 소", "장소", "대 상", "대상", "내용", "문의", "비용", "수강료"]


def clean_text(text: str) -> str:
    text = re.sub(r"\r|\t", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def summarize_event(title: str, body_text: str, max_sentences: int = 3) -> str:
    body = clean_text(body_text)
    if not body:
        return f"{title} 관련 모집/행사 정보입니다. 세부 내용은 원문을 확인하세요."

    # Split public-office style bullet text into meaningful chunks.
    chunks = re.split(r"(?:■|○|\\n|\n| - |ㆍ|\*)", body_text)
    picked: list[str] = []
    for raw in chunks:
        sent = clean_text(raw)
        if len(sent) < 8:
            continue
        if any(label in sent for label in IMPORTANT_LABELS):
            picked.append(sent)
        if len(picked) >= max_sentences:
            break

    if not picked:
        sentences = re.split(r"(?<=[.!?。])\s+", body)
        picked = [s for s in sentences if len(s) >= 8][:max_sentences]
    if not picked:
        picked = [body[:180]]
    return " ".join(picked)[:500]

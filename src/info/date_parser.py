"""한글 날짜·기간 파싱 (온동네 플랫폼에서 이식).

'2026.07.21', '2026년 7월 21일', '2026.7.1 ~ 7.5', '접수기간 2026.6.1~6.15' 등
다양한 표기를 안정적으로 파싱한다. 내부 표현은 'YYYY-MM-DD' 문자열.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

FULL_DATE_RE = re.compile(r"(20\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})")
SHORT_DATE_RE = re.compile(r"(\d{1,2})[.\-/월\s]+(\d{1,2})")


@dataclass
class DateRange:
    start: str | None = None
    end: str | None = None


def normalize_date(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_first_date(text: str) -> str | None:
    m = FULL_DATE_RE.search(text or "")
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    return normalize_date(y, mo, d)


def parse_date_range(text: str) -> DateRange:
    text = text or ""
    first = FULL_DATE_RE.search(text)
    if not first:
        return DateRange()
    y1, m1, d1 = map(int, first.groups())
    start = normalize_date(y1, m1, d1)
    tail = text[first.end():]
    if "~" not in tail:
        return DateRange(start=start, end=start)
    after_tilde = tail.split("~", 1)[1]
    full_end = FULL_DATE_RE.search(after_tilde)
    if full_end:
        y2, m2, d2 = map(int, full_end.groups())
        return DateRange(start=start, end=normalize_date(y2, m2, d2))
    short_end = SHORT_DATE_RE.search(after_tilde)
    if short_end:
        m2, d2 = map(int, short_end.groups())
        return DateRange(start=start, end=normalize_date(y1, m2, d2))
    return DateRange(start=start, end=start)


def is_within_days(date_text: str | None, days: int, now: datetime | None = None) -> bool:
    if not date_text:
        return True
    now = now or datetime.now()
    try:
        d = datetime.strptime(date_text[:10], "%Y-%m-%d")
    except ValueError:
        return True
    return d >= now - timedelta(days=days)


def extract_labeled_range(text: str, labels: list[str]) -> DateRange:
    text = re.sub(r"\s+", " ", text or "")
    for label in labels:
        idx = text.find(label)
        if idx >= 0:
            snippet = text[idx: idx + 160]
            rng = parse_date_range(snippet)
            if rng.start:
                return rng
    return DateRange()


def to_ms(date_str: str | None) -> int | None:
    """'YYYY-MM-DD' → epoch ms (자정 기준). posts 스키마 통합용."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def parse_first_ms(text: str) -> int | None:
    """텍스트에서 첫 날짜를 찾아 epoch ms로. 기존 collector 날짜 파싱 대체용."""
    return to_ms(parse_first_date(text))

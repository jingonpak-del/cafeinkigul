from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
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
            snippet = text[idx : idx + 160]
            rng = parse_date_range(snippet)
            if rng.start:
                return rng
    return DateRange()

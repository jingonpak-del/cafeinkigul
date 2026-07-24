from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional
import hashlib


@dataclass
class Event:
    source_id: str
    source_name: str
    organization_name: str
    region_level1: str
    region_level2: str
    title: str
    source_url: str
    category: str = "기타"
    summary: str = ""
    body_text: str = ""
    target_audience: str = "전체"
    region_level3: str = ""
    event_start_date: Optional[str] = None
    event_end_date: Optional[str] = None
    application_start_date: Optional[str] = None
    application_end_date: Optional[str] = None
    location_name: str = ""
    address: str = ""
    price_type: str = "미확인"
    price_amount: Optional[int] = None
    status: str = "검수필요"
    published_at: Optional[str] = None
    updated_at: Optional[str] = None
    apply_url: str = ""
    attachment_urls: list[str] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    content_hash: str = ""
    dedupe_key: str = ""
    quality_score: float = 0.0
    parser_version: str = "v1"
    id: str = ""

    def finalize(self) -> "Event":
        import re

        normalized_title = re.sub(r"\W+", "", self.title.lower())[:80]
        if not self.dedupe_key:
            self.dedupe_key = "|".join(
                [
                    self.source_id,
                    self.source_url or "",
                    normalized_title,
                    self.event_start_date or self.application_end_date or "",
                ]
            )
        raw = self.dedupe_key or f"{self.source_id}|{self.source_url}|{self.title}"
        self.id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        content_basis = self.title + self.summary + self.body_text
        self.content_hash = hashlib.sha1(content_basis.encode("utf-8")).hexdigest()
        if not self.apply_url:
            self.apply_url = self.source_url
        # Simple data completeness score for parser QA.
        checks = [self.title, self.source_url, self.body_text, self.summary, self.application_start_date or self.event_start_date]
        self.quality_score = sum(1 for value in checks if value) / len(checks)
        return self

    def to_dict(self):
        return asdict(self)

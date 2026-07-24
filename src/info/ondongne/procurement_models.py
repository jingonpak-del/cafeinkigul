from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional
import hashlib
import re


@dataclass
class NoticeAttachment:
    name: str
    url: str
    content_type: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DiscoveryEvidence:
    title: str
    url: str
    published_date: Optional[str] = None
    matched_keywords: list[str] = field(default_factory=list)
    score: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Institution:
    institution_id: str
    name: str
    region: str
    institution_type: str = ""
    homepage_url: str = ""
    notice_urls: list[dict] = field(default_factory=list)
    evidence: list[DiscoveryEvidence] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "candidate"
    last_verified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def finalize(self) -> "Institution":
        if not self.institution_id:
            self.institution_id = re.sub(r"\W+", "_", f"{self.region}_{self.name}".lower()).strip("_")
        if not self.confidence:
            self.confidence = min(1.0, 0.35 + len(self.evidence) * 0.15 + len(self.notice_urls) * 0.1)
        return self

    def to_dict(self) -> dict:
        row = asdict(self)
        row["evidence"] = [e.to_dict() if hasattr(e, "to_dict") else e for e in self.evidence]
        return row


@dataclass
class ProcurementNotice:
    source_id: str
    source_name: str
    organization_name: str
    region_level1: str
    region_level2: str
    title: str
    source_url: str
    notice_type: str = "입찰공모"
    summary: str = ""
    body_text: str = ""
    published_at: Optional[str] = None
    application_start_date: Optional[str] = None
    application_end_date: Optional[str] = None
    event_start_date: Optional[str] = None
    event_end_date: Optional[str] = None
    budget: str = ""
    location_name: str = ""
    target: str = ""
    apply_url: str = ""
    notice_number: str = ""
    attachments: list[NoticeAttachment] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    relevance_score: int = 0
    status: str = "검수필요"
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    content_hash: str = ""
    dedupe_key: str = ""
    quality_score: float = 0.0
    parser_version: str = "v1"
    id: str = ""

    def finalize(self) -> "ProcurementNotice":
        normalized_title = re.sub(r"\W+", "", self.title.lower())[:90]
        stable_ref = self.notice_number or self.source_url or ""
        date_ref = self.published_at or self.application_end_date or ""
        if not self.dedupe_key:
            self.dedupe_key = "|".join([self.source_id, stable_ref, normalized_title, date_ref])
        raw = self.dedupe_key or f"{self.source_id}|{self.source_url}|{self.title}"
        self.id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        attachment_basis = "|".join(a.name + a.url for a in self.attachments)
        content_basis = "|".join([
            self.title,
            self.summary,
            self.body_text,
            attachment_basis,
            self.application_end_date or "",
            self.budget,
        ])
        self.content_hash = hashlib.sha1(content_basis.encode("utf-8")).hexdigest()
        if not self.apply_url:
            self.apply_url = self.source_url
        checks = [
            self.title,
            self.source_url,
            self.body_text,
            self.summary,
            self.published_at or self.application_end_date,
            self.matched_keywords,
        ]
        self.quality_score = sum(1 for value in checks if value) / len(checks)
        return self

    def to_dict(self) -> dict:
        row = asdict(self)
        row["attachments"] = [a.to_dict() if hasattr(a, "to_dict") else a for a in self.attachments]
        return row

"""Nationwide source-registry normalization and inventory reporting.

The existing crawler uses separate JSON files for event, procurement, and public-call
sources.  This module reads those files without changing their runtime contract and
projects them into one operational registry suitable for incremental migration.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import csv
import json
from pathlib import Path
from typing import Any


COLLECTION_METHODS = {
    "official_api",
    "rss",
    "sitemap",
    "html",
    "xhr",
    "attachment_only",
    "manual",
}
LIFECYCLES = {"candidate", "validating", "stable", "degraded", "paused"}

TRACK_FILES = (
    ("events", "data/sources.json"),
    ("procurement", "data/procurement_sources.json"),
    ("public_call", "data/public_call_sources.json"),
)


@dataclass(frozen=True)
class SourceRegistryRecord:
    """Normalized operational representation of a legacy source configuration."""

    registry_id: str
    track: str
    source_id: str
    source_name: str
    institution_id: str
    organization_name: str
    region_level1: str
    region_level2: str
    region_detail: str
    category_hint: str
    base_url: str
    crawler_type: str
    collection_method: str
    lifecycle: str
    polling_tier: str
    detail_fetch_policy: str
    access_evidence: str
    notes: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def infer_collection_method(source: dict[str, Any]) -> str:
    """Return a conservative method classification without making network calls.

    Explicit migration metadata always wins.  Legacy sources otherwise default to
    HTML because that is the only collection path verified by their current config;
    names indicating a dynamic application are marked XHR for follow-up validation,
    not assumed to be a working API.
    """
    explicit = str(source.get("collection_method", "")).strip().lower()
    if explicit in COLLECTION_METHODS:
        return explicit

    haystack = " ".join(
        str(source.get(key, "")).lower()
        for key in ("crawler_type", "base_url", "notes")
    )
    if any(token in haystack for token in ("rss", "atom", "feed.xml", "/feed")):
        return "rss"
    if any(token in haystack for token in ("sitemap",)):
        return "sitemap"
    if any(token in haystack for token in ("dynamic", "xhr", "ajax", "spa", "csrf")):
        return "xhr"
    if any(token in haystack for token in ("attachment_only", "첨부파일")):
        return "attachment_only"
    return "html"


def normalize_lifecycle(source: dict[str, Any], track: str) -> str:
    raw = str(source.get("lifecycle") or source.get("status") or "").strip().lower()
    if raw in LIFECYCLES:
        return raw
    if raw in {"candidate_only", "seed_candidate", "discovery"} or "candidate" in raw:
        return "candidate"
    # Existing event sources have no lifecycle field but are active in the daily path.
    return "stable" if track == "events" else "candidate"


def _institution_id(source: dict[str, Any]) -> str:
    explicit = str(source.get("institution_id", "")).strip()
    if explicit:
        return explicit
    organization = str(source.get("organization_name", "unknown")).strip()
    region = str(source.get("region_level2", "")).strip()
    return f"{region}:{organization}" if region else organization


def _polling_tier(lifecycle: str) -> str:
    if lifecycle == "stable":
        return "daily"
    if lifecycle == "validating":
        return "validation"
    if lifecycle in {"degraded", "paused"}:
        return "paused"
    return "manual"


def make_registry_record(track: str, source: dict[str, Any]) -> SourceRegistryRecord:
    source_id = str(source["id"])
    lifecycle = normalize_lifecycle(source, track)
    return SourceRegistryRecord(
        registry_id=f"{track}:{source_id}",
        track=track,
        source_id=source_id,
        source_name=str(source.get("name", source_id)),
        institution_id=_institution_id(source),
        organization_name=str(source.get("organization_name", "")),
        region_level1=str(source.get("region_level1", "")),
        region_level2=str(source.get("region_level2", "")),
        region_detail=str(source.get("region_detail", "")),
        category_hint=str(source.get("category_hint", "")),
        base_url=str(source.get("base_url", "")),
        crawler_type=str(source.get("crawler_type", "")),
        collection_method=infer_collection_method(source),
        lifecycle=lifecycle,
        polling_tier=_polling_tier(lifecycle),
        detail_fetch_policy="on_change",
        access_evidence=str(source.get("access_evidence", "unverified")),
        notes=str(source.get("notes", "")),
    )


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"Expected a JSON list in {path}")
    return rows


def build_registry(root: Path) -> list[SourceRegistryRecord]:
    """Create a sorted registry from all configured source tracks.

    It is intentionally read-only: existing daily commands continue to use their
    present configuration files until a later migration wires them to this registry.
    """
    records: list[SourceRegistryRecord] = []
    for track, relative_path in TRACK_FILES:
        for source in _load_json_rows(root / relative_path):
            if "id" not in source:
                raise ValueError(f"Source without id in {relative_path}")
            records.append(make_registry_record(track, source))
    ids = [record.registry_id for record in records]
    if len(ids) != len(set(ids)):
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        raise ValueError(f"Duplicate registry ids: {', '.join(duplicates)}")
    return sorted(records, key=lambda record: (record.track, record.source_id))


def make_inventory_summary(records: list[SourceRegistryRecord]) -> dict[str, Any]:
    return {
        "total_sources": len(records),
        "total_institutions": len({record.institution_id for record in records}),
        "by_track": dict(sorted(Counter(record.track for record in records).items())),
        "by_collection_method": dict(sorted(Counter(record.collection_method for record in records).items())),
        "by_lifecycle": dict(sorted(Counter(record.lifecycle for record in records).items())),
        "by_polling_tier": dict(sorted(Counter(record.polling_tier for record in records).items())),
        "regions_level1": dict(sorted(Counter(record.region_level1 or "unclassified" for record in records).items())),
        "needs_access_review": sum(record.access_evidence == "unverified" for record in records),
    }


def write_inventory(records: list[SourceRegistryRecord], output_dir: Path) -> tuple[dict[str, Path], dict[str, Any]]:
    """Write JSON, spreadsheet-friendly CSV, and a machine-readable summary."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [record.to_dict() for record in records]
    summary = make_inventory_summary(records)
    paths = {
        "json": output_dir / "source_inventory.json",
        "csv": output_dir / "source_inventory.csv",
        "summary": output_dir / "source_inventory_summary.json",
    }
    paths["json"].write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["summary"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with paths["csv"].open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = list(SourceRegistryRecord.__dataclass_fields__)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return paths, summary

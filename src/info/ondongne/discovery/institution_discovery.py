from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import json
import re

from ..procurement_classifier import load_keyword_config, score_procurement_text
from ..procurement_models import DiscoveryEvidence, Institution


@dataclass
class DiscoverySeed:
    region: str
    query: str


def build_discovery_queries(regions: list[str], config: dict | None = None) -> list[DiscoverySeed]:
    config = config or load_keyword_config()
    templates = config.get("discovery_query_templates", [])
    seeds: list[DiscoverySeed] = []
    for region in regions:
        for template in templates:
            seeds.append(DiscoverySeed(region=region, query=template.format(region=region)))
    return seeds


def normalize_institution_id(region: str, name: str) -> str:
    token = re.sub(r"\W+", "_", f"{region}_{name}".lower()).strip("_")
    return token or "unknown_institution"


def make_seed_institutions(regions: list[str], years: int = 2, config: dict | None = None) -> list[Institution]:
    """Create deterministic discovery scaffolding.

    This does not pretend to have crawled the web. It creates region/query evidence
    rows that the next implementation step can feed into web/Nara/local board
    collectors while preserving the same output schema.
    """
    config = config or load_keyword_config()
    region_to_core_orgs = {
        "창원": ["창원특례시", "창원문화재단", "창원시설공단", "창원복지재단", "창원산업진흥원"],
        "마산": ["창원특례시 마산합포구", "창원특례시 마산회원구", "마산문화원", "마산회원노인종합복지관"],
        "진해": ["창원특례시 진해구", "진해문화원", "진해청소년수련관", "진해장애인복지관"],
        "김해": ["김해시", "김해문화재단", "김해문화관광재단", "김해시복지재단", "김해의생명산업진흥원"],
        "함안": ["함안군", "함안문화예술회관", "함안문화원", "함안군체육회", "함안군청소년수련관"],
    }
    queries = build_discovery_queries(regions, config=config)
    queries_by_region: dict[str, list[str]] = {}
    for seed in queries:
        queries_by_region.setdefault(seed.region, []).append(seed.query)

    institutions: list[Institution] = []
    for region in regions:
        for org in region_to_core_orgs.get(region, [f"{region} 지자체"]):
            evidence: list[DiscoveryEvidence] = []
            for query in queries_by_region.get(region, [])[:3]:
                scored = score_procurement_text(query, config)
                evidence.append(
                    DiscoveryEvidence(
                        title=f"최근 {years}년 후보 검색식: {query}",
                        url="",
                        matched_keywords=scored["matched_keywords"],
                        score=scored["score"],
                    )
                )
            institutions.append(
                Institution(
                    institution_id=normalize_institution_id(region, org),
                    name=org,
                    region=region,
                    institution_type="공공/유관기관 후보",
                    evidence=evidence,
                    status="seed_candidate",
                ).finalize()
            )
    return institutions


def write_institutions_json(institutions: list[Institution], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([i.to_dict() for i in institutions], ensure_ascii=False, indent=2), encoding="utf-8")


def write_institutions_csv(institutions: list[Institution], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for institution in institutions:
        rows.append({
            "institution_id": institution.institution_id,
            "name": institution.name,
            "region": institution.region,
            "institution_type": institution.institution_type,
            "homepage_url": institution.homepage_url,
            "evidence_count": len(institution.evidence),
            "confidence": institution.confidence,
            "status": institution.status,
            "last_verified_at": institution.last_verified_at,
        })
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

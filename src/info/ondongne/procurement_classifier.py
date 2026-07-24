from __future__ import annotations

from pathlib import Path
import json
import re

DEFAULT_CONFIG_PATH = Path("data/procurement_keywords.json")


def load_keyword_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        p = Path(__file__).resolve().parents[2] / "data" / "procurement_keywords.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _contains_term(text: str, term: str) -> bool:
    compact_text = re.sub(r"\s+", "", text.lower())
    compact_term = re.sub(r"\s+", "", term.lower())
    return compact_term in compact_text


def score_procurement_text(text: str, config: dict | None = None) -> dict:
    config = config or load_keyword_config()
    score = 0
    matched_positive: list[str] = []
    matched_negative: list[str] = []

    for group in config.get("positive_terms", {}).values():
        group_score = int(group.get("score", 0))
        for term in group.get("terms", []):
            if _contains_term(text, term):
                score += group_score
                matched_positive.append(term)

    for group in config.get("negative_terms", {}).values():
        group_score = int(group.get("score", 0))
        for term in group.get("terms", []):
            if _contains_term(text, term):
                score += group_score
                matched_negative.append(term)

    minimum = int(config.get("minimum_collect_score", 5))
    candidate = int(config.get("candidate_score", 3))
    if score >= minimum:
        decision = "collect"
    elif score >= candidate:
        decision = "candidate"
    else:
        decision = "exclude"

    return {
        "score": score,
        "decision": decision,
        "matched_keywords": matched_positive,
        "negative_keywords": matched_negative,
    }

from __future__ import annotations

import csv
import json
import re
from pathlib import Path


def load_sources(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def dedupe_events(events):
    seen = set()
    result = []
    for event in events:
        normalized_title = re.sub(r"\W+", "", event.title.lower())[:50]
        key = normalized_title + "|" + (event.event_start_date or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result


def write_json(events, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([e.to_dict() for e in events], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_csv(events, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [e.to_dict() for e in events]
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

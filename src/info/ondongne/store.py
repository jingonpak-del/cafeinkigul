from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from .models import Event


@dataclass
class UpsertResult:
    new_or_updated: list[Event]
    new_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0


class EventStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        rows: dict[str, dict] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rows[row.get("dedupe_key") or row["id"]] = row
        return rows

    def save_all(self, rows: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows.values())
        self.path.write_text(content + ("\n" if content else ""), encoding="utf-8")

    def upsert_many(self, events: list[Event]) -> UpsertResult:
        rows = self.load()
        result = UpsertResult(new_or_updated=[])
        for event in events:
            event.finalize()
            key = event.dedupe_key or event.id
            existing = rows.get(key)
            if not existing:
                rows[key] = event.to_dict()
                result.new_count += 1
                result.new_or_updated.append(event)
                continue
            if existing.get("content_hash") != event.content_hash:
                rows[key] = event.to_dict()
                result.updated_count += 1
                result.new_or_updated.append(event)
            else:
                result.skipped_count += 1
        self.save_all(rows)
        return result

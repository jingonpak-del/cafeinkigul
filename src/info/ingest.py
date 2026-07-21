"""수집 실행기 — config의 소스를 순회하며 수집·저장.

첫 등록(해당 소스의 저장된 글이 하나도 없을 때)은 default_window_days(기본 30일)
이내 글만 가져온다. 이후 실행은 피드에 있는 새 글을 증분 저장(중복 무시).

사용:
    python -m src.info.ingest            # 전체 소스 수집
    python -m src.info.ingest mltmkr     # id에 mltmkr 포함된 소스만
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import collectors
from .db import Database

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "info_sources.json"
DB_PATH = ROOT / "data" / "info.db"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def ingest_source(db: Database, source: dict, window_days: int) -> dict:
    """단일 소스 수집. 결과 요약 dict 반환.

    첫 등록: 최근 window_days 이내 글만. 이후(증분): 이미 저장된 최신 발행일보다
    새로운 글만 저장 → 과거 이력이 큰 피드(예: 1000건 RSS)를 백필하지 않음.
    """
    latest = db.latest_published(source["id"])
    first_time = latest is None
    posts = collectors.collect(source)
    fetched = len(posts)
    if first_time:
        posts = collectors.within_window(posts, window_days)
    else:
        posts = [p for p in posts if p["published_at"] is None or p["published_at"] > latest]
    inserted = sum(1 for p in posts if db.upsert_post(p))
    return {
        "id": source["id"],
        "name": source.get("name", source["id"]),
        "first_time": first_time,
        "fetched": fetched,
        "kept": len(posts),
        "inserted": inserted,
    }


def run(filter_str: str | None = None) -> list[dict]:
    cfg = load_config()
    window = int(cfg.get("default_window_days", 30))
    db = Database(DB_PATH)
    results = []
    try:
        for src in cfg.get("sources", []):
            if not src.get("enabled", True):
                continue
            if filter_str and filter_str not in src["id"]:
                continue
            try:
                res = ingest_source(db, src, window)
            except Exception as e:
                res = {"id": src["id"], "name": src.get("name", src["id"]), "error": str(e)}
            results.append(res)
    finally:
        db.close()
    return results


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    filt = sys.argv[1] if len(sys.argv) > 1 else None
    for r in run(filt):
        if "error" in r:
            print(f"[!] {r['name']} ({r['id']}) — 수집 실패: {r['error']}")
        else:
            tag = "첫등록" if r["first_time"] else "증분"
            print(f"[{tag}] {r['name']}: 피드 {r['fetched']}건 → "
                  f"창내 {r['kept']}건 → 신규저장 {r['inserted']}건")


if __name__ == "__main__":
    main()

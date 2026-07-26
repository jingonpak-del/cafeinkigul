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
from . import classify
from . import date_parser as dp
from .db import Database

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "info_sources.json"
DB_PATH = ROOT / "data" / "info.db"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


_APPLY_LABELS = ["신청기간", "접수기간", "모집기간", "공모기간", "운영기간", "신청", "접수", "모집"]
_EVENT_LABELS = ["행사기간", "교육기간", "운영기간", "활동기간", "일시", "일정", "기간"]
_LOC_LABELS = ["장소", "교육장소", "행사장소", "운영장소", "위치"]


def enrich(post: dict) -> dict:
    """수집한 글에 자동분류(topic/kind/대상)와 행사·신청 기간·장소를 채운다.
    본문이 없으면 제목만으로 topic/kind 판별(부분 채움)."""
    title = post.get("title") or ""
    body = post.get("content_text") or ""
    text = f"{title} {body}"
    topic = classify.classify_topic(text)
    post["topic"] = topic
    post["kind"] = "event" if classify.is_event_topic(topic) else "general"
    if post["kind"] == "event":
        post["target_audience"] = classify.classify_audience(text) or None
    if body:
        # 어댑터 등이 이미 채운 값은 보존, 비어있을 때만 본문에서 파싱
        if not post.get("apply_start_at") and not post.get("apply_end_at"):
            app = dp.extract_labeled_range(body, _APPLY_LABELS)
            post["apply_start_at"] = dp.to_ms(app.start)
            post["apply_end_at"] = dp.to_ms(app.end)
        if not post.get("event_start_at") and not post.get("event_end_at"):
            ev = dp.extract_labeled_range(body, _EVENT_LABELS)
            post["event_start_at"] = dp.to_ms(ev.start)
            post["event_end_at"] = dp.to_ms(ev.end)
        if not post.get("location"):
            for label in _LOC_LABELS:
                m = _re_label(body, label)
                if m:
                    post["location"] = m
                    break
    return post


def _re_label(text: str, label: str) -> str:
    import re
    m = re.search(r"(?:^|[\n\r\s▶□○·-])" + re.escape(label) + r"\s*[:：]\s*([^\n\r]{2,60})", text)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def ingest_source(db: Database, source: dict, window_days: int) -> dict:
    """단일 소스 수집. 결과 요약 dict 반환.

    첫 등록: 최근 window_days 이내 글만. 이후(증분): 이미 저장된 최신 발행일보다
    새로운 글만 저장 → 과거 이력이 큰 피드(예: 1000건 RSS)를 백필하지 않음.
    소스에 window_days가 있으면 그 값으로 창을 넓힌다(예: 전시는 수개월 진행).
    """
    latest = db.latest_published(source["id"])
    first_time = latest is None
    posts = collectors.collect(source)
    fetched = len(posts)
    if first_time:
        posts = collectors.within_window(posts, int(source.get("window_days", window_days)))
    else:
        posts = [p for p in posts if p["published_at"] is None or p["published_at"] > latest]
    region = source.get("region") or "전국"
    region2 = source.get("region2") or ""
    org_type = source.get("org_type") or classify.classify_org_type(source.get("name", ""))
    for p in posts:
        p["region"], p["region2"], p["org_type"] = region, region2, org_type
    inserted = sum(1 for p in posts if db.upsert_post(enrich(p)))
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

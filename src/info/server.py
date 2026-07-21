"""info.whitedr.com — 다중 사이트 정보 수집 대시보드 (FastAPI).

여러 사이트(블로그·정부·비영리·교육 등)에서 가져온 글을 한 표에 모아 보여준다.
표시: 수집일 · 제목 · 출처 · 작성자 · 조회수 (없는 값은 빈칸). 행 펼치면 본문 txt +
원문 링크.

실행:  python -m src.info.server                # 수집기 스케줄 포함
       python -m src.info.server --no-ingest    # 뷰어만 (자동수집 끔)
접속:  http://localhost:8091
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "info.db"
CONFIG_PATH = ROOT / "config" / "info_sources.json"
STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="정보 수집 대시보드")
STATE = {"last_ingest": None, "last_result": []}


def _ro_conn():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _fmt(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") if ms else ""


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"sources": [], "categories": []}


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/sources")
def sources():
    cfg = _load_config()
    return {
        "categories": cfg.get("categories", []),
        "sources": [{"id": s["id"], "name": s.get("name", s["id"]),
                     "category": s.get("category", ""), "type": s.get("type", "")}
                    for s in cfg.get("sources", [])],
    }


@app.get("/api/stats")
def stats():
    c = _ro_conn()
    try:
        q = c.execute
        return {
            "posts": q("SELECT COUNT(*) FROM posts").fetchone()[0],
            "sources": q("SELECT COUNT(DISTINCT source_id) FROM posts").fetchone()[0],
            "last_ingest": _fmt(STATE["last_ingest"]) if STATE["last_ingest"] else None,
        }
    finally:
        c.close()


@app.get("/api/posts")
def posts(q: str = "", category: str = "", source: str = "",
          limit: int = 100, offset: int = 0):
    """수집한 글 목록. 최신 발행순(발행일 없으면 수집일). category/source/q 필터."""
    conn = _ro_conn()
    try:
        where, params = [], []
        if category:
            where.append("category = ?"); params.append(category)
        if source:
            where.append("source_id = ?"); params.append(source)
        if q:
            where.append("(title LIKE ? OR content_text LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        sql = "SELECT * FROM posts"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY COALESCE(published_at, collected_at) DESC LIMIT ? OFFSET ?"
        rows = [dict(r) for r in conn.execute(sql, params + [limit, offset]).fetchall()]
        for r in rows:
            r["published_str"] = _fmt(r["published_at"])
            r["collected_str"] = _fmt(r["collected_at"])
        return {"rows": rows, "has_more": len(rows) == limit}
    finally:
        conn.close()


@app.post("/api/ingest")
def ingest_now(source: str = ""):
    """수동 수집 트리거. source에 소스 id 일부 전달 시 해당 소스만."""
    from . import ingest
    res = ingest.run(source or None)
    STATE["last_ingest"] = int(time.time() * 1000)
    STATE["last_result"] = res
    return {"ok": True, "results": res}


# ── 백그라운드 자동 수집 (기본 30분 간격) ──────────────────────────────────
INGEST_INTERVAL_S = 30 * 60


def _ingest_loop():
    from . import ingest
    while True:
        try:
            res = ingest.run()
            STATE["last_ingest"] = int(time.time() * 1000)
            STATE["last_result"] = res
            n = sum(r.get("inserted", 0) for r in res)
            print(f"[info] 자동수집 완료 — 신규 {n}건")
        except Exception as e:
            print("[info] 자동수집 오류:", e)
        time.sleep(INGEST_INTERVAL_S)


@app.on_event("startup")
async def _startup():
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass
    if getattr(app.state, "ingest", True):
        threading.Thread(target=_ingest_loop, daemon=True).start()


def main():
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8091)
    p.add_argument("--no-ingest", action="store_true", help="자동 수집 끔(뷰어만)")
    args = p.parse_args()
    app.state.ingest = not args.no_ingest
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

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
import base64
import hashlib
import hmac
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


# ── 관리자 인증 (dashboard.whitedr.com과 동일한 .whitedr.com SSO 쿠키 검증) ──
def _load_sso_secret():
    p = ROOT / "config" / "sso_secret.txt"
    if p.exists():
        s = p.read_text(encoding="utf-8").strip()
        if s:
            return s.encode()
    return None


SSO_SECRET = _load_sso_secret()


def _sso_admin(token: str | None) -> bool:
    """dashboard가 발급한 sso 토큰(base64url(payload).hmac)을 검증해 admin 여부 반환."""
    if not token or SSO_SECRET is None or "." not in token:
        return False
    body, _, sig = token.partition(".")
    good = hmac.new(SSO_SECRET, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    try:
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
    except Exception:
        return False
    if payload.get("exp", 0) < time.time():
        return False
    return bool(payload.get("admin"))


def _is_admin(request: Request) -> bool:
    """터널을 거치지 않은 직접 로컬 접속 = 운영자로 허용.
    터널(cloudflare) 경유는 dashboard master 로그인의 SSO 쿠키가 있어야 함."""
    if "cf-connecting-ip" not in request.headers:
        return True   # 서버 로컬에서 직접 접속(운영자)
    return _sso_admin(request.cookies.get("sso"))


def _ro_conn():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _fmt(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") if ms else ""


def _fmtd(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d") if ms else ""


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
    from .classify import TOPIC_RULES
    cfg = _load_config()
    # 지역 목록(전국을 맨 앞으로, 나머지는 소스 등장순 유지)
    regions, seen = [], set()
    for s in cfg.get("sources", []):
        rg = s.get("region") or "전국"
        if rg not in seen:
            seen.add(rg); regions.append(rg)
    regions = (["전국"] if "전국" in seen else []) + [r for r in regions if r != "전국"]
    return {
        "categories": cfg.get("categories", []),
        "topics": [t for t, _ in TOPIC_RULES] + ["기타"],
        "regions": regions,
        "sources": [{"id": s["id"], "name": s.get("name", s["id"]),
                     "category": s.get("category", ""), "type": s.get("type", ""),
                     "region": s.get("region", "전국")}
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
def posts(q: str = "", category: str = "", source: str = "", kind: str = "",
          topic: str = "", region: str = "", limit: int = 100, offset: int = 0):
    """수집한 글 목록. 최신 발행순(발행일 없으면 수집일).
    category/source/kind/topic/region/q 필터."""
    conn = _ro_conn()
    try:
        where, params = [], []
        if category:
            where.append("category = ?"); params.append(category)
        if source:
            where.append("source_id = ?"); params.append(source)
        if kind:
            where.append("kind = ?"); params.append(kind)
        if topic:
            where.append("topic = ?"); params.append(topic)
        if region:
            where.append("region = ?"); params.append(region)
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
            r["apply_start_str"] = _fmtd(r.get("apply_start_at"))
            r["apply_end_str"] = _fmtd(r.get("apply_end_at"))
            r["event_start_str"] = _fmtd(r.get("event_start_at"))
            r["event_end_str"] = _fmtd(r.get("event_end_at"))
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


# ── 소스 관리 API (관리자 전용) ────────────────────────────────────────────
def _save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/admin/me")
def admin_me(request: Request):
    return {"admin": _is_admin(request)}


@app.get("/api/admin/sources")
def admin_sources(request: Request):
    """등록된 소스 목록 + 각 소스 글 수 (관리 패널용)."""
    if not _is_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    cfg = _load_config()
    conn = _ro_conn()
    try:
        counts = {r["source_id"]: r["n"] for r in conn.execute(
            "SELECT source_id, COUNT(*) n FROM posts GROUP BY source_id")}
    finally:
        conn.close()
    out = []
    for s in cfg.get("sources", []):
        out.append({"id": s["id"], "name": s.get("name", s["id"]),
                    "category": s.get("category", ""), "type": s.get("type", ""),
                    "enabled": s.get("enabled", True), "posts": counts.get(s["id"], 0)})
    return {"sources": out, "categories": cfg.get("categories", [])}


@app.post("/api/admin/add-source")
async def admin_add_source(request: Request):
    """블로그 ID/주소 또는 RSS 주소를 받아 소스로 등록하고 즉시 수집.
    body: {input, name?, category?}"""
    if not _is_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    from . import collectors, ingest
    body = await request.json()
    raw = (body.get("input") or "").strip()
    try:
        info = collectors.resolve_source(raw)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    src = info["source"]
    cfg = _load_config()
    if any(s["id"] == src["id"] for s in cfg.get("sources", [])):
        return JSONResponse({"error": f"이미 등록된 소스입니다: {info['sample_name']}"}, status_code=409)
    src["name"] = (body.get("name") or "").strip() or info["sample_name"]
    src["category"] = (body.get("category") or "").strip() or "기타"
    src["enabled"] = True
    cfg.setdefault("sources", []).append(src)
    _save_config(cfg)
    # 방금 추가한 소스만 즉시 첫 수집(최근 30일)
    res = ingest.run(src["id"])
    STATE["last_ingest"] = int(time.time() * 1000)
    inserted = sum(r.get("inserted", 0) for r in res)
    return {"ok": True, "id": src["id"], "name": src["name"],
            "category": src["category"], "type": src["type"], "inserted": inserted}


@app.post("/api/admin/toggle-source")
async def admin_toggle_source(request: Request):
    """소스 수집 켜기/끄기. body: {id, enabled}"""
    if not _is_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    body = await request.json()
    sid, enabled = body.get("id"), bool(body.get("enabled"))
    cfg = _load_config()
    hit = False
    for s in cfg.get("sources", []):
        if s["id"] == sid:
            s["enabled"] = enabled; hit = True
    if not hit:
        return JSONResponse({"error": "소스를 찾을 수 없습니다."}, status_code=404)
    _save_config(cfg)
    return {"ok": True, "id": sid, "enabled": enabled}


@app.post("/api/admin/delete-source")
async def admin_delete_source(request: Request):
    """소스 삭제. body: {id, purge?} — purge=true면 수집된 글도 함께 삭제."""
    if not _is_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    body = await request.json()
    sid = body.get("id")
    cfg = _load_config()
    before = len(cfg.get("sources", []))
    cfg["sources"] = [s for s in cfg.get("sources", []) if s["id"] != sid]
    if len(cfg["sources"]) == before:
        return JSONResponse({"error": "소스를 찾을 수 없습니다."}, status_code=404)
    _save_config(cfg)
    purged = 0
    if body.get("purge"):
        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            cur = conn.execute("DELETE FROM posts WHERE source_id=?", (sid,))
            purged = cur.rowcount
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "id": sid, "purged": purged}


# ── 백그라운드 자동 수집 (12시간 간격 = 하루 2회) ──────────────────────────
INGEST_INTERVAL_S = 12 * 60 * 60


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

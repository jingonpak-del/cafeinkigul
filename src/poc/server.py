"""FastAPI 대시보드 서버 — 중앙 서버 형태.

- REST: 최근 글 목록/상세/통계 (SQLite 읽기)
- WebSocket: Watcher가 감지한 신규/재방문 이벤트를 접속 브라우저들에 실시간 push
- Watcher를 백그라운드 스레드로 함께 구동 (config에 세션/시트 있으면 자동 활용)

실행:  python -m src.poc.server            (워처 포함)
       python -m src.poc.server --no-watch  (DB 뷰어만)
접속:  http://localhost:8000  (같은 네트워크의 다른 PC는 http://<서버IP>:8000)
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import bisect
import json
import secrets
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "tracker.db"
CONFIG_PATH = ROOT / "config" / "targets.json"
STATIC = Path(__file__).resolve().parent / "static"


def _row_conn():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _fmt(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") if ms else ""


def _cafe_names() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {c["club_id"]: c.get("name") or c["cluburl"] for c in cfg["cafes"]}
    except Exception:
        return {}


# ── 인기점수(호응) 계산 ────────────────────────────────────────────────────
HOT_WINDOW_H = 24                       # '호응좋은 일반글' 대상 시간창
W_VV, W_CV, W_ER, W_LR = 0.35, 0.30, 0.25, 0.10   # 조회속도/댓글속도/참여율/좋아요율
ER_CAP, LR_CAP = 0.30, 0.10             # 참여율/좋아요율 상한(정규화용)
MIN_READ = 50                           # 이 미만 조회는 채점 제외(이른 글 노이즈)
TIERS = ((75, 3), (55, 2), (40, 1))     # 점수→티어(🔥 개수)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _pct(sorted_vals, v) -> float:
    # 값보다 '엄격히 작은' 항목 비율 → 0(댓글 없음 등) 동점은 하위로 감.
    n = len(sorted_vals)
    if n <= 1:
        return 0.5
    return bisect.bisect_left(sorted_vals, v) / (n - 1)


def _recent_scores(conn) -> dict:
    """최근 24h 일반글의 인기점수 {(cafe,article): score|None} (카페별 백분위 정규화)."""
    since = _now_ms() - HOT_WINDOW_H * 3600 * 1000
    rows = conn.execute(
        """SELECT a.cafe_id, a.article_id, a.write_ts,
                  COALESCE(a.cur_read, a.first_read_count, 0) AS r,
                  COALESCE(a.cur_comment, a.first_comment_count, 0) AS c,
                  COALESCE(a.cur_like, a.like_count, 0) AS lk
           FROM articles a
           WHERE a.write_ts >= ? AND a.status != 'deleted'
             AND EXISTS (SELECT 1 FROM board_detections d
                         WHERE d.cafe_id=a.cafe_id AND d.article_id=a.article_id
                           AND d.board_key LIKE 'menu:%')""",
        (since,)).fetchall()
    now = _now_ms()
    by_cafe, met = defaultdict(list), {}
    for row in rows:
        key = (row["cafe_id"], row["article_id"])
        r = row["r"] or 0
        age_h = max((now - (row["write_ts"] or now)) / 3600000, 0.15)
        vv = r / age_h
        cv = (row["c"] or 0) / age_h
        er = min((row["c"] or 0) / max(r, 1), ER_CAP) / ER_CAP
        lr = min((row["lk"] or 0) / max(r, 1), LR_CAP) / LR_CAP
        met[key] = (vv, cv, er, lr, r)
        by_cafe[row["cafe_id"]].append(key)
    scores = {}
    for keys in by_cafe.values():
        vvs = sorted(met[k][0] for k in keys)
        cvs = sorted(met[k][1] for k in keys)
        for k in keys:
            vv, cv, er, lr, r = met[k]
            if r < MIN_READ:
                scores[k] = None
                continue
            scores[k] = round(100 * (W_VV * _pct(vvs, vv) + W_CV * _pct(cvs, cv)
                                     + W_ER * er + W_LR * lr), 1)
    return scores


def _tier(s) -> int:
    if s is None:
        return 0
    for thr, t in TIERS:
        if s >= thr:
            return t
    return 0


# ── WebSocket 브로드캐스트 ────────────────────────────────────────────────
class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def _send_all(self, msg: dict):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_threadsafe(self, msg: dict):
        """워처 스레드에서 호출 — 서버 이벤트루프로 안전하게 넘김."""
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._send_all(msg), self.loop)


hub = Hub()
app = FastAPI(title="인기글 트래커")
STATE = {"session_ok": True}   # 워처가 갱신하는 런타임 상태


def _load_auth():
    """config/dashboard_auth.json 이 있으면 (user, password) 반환, 없으면 None(인증 끔)."""
    p = ROOT / "config" / "dashboard_auth.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("user") and d.get("password"):
                return d["user"], d["password"]
        except Exception:
            pass
    return None


AUTH = _load_auth()


def _auth_ok(header: str | None) -> bool:
    if AUTH is None:
        return True
    if not header or not header.startswith("Basic "):
        return False
    try:
        user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except Exception:
        return False
    return secrets.compare_digest(user, AUTH[0]) and secrets.compare_digest(pw, AUTH[1])


@app.middleware("http")
async def _basic_auth(request, call_next):
    # 브라우저가 Basic 인증 통과 후 자격증명을 캐시 → /api, /ws 핸드셰이크에도 자동 전송.
    if AUTH is None or _auth_ok(request.headers.get("Authorization")):
        return await call_next(request)
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Ingigeul Tracker"'})


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/stats")
def stats():
    c = _row_conn()
    try:
        q = c.execute
        return {
            "articles": q("SELECT COUNT(*) FROM articles").fetchone()[0],
            "comments": q("SELECT COUNT(*) FROM comments").fetchone()[0],
            "revisited": q("SELECT COUNT(*) FROM articles WHERE revisit_done=1").fetchone()[0],
            "pending_revisit": q("SELECT COUNT(*) FROM articles WHERE revisit_done=0").fetchone()[0],
            "deleted": q("SELECT COUNT(*) FROM articles WHERE status='deleted'").fetchone()[0],
            "session_ok": STATE["session_ok"],
        }
    finally:
        c.close()


@app.get("/api/articles")
def articles(type: str = "", q: str = "", limit: int = 100, offset: int = 0, order: str = "latest"):
    """type: 'popular'|'general'|''. order: 'latest'(작성시간 최신순) | 'hot'(24h 인기점수순).
    반환: {rows, has_more}."""
    names = _cafe_names()
    conn = _row_conn()
    try:
        scores = _recent_scores(conn)
        base = """SELECT a.cafe_id, a.article_id, a.menu_id, a.title, a.writer_nickname,
                         a.write_ts, a.first_seen_at, a.read_delta, a.revisit_done, a.status,
                         COALESCE(a.cur_read, a.first_read_count) AS read_cnt,
                         COALESCE(a.cur_comment, a.first_comment_count) AS comment_cnt,
                         COALESCE(a.cur_like, a.like_count) AS like_cnt,
                         (SELECT group_concat(board_key, ',') FROM board_detections d
                          WHERE d.cafe_id=a.cafe_id AND d.article_id=a.article_id) AS boards
                  FROM articles a"""
        where, params = [], []
        if type == "popular":
            where.append("""EXISTS (SELECT 1 FROM board_detections d WHERE d.cafe_id=a.cafe_id
                            AND d.article_id=a.article_id AND d.board_key='popular')""")
        elif type == "general" or order == "hot":
            where.append("""EXISTS (SELECT 1 FROM board_detections d WHERE d.cafe_id=a.cafe_id
                            AND d.article_id=a.article_id AND d.board_key LIKE 'menu:%')""")
        if q:
            where.append("a.title LIKE ?"); params.append(f"%{q}%")

        if order == "hot":
            # 최근 24h 일반글 중 점수 있는 것만, 점수 내림차순
            where.append("a.write_ts >= ?"); params.append(_now_ms() - HOT_WINDOW_H * 3600 * 1000)
            where.append("a.status != 'deleted'")
            sql = base + " WHERE " + " AND ".join(where)
            allrows = [dict(r) for r in conn.execute(sql, params).fetchall()]
            allrows = [r for r in allrows if scores.get((r["cafe_id"], r["article_id"])) is not None]
            allrows.sort(key=lambda r: scores[(r["cafe_id"], r["article_id"])], reverse=True)
            page = allrows[offset:offset + limit]
        else:
            sql = base + (" WHERE " + " AND ".join(where) if where else "")
            sql += " ORDER BY a.write_ts DESC LIMIT ? OFFSET ?"
            page = [dict(r) for r in conn.execute(sql, params + [limit, offset]).fetchall()]

        for r in page:
            key = (r["cafe_id"], r["article_id"])
            r["cafe_name"] = names.get(r["cafe_id"], str(r["cafe_id"]))
            r["write_str"] = _fmt(r["write_ts"])
            r["seen_str"] = _fmt(r["first_seen_at"])
            r["hot_score"] = scores.get(key)
            r["tier"] = _tier(scores.get(key))
            r["url"] = f"https://cafe.naver.com/ca-fe/cafes/{r['cafe_id']}/articles/{r['article_id']}"
        return {"rows": page, "has_more": len(page) == limit}
    finally:
        conn.close()


@app.get("/api/articles/{cafe_id}/{article_id}")
def article_detail(cafe_id: int, article_id: int):
    conn = _row_conn()
    try:
        a = conn.execute("SELECT * FROM articles WHERE cafe_id=? AND article_id=?",
                         (cafe_id, article_id)).fetchone()
        if not a:
            return JSONResponse({"error": "not found"}, status_code=404)
        comments = [dict(r) for r in conn.execute(
            """SELECT * FROM comments WHERE cafe_id=? AND article_id=? AND phase='first'
               ORDER BY comment_id""", (cafe_id, article_id)).fetchall()]
        d = dict(a)
        d["cafe_name"] = _cafe_names().get(d["cafe_id"], str(d["cafe_id"]))
        d["write_str"] = _fmt(d["write_ts"])
        d["comments"] = comments
        return d
    finally:
        conn.close()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not _auth_ok(ws.headers.get("authorization")):
        await ws.close(code=1008)   # policy violation (인증 실패)
        return
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()   # keepalive / ignore client msgs
    except WebSocketDisconnect:
        hub.disconnect(ws)


# ── Watcher 백그라운드 구동 ───────────────────────────────────────────────
def _start_watcher():
    from . import watcher
    cfg, db, client = watcher.build(None, DB_PATH, CONFIG_PATH)
    buf = None
    s = cfg.get("sheets", {})
    if s.get("spreadsheet_id"):
        try:
            from .sheets import SheetsSink, SheetsBuffer
            buf = SheetsBuffer(SheetsSink(s["credentials_path"], spreadsheet_id=s["spreadsheet_id"]))
        except Exception as e:
            print("시트 비활성:", e)
    def emit(kind: str, payload: dict):
        if kind == "session":
            STATE["session_ok"] = payload.get("ok", True)
        hub.broadcast_threadsafe({"type": kind, **payload})

    w = watcher.Watcher(cfg, db, client, sheets=buf, on_event=emit, per_page=20)
    print(f"Watcher 백그라운드 시작 — 일반 {len(w.menu_boards)}개 / 인기글 {len(w.popular_boards)}개")
    w.run(tick_s=1.0)


@app.on_event("startup")
async def _startup():
    hub.loop = asyncio.get_running_loop()
    if app.state.watch:
        threading.Thread(target=_start_watcher, daemon=True).start()


def _force_utf8():
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass


def main():
    _force_utf8()   # Windows 콘솔 cp949에서 로그 특수문자 인코딩 오류 방지
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8090)   # 8000은 타 프로젝트와 충돌 → 전용 포트
    p.add_argument("--no-watch", action="store_true", help="워처 없이 DB 뷰어만")
    args = p.parse_args()
    app.state.watch = not args.no_watch
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

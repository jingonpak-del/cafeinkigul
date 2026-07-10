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
import hashlib
import hmac
import json
import secrets
import sqlite3
import statistics
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "tracker.db"
CONFIG_PATH = ROOT / "config" / "targets.json"
STATIC = Path(__file__).resolve().parent / "static"


def _row_conn():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _write_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _fmt(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") if ms else ""


def _cafe_names() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {c["club_id"]: c.get("name") or c["cluburl"] for c in cfg["cafes"]}
    except Exception:
        return {}


def _board_names() -> dict:
    """{(club_id, menu_id): 게시판명} — 크롤 menuName이 없을 때 폴백."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        m = {}
        for c in cfg["cafes"]:
            for b in c.get("boards", []):
                if b.get("type") == "menu" and b.get("name"):
                    m[(c["club_id"], b["menu_id"])] = b["name"]
        return m
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


# ── 급상승(1시간): 게시판별 조회속도 평균+2σ 이상 이상치 ─────────────────────
SURGE_WINDOW_H = 1        # 후보: 최근 1시간 작성글
SURGE_BASELINE_H = 24     # 기준 분포: 최근 24시간 그 게시판 글
SURGE_SIGMA = 2.0         # 평균 + Nσ 이상 = 급상승
SURGE_MIN_SAMPLES = 5     # 게시판 표본 이만큼 미만이면 폴백(절대 조회)
SURGE_MIN_READ = 20       # 이 미만 조회는 급상승에서 제외(잡음)
SURGE_FALLBACK_READ = 100 # 표본 부족 게시판은 절대 조회 이 이상만


def _surge_list(conn) -> dict:
    """최근 1시간 일반글 중 '게시판 평균 조회속도 대비 이례적으로 빠른' 글.
    반환 {(cafe,article): {"z": 표준편차배수, "ratio": 평균대비배율}}."""
    now = _now_ms()
    rows = conn.execute(
        """SELECT a.cafe_id, a.article_id, a.menu_id, a.write_ts,
                  COALESCE(a.cur_read, a.first_read_count, 0) AS r
           FROM articles a
           WHERE a.write_ts >= ? AND a.status != 'deleted'
             AND EXISTS (SELECT 1 FROM board_detections d
                         WHERE d.cafe_id=a.cafe_id AND d.article_id=a.article_id
                           AND d.board_key LIKE 'menu:%')""",
        (now - SURGE_BASELINE_H * 3600 * 1000,)).fetchall()
    board_vel, info = defaultdict(list), {}
    for row in rows:
        age_h = max((now - (row["write_ts"] or now)) / 3600000, 0.15)
        vel = (row["r"] or 0) / age_h
        board = (row["cafe_id"], row["menu_id"])
        board_vel[board].append(vel)
        info[(row["cafe_id"], row["article_id"])] = (board, vel, row["write_ts"], row["r"])
    stat = {}
    for board, vels in board_vel.items():
        if len(vels) >= SURGE_MIN_SAMPLES:
            mu = statistics.mean(vels)
            sd = statistics.pstdev(vels) or 1.0
            stat[board] = (mu, sd)
    cut1h = now - SURGE_WINDOW_H * 3600 * 1000
    out = {}
    for key, (board, vel, wts, r) in info.items():
        if (wts or 0) < cut1h or r < SURGE_MIN_READ:
            continue
        st = stat.get(board)
        if st:
            mu, sd = st
            z = (vel - mu) / sd
            if z >= SURGE_SIGMA:
                out[key] = {"z": round(z, 2), "ratio": round(vel / mu, 1) if mu > 0 else None}
        elif r >= SURGE_FALLBACK_READ:      # 표본 부족 게시판 폴백
            out[key] = {"z": None, "ratio": None}
    return out


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


def _load_accounts():
    """config/dashboard_auth.json → 계정 목록 [{user,password,group,admin?}].
    구버전({user,password}) 호환. 파일 없으면 None(인증 끔)."""
    p = ROOT / "config" / "dashboard_auth.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d.get("accounts"), list) and d["accounts"]:
                return d["accounts"]
            if d.get("user") and d.get("password"):
                return [{"user": d["user"], "password": d["password"], "group": "관리자", "admin": True}]
        except Exception:
            pass
    return None


ACCOUNTS = _load_accounts()
ACCESS = {}   # (group, ip) -> [first_ms, last_ms, count]


def _auth_match(header: str | None):
    """자격증명 일치하는 계정 dict 반환, 없으면 None. 인증 끔이면 관리자로 취급."""
    if ACCOUNTS is None:
        return {"group": "(무인증)", "admin": True}
    if not header or not header.startswith("Basic "):
        return None
    try:
        user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except Exception:
        return None
    for a in ACCOUNTS:
        if secrets.compare_digest(user, a.get("user", "")) and secrets.compare_digest(pw, a.get("password", "")):
            return a
    return None


def _client_ip(headers, fallback) -> str:
    # Cloudflare 터널 뒤에선 실제 IP가 헤더에 있음.
    return (headers.get("cf-connecting-ip")
            or headers.get("x-forwarded-for", "").split(",")[0].strip()
            or fallback or "?")


def _record_access(acct, ip):
    key = (acct.get("group", "?"), ip)
    now = _now_ms()
    e = ACCESS.get(key)
    if e:
        e[1] = now; e[2] += 1
    else:
        ACCESS[key] = [now, now, 1]


SESSIONS = {}   # cookie token -> account (인메모리, 재시작 시 재로그인)


def _load_sso_secret():
    p = ROOT / "config" / "sso_secret.txt"
    if p.exists():
        s = p.read_text(encoding="utf-8").strip()
        if s:
            return s.encode()
    return None


SSO_SECRET = _load_sso_secret()


def _sso_sign(payload: dict) -> str:
    """통합 SSO 서명 토큰: base64url(payload).hmac_sha256 (다른 앱이 검증)."""
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SSO_SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _new_session(acct) -> str:
    token = secrets.token_urlsafe(24)
    SESSIONS[token] = acct
    return token


def _conn_account(conn):
    """Request/WebSocket 공통: 쿠키 세션 또는 Basic Auth로 계정 판별."""
    if ACCOUNTS is None:
        return {"group": "(무인증)", "admin": True}
    tok = conn.cookies.get("sess")
    if tok and tok in SESSIONS:
        return SESSIONS[tok]
    return _auth_match(conn.headers.get("authorization"))


_PUBLIC = {"/login", "/favicon.ico"}


@app.middleware("http")
async def _auth(request: Request, call_next):
    if ACCOUNTS is None:
        return await call_next(request)
    path = request.url.path
    if path in _PUBLIC or path.startswith("/static"):
        return await call_next(request)
    acct = _conn_account(request)
    if acct is None:
        # 브라우저(HTML)는 로그인 페이지로, API/도구는 401.
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/login", status_code=303)
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Ingigeul Tracker"'})
    _record_access(acct, _client_ip(request.headers, request.client.host if request.client else None))
    return await call_next(request)


LOGIN_HTML = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/><title>로그인 · 인기글 트래커</title>
<style>
 body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0f1420;
   font-family:"Segoe UI","Malgun Gothic",sans-serif;color:#e6ebf5}
 .box{background:#171d2b;border:1px solid #26304a;border-radius:14px;padding:28px 26px;width:300px;box-shadow:0 10px 40px #0007}
 h1{font-size:19px;margin:0 0 4px;text-align:center} .sub{color:#8a97b5;font-size:12px;text-align:center;margin-bottom:18px}
 input{width:100%;box-sizing:border-box;background:#0f1420;border:1px solid #26304a;border-radius:8px;
   padding:11px 12px;color:#e6ebf5;font-size:15px;margin-bottom:10px}
 input:focus{outline:none;border-color:#4c8dff}
 button{width:100%;background:#4c8dff;color:#fff;border:0;border-radius:8px;padding:12px;font-size:15px;font-weight:600;cursor:pointer}
 .err{color:#ff9a9a;font-size:12.5px;text-align:center;min-height:16px;margin-bottom:6px}
</style></head><body>
 <form class="box" method="post" action="/login">
   <h1>📈 인기글 트래커</h1><div class="sub">팀 계정으로 로그인하세요</div>
   <div class="err">{{ERR}}</div>
   <input name="username" placeholder="아이디" autofocus autocapitalize="off" autocorrect="off" spellcheck="false"/>
   <input name="password" type="password" placeholder="비밀번호"/>
   <button type="submit">로그인</button>
 </form></body></html>"""


@app.get("/login", response_class=HTMLResponse)
def login_page(err: str = ""):
    return LOGIN_HTML.replace("{{ERR}}", "아이디 또는 비밀번호가 올바르지 않습니다." if err else "")


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    user = (form.get("username") or "").strip()
    pw = form.get("password") or ""
    for a in (ACCOUNTS or []):
        if secrets.compare_digest(user, a.get("user", "")) and secrets.compare_digest(pw, a.get("password", "")):
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie("sess", _new_session(a), httponly=True, samesite="lax",
                            max_age=60 * 60 * 24 * 30, path="/")
            # 통합 SSO 쿠키 (.whitedr.com 공유 → checker 등 다른 앱에서 검증)
            host = (request.headers.get("host") or "").split(":")[0]
            if SSO_SECRET and host.endswith("whitedr.com"):
                tok = _sso_sign({"group": a.get("group", "?"), "admin": bool(a.get("admin")),
                                 "perms": a.get("perms", []),
                                 "exp": int(time.time()) + 60 * 60 * 24 * 30})
                resp.set_cookie("sso", tok, domain=".whitedr.com", httponly=True,
                                samesite="lax", max_age=60 * 60 * 24 * 30, path="/")
            return resp
    return RedirectResponse("/login?err=1", status_code=303)


@app.get("/api/me")
def me(request: Request):
    a = _conn_account(request) or {}
    return {"group": a.get("group"), "admin": bool(a.get("admin")), "perms": a.get("perms", [])}


@app.get("/logout")
def logout(request: Request):
    tok = request.cookies.get("sess")
    if tok:
        SESSIONS.pop(tok, None)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("sess", path="/")
    return resp


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
    bnames = _board_names()
    conn = _row_conn()
    try:
        scores = _recent_scores(conn)
        base = """SELECT a.cafe_id, a.article_id, a.menu_id, a.menu_name, a.title, a.writer_nickname,
                         a.write_ts, a.first_seen_at, a.read_delta, a.revisit_done, a.status,
                         COALESCE(a.cur_read, a.first_read_count) AS read_cnt,
                         COALESCE(a.cur_comment, a.first_comment_count) AS comment_cnt,
                         COALESCE(a.cur_like, a.like_count) AS like_cnt,
                         COALESCE(a.used, 0) AS used, a.used_by, a.used_at,
                         (SELECT group_concat(board_key, ',') FROM board_detections d
                          WHERE d.cafe_id=a.cafe_id AND d.article_id=a.article_id) AS boards
                  FROM articles a"""
        where, params = [], []
        if type == "popular":
            where.append("""EXISTS (SELECT 1 FROM board_detections d WHERE d.cafe_id=a.cafe_id
                            AND d.article_id=a.article_id AND d.board_key='popular')""")
        elif type == "general" or order in ("hot", "surge"):
            where.append("""EXISTS (SELECT 1 FROM board_detections d WHERE d.cafe_id=a.cafe_id
                            AND d.article_id=a.article_id AND d.board_key LIKE 'menu:%')""")
        if q:
            where.append("a.title LIKE ?"); params.append(f"%{q}%")

        if order == "surge":
            # 최근 1h 일반글 중 게시판 평균+2σ 이상 급상승, 이상치 큰 순
            surge = _surge_list(conn)
            where.append("a.write_ts >= ?"); params.append(_now_ms() - SURGE_WINDOW_H * 3600 * 1000)
            where.append("a.status != 'deleted'")
            sql = base + " WHERE " + " AND ".join(where)
            allrows = [dict(r) for r in conn.execute(sql, params).fetchall()]
            allrows = [r for r in allrows if (r["cafe_id"], r["article_id"]) in surge]
            for r in allrows:
                s = surge[(r["cafe_id"], r["article_id"])]
                r["surge_z"], r["surge_ratio"] = s["z"], s["ratio"]
            allrows.sort(key=lambda r: (r["surge_z"] if r["surge_z"] is not None else 0), reverse=True)
            page = allrows[offset:offset + limit]
        elif order == "hot":
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
            r["board_name"] = r.get("menu_name") or bnames.get((r["cafe_id"], r["menu_id"]), "")
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
        d["board_name"] = d.get("menu_name") or _board_names().get((d["cafe_id"], d["menu_id"]), "")
        d["write_str"] = _fmt(d["write_ts"])
        d["comments"] = comments
        return d
    finally:
        conn.close()


@app.get("/api/access")
def access(request: Request):
    """그룹별 접속 현황 (관리자 전용). 인원=고유 IP, 활성=최근 5분 접속."""
    acct = _conn_account(request)
    if not (acct and acct.get("admin")):
        return JSONResponse({"error": "관리자 계정만 볼 수 있습니다."}, status_code=403)
    now = _now_ms()
    groups = {}
    for (g, ip), (first, last, cnt) in ACCESS.items():
        st = groups.setdefault(g, {"group": g, "people": 0, "active": 0, "requests": 0, "last": 0})
        st["people"] += 1
        st["requests"] += cnt
        st["last"] = max(st["last"], last)
        if now - last <= 5 * 60 * 1000:
            st["active"] += 1
    out = sorted(groups.values(), key=lambda x: -x["last"])
    for g in out:
        g["last_str"] = _fmt(g["last"])
    return {"groups": out, "total_ips": len(ACCESS)}


@app.post("/api/articles/{cafe_id}/{article_id}/use")
async def mark_used(cafe_id: int, article_id: int, request: Request):
    """소프트 '사용됨' 표시 토글. 표시자 그룹 기록 + 전 접속자에 실시간 브로드캐스트."""
    acct = _conn_account(request)
    if acct is None:
        return JSONResponse({"error": "auth"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    used = 1 if body.get("used") else 0
    group = acct.get("group", "?")
    now = _now_ms()
    conn = _write_conn()
    try:
        if used:
            conn.execute("UPDATE articles SET used=1, used_by=?, used_at=? WHERE cafe_id=? AND article_id=?",
                         (group, now, cafe_id, article_id))
        else:
            conn.execute("UPDATE articles SET used=0, used_by=NULL, used_at=NULL WHERE cafe_id=? AND article_id=?",
                         (cafe_id, article_id))
        conn.commit()
    finally:
        conn.close()
    payload = {"type": "used", "cafe_id": cafe_id, "article_id": article_id,
               "used": bool(used), "used_by": group if used else None, "used_at": now if used else None}
    await hub._send_all(payload)   # 모든 접속 브라우저에 즉시 반영
    return {"ok": True, **payload}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    acct = _conn_account(ws)
    if acct is None:
        await ws.close(code=1008)   # policy violation (인증 실패)
        return
    _record_access(acct, _client_ip(ws.headers, ws.client.host if ws.client else None))
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
    _force_utf8()   # uvicorn 실행 시에도 stdout UTF-8 → 워처 로그(엠대시 등) cp949 인코딩 크래시 방지
    hub.loop = asyncio.get_running_loop()
    if getattr(app.state, "watch", True):   # uvicorn CLI(--reload) 실행 시 기본 워처 ON
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

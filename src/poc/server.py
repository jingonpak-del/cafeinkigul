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

from .paths import DB_PATH  # 데이터는 D:\cafe-corpus (paths.py 참고)

ROOT = Path(__file__).resolve().parents[2]
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


def _board_categories() -> dict:
    """{(club_id, menu_id): category} — config에서 지정한 일반게시판 분류."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        m = {}
        for c in cfg["cafes"]:
            for b in c.get("boards", []):
                if b.get("type") == "menu" and b.get("category"):
                    m[(c["club_id"], b["menu_id"])] = b["category"]
        return m
    except Exception:
        return {}


# ── Phase 4-2: 키워드/주제 자동 라우팅 ───────────────────────────────────────
# 게시판을 일일이 지정하지 않아도 글 제목 키워드(및 선택적으로 카페 theme)로
# 카테고리를 쿼리 시점에 자동 배정한다(재크롤 불필요). 우선순위는 _resolve_cat 참조:
# 게시판 지정 > 키워드 규칙 > 주제 규칙.
def _category_rules() -> list:
    """config.category_rules 정규화 →
    [{category, keywords:[소문자], themes:[소문자], board_pairs:set((club_id,menu_id))}]."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        out = []
        for r in cfg.get("category_rules", []):
            cat = (r.get("category") or "").strip()
            if not cat:
                continue
            kws = [str(k).strip().lower() for k in (r.get("any_keywords") or []) if str(k).strip()]
            ths = [str(t).strip().lower() for t in (r.get("any_themes") or []) if str(t).strip()]
            pairs = set()
            for b in (r.get("boards") or []):
                try:
                    pairs.add((int(b["club_id"]), int(b["menu_id"])))
                except (KeyError, TypeError, ValueError):
                    pass
            if kws or ths or pairs:
                out.append({"category": cat, "keywords": kws, "themes": ths, "board_pairs": pairs})
        return out
    except Exception:
        return []


def _cafe_themes() -> dict:
    """{club_id: theme} — cafe_candidates에서 (주제 규칙용). 없으면 빈 dict."""
    try:
        conn = _row_conn()
        try:
            return {r["club_id"]: r["theme"] for r in conn.execute(
                "SELECT club_id, theme FROM cafe_candidates WHERE theme IS NOT NULL AND theme != ''")}
        finally:
            conn.close()
    except Exception:
        return {}


def _resolve_cat(r: dict, bcats: dict, rules: list, theme_map: dict) -> str:
    """한 글의 분류 결정. 우선순위: 게시판 지정 > 제목 키워드 > 카페 주제. 없으면 ''."""
    c = bcats.get((r["cafe_id"], r["menu_id"]))
    if c:
        return c
    title = (r.get("title") or "").lower()
    if title:
        for rule in rules:
            if rule["keywords"] and any(k in title for k in rule["keywords"]):
                return rule["category"]
    if theme_map:
        th = (theme_map.get(r["cafe_id"]) or "").lower()
        if th:
            for rule in rules:
                if rule["themes"] and any(t in th for t in rule["themes"]):
                    return rule["category"]
    return ""


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
STATE = {"session_ok": True, "session_days_left": None, "session_expiring": False}   # 워처가 갱신하는 런타임 상태


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
   <input type="hidden" name="next" value="{{NEXT}}"/>
   <input name="username" placeholder="아이디" autofocus autocapitalize="off" autocorrect="off" spellcheck="false"/>
   <input name="password" type="password" placeholder="비밀번호"/>
   <button type="submit">로그인</button>
 </form></body></html>"""


def _safe_next(nxt: str) -> str:
    """오픈 리다이렉트 방지: whitedr.com 도메인만 허용."""
    if nxt.startswith("https://"):
        hostpart = nxt[len("https://"):].split("/")[0]
        if hostpart == "whitedr.com" or hostpart.endswith(".whitedr.com"):
            return nxt
    return "/"


@app.get("/login", response_class=HTMLResponse)
def login_page(err: str = "", next: str = ""):
    html = LOGIN_HTML.replace("{{ERR}}", "아이디 또는 비밀번호가 올바르지 않습니다." if err else "")
    return html.replace("{{NEXT}}", _safe_next(next).replace('"', "") if next else "")


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    user = (form.get("username") or "").strip()
    pw = form.get("password") or ""
    nxt = _safe_next((form.get("next") or "").strip())
    for a in (ACCOUNTS or []):
        if secrets.compare_digest(user, a.get("user", "")) and secrets.compare_digest(pw, a.get("password", "")):
            resp = RedirectResponse(nxt, status_code=303)   # 로그인 후 원래 가려던 곳(포털 등)으로
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
    from urllib.parse import quote
    return RedirectResponse("/login?err=1" + (f"&next={quote(nxt, safe='')}" if nxt != "/" else ""), status_code=303)


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


@app.get("/studio", response_class=HTMLResponse)
def studio_page(request: Request):
    """핫딜 원고작성 스튜디오 — master 전용(페이지는 열리되 API가 막힘 → JS에서도 확인)."""
    return (STATIC / "studio.html").read_text(encoding="utf-8")


@app.get("/api/categories")
def categories_list():
    """대시보드 카테고리 바용 — config의 동적 카테고리 목록."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {"categories": cfg.get("categories", []),
                "popular_category": cfg.get("popular_category", "일반인기글")}
    except Exception:
        return {"categories": [], "popular_category": "일반인기글"}


def _naver_client():
    """크롤 계정 세션으로 인증된 httpx 클라이언트 (게시판 추출용)."""
    from .session import SessionManager
    from . import cafe_api
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    acct = cfg.get("account")
    sm = SessionManager(ROOT / "data" / "sessions")
    cookies = sm.load_cookies(acct) if acct and sm.verify(acct).ok else None
    return cafe_api.make_client(cookies)


def _require_admin(request):
    acct = _conn_account(request)
    return acct if (acct and acct.get("admin")) else None


def _require_write(request):
    """글쓰기(핫딜 원고작성 스튜디오) 권한: master(admin) 또는 perms에 'write' 포함.
    → dashboard_auth.json 계정에 "write"를 넣으면 member 등급도 글쓰기 사용 가능."""
    acct = _conn_account(request)
    return acct if (acct and (acct.get("admin") or "write" in (acct.get("perms") or []))) else None


@app.get("/api/admin/config")
def admin_config(request: Request):
    """현재 설정(카페·게시판·카테고리) — 설정 화면용. master 전용."""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {"categories": cfg.get("categories", []),
            "popular_category": cfg.get("popular_category", "일반인기글"),
            "category_rules": cfg.get("category_rules", []),
            "cafes": [{"cluburl": c["cluburl"], "club_id": c["club_id"], "name": c.get("name", ""),
                       "boards": c.get("boards", [])} for c in cfg.get("cafes", [])]}


@app.get("/api/admin/cafe-boards")
def admin_cafe_boards(request: Request, cafe: str):
    """카페 주소로 게시판 목록 자동추출 + 현재 추적/분류 표시. master 전용."""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    from . import cafe_api
    cl = _naver_client()
    try:
        cid = cafe_api.resolve_club_id(cafe, client=cl)
        boards = cafe_api.fetch_board_list(cid, client=cl)
    except Exception as e:
        return JSONResponse({"error": f"게시판 추출 실패: {e}"}, status_code=400)
    finally:
        cl.close()
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    tracked, has_pop, name = {}, False, cafe
    for c in cfg["cafes"]:
        if c["club_id"] == cid:
            name = c.get("name", cafe)
            for b in c["boards"]:
                if b.get("type") == "menu":
                    tracked[b["menu_id"]] = b.get("category", "")
                if b.get("type") == "popular":
                    has_pop = True
    for b in boards:
        b["tracked"] = b["menu_id"] in tracked
        b["category"] = tracked.get(b["menu_id"], "")
    return {"club_id": cid, "cluburl": cafe, "name": name, "popular": has_pop, "boards": boards}


@app.post("/api/admin/save-cafe")
async def admin_save_cafe(request: Request):
    """한 카페의 추적 게시판·분류 저장(체크된 것만). master 전용. → 워처 핫리로드."""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    body = await request.json()
    cid = int(body["club_id"]); cluburl = body["cluburl"]; name = body.get("name") or cluburl
    boards = []
    for b in body.get("boards", []):     # 체크된 일반게시판만 전달됨
        boards.append({"type": "menu", "menu_id": int(b["menu_id"]),
                       "name": b.get("name", ""), "category": b.get("category", "")})
    if body.get("popular"):
        boards.append({"type": "popular", "name": "인기글"})
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["cafes"] = [c for c in cfg["cafes"] if c["club_id"] != cid]   # 기존 제거
    if boards:
        cfg["cafes"].append({"cluburl": cluburl, "club_id": cid, "name": name, "boards": boards})
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    if boards:                              # 발굴 후보였다면 '등록됨'으로 표시
        try:
            _cand_set_status(cid, "tracked")
        except Exception:
            pass
    return {"ok": True, "boards": len(boards)}


@app.post("/api/admin/categories")
async def admin_categories(request: Request):
    """카테고리 목록 저장(추가/이름변경/삭제 반영). master 전용."""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    body = await request.json()
    cats = [str(x).strip() for x in body.get("categories", []) if str(x).strip()]
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["categories"] = cats
    if body.get("popular_category"):
        cfg["popular_category"] = body["popular_category"]
    # 삭제된 분류의 라우팅 규칙도 정리
    if "category_rules" in cfg:
        cfg["category_rules"] = [r for r in cfg["category_rules"]
                                 if (r.get("category") or "") in cats]
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "categories": cats}


@app.post("/api/admin/category-rules")
async def admin_category_rules(request: Request):
    """키워드/주제 자동 라우팅 규칙 저장(Phase 4-2). 쿼리 시점 적용 — 재크롤 불필요. master 전용.
    body: {rules: [{category, any_keywords:[...], any_themes:[...], boards:[{club_id,menu_id}]}]}"""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    body = await request.json()
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    valid_cats = set(cfg.get("categories", []))
    pop_cat = cfg.get("popular_category", "일반인기글")
    out = []
    for r in body.get("rules", []):
        cat = (r.get("category") or "").strip()
        if not cat or cat not in valid_cats or cat == pop_cat:
            continue                       # 존재하는 일반 분류에만 규칙 허용
        kws = _dedup_strs(r.get("any_keywords"))
        ths = _dedup_strs(r.get("any_themes"))
        boards = []
        for b in (r.get("boards") or []):
            try:
                boards.append({"club_id": int(b["club_id"]), "menu_id": int(b["menu_id"])})
            except (KeyError, TypeError, ValueError):
                pass
        if kws or ths or boards:
            rule = {"category": cat, "any_keywords": kws}
            if ths:
                rule["any_themes"] = ths
            if boards:
                rule["boards"] = boards
            out.append(rule)
    cfg["category_rules"] = out
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "rules": out}


def _dedup_strs(seq) -> list:
    """공백 제거 + 중복 제거(대소문자 무시, 원문 보존, 순서 유지)."""
    out, seen = [], set()
    for x in (seq or []):
        s = str(x).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower()); out.append(s)
    return out


# ── 카페 발굴 후보 ───────────────────────────────────────────────────────────
_CAND_DDL = """
CREATE TABLE IF NOT EXISTS cafe_candidates (
    club_id INTEGER PRIMARY KEY, cluburl TEXT, name TEXT, source TEXT, theme TEXT,
    is_power INTEGER DEFAULT 0, is_local INTEGER DEFAULT 0, member_count INTEGER,
    daily_posts REAL, open_level TEXT, join_required INTEGER DEFAULT 0,
    sample_boards TEXT, score REAL, discovered_at INTEGER, updated_at INTEGER,
    status TEXT DEFAULT 'new');
"""
_CAND_FIELDS = ("cluburl", "name", "source", "theme", "is_power", "is_local",
                "member_count", "daily_posts", "open_level", "join_required",
                "sample_boards", "score")
_DISCOVER_RUNNING = False


def _ensure_candidates_table():
    c = _write_conn()
    try:
        c.executescript(_CAND_DDL)
        c.commit()
    finally:
        c.close()


_ensure_candidates_table()


def _cand_upsert(d: dict):
    """후보 저장/갱신. 기존 후보의 status(dismissed/tracked)는 보존."""
    ts = int(time.time() * 1000)
    p = {k: d.get(k) for k in _CAND_FIELDS}
    p["club_id"] = d["club_id"]
    p["ts"] = ts
    p["status"] = d.get("status", "new")
    c = _write_conn()
    try:
        c.execute(
            """INSERT INTO cafe_candidates
               (club_id,cluburl,name,source,theme,is_power,is_local,member_count,
                daily_posts,open_level,join_required,sample_boards,score,
                discovered_at,updated_at,status)
               VALUES (:club_id,:cluburl,:name,:source,:theme,:is_power,:is_local,
                :member_count,:daily_posts,:open_level,:join_required,:sample_boards,
                :score,:ts,:ts,:status)
               ON CONFLICT(club_id) DO UPDATE SET
                 cluburl=excluded.cluburl,name=excluded.name,source=excluded.source,
                 theme=excluded.theme,is_power=excluded.is_power,is_local=excluded.is_local,
                 member_count=excluded.member_count,daily_posts=excluded.daily_posts,
                 open_level=excluded.open_level,join_required=excluded.join_required,
                 sample_boards=excluded.sample_boards,score=excluded.score,
                 updated_at=excluded.updated_at""",
            p,
        )
        c.commit()
    finally:
        c.close()


def _cand_set_status(club_id: int, status: str):
    c = _write_conn()
    try:
        c.execute("UPDATE cafe_candidates SET status=?, updated_at=? WHERE club_id=?",
                  (status, int(time.time() * 1000), club_id))
        c.commit()
    finally:
        c.close()


@app.get("/api/admin/candidates")
def admin_candidates(request: Request, status: str = "new"):
    """발굴 후보 목록. status=new|join_needed|dismissed|tracked|all. master 전용."""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    c = _row_conn()
    try:
        if status == "all":
            rows = c.execute("SELECT * FROM cafe_candidates ORDER BY status, score DESC").fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM cafe_candidates WHERE status=? ORDER BY score DESC, member_count DESC",
                (status,)).fetchall()
        return {"candidates": [dict(r) for r in rows], "running": _DISCOVER_RUNNING}
    finally:
        c.close()


@app.post("/api/admin/candidates/probe-add")
async def admin_candidate_probe_add(request: Request):
    """카페 주소를 직접 조사해 후보로 추가. master 전용."""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    body = await request.json()
    cafe = (body.get("cafe") or "").strip()
    if not cafe:
        return JSONResponse({"error": "카페 주소를 입력하세요"}, status_code=400)
    from . import discovery
    cl = _naver_client()
    try:
        cand = discovery.probe_cafe(cafe, source="manual", client=cl)
    except Exception as e:
        return JSONResponse({"error": f"조사 실패: {e}"}, status_code=400)
    finally:
        cl.close()
    if not cand.get("club_id"):
        return JSONResponse({"error": "카페를 찾지 못했습니다"}, status_code=400)
    if cand.get("join_required"):
        cand["status"] = "join_needed"
    _cand_upsert(cand)
    return {"ok": True, "candidate": cand}


@app.post("/api/admin/candidates/dismiss")
async def admin_candidate_dismiss(request: Request):
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    body = await request.json()
    _cand_set_status(int(body["club_id"]), "dismissed")
    return {"ok": True}


@app.post("/api/admin/candidates/{club_id}/join-confirmed")
async def admin_candidate_join(request: Request, club_id: int):
    """가입 완료 후 재확인 — 인기글 접근되면 등록 가능(new)으로 전환."""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    c = _row_conn()
    try:
        row = c.execute("SELECT cluburl FROM cafe_candidates WHERE club_id=?", (club_id,)).fetchone()
    finally:
        c.close()
    if not row:
        return JSONResponse({"error": "후보를 찾을 수 없습니다"}, status_code=404)
    from . import discovery
    cl = _naver_client()
    try:
        cand = discovery.probe_cafe(row["cluburl"], client=cl)
    finally:
        cl.close()
    status = "join_needed" if cand.get("join_required") else "new"
    _cand_upsert(cand)
    _cand_set_status(club_id, status)
    return {"ok": True, "join_required": bool(cand.get("join_required")), "status": status}


@app.post("/api/admin/candidates/{club_id}/adopt")
async def admin_candidate_adopt(request: Request, club_id: int):
    """게시판을 고르지 않고 카페를 통째로 크롤 대상에 편입(crawl_all).
    → 인기글 무조건 수집(워처) + 전 게시판 과거글은 backfill이 축적. master 전용."""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    c = _row_conn()
    try:
        row = c.execute(
            "SELECT cluburl, name, join_required FROM cafe_candidates WHERE club_id=?",
            (club_id,)).fetchone()
    finally:
        c.close()
    if not row:
        return JSONResponse({"error": "후보를 찾을 수 없습니다"}, status_code=404)
    if row["join_required"]:
        return JSONResponse(
            {"error": "가입이 필요한 카페입니다 — 크롤 계정으로 가입 후 [가입완료]를 먼저 누르세요"},
            status_code=409)
    cluburl = row["cluburl"]
    name = row["name"] or cluburl
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["cafes"] = [x for x in cfg.get("cafes", []) if x["club_id"] != club_id]
    cfg["cafes"].append({"cluburl": cluburl, "club_id": club_id, "name": name,
                         "crawl_all": True,
                         "boards": [{"type": "popular", "name": "인기글"}]})
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    _cand_set_status(club_id, "tracked")
    return {"ok": True, "cluburl": cluburl, "crawl_all": True}


@app.post("/api/admin/candidates/refresh")
async def admin_candidate_refresh(request: Request):
    """섹션 발굴을 백그라운드로 1회 실행(등록카페 제외 후 후보 저장). master 전용."""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    global _DISCOVER_RUNNING
    if _DISCOVER_RUNNING:
        return {"ok": True, "running": True}

    def job():
        global _DISCOVER_RUNNING
        _DISCOVER_RUNNING = True
        try:
            from . import discovery
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            registered = {c["club_id"] for c in cfg.get("cafes", [])}
            cl = _naver_client()
            try:
                for cand in discovery.discover(cl, cfg.get("discovery")):
                    if cand["club_id"] in registered:
                        continue
                    _cand_upsert(cand)
            finally:
                cl.close()
        except Exception:
            pass
        finally:
            _DISCOVER_RUNNING = False

    threading.Thread(target=job, daemon=True).start()
    return {"ok": True, "started": True}


@app.get("/api/admin/board-stats")
def admin_board_stats(request: Request, min_n: int = 10, limit: int = 40,
                      unclassified: bool = False):
    """게시판 가치 분석(읽기전용): 인기글 진입률·반응·볼륨 랭크 + 주제 롤업. master 전용."""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    from . import analytics
    c = _row_conn()
    try:
        return {"boards": analytics.rank_boards(c, min_n=min_n, limit=limit,
                                                only_unclassified=unclassified),
                "themes": analytics.theme_rollup(c, min_n=min_n)}
    except Exception as e:
        return JSONResponse({"error": f"분석 실패: {e}"}, status_code=500)
    finally:
        c.close()


@app.get("/api/admin/recommendations")
def admin_recommendations(request: Request, min_n: int = 20, limit: int = 20):
    """큐레이션 추천(Phase 5-3): 승격 후보 게시판 + 새 카테고리 후보. master 전용."""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    from . import analytics
    c = _row_conn()
    try:
        return analytics.recommend(c, min_n=min_n, limit=limit)
    except Exception as e:
        return JSONResponse({"error": f"추천 실패: {e}"}, status_code=500)
    finally:
        c.close()


@app.post("/api/admin/promote-board")
async def admin_promote_board(request: Request):
    """추천 게시판을 '승격'(등록형)으로 config에 반영 → 스트림 실시간+호응도. master 전용.
    body: {club_id, cluburl?, cafe_name?, menu_id, board_name?, category}"""
    if not _require_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    body = await request.json()
    cid = int(body["club_id"]); mid = int(body["menu_id"])
    category = (body.get("category") or "").strip()
    if not category:
        return JSONResponse({"error": "카테고리를 지정하세요"}, status_code=400)
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cafe = next((c for c in cfg.get("cafes", []) if c["club_id"] == cid), None)
    if cafe is None:
        cafe = {"cluburl": body.get("cluburl") or str(cid), "club_id": cid,
                "name": body.get("cafe_name") or body.get("cluburl") or str(cid),
                "crawl_all": True, "boards": []}
        cfg.setdefault("cafes", []).append(cafe)
    b = next((x for x in cafe.get("boards", [])
              if x.get("type") == "menu" and x.get("menu_id") == mid), None)
    if b is None:
        cafe.setdefault("boards", []).append(
            {"type": "menu", "menu_id": mid, "name": body.get("board_name", ""), "category": category})
    else:
        b["category"] = category
        if body.get("board_name"):
            b["name"] = body["board_name"]
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        _cand_set_status(cid, "tracked")
    except Exception:
        pass
    return {"ok": True, "club_id": cid, "menu_id": mid, "category": category}


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
            "session_days_left": STATE.get("session_days_left"),
            "session_expiring": STATE.get("session_expiring", False),
        }
    finally:
        c.close()


@app.get("/api/articles")
def articles(type: str = "", q: str = "", limit: int = 100, offset: int = 0, order: str = "latest",
             category: str = ""):
    """type: 'popular'|'general'|''. order: 'latest'|'hot'|'surge'.
    category: 일반게시판 분류(핫딜/이벤트 등) 필터. 반환: {rows, has_more}."""
    names = _cafe_names()
    bnames = _board_names()
    bcats = _board_categories()
    rules = _category_rules()
    for _r in rules:                       # 규칙에 지정한 board도 '게시판 지정' 티어로 병합(config가 우선)
        for _p in _r["board_pairs"]:
            bcats.setdefault(_p, _r["category"])
    need_theme = any(r["themes"] for r in rules)
    theme_map = _cafe_themes() if need_theme else {}
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
        # 카테고리 필터 → 그 분류의 '후보 상위집합'만 SQL로 좁힌다(게시판 지정 OR 제목 키워드
        # OR 카페 주제). 정확한 우선순위 판정은 아래 _resolve_cat로 파이썬에서 확정한다.
        if category:
            ors, ps = [], []
            for (cid, mid), v in bcats.items():
                if v == category:
                    ors.append("(a.cafe_id=? AND a.menu_id=?)"); ps.extend([cid, mid])
            for rule in rules:
                if rule["category"] == category:
                    for kw in rule["keywords"]:
                        ors.append("LOWER(a.title) LIKE ?"); ps.append(f"%{kw}%")
            if theme_map:
                tcafes = [cid for cid, th in theme_map.items()
                          if th and any(t in th.lower() for rule in rules
                                        if rule["category"] == category for t in rule["themes"])]
                if tcafes:
                    ors.append("a.cafe_id IN (%s)" % ",".join("?" * len(tcafes))); ps.extend(tcafes)
            if ors:
                where.append("(" + " OR ".join(ors) + ")"); params.extend(ps)
            else:
                where.append("1=0")   # 해당 카테고리에 규칙/게시판 없음 → 빈 결과
        if q:
            where.append("a.title LIKE ?"); params.append(f"%{q}%")

        # 카테고리가 지정되면 상위집합에서 우선순위(_resolve_cat)로 정확히 걸러낸다.
        def _keep(rs):
            return [r for r in rs if _resolve_cat(r, bcats, rules, theme_map) == category] \
                if category else rs

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
            allrows = _keep(allrows)
            page = allrows[offset:offset + limit]
        elif order == "hot":
            # 최근 24h 일반글 중 점수 있는 것만, 점수 내림차순
            where.append("a.write_ts >= ?"); params.append(_now_ms() - HOT_WINDOW_H * 3600 * 1000)
            where.append("a.status != 'deleted'")
            sql = base + " WHERE " + " AND ".join(where)
            allrows = [dict(r) for r in conn.execute(sql, params).fetchall()]
            allrows = [r for r in allrows if scores.get((r["cafe_id"], r["article_id"])) is not None]
            allrows.sort(key=lambda r: scores[(r["cafe_id"], r["article_id"])], reverse=True)
            allrows = _keep(allrows)
            page = allrows[offset:offset + limit]
        elif category:
            # 최신순 + 카테고리: 키워드/주제 규칙은 SQL LIMIT로 못 자르므로 상위집합을 받아
            # 파이썬에서 우선순위 확정 후 페이지네이션한다.
            sql = base + " WHERE " + " AND ".join(where) + " ORDER BY a.write_ts DESC"
            allrows = _keep([dict(r) for r in conn.execute(sql, params).fetchall()])
            page = allrows[offset:offset + limit]
        else:
            sql = base + (" WHERE " + " AND ".join(where) if where else "")
            sql += " ORDER BY a.write_ts DESC LIMIT ? OFFSET ?"
            page = [dict(r) for r in conn.execute(sql, params + [limit, offset]).fetchall()]

        for r in page:
            key = (r["cafe_id"], r["article_id"])
            r["cafe_name"] = names.get(r["cafe_id"], str(r["cafe_id"]))
            r["board_name"] = r.get("menu_name") or bnames.get((r["cafe_id"], r["menu_id"]), "")
            _pop = (r.get("boards") or "").find("popular") >= 0
            r["category"] = _resolve_cat(r, bcats, rules, theme_map) or ("일상인기글" if _pop else "")
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


# ── 핫딜 원고작성 스튜디오 (master 전용, 실험용) ──────────────────────────────
@app.get("/api/studio/candidates")
def studio_candidates(request: Request, category: str = "", order: str = "hot", limit: int = 60):
    """원고 후보 목록 — 기본은 반응 좋은 일반글. category로 핫딜 등 좁힘."""
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    return articles(type="general", order=order, category=category, limit=limit)


def _studio_material(cafe_id: int, article_id: int) -> dict | None:
    """한 글의 글감(본문·댓글·링크·이미지)을 조립해 반환. 없으면 None."""
    from . import studio
    conn = _row_conn()
    try:
        a = conn.execute("SELECT * FROM articles WHERE cafe_id=? AND article_id=?",
                         (cafe_id, article_id)).fetchone()
        if not a:
            return None
        a = dict(a)
        comments = [dict(r) for r in conn.execute(
            """SELECT writer_nickname, content, update_ts FROM comments
               WHERE cafe_id=? AND article_id=? AND phase='first'
               ORDER BY comment_id""", (cafe_id, article_id)).fetchall()]
    finally:
        conn.close()
    # Phase 0 이후 HTML은 DB에 없다. 크롤 시점에 뽑아둔 material_json을 쓰고,
    # 그 이전에 수집된 글은 본문 텍스트에서 URL만 뽑는 폴백으로 처리한다.
    mat = None
    if a.get("material_json"):
        try:
            mat = json.loads(a["material_json"])
        except Exception:
            mat = None
    if mat is None:
        mat = studio.extract_material(a.get("content_html"), a.get("content_text"))
    return {
        "cafe_id": cafe_id, "article_id": article_id,
        "title": a.get("title"), "writer": a.get("writer_nickname"),
        "cafe_name": _cafe_names().get(cafe_id, str(cafe_id)),
        "board_name": a.get("menu_name") or _board_names().get((cafe_id, a.get("menu_id")), ""),
        "write_str": _fmt(a.get("write_ts")),
        "content_text": a.get("content_text") or "",
        "comments": comments,
        "links": mat["links"], "images": mat["images"],
        "url": f"https://cafe.naver.com/ca-fe/cafes/{cafe_id}/articles/{article_id}",
    }


@app.get("/api/studio/material/{cafe_id}/{article_id}")
def studio_material(cafe_id: int, article_id: int, request: Request):
    """한 글의 글감: 본문 텍스트 + 댓글 + 추출된 외부링크/이미지 URL(재크롤 없음)."""
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    m = _studio_material(cafe_id, article_id)
    return m or JSONResponse({"error": "not found"}, status_code=404)


@app.post("/api/studio/unfurl")
async def studio_unfurl(request: Request):
    """링크 자동 해제: 리다이렉트 최종 URL·도메인·OG메타·가격·생사 판정."""
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    from . import studio
    body = await request.json()
    url = (body.get("url") or "").strip()
    if not url.startswith("http"):
        return JSONResponse({"error": "http(s) URL 필요"}, status_code=400)
    return await asyncio.to_thread(studio.unfurl, url)


@app.get("/api/studio/drafts")
def studio_drafts(request: Request):
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    from . import studio
    return {"drafts": studio.list_drafts(DB_PATH)}


@app.get("/api/studio/drafts/{did}")
def studio_draft_get(did: int, request: Request):
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    from . import studio
    d = studio.get_draft(DB_PATH, did)
    return d or JSONResponse({"error": "not found"}, status_code=404)


@app.post("/api/studio/drafts")
async def studio_draft_save(request: Request):
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    from . import studio
    body = await request.json()
    did = studio.save_draft(DB_PATH, body)
    return {"ok": True, "id": did}


@app.post("/api/studio/drafts/{did}/delete")
def studio_draft_delete(did: int, request: Request):
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    from . import studio
    studio.delete_draft(DB_PATH, did)
    return {"ok": True}


STUDIO_PERSONAS = ROOT / "config" / "studio_personas.json"
STUDIO_ENGINE = ROOT / "config" / "studio_engine.json"   # gitignore — OAuth 토큰 보관


def _studio_token():
    from . import studio
    return studio.load_engine_cfg(STUDIO_ENGINE).get("oauth_token") or None


@app.get("/api/studio/engine-config")
def studio_engine_config(request: Request):
    """토큰 저장 여부만 반환(토큰 값은 노출하지 않음). master 전용."""
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    return {"has_token": bool(_studio_token())}


@app.post("/api/studio/engine-config")
async def studio_engine_config_save(request: Request):
    """claude setup-token으로 발급한 OAuth 토큰 저장. master 전용."""
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    from . import studio
    body = await request.json()
    tok = (body.get("oauth_token") or "").strip()
    if not tok:
        return JSONResponse({"error": "토큰이 비었습니다."}, status_code=400)
    studio.save_engine_token(STUDIO_ENGINE, tok)
    return {"ok": True, "has_token": True}


@app.get("/api/studio/personas")
def studio_personas(request: Request):
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    from . import studio
    return studio.load_personas(STUDIO_PERSONAS)


@app.post("/api/studio/personas")
async def studio_personas_save(request: Request):
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    from . import studio
    body = await request.json()
    studio.save_personas(STUDIO_PERSONAS, body)
    return {"ok": True, **studio.load_personas(STUDIO_PERSONAS)}


@app.post("/api/studio/generate")
async def studio_generate(request: Request):
    """구독(claude -p)으로 글감 재작성/큐레이션 → 초안. items=[{cafe_id,article_id}]."""
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    from . import studio
    body = await request.json()
    items = body.get("items") or []
    if not items:
        return JSONResponse({"error": "글감(items)이 없습니다."}, status_code=400)
    mats = []
    for it in items[:6]:   # 한 번에 최대 6개 글감
        m = _studio_material(int(it["cafe_id"]), int(it["article_id"]))
        if m:
            mats.append(m)
    if not mats:
        return JSONResponse({"error": "글감을 찾지 못했습니다."}, status_code=404)
    d = await asyncio.to_thread(
        studio.generate, mats, body.get("persona", ""), body.get("extra", ""),
        body.get("verified_links") or None, body.get("model") or None, 180, _studio_token(),
        body.get("length") or "medium")
    return d


@app.post("/api/studio/engine-check")
async def studio_engine_check(request: Request):
    if not _require_write(request):
        return JSONResponse({"error": "글쓰기 권한 필요"}, status_code=403)
    from . import studio
    return await asyncio.to_thread(studio.engine_check, _studio_token())


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
        elif kind in ("session_saved", "session_expiring"):
            STATE["session_days_left"] = payload.get("days_left")
            STATE["session_expiring"] = (kind == "session_expiring")
        hub.broadcast_threadsafe({"type": kind, **payload})

    # session_mgr를 넘겨야 워처가 갱신된 쿠키를 파일로 되쓴다(재시작해도 세션 유지).
    w = watcher.Watcher(cfg, db, client, sheets=buf, on_event=emit, per_page=20,
                        session_mgr=watcher.build_session_manager())
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

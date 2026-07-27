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
import re
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
    # 지역 목록: 광역(region) + 세부지역(region2, 창원/김해/함안 등)을 함께 노출
    regions, seen = [], set()
    for s in cfg.get("sources", []):
        rg = s.get("region") or "전국"
        if rg not in seen:
            seen.add(rg); regions.append(rg)
    regions = (["전국"] if "전국" in seen else []) + [r for r in regions if r != "전국"]
    subs = []
    for s in cfg.get("sources", []):
        r2 = s.get("region2")
        if r2 and r2 not in seen:
            seen.add(r2); subs.append(r2)
    regions = regions + sorted(subs)
    from .classify import ORG_TYPE_RULES
    return {
        "categories": cfg.get("categories", []),
        "topics": [t for t, _ in TOPIC_RULES] + ["기타"],
        "regions": regions,
        "org_types": [t for t, _ in ORG_TYPE_RULES] + ["기타"],
        "sources": [{"id": s["id"], "name": s.get("name", s["id"]),
                     "category": s.get("category", ""), "type": s.get("type", ""),
                     "region": s.get("region", "전국"), "org_type": s.get("org_type", "기타")}
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
          topic: str = "", region: str = "", org_type: str = "",
          limit: int = 100, offset: int = 0):
    """수집한 글 목록. 최신 발행순(발행일 없으면 수집일).
    category/source/kind/topic/region/org_type/q 필터."""
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
            where.append("(region = ? OR region2 = ?)"); params.extend([region, region])
        if org_type:
            where.append("org_type = ?"); params.append(org_type)
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


# ── 지역별 일일 정보글 생성 ────────────────────────────────────────────────
_TOPIC_EMOJI = {"행사": "🎪", "이벤트": "🎁", "교육": "📚", "모집·채용": "📢",
                "복지·건강": "💚", "문화·관광": "🎨", "정책·경제": "📈", "기타": "📌"}
_TOPIC_ORDER = ["행사", "이벤트", "교육", "모집·채용", "복지·건강", "문화·관광", "정책·경제", "기타"]
# 전국(national) 일일글 기본 주제: 전 국민에게 도움되는 정책·복지·건강·경제 중심
_NATIONAL_TOPICS = ["정책·경제", "복지·건강", "교육", "모집·채용"]


def _day_start_ms(date_str: str) -> int:
    d = datetime.strptime(date_str[:10], "%Y-%m-%d")
    return int(datetime(d.year, d.month, d.day).timestamp() * 1000)


def _norm_title(t: str) -> str:
    """중복 판정용 제목 정규화. 같은 글이 여러 출처·표기로 들어와도 하나로 본다.
    - 끝의 기간/날짜 괄호 제거: '(26. 7. 29. ~ 8. 12.)'
    - 괄호문자 제거(내용은 유지) → 전체가 [ ]로 묶인 제목도 살린다
    - 한글/영숫자만 남기고 소문자화(띄어쓰기·문장부호 차이 무시)
    - 흔한 접미사(안내/알림/공고) 제거 → '모집 안내' == '모집'"""
    t = (t or "").lower()
    t = re.sub(r"[\(\[【][\d\s.,~\-]*[\)\]】]\s*$", "", t)   # 끝 괄호 안 날짜/기간
    t = re.sub(r"[\[\]\(\)【】]", "", t)                     # 남은 괄호문자
    t = re.sub(r"[^0-9a-z가-힣]", "", t)
    t = re.sub(r"(안내문|안내|알림|공고)$", "", t)
    return t


def _dedup_rows(rows: list[dict]) -> list[dict]:
    """정규화 제목+지역이 같으면 첫 항목만 남긴다(중복 내용 1개만 노출).
    지역을 키에 넣어 서로 다른 지역의 동명 글이 잘못 합쳐지는 것을 막는다."""
    seen, out = set(), []
    for r in rows:
        nt = _norm_title(r.get("title") or "") or (r.get("title") or "").strip()
        key = (nt, r.get("region2") or r.get("region") or "")
        if not nt or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _pub_key(r: dict) -> str:
    """발행 이력 키 = 중복 판정키와 동일(정규화 제목|지역)."""
    nt = _norm_title(r.get("title") or "") or (r.get("title") or "").strip()
    return nt + "|" + (r.get("region2") or r.get("region") or "")


# 일일글 자동 발행 시 최근 며칠치를 훑을지(미발행분만 나오므로 넉넉히)
PUBLISH_WINDOW_DAYS = 7


@app.get("/api/digest")
def digest(region: str = "", regions: str = "", topics: str = "",
           date: str = "", date_from: str = "", date_to: str = "", scope: str = "",
           new_only: str = ""):
    """지역·주제 다중선택 + 날짜 기간으로 신규 수집글을 주제별 마크다운 생성.
    - regions/topics: 콤마구분 다중값(비우면 전체). region/date는 하위호환.
    - date_from~date_to: 기간(둘 다 없으면 date, 그것도 없으면 오늘).
    - scope: ''(기존) | 'local'(지역: 전국글 제외, 해당 지역 소식만)
             | 'national'(전국: 전국 작성글 중 도움되는 정책·복지·건강·경제 등).
    - new_only: '1'이면 이미 발행한 항목 제외 + 기간 미지정 시 최근 PUBLISH_WINDOW_DAYS일.
    중복(정규화 제목 동일)은 하나만 남긴다."""
    reg_list = [r for r in (regions or region).split(",") if r.strip()]
    topic_list = [t for t in topics.split(",") if t.strip()]
    if scope == "national" and not topic_list:
        topic_list = list(_NATIONAL_TOPICS)
    try:
        if date_from or date_to:
            df = date_from or date_to
            dt = date_to or date_from
            start = _day_start_ms(df)
            end = _day_start_ms(dt) + 86400 * 1000
            date_label = df if df == dt else f"{df} ~ {dt}"
        elif date:
            start = _day_start_ms(date); end = start + 86400 * 1000
            date_label = date[:10]
        else:
            now = datetime.now()
            today0 = int(datetime(now.year, now.month, now.day).timestamp() * 1000)
            end = today0 + 86400 * 1000
            # 발행 모드: 최근 N일치(미발행분만) / 일반: 오늘치
            start = today0 - (PUBLISH_WINDOW_DAYS - 1) * 86400 * 1000 if new_only else today0
            date_label = now.strftime("%Y-%m-%d")
    except ValueError:
        return JSONResponse({"error": "날짜 형식은 YYYY-MM-DD"}, status_code=400)

    conn = _ro_conn()
    try:
        where = ["collected_at >= ? AND collected_at < ?"]
        params = [start, end]
        if scope == "national":
            # 전국 단위로 작성된 글만(특정 지역 태그 없는 글)
            where.append("(region = '전국' OR region IS NULL OR region = '') "
                         "AND (region2 IS NULL OR region2 = '')")
        elif scope == "local":
            # 특정 지역 소식만(전국글 제외)
            where.append("(region <> '전국' OR (region2 IS NOT NULL AND region2 <> ''))")
        if reg_list:
            ph = ",".join("?" * len(reg_list))
            where.append(f"(region IN ({ph}) OR region2 IN ({ph}))")
            params += reg_list + reg_list
        if topic_list:
            where.append("topic IN (" + ",".join("?" * len(topic_list)) + ")"); params += topic_list
        sql = ("SELECT title, url, source_name, region, region2, topic, kind, "
               "apply_end_at, event_start_at FROM posts WHERE "
               + " AND ".join(where) + " ORDER BY topic, source_name")
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()

    rows = _dedup_rows(rows)      # 중복 내용은 하나만
    if new_only:                  # 이미 발행한 항목 제외
        from .db import Database
        _db = Database(DB_PATH)
        try:
            done = _db.published_keys()
        finally:
            _db.close()
        rows = [r for r in rows if _pub_key(r) not in done]
    keys = [_pub_key(r) for r in rows]
    titles = {_pub_key(r): (r.get("title") or "") for r in rows}
    by_topic: dict[str, list] = {}
    for r in rows:
        by_topic.setdefault(r.get("topic") or "기타", []).append(r)

    if scope == "national":
        reg_label = "전국"
    elif reg_list:
        reg_label = "·".join(reg_list)
    else:
        reg_label = "지역" if scope == "local" else "전국"
    order = [t for t in _TOPIC_ORDER if not topic_list or t in topic_list]
    lines = [f"# [{reg_label}온동네] {date_label} 공공정보 소식", ""]
    lines.append(f"> {reg_label} 신규 소식 {len(rows)}건" if rows
                 else f"> {date_label} 신규 소식이 없습니다.")
    lines.append("")
    for topic in order:
        items = by_topic.get(topic)
        if not items:
            continue
        lines.append(f"## {_TOPIC_EMOJI.get(topic, '📌')} {topic} ({len(items)})")
        for r in items:
            loc = r.get("region2") or r.get("region") or ""
            src = r.get("source_name") or ""
            tail = ""
            if r.get("apply_end_at"):
                tail = f" · ~{_fmtd(r['apply_end_at'])} 마감"
            elif r.get("event_start_at"):
                tail = f" · {_fmtd(r['event_start_at'])}"
            lines.append(f"- {r['title']}  \n  {src}{(' · '+loc) if loc and loc != '전국' else ''}{tail}  \n  {r['url']}")
            lines.append("")   # 항목 사이 빈 줄(가시성)
        lines.append("")
    return {"date": date_label, "region": reg_label, "count": len(rows),
            "markdown": "\n".join(lines), "scope": scope,
            "keys": keys, "titles": titles}


@app.post("/api/digest/mark-published")
async def digest_mark_published(request: Request):
    """일일글을 카페에 올린 뒤 호출 → 해당 항목들을 발행 완료로 기록해
    다음날 일일글에서 제외한다. body: {scope, keys:[...], titles:{key:title}}"""
    body = await request.json()
    keys = body.get("keys") or []
    if not keys:
        return {"ok": True, "marked": 0}
    from .db import Database
    db = Database(DB_PATH)
    try:
        db.mark_published(keys, body.get("scope", ""), body.get("titles") or {})
        db.prune_published(90)
    finally:
        db.close()
    return {"ok": True, "marked": len(keys)}


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
        stats = {r["source_id"]: (r["n"], r["last"]) for r in conn.execute(
            "SELECT source_id, COUNT(*) n, MAX(collected_at) last FROM posts GROUP BY source_id")}
    finally:
        conn.close()
    out = []
    for s in cfg.get("sources", []):
        n, last = stats.get(s["id"], (0, None))
        out.append({"id": s["id"], "name": s.get("name", s["id"]),
                    "category": s.get("category", ""), "type": s.get("type", ""),
                    "region": s.get("region", "전국"), "org_type": s.get("org_type", "기타"),
                    "enabled": s.get("enabled", True), "posts": n, "last_str": _fmt(last)})
    return {"sources": out, "categories": cfg.get("categories", [])}


@app.post("/api/admin/bulk-toggle")
async def admin_bulk_toggle(request: Request):
    """여러 소스 일괄 켜기/끄기. body: {ids:[...], enabled:bool}"""
    if not _is_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    body = await request.json()
    ids = set(body.get("ids") or [])
    enabled = bool(body.get("enabled"))
    cfg = _load_config()
    n = 0
    for s in cfg.get("sources", []):
        if s["id"] in ids:
            s["enabled"] = enabled; n += 1
    _save_config(cfg)
    return {"ok": True, "count": n, "enabled": enabled}


# ── 기관 발굴 패널 API ─────────────────────────────────────────────────────
@app.get("/api/admin/candidates")
def admin_candidates(request: Request, status: str = "new"):
    """발굴된 기관 후보 목록. crawl_type로 크롤 가능성 표시."""
    if not _is_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    conn = _ro_conn()
    try:
        q = "SELECT * FROM candidates"
        params = []
        if status and status != "all":
            q += " WHERE status=?"; params.append(status)
        q += " ORDER BY CASE crawl_type WHEN 'gnuboard' THEN 0 WHEN 'html' THEN 1 " \
             "WHEN 'rss' THEN 2 WHEN 'html?' THEN 3 ELSE 9 END, name"
        rows = [dict(r) for r in conn.execute(q, params).fetchall()]
        lm = conn.execute("SELECT value FROM meta WHERE key='last_discovery'").fetchone()
    finally:
        conn.close()
    crawlable = sum(1 for r in rows if r.get("crawl_type") in ("gnuboard", "html", "rss", "naver_blog"))
    last_disc = _fmt(int(lm[0])) if lm and lm[0] else None
    return {"candidates": rows, "crawlable": crawlable, "last_discovery": last_disc}


@app.post("/api/admin/candidate-register")
async def admin_candidate_register(request: Request):
    """후보를 게시판 자동탐색·검증 후 등록·수집. body: {cand_key, name?, region?, region2?, org_type?, category?}"""
    if not _is_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    from .discovery import register_candidate
    body = await request.json()
    ck = body.get("cand_key")
    ov = {k: body[k] for k in ("name", "region", "region2", "org_type", "category") if body.get(k)}
    res = register_candidate(ck, ov)
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@app.post("/api/admin/candidate-reject")
async def admin_candidate_reject(request: Request):
    if not _is_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    from .db import Database
    body = await request.json()
    db = Database(DB_PATH)
    db.set_candidate_status(body.get("cand_key"), "rejected")
    db.close()
    return {"ok": True}


@app.post("/api/admin/discover")
async def admin_discover(request: Request):
    """발굴 실행(느릴 수 있음). body: {regions:[...]}"""
    if not _is_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    from .discovery import run
    body = await request.json()
    regions = body.get("regions") or ["창원", "김해"]
    res = run(regions)
    return {"ok": True, **res}


@app.post("/api/admin/auto-register")
async def admin_auto_register(request: Request):
    """적체된 'new' 후보를 게시판 자동탐색·검증 후 통과분만 일괄 등록.
    body: {limit?} — 검증 통과(≥2건)한 후보만 등록, 나머지는 review로 분리."""
    if not _is_admin(request):
        return JSONResponse({"error": "관리자 전용"}, status_code=403)
    from .discovery import auto_register
    body = await request.json()
    res = auto_register(limit=body.get("limit"))
    return {"ok": True, **res}


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


# ── 주간 기관 자동 발굴 (매주 1회) ─────────────────────────────────────────
DISCOVERY_INTERVAL_S = 7 * 24 * 60 * 60      # 주 1회
_DISCOVERY_CHECK_S = 6 * 60 * 60             # 6시간마다 경과 확인


def _discovery_loop():
    from .discovery import run as discover_run
    from .db import Database
    while True:
        try:
            db = Database(DB_PATH)
            last = db.get_meta("last_discovery")
            db.close()
            last_ms = int(last) if last else 0
            if int(time.time() * 1000) - last_ms >= DISCOVERY_INTERVAL_S * 1000:
                regions = _load_config().get("discovery_regions") or ["창원", "김해"]
                res = discover_run(regions)
                db = Database(DB_PATH)
                db.set_meta("last_discovery", str(int(time.time() * 1000)))
                db.close()
                print(f"[info] 주간 발굴 완료 — 신규 후보 {res.get('added')}곳 "
                      f"(총 대기 {res.get('total_new')})")
        except Exception as e:
            print("[info] 주간 발굴 오류:", e)
        time.sleep(_DISCOVERY_CHECK_S)


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
        threading.Thread(target=_discovery_loop, daemon=True).start()


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

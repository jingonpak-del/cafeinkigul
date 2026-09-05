"""게시판 가치 분석 (읽기전용) — '어떤 게시판/주제가 인기·가치 있는가'.

크롤 엔진을 건드리지 않고 articles + board_detections를 집계한다.
- 게시판별: 글 수, 인기글 진입 수/비율, 평균 조회증가·댓글, 최근 활동
- 가치점수로 랭크 → 등록/카테고리화 추천(특히 crawl_all인데 아직 분류 안 된 게시판)
- 주제(카페 theme) 롤업 → 새 카테고리 신설 판단 근거(Phase 4)

이 모듈은 읽기전용이다. 어떤 것도 크롤·수정하지 않는다.

실행:
    python -m src.poc.analytics boards          # 가치 상위 게시판
    python -m src.poc.analytics boards --unclassified   # 아직 분류 안 된 것만
    python -m src.poc.analytics themes          # 주제별 가치 롤업
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

from .paths import CONFIG_PATH, DB_PATH


# ── 대시보드 노출 성격 분류 (지속 파이프라인용) ──────────────────────────────
# "줌마렐라"(동네 생활밀착형 커뮤니티) 대상과 성격이 다른 카페를 판정한다.
# 발굴이 매일 자동으로 카페를 채택하므로(discovery.run_discovery), 이 판정은
# 정적 스냅샷이 아니라 채택되는 그 순간 함수 호출로 이루어져야 한다 — 그래야
# 화면 기본 제외 목록(config.dashboard_default_exclude)이 카페 풀 성장을 따라간다.
EXCLUDE_THEMES = {
    "FPS/슈팅게임", "게임일반", "레이싱게임", "롤플레잉게임", "모바일게임",
    "스포츠게임", "시뮬레이션게임", "액션/어드벤쳐게임",
    "사진", "스트리머/유튜버", "국내가수",
    "시험/자격증", "교육일반", "고등학교교육", "중학교교육", "영어", "중국어",
    "부동산", "취업/창업", "재테크", "증권", "경제기관/단체",
    "자동차", "자전거", "등산/낚시", "마라톤/달리기", "수영", "탁구/당구",
    "모형", "이색취미", "파충류/양서류", "어류/갑각류",
    "음악일반", "운영체제", "취미일반", "업종/직종", "호텔/리조트", "철학", "야구",
    "결혼", "연인/친구", "이민",
    "동남아시아", "일본", "중국", "유럽", "미주", "국내여행",
}
# theme이 없거나(수동등록) 지역명(동네카페)이면 기본은 유지 대상이지만, 카페 '이름'
# 자체가 특정 전문/투자 주제를 강하게 시사하면 theme과 무관하게 제외한다. 지역코드로
# 발굴된 카페는 theme이 항상 지역명으로만 찍혀 실제 성격(예: 재테크 브랜드 카페)이
# 가려지는 경우가 있어(실측: "텐인텐 대전세종"=재테크 카페인데 theme="대전광역시")
# 이름 기반 보강 판정이 꼭 필요하다.
_FINANCE_KEYWORDS = ["주식", "트레이더", "증권", "재테크", "부동산", "적금", "펀드",
                     "부자되기", "투자", "텐인텐"]
_FINANCE_ALLOW = ["절약", "짠돌이", "짠테크", "알뜰"]   # 소비절약형은 앱테크 정신과 맞아 예외


def classify_exclude(name: str, theme: str | None) -> bool:
    """True면 '성격이 다름' → 대시보드 기본 표시에서 제외 대상(수집은 계속됨)."""
    name = name or ""
    if any(k in name for k in _FINANCE_KEYWORDS) and not any(k in name for k in _FINANCE_ALLOW):
        return True
    if theme is None:
        return False           # 수동등록(원래 핵심 카페) — 항상 유지
    return theme in EXCLUDE_THEMES


def recompute_default_exclude(conn_or_cfg) -> list[int]:
    """등록된 전 카페를 재판정해 제외 club_id 목록을 새로 계산한다(전체 재검사용).
    conn_or_cfg: sqlite3 connection(cafe_candidates 조회용). config는 내부에서 새로 읽는다."""
    cfg = _config()
    themes = dict(conn_or_cfg.execute("SELECT club_id, theme FROM cafe_candidates").fetchall())
    out = []
    for c in cfg.get("cafes", []):
        cid = c["club_id"]
        name = c.get("name") or c["cluburl"]
        if classify_exclude(name, themes.get(cid)):
            out.append(cid)
    return out


# ── config 도우미 ────────────────────────────────────────────────────────────
def _config() -> dict:
    try:
        return json.loads(Path(CONFIG_PATH).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _classified_menus(cfg: dict) -> set[tuple[int, int]]:
    """이미 분류(category)가 지정된 (club_id, menu_id)."""
    out = set()
    for c in cfg.get("cafes", []):
        for b in c.get("boards", []):
            if b.get("type") == "menu" and b.get("category"):
                out.add((c["club_id"], b["menu_id"]))
    return out


def _cafe_meta(conn) -> dict[int, dict]:
    """club_id → {name, theme}. 이름은 config, 주제는 cafe_candidates(있으면)."""
    cfg = _config()
    meta = {c["club_id"]: {"name": c.get("name") or c["cluburl"],
                           "cluburl": c["cluburl"], "theme": ""}
            for c in cfg.get("cafes", [])}
    try:
        for r in conn.execute("SELECT club_id, name, theme FROM cafe_candidates"):
            m = meta.setdefault(r["club_id"], {"name": r["name"], "cluburl": "", "theme": ""})
            if r["theme"]:
                m["theme"] = r["theme"]
    except sqlite3.Error:
        pass
    return meta


# ── 가치 점수 ────────────────────────────────────────────────────────────────
def value_score(n: int, pop_n: int, avg_delta: float, avg_comments: float) -> float:
    """게시판 가치: 인기글 진입률 + 반응(조회증가·댓글) + 볼륨(로그).
    상대 랭킹용 — 절대값에 의미를 두지 않는다."""
    pop_rate = (pop_n / n) if n else 0.0
    return round(
        pop_rate * 100                       # 인기글 진입률(핵심)
        + min(avg_comments or 0, 20) * 1.5    # 댓글 반응
        + min((avg_delta or 0) / 10, 30)      # 조회 증가
        + math.log10(n + 1) * 5,              # 볼륨
        1)


# ── 게시판 통계 ──────────────────────────────────────────────────────────────
def board_stats(conn, *, min_n: int = 10) -> list[dict]:
    """(cafe, menu)별 집계. read-only sqlite3 conn(row_factory=Row) 필요."""
    rows = conn.execute(
        """
        SELECT a.cafe_id AS cafe_id, a.menu_id AS menu_id,
               COALESCE(MAX(NULLIF(a.menu_name,'')), '') AS menu_name,
               COUNT(*) AS n,
               SUM(CASE WHEN p.article_id IS NOT NULL THEN 1 ELSE 0 END) AS pop_n,
               AVG(a.read_delta)  AS avg_delta,
               AVG(a.cur_comment) AS avg_comments,
               MAX(a.write_ts)    AS last_write
        FROM articles a
        LEFT JOIN (SELECT DISTINCT cafe_id, article_id
                     FROM board_detections WHERE board_key='popular') p
          ON p.cafe_id = a.cafe_id AND p.article_id = a.article_id
        WHERE (a.status IS NULL OR a.status != 'deleted')
          AND a.menu_id IS NOT NULL AND a.menu_id != 0
        GROUP BY a.cafe_id, a.menu_id
        HAVING n >= ?
        """,
        (min_n,)).fetchall()
    out = []
    for r in rows:
        n, pop_n = r["n"], r["pop_n"] or 0
        out.append({
            "cafe_id": r["cafe_id"], "menu_id": r["menu_id"],
            "menu_name": r["menu_name"] or "",
            "n": n, "pop_n": pop_n,
            "pop_rate": round(pop_n / n, 3) if n else 0.0,
            "avg_delta": round(r["avg_delta"] or 0, 1),
            "avg_comments": round(r["avg_comments"] or 0, 1),
            "last_write": r["last_write"] or 0,
            "score": value_score(n, pop_n, r["avg_delta"] or 0, r["avg_comments"] or 0),
        })
    return out


def rank_boards(conn, *, min_n: int = 10, limit: int = 40,
                only_unclassified: bool = False) -> list[dict]:
    """가치 상위 게시판. only_unclassified면 아직 분류 안 된 것만(추천 대상)."""
    cfg = _config()
    classified = _classified_menus(cfg)
    meta = _cafe_meta(conn)
    stats = board_stats(conn, min_n=min_n)
    for s in stats:
        key = (s["cafe_id"], s["menu_id"])
        s["classified"] = key in classified
        m = meta.get(s["cafe_id"], {})
        s["cafe_name"] = m.get("name", str(s["cafe_id"]))
        s["cluburl"] = m.get("cluburl", "")
        s["theme"] = m.get("theme", "")
    if only_unclassified:
        stats = [s for s in stats if not s["classified"]]
    stats.sort(key=lambda x: x["score"], reverse=True)
    return stats[:limit]


def theme_rollup(conn, *, min_n: int = 10) -> list[dict]:
    """주제(카페 theme)별 가치 롤업 — 새 카테고리 신설 근거(Phase 4).
    '운동 카페들이 인기 많다' 같은 신호를 잡는다."""
    meta = _cafe_meta(conn)
    agg: dict[str, dict] = {}
    for s in board_stats(conn, min_n=min_n):
        theme = meta.get(s["cafe_id"], {}).get("theme") or "(주제없음)"
        a = agg.setdefault(theme, {"theme": theme, "boards": 0, "articles": 0,
                                   "pop_n": 0, "score_sum": 0.0, "cafes": set()})
        a["boards"] += 1
        a["articles"] += s["n"]
        a["pop_n"] += s["pop_n"]
        a["score_sum"] += s["score"]
        a["cafes"].add(s["cafe_id"])
    out = []
    for a in agg.values():
        out.append({"theme": a["theme"], "cafes": len(a["cafes"]), "boards": a["boards"],
                    "articles": a["articles"], "pop_n": a["pop_n"],
                    "avg_score": round(a["score_sum"] / a["boards"], 1) if a["boards"] else 0.0})
    out.sort(key=lambda x: (x["cafes"], x["avg_score"]), reverse=True)
    return out


# ── 추천(Phase 5-3) ─────────────────────────────────────────────────────────
def _cafe_category_hint(cfg: dict) -> dict[int, str]:
    """club_id → 그 카페 등록보드들의 다수 카테고리(승격 시 제안 카테고리)."""
    from collections import Counter
    out = {}
    for c in cfg.get("cafes", []):
        cats = [b.get("category") for b in c.get("boards", [])
                if b.get("type") == "menu" and b.get("category")]
        if cats:
            out[c["club_id"]] = Counter(cats).most_common(1)[0][0]
    return out


def recommend(conn, *, min_n: int = 20, limit: int = 20) -> dict:
    """통째 corpus 분석 → 큐레이션 추천.
    - promote: 아직 분류 안 된 고가치 게시판 + 제안 카테고리(카페 다수분류/주제) → '승격' 후보.
    - new_categories: 여러 카페에 걸쳐 가치 높은 미등록 주제 → '새 카테고리' 후보.
    """
    cfg = _config()
    existing = set(cfg.get("categories", []))
    hint = _cafe_category_hint(cfg)
    boards = rank_boards(conn, min_n=min_n, limit=limit, only_unclassified=True)
    promote = []
    for b in boards:
        sug = hint.get(b["cafe_id"]) or (b["theme"] if b.get("theme") in existing else "") or ""
        b["suggest_category"] = sug
        promote.append(b)
    new_categories = [t for t in theme_rollup(conn, min_n=min_n)
                      if t["theme"] and t["theme"] != "(주제없음)"
                      and t["cafes"] >= 2 and t["theme"] not in existing][:8]
    return {"promote": promote, "new_categories": new_categories}


# ── CLI ─────────────────────────────────────────────────────────────────────
def _ro_conn():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main():
    import argparse
    p = argparse.ArgumentParser(prog="analytics")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("boards", help="가치 상위 게시판")
    b.add_argument("--min-n", type=int, default=10)
    b.add_argument("--limit", type=int, default=30)
    b.add_argument("--unclassified", action="store_true", help="분류 안 된 것만")
    sub.add_parser("themes", help="주제별 가치 롤업")
    a = p.parse_args()
    conn = _ro_conn()
    try:
        if a.cmd == "boards":
            rows = rank_boards(conn, min_n=a.min_n, limit=a.limit,
                               only_unclassified=a.unclassified)
            print(f"{'점수':>6} {'인기율':>6} {'글수':>7} {'댓글':>5}  게시판 (카페)")
            for r in rows:
                mark = "" if r["classified"] else "★"
                print(f"{r['score']:>6.1f} {r['pop_rate']*100:>5.1f}% {r['n']:>7,} "
                      f"{r['avg_comments']:>5.1f}  {mark}{r['menu_name'] or r['menu_id']} "
                      f"({r['cafe_name']})")
        else:
            for r in theme_rollup(conn, min_n=a.min_n):
                print(f"  {r['theme'][:16]:16} 카페 {r['cafes']:>3} 게시판 {r['boards']:>3} "
                      f"글 {r['articles']:>8,} 인기 {r['pop_n']:>6,} 평균가치 {r['avg_score']:>6.1f}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

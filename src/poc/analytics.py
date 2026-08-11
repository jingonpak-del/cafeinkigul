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

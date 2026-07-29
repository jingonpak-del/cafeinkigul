"""카페 발굴 — 후보 카페 1건을 조사(probe)해 판단 지표를 산출한다.

현재: 검증된 cafe_api 엔드포인트만 사용 → 카페 주소(cluburl)만 있으면 후보 생성.
      (이름·게시판·일발행량·가입필요는 지금 동작. 회원수/대표·동네 플래그는 best-effort.)
추후: 섹션(themes/areas/powers) 내부 JSON API 확보 후 '매일 자동 5건 열거'를 얹는다
      (발굴 설계 0단계). 그 API가 회원수·대표/동네 여부를 함께 제공한다.
"""
from __future__ import annotations

import math

from . import cafe_api


def _estimate_daily_posts(arts) -> float | None:
    """최근 글들의 작성 시각 간격으로 하루 발행량 추정."""
    ts = sorted((a.write_ts for a in arts if a.write_ts), reverse=True)
    if len(ts) < 2:
        return None
    span_ms = ts[0] - ts[-1]
    if span_ms <= 0:
        return None
    days = span_ms / 86_400_000
    return round((len(ts) - 1) / days, 1) if days > 0 else None


def _score(c: dict) -> float:
    """참조가치 점수(정렬용): 규모(회원수) + 활동성(일발행) − 가입장벽."""
    s = 0.0
    if c.get("member_count"):
        s += math.log10(c["member_count"] + 1) * 10
    s += min(c.get("daily_posts") or 0, 50)
    if c.get("join_required"):
        s -= 15
    return round(s, 1)


def probe_cafe(cluburl: str, *, source: str = "manual", theme: str = "",
               client=None) -> dict:
    """카페 주소를 조사해 후보 dict를 반환. cafe_candidates 스키마와 1:1."""
    own = client is None
    client = client or cafe_api.make_client()
    out = {
        "cluburl": cluburl, "club_id": None, "name": cluburl,
        "source": source, "theme": theme, "is_power": 0, "is_local": 0,
        "member_count": None, "daily_posts": None, "open_level": None,
        "join_required": 0, "sample_boards": "", "score": 0.0,
    }
    try:
        cid = cafe_api.resolve_club_id(cluburl, client=client)
        out["club_id"] = cid

        boards = []
        try:
            boards = cafe_api.fetch_board_list(cid, client=client)
            out["sample_boards"] = ", ".join(b["name"] for b in boards[:5])
        except Exception:
            pass

        info = cafe_api.fetch_cafe_info(cid, client=client)
        if info.get("name"):
            out["name"] = info["name"]
        out["member_count"] = info.get("member_count")
        out["open_level"] = info.get("open_level")

        join_required = 0
        if boards:                       # 첫 게시판 최근글 → 일발행량 + 접근성
            try:
                arts = cafe_api.fetch_article_list(
                    cid, boards[0]["menu_id"], per_page=30, client=client)
                out["daily_posts"] = _estimate_daily_posts(arts)
            except Exception:
                join_required = 1
        try:                             # 인기글(메인화면 반영 대상) 접근 가능?
            cafe_api.fetch_popular_list(cid, per_page=5, client=client)
        except Exception:
            join_required = 1
        out["join_required"] = join_required

        out["score"] = _score(out)
        return out
    finally:
        if own:
            client.close()

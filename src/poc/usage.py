"""계정별 API 사용량 시계열 스냅샷.

왜 필요한가 — 네이버 카페 내부 엔드포인트(`apis.naver.com/cafe-web/...`)에는 공개된
요청 한도가 없다. 개발자센터의 일 25,000회는 오픈API(`openapi.naver.com`) 얘기라
여기엔 적용되지 않는다. 그래서 상한은 **관측으로만** 알 수 있다.

`ratelimit.db`의 buckets 테이블은 현재값만 들고 있다(hour_count는 매시 리셋). 이력이
없으면 나중에 계정을 늘렸을 때 "어디서부터 막히기 시작했는지"를 되짚을 수 없다.
이 모듈이 그 이력을 남긴다.

방식: 주기적으로 buckets를 훑어 (account, hour_start)별 최대 hour_count를 적재한다.
카운터가 매시 0으로 리셋되므로 최대값이 곧 그 시간의 총 요청 수다. 요청 경로(acquire)를
건드리지 않아 크롤링에 영향이 없다.

같이 남기는 신호:
  min_factor  그 시간에 관측된 최저 감속계수. 1.0 미만이면 429/403을 맞아 감속한 것이다.
  auth_errors 401 누적. 세션 문제의 선행 지표.
  tripped     서킷 차단 발생 여부.
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime

from .paths import DATA_DIR, DB_PATH

RATELIMIT_DB = DATA_DIR / "db" / "ratelimit.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_usage (
    account     TEXT    NOT NULL,
    hour_start  INTEGER NOT NULL,   -- 시간 경계 epoch(초)
    requests    INTEGER NOT NULL,   -- 그 시간의 요청 수
    min_factor  REAL,               -- 최저 감속계수 (1.0=무감속, <1=429/403 맞음)
    auth_errors INTEGER DEFAULT 0,
    tripped     INTEGER DEFAULT 0,
    updated_at  INTEGER,
    PRIMARY KEY (account, hour_start)
);
CREATE INDEX IF NOT EXISTS idx_api_usage_hour ON api_usage(hour_start);
"""


def _open(path, readonly=False):
    uri = f"file:{str(path).replace(chr(92), '/')}" + ("?mode=ro" if readonly else "")
    con = sqlite3.connect(uri, uri=True, timeout=10)
    con.execute("PRAGMA busy_timeout=5000")
    return con


def snapshot() -> int:
    """지금 시점의 buckets를 읽어 api_usage에 반영. 갱신된 계정 수를 반환."""
    try:
        src = _open(RATELIMIT_DB, readonly=True)
    except sqlite3.Error:
        return 0
    try:
        rows = src.execute(
            "SELECT account, hour_start, hour_count, factor, auth_errors, tripped_until "
            "FROM buckets"
        ).fetchall()
    except sqlite3.Error:
        return 0
    finally:
        src.close()
    if not rows:
        return 0

    now = int(time.time())
    dst = _open(DB_PATH)
    try:
        dst.executescript(SCHEMA)
        n = 0
        for account, hour_start, hour_count, factor, auth_errors, tripped_until in rows:
            if not account or hour_start is None:
                continue
            # 테스트용 버킷(test/xproc/lanetest)은 이력에 남길 이유가 없다.
            if account in ("test", "xproc", "lanetest"):
                continue
            dst.execute(
                """INSERT INTO api_usage
                     (account, hour_start, requests, min_factor, auth_errors, tripped, updated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(account, hour_start) DO UPDATE SET
                     requests    = MAX(api_usage.requests, excluded.requests),
                     min_factor  = MIN(COALESCE(api_usage.min_factor, 1.0),
                                       COALESCE(excluded.min_factor, 1.0)),
                     auth_errors = MAX(api_usage.auth_errors, excluded.auth_errors),
                     tripped     = MAX(api_usage.tripped, excluded.tripped),
                     updated_at  = excluded.updated_at""",
                (account, int(hour_start), int(hour_count or 0), float(factor or 1.0),
                 int(auth_errors or 0), 1 if (tripped_until or 0) > 0 else 0, now),
            )
            n += 1
        dst.commit()
        return n
    finally:
        dst.close()


def daily(days: int = 14) -> list[dict]:
    """계정별 일 사용량 집계."""
    since = int(time.time()) - days * 86400
    con = _open(DB_PATH, readonly=True)
    try:
        rows = con.execute(
            """SELECT account,
                      date(hour_start, 'unixepoch', 'localtime') AS d,
                      SUM(requests)  AS total,
                      MAX(requests)  AS peak_hour,
                      MIN(min_factor) AS worst_factor,
                      MAX(auth_errors) AS auth_errors,
                      MAX(tripped)   AS tripped
               FROM api_usage WHERE hour_start >= ?
               GROUP BY account, d ORDER BY d DESC, total DESC""",
            (since,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [dict(zip(("account", "date", "total", "peak_hour",
                      "worst_factor", "auth_errors", "tripped"), r)) for r in rows]


def ceiling_hint() -> dict:
    """관측된 상한 힌트. 감속 없이 통과한 최대 시간당 요청 수가 '적어도 이만큼은 된다'는 하한."""
    con = _open(DB_PATH, readonly=True)
    try:
        clean = con.execute(
            "SELECT MAX(requests) FROM api_usage WHERE COALESCE(min_factor,1.0) >= 1.0"
        ).fetchone()[0]
        throttled = con.execute(
            "SELECT MIN(requests) FROM api_usage WHERE COALESCE(min_factor,1.0) < 1.0 AND requests > 0"
        ).fetchone()[0]
        hours = con.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0]
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return {
        "observed_hours": hours,
        "max_clean_hour": clean,          # 이만큼은 문제없이 통과했다
        "min_throttled_hour": throttled,  # 감속을 맞은 가장 낮은 시간당 요청 수
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="계정별 API 사용량 스냅샷/조회")
    p.add_argument("cmd", choices=["snapshot", "report"], nargs="?", default="report")
    p.add_argument("--days", type=int, default=14)
    args = p.parse_args(argv)

    if args.cmd == "snapshot":
        print(f"스냅샷 반영: 계정 {snapshot()}개")
        return

    snapshot()   # 조회 전에 최신값 한 번 반영
    rows = daily(args.days)
    if not rows:
        print("기록된 사용량이 없습니다. 워처가 돌면 5분마다 쌓입니다.")
        return
    print(f"{'날짜':<12}{'계정':<18}{'일요청':>8}{'최대/시':>8}{'감속':>7}{'401':>5}  비고")
    print("-" * 72)
    for r in rows:
        note = []
        if r["worst_factor"] is not None and r["worst_factor"] < 1.0:
            note.append("감속발생")
        if r["tripped"]:
            note.append("서킷차단")
        if r["auth_errors"]:
            note.append("인증오류")
        print(f"{r['date']:<12}{r['account']:<18}{r['total']:>8,}{r['peak_hour']:>8,}"
              f"{(r['worst_factor'] or 1.0):>7.2f}{r['auth_errors']:>5}  {' '.join(note)}")
    h = ceiling_hint()
    print()
    print(f"관측 시간 수: {h.get('observed_hours', 0)}")
    print(f"감속 없이 통과한 최대 시간당 요청: {h.get('max_clean_hour') or '-'}"
          "  ← 실제 상한은 최소 이 값 이상")
    mt = h.get("min_throttled_hour")
    print(f"감속을 맞은 최저 시간당 요청     : {mt if mt else '없음 (아직 한 번도 막힌 적 없음)'}")


if __name__ == "__main__":
    main()

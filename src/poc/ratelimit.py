"""계정별 전역 요청 예산 — 프로세스를 넘어 공유되는 토큰버킷.

스트림 워처(서버 프로세스)와 백필 워커(별도 프로세스)가 같은 계정으로 동시에 요청하면
각자 1 req/s를 지켜도 합쳐서 2 req/s가 된다. 그래서 레이트 상태를 SQLite 파일 하나에 두고
프로세스가 몇 개든 계정당 예산이 하나가 되게 한다. SQLite의 쓰기 락이 프로세스 간
상호배제를 대신한다(획득당 1ms 남짓, 1~1.5 req/s에서는 무시할 수준).

담고 있는 것:
  · 토큰버킷      초당 rate, 최대 burst
  · 시간당 상한   hourly_cap (버킷과 별개의 하드캡)
  · 야간 가속     night_hours 구간에서만 rate를 올린다
  · 적응형 감속   429/403이 나오면 즉시 절반으로 → 서서히 복구
  · 서킷 브레이커 401이 연달아 나오면(세션 만료) 전면 정지 + 알림 대상
  · 지터          기계적으로 정확한 간격이 오히려 눈에 띄므로 ±30% 흔든다
"""
from __future__ import annotations

import random
import sqlite3
import time

from .paths import DATA_DIR

DB_FILE = DATA_DIR / "db" / "ratelimit.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS buckets (
    account          TEXT PRIMARY KEY,
    tokens           REAL NOT NULL,
    last_refill      REAL NOT NULL,
    hour_start       REAL NOT NULL,
    hour_count       INTEGER NOT NULL DEFAULT 0,
    factor           REAL NOT NULL DEFAULT 1.0,   -- 감속 계수 (1.0 = 정상)
    factor_next      REAL NOT NULL DEFAULT 0.0,   -- 이 시각 이후 복구 시도
    auth_errors      INTEGER NOT NULL DEFAULT 0,
    tripped_until    REAL NOT NULL DEFAULT 0.0    -- 서킷 브레이커 해제 시각
);
"""

DEFAULTS = {
    "rate": 1.0,            # 평상시 초당 요청
    "night_rate": 1.5,      # 야간(백필) 가속
    "night_hours": (0, 8),  # [0시, 8시)
    "burst": 3.0,
    "hourly_cap": 3000,
    # reserve 1단위당 시간당 상한에서 깎는 양. 스트림(0)은 3000, 발굴(0.5)은 2750,
    # 백필(1.0)은 2500까지만 쓴다 → 스트림 몫 500건/시간이 항상 남는다.
    "hourly_reserve": 500,
    "min_factor": 0.25,     # 감속 하한
    "penalty_s": 600,       # 감속 유지 시간
    "recover_s": 60,        # 복구 시도 간격
    "trip_after": 3,        # 연속 인증오류 N회 → 차단
    "trip_s": 1800,         # 차단 유지 시간
    "jitter": 0.30,
}


# 레인 우선순위 — 값이 클수록 양보한다. 스트림은 신규글을 놓치면 복구가 안 되므로 0.
RESERVE_STREAM = 0.0
RESERVE_DISCOVERY = 0.5
RESERVE_BACKFILL = 1.0


class Tripped(RuntimeError):
    """서킷 브레이커 작동 — 세션이 죽었거나 계정이 막혔다. 사람이 봐야 한다."""


class RateLimiter:
    def __init__(self, account: str, **opts):
        self.account = account or "default"
        self.opt = {**DEFAULTS, **opts}
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(DB_FILE, timeout=30, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.executescript(SCHEMA)
        now = time.time()
        self.conn.execute(
            "INSERT OR IGNORE INTO buckets (account, tokens, last_refill, hour_start) "
            "VALUES (?,?,?,?)", (self.account, self.opt["burst"], now, now))

    # --- 내부 ---------------------------------------------------------------
    def _rate_now(self, factor: float) -> float:
        lo, hi = self.opt["night_hours"]
        h = time.localtime().tm_hour
        night = (lo <= h < hi) if lo < hi else (h >= lo or h < hi)
        base = self.opt["night_rate"] if night else self.opt["rate"]
        return max(base * factor, 0.05)

    def _attempt(self, reserve: float = 0.0) -> float:
        """토큰 1개를 시도한다. 성공하면 0, 아니면 기다려야 할 초를 돌려준다.

        reserve는 '이만큼은 남겨두고 가져간다'는 뜻이다. 백필처럼 급하지 않은 레인에
        reserve를 주면, 버킷에 여유가 있을 때만 소비하므로 지연에 민감한 스트림 레인을
        굶기지 않는다. 같은 버킷을 두 프로세스가 다투면 분배가 크게 치우치기 때문에
        (실측 19:2) 공정성 대신 명시적 우선순위로 정리한다."""
        now = time.time()
        cur = self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT tokens, last_refill, hour_start, hour_count, factor, factor_next, "
                "tripped_until FROM buckets WHERE account=?", (self.account,)).fetchone()
            tokens, last, hstart, hcount, factor, fnext, tripped = row

            if tripped > now:
                raise Tripped(f"{self.account}: 인증 오류로 {int(tripped - now)}초간 정지")

            # 감속 복구: 벌칙 시간이 지났으면 조금씩 정상으로 되돌린다.
            if factor < 1.0 and now >= fnext:
                factor = min(1.0, factor * 1.5)
                fnext = now + self.opt["recover_s"]

            if now - hstart >= 3600:
                hstart, hcount = now, 0
            # 시간당 상한에도 레인 우선순위를 적용한다. 상한을 전 레인이 공평하게 나눠 쓰면
            # 백필이 먼저 다 태워버려 스트림까지 다음 정각까지 막힌다(실측: 2,571/3,000을
            # 백필이 점유). 낮은 우선순위일수록 상한을 낮게 잡아 스트림 몫을 남긴다.
            cap = self.opt["hourly_cap"] - reserve * self.opt["hourly_reserve"]
            if hcount >= cap:
                self.conn.execute("COMMIT")
                return max(1.0, 3600 - (now - hstart))

            rate = self._rate_now(factor)
            tokens = min(self.opt["burst"], tokens + (now - last) * rate)
            need = 1.0 + max(0.0, reserve)
            if tokens < need:
                self.conn.execute(
                    "UPDATE buckets SET tokens=?, last_refill=?, hour_start=?, hour_count=?, "
                    "factor=?, factor_next=? WHERE account=?",
                    (tokens, now, hstart, hcount, factor, fnext, self.account))
                self.conn.execute("COMMIT")
                return (need - tokens) / rate

            self.conn.execute(
                "UPDATE buckets SET tokens=?, last_refill=?, hour_start=?, hour_count=?, "
                "factor=?, factor_next=? WHERE account=?",
                (tokens - 1.0, now, hstart, hcount + 1, factor, fnext, self.account))
            self.conn.execute("COMMIT")
            return 0.0
        except Tripped:
            self.conn.execute("ROLLBACK")
            raise
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        finally:
            del cur

    # --- 공개 API -----------------------------------------------------------
    def acquire(self, timeout: float | None = None, reserve: float = 0.0) -> bool:
        """요청 1건 분의 예산을 얻을 때까지 대기. timeout 초과 시 False.

        reserve: 0=스트림(최우선), RESERVE_DISCOVERY, RESERVE_BACKFILL 참고."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            wait = self._attempt(reserve)
            if wait <= 0:
                j = self.opt["jitter"]
                if j:
                    time.sleep(random.uniform(0, j / max(self._rate_now(1.0), 0.05)))
                return True
            if deadline is not None and time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, 2.0))

    def penalize(self, reason: str = "429") -> float:
        """429/403 — 즉시 절반으로 감속하고 벌칙 시간을 건다. 새 factor 반환."""
        now = time.time()
        self.conn.execute("BEGIN IMMEDIATE")
        f = self.conn.execute("SELECT factor FROM buckets WHERE account=?",
                              (self.account,)).fetchone()[0]
        f = max(self.opt["min_factor"], f * 0.5)
        self.conn.execute(
            "UPDATE buckets SET factor=?, factor_next=? WHERE account=?",
            (f, now + self.opt["penalty_s"], self.account))
        self.conn.execute("COMMIT")
        return f

    def note_auth_error(self) -> bool:
        """401 등 인증 오류. 연속 N회면 서킷을 끊는다. 끊겼으면 True."""
        now = time.time()
        self.conn.execute("BEGIN IMMEDIATE")
        n = self.conn.execute("SELECT auth_errors FROM buckets WHERE account=?",
                              (self.account,)).fetchone()[0] + 1
        tripped = n >= self.opt["trip_after"]
        self.conn.execute(
            "UPDATE buckets SET auth_errors=?, tripped_until=? WHERE account=?",
            (n, now + self.opt["trip_s"] if tripped else 0.0, self.account))
        self.conn.execute("COMMIT")
        return tripped

    def note_ok(self) -> None:
        """정상 응답 — 인증 오류 카운터를 되돌린다."""
        self.conn.execute(
            "UPDATE buckets SET auth_errors=0 WHERE account=? AND auth_errors>0",
            (self.account,))

    def on_response(self, status_code: int) -> None:
        """HTTP 상태코드 하나로 감속/차단/복구를 판정한다(호출부 단순화용)."""
        if status_code in (429, 403):
            self.penalize(str(status_code))
        elif status_code == 401:
            self.note_auth_error()
        elif 200 <= status_code < 400:
            self.note_ok()

    def status(self) -> dict:
        r = self.conn.execute(
            "SELECT tokens, hour_count, factor, auth_errors, tripped_until "
            "FROM buckets WHERE account=?", (self.account,)).fetchone()
        return {"account": self.account, "tokens": round(r[0], 2), "hour_count": r[1],
                "factor": r[2], "auth_errors": r[3],
                "tripped": r[4] > time.time(),
                "rate_now": round(self._rate_now(r[2]), 2)}

    def reset_trip(self) -> None:
        """세션을 갱신한 뒤 사람이 푸는 용도."""
        self.conn.execute(
            "UPDATE buckets SET auth_errors=0, tripped_until=0 WHERE account=?",
            (self.account,))

    def close(self):
        self.conn.close()


_cache: dict[str, RateLimiter] = {}


def get(account: str | None = None, **opts) -> RateLimiter:
    key = account or "default"
    if key not in _cache:
        _cache[key] = RateLimiter(key, **opts)
    return _cache[key]

"""데이터 경로 한 곳 정의.

Phase 0(2026-08-07)에서 데이터를 C:에서 D:로 옮겼다. C: 잔여가 10.6GB(96% 사용)라
코퍼스가 쌓이면 수집이 멈추기 때문이다. 코드는 C:에, 데이터는 D:에 둔다.

환경변수 CORPUS_DATA_DIR 로 덮어쓸 수 있다(테스트·이전용).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("CORPUS_DATA_DIR") or r"D:\cafe-corpus")

DB_PATH = DATA_DIR / "db" / "tracker.db"
RAW_DIR = DATA_DIR / "raw"
LOG_DIR = DATA_DIR / "logs"

# 설정·비밀은 코드 옆에 남긴다(백업 정책이 다르다).
CONFIG_PATH = ROOT / "config" / "targets.json"


def prune_logs(prefix: str, days: int = 14) -> int:
    """오래된 잡 로그 정리. 스케줄 잡이 시작할 때 스스로 부른다.

    배치 파일에서 처리하지 않는 이유: 날짜 계산·삭제를 cmd로 쓰면 인코딩과 따옴표 문제로
    깨지기 쉽다. 잡 자신이 정리하는 편이 안전하다."""
    import time as _t
    cutoff = _t.time() - days * 86400
    n = 0
    try:
        for p in LOG_DIR.glob(f"{prefix}_*.log"):
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                n += 1
    except OSError:
        pass
    return n

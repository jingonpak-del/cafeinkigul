"""아이디관리(네이버마케팅\\아이디관리)와 크롤러 사이의 계정·세션 다리.

배경: 계정 정보가 두 곳에 따로 있었다.

  아이디관리   data/accounts.json + data/sessions/{KEY}.json   (Playwright storageState, 평문)
  크롤러       data/sessions/{sha256(id)[:24]}.session          (자체 포맷, DPAPI 암호화)

서로 몰라서 크롤러 쪽에 `내네이버아이디` 같은 정체불명 계정이 생겼다. 계정이 50개
규모가 되면 이 상태로는 관리가 안 된다. 아이디관리를 **계정·세션의 단일 소유자**로 두고
(PHASE0 스펙의 원래 설계), 크롤러는 여기를 통해 읽는다.

이 모듈은 읽기 전용이다. 아이디관리의 파일을 고치지 않는다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ID_MANAGER_ROOT = Path(r"C:\Users\USER\네이버마케팅\아이디관리")
ACCOUNTS_PATH = ID_MANAGER_ROOT / "data" / "accounts.json"
SESSIONS_DIR = ID_MANAGER_ROOT / "data" / "sessions"
FINGERPRINTS_DIR = ID_MANAGER_ROOT / "data" / "fingerprints"


@dataclass(frozen=True)
class Account:
    key: str                 # 아이디관리 키 (예: SNOWGREENT)
    naver_id: str
    name: str = ""
    memo: str = ""
    source: str = "idmanager"   # idmanager | crawler

    @property
    def session_path(self) -> Path:
        return SESSIONS_DIR / f"{self.key}.json"


def list_accounts() -> list[Account]:
    """아이디관리에 등록된 계정 전체."""
    try:
        raw = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for a in raw:
        key = a.get("key")
        if not key:
            continue
        out.append(Account(key=key, naver_id=a.get("naverId") or key.lower(),
                           name=a.get("name") or "", memo=a.get("memo") or ""))
    return out


def storage_state_to_cookies(state: dict[str, Any]) -> list[dict]:
    """Playwright storageState → 크롤러 CookieStore 포맷.

    차이는 만료 필드뿐이다: storageState는 `expires`(초, float, 세션쿠키는 -1),
    크롤러는 `expiry`(초, int). -1은 만료 없음(세션쿠키)이므로 필드를 빼야 한다 —
    -1을 그대로 넣으면 1969년 만료로 읽힌다.
    """
    out: list[dict] = []
    for c in state.get("cookies") or []:
        if not c.get("name") or c.get("value") is None or not c.get("domain"):
            continue
        item: dict[str, Any] = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path") or "/",
            "secure": bool(c.get("secure")),
            "httpOnly": bool(c.get("httpOnly")),
        }
        exp = c.get("expires")
        if exp is not None and exp > 0:
            item["expiry"] = int(exp)
        out.append(item)
    return out


def load_cookies(account: Account) -> list[dict] | None:
    """해당 계정의 세션을 크롤러 포맷으로. 없으면 None."""
    try:
        state = json.loads(account.session_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    cookies = storage_state_to_cookies(state)
    return cookies or None


def load_fingerprint(key: str) -> dict | None:
    """계정 고정 지문(창 크기·로케일 등). 아이디관리가 생성·소유한다."""
    try:
        return json.loads((FINGERPRINTS_DIR / f"{key}.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def has_login_cookies(cookies: list[dict] | None) -> bool:
    if not cookies:
        return False
    names = {c.get("name") for c in cookies}
    return "NID_AUT" in names and "NID_SES" in names

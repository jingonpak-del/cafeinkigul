"""공용 코어(navercafe_core.cookie_store)로 이관됨. 이 파일은 얇은 shim이다.

이 프로젝트의 entropy를 미리 물려 둔 CookieStore를 내보낸다. 호출부는
`CookieStore(session_dir)` 형태 그대로 쓰면 된다.
"""
from __future__ import annotations

from pathlib import Path

from navercafe_core.cookie_store import (
    SESSION_VERSION,
    CookieStore as _CookieStore,
    SessionRecord,
    _normalize_cookies,
)

from .dpapi import ENTROPY

__all__ = ["CookieStore", "SessionRecord", "SESSION_VERSION", "_normalize_cookies"]


class CookieStore(_CookieStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root, entropy=ENTROPY)

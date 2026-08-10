"""공용 코어(navercafe_core.dpapi)로 이관됨. 이 파일은 얇은 shim이다.

entropy는 프로젝트마다 다르다. 통일하면 기존 세션 파일을 못 읽으므로 여기서 고정한다.
호출부(`from .dpapi import protect, unprotect`)는 그대로 두면 된다.
"""
from __future__ import annotations

from navercafe_core.dpapi import DPAPIError, protect as _protect, unprotect as _unprotect

ENTROPY = b"ingigeul-tracker"

__all__ = ["protect", "unprotect", "DPAPIError", "ENTROPY"]


def protect(data: bytes, entropy: bytes = ENTROPY) -> bytes:
    return _protect(data, entropy)


def unprotect(data: bytes, entropy: bytes = ENTROPY) -> bytes:
    return _unprotect(data, entropy)

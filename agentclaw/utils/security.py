"""Security-oriented comparison helpers."""

from __future__ import annotations

import hmac
from typing import Union


ComparableSecret = Union[str, bytes, bytearray, memoryview]


def safe_compare_digest(left: ComparableSecret | None, right: ComparableSecret | None) -> bool:
    """Constant-time secret comparison that treats malformed text as a mismatch."""
    if left is None or right is None:
        return False
    try:
        left_bytes = left.encode("utf-8") if isinstance(left, str) else bytes(left)
        right_bytes = right.encode("utf-8") if isinstance(right, str) else bytes(right)
    except Exception:
        return False
    return hmac.compare_digest(left_bytes, right_bytes)


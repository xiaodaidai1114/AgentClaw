"""Authentication utility helpers."""

from __future__ import annotations


def mask_secret(value: str | None, *, visible: int = 6) -> str:
    """Return a log-safe representation of a secret."""
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "***"
    return f"{value[:visible]}...{value[-visible:]}"

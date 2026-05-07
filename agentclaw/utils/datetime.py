"""
Datetime helpers for mixed PostgreSQL timestamp column types.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def _local_timezone():
    """Return the current local timezone used by the running process."""
    return datetime.now().astimezone().tzinfo or timezone.utc


def is_aware_datetime(value: datetime) -> bool:
    """Whether a datetime carries timezone information."""
    return value.tzinfo is not None and value.utcoffset() is not None


def to_local_naive_datetime(value: Optional[datetime]) -> Optional[datetime]:
    """
    Normalize a datetime for PostgreSQL TIMESTAMP columns.

    Trace tables currently store naive local datetimes, so aware values coming
    from ISO query params must be converted to local naive datetimes first.
    """
    if value is None:
        return None
    if not is_aware_datetime(value):
        return value.replace(tzinfo=None)
    return value.astimezone(_local_timezone()).replace(tzinfo=None)


def to_local_aware_datetime(value: Optional[datetime]) -> Optional[datetime]:
    """
    Normalize a datetime for PostgreSQL TIMESTAMPTZ columns.
    """
    if value is None:
        return None
    local_tz = _local_timezone()
    if not is_aware_datetime(value):
        return value.replace(tzinfo=local_tz)
    return value.astimezone(local_tz)

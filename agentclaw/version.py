from __future__ import annotations

from pathlib import Path

_FALLBACK_VERSION = "1.0.8"


def get_version() -> str:
    """Return the project version from the repository VERSION file."""
    try:
        version_file = Path(__file__).resolve().parent.parent / "VERSION"
        version = version_file.read_text(encoding="utf-8").strip()
        return version or _FALLBACK_VERSION
    except Exception:
        return _FALLBACK_VERSION


__version__ = get_version()

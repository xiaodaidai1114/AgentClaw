from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class AudioArtifact:
    data: bytes
    mime_type: str | None = None
    filename: str | None = None
    ext: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    duration_ms: int | None = None


@dataclass
class Voice:
    name: str
    value: str
    language: list[str] | None = None


@dataclass
class AudioStream:
    chunks: AsyncIterator[bytes]
    mime_type: str
    ext: str

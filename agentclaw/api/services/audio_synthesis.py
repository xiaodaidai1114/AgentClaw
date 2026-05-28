"""Shared audio synthesis helpers for admin and public routes."""

from __future__ import annotations

import base64
import hashlib
import json
from collections import OrderedDict

from agentclaw.audio import AudioService
from agentclaw.audio.types import AudioStream
from agentclaw.database import get_database


TTS_CACHE_TTL_SECONDS = 24 * 60 * 60
MEMORY_TTS_CACHE_MAX_ITEMS = 128
_memory_tts_cache: OrderedDict[str, str] = OrderedDict()


def tts_cache_key(*, text: str, voice: str = "", model_id: str = "") -> str:
    payload = {
        "text": text,
        "voice": voice or "",
        "model_id": model_id or "",
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"agentclaw:tts:{digest}"


def encode_cached_audio(data: bytes, mime_type: str, ext: str) -> str:
    return json.dumps(
        {
            "data": base64.b64encode(data).decode("ascii"),
            "mime_type": mime_type,
            "ext": ext,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_cached_audio(value: str | bytes | None) -> tuple[bytes, str] | None:
    if not value:
        return None
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        payload = json.loads(value)
        return base64.b64decode(payload["data"]), payload.get("mime_type") or "application/octet-stream"
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def get_memory_tts_cache(key: str) -> tuple[bytes, str] | None:
    cached = _memory_tts_cache.get(key)
    if cached is None:
        return None
    _memory_tts_cache.move_to_end(key)
    return decode_cached_audio(cached)


def set_memory_tts_cache(key: str, value: str) -> None:
    _memory_tts_cache[key] = value
    _memory_tts_cache.move_to_end(key)
    while len(_memory_tts_cache) > MEMORY_TTS_CACHE_MAX_ITEMS:
        _memory_tts_cache.popitem(last=False)


def get_redis_cache_db(database_getter=None):
    database_getter = database_getter or get_database
    try:
        db = database_getter()
    except Exception:
        return None
    if not db:
        return None
    try:
        return db if db.is_redis_available() else None
    except Exception:
        return None


async def collect_audio(stream: AudioStream) -> bytes:
    chunks: list[bytes] = []
    async for chunk in stream.chunks:
        if chunk:
            chunks.append(chunk)
    return b"".join(chunks)


async def synthesize_with_cache(
    service: AudioService,
    *,
    text: str,
    voice: str = "",
    model_id: str = "",
    database_getter=None,
) -> tuple[bytes, str]:
    cache_key = tts_cache_key(text=text, voice=voice, model_id=model_id)
    redis_db = get_redis_cache_db(database_getter)

    if redis_db:
        try:
            cached = decode_cached_audio(await redis_db.redis_get(cache_key))
        except Exception:
            cached = None
        if cached:
            return cached

    cached = get_memory_tts_cache(cache_key)
    if cached:
        return cached

    stream = await service.synthesize(text=text, voice=voice or None, model_id=model_id or None)
    data = await collect_audio(stream)
    cached_value = encode_cached_audio(data, stream.mime_type, stream.ext)

    stored_in_redis = False
    if redis_db:
        try:
            await redis_db.redis_set(cache_key, cached_value, ex=TTS_CACHE_TTL_SECONDS)
            stored_in_redis = True
        except Exception:
            stored_in_redis = False
    if not stored_in_redis:
        set_memory_tts_cache(cache_key, cached_value)

    return data, stream.mime_type


def clear_memory_tts_cache() -> None:
    _memory_tts_cache.clear()

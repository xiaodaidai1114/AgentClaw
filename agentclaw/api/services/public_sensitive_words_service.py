"""Sensitive word masking for anonymous public content."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agentclaw.config import get_config
from agentclaw.logger.config import get_logger


logger = get_logger(__name__)

SENSITIVE_WORDS_ENV = "AGENTCLAW_PUBLIC_SENSITIVE_WORDS_PATH"

_cache_key: tuple[str, int, int] | None = None
_cache_words: tuple[str, ...] = ()


def reset_public_sensitive_words_cache() -> None:
    global _cache_key, _cache_words
    _cache_key = None
    _cache_words = ()


def _sensitive_words_path() -> Path | None:
    raw_path = os.getenv(SENSITIVE_WORDS_ENV, "").strip()
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    try:
        project_dir = Path(get_config().project.project_dir)
    except Exception:
        project_dir = Path.cwd()
    return project_dir / path


def _load_sensitive_words() -> tuple[str, ...]:
    global _cache_key, _cache_words

    path = _sensitive_words_path()
    if path is None:
        if _cache_key != ("", 0, 0):
            _cache_key = ("", 0, 0)
            _cache_words = ()
        return _cache_words

    try:
        stat = path.stat()
    except FileNotFoundError:
        key = (str(path), 0, 0)
        if _cache_key != key:
            logger.warning(f"公开敏感词库不存在: {path}")
            _cache_key = key
            _cache_words = ()
        return _cache_words
    except OSError as exc:
        key = (str(path), 0, 0)
        if _cache_key != key:
            logger.warning(f"读取公开敏感词库失败: {path}, error={exc}")
            _cache_key = key
            _cache_words = ()
        return _cache_words

    key = (str(path), int(stat.st_mtime_ns), int(stat.st_size))
    if _cache_key == key:
        return _cache_words

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning(f"读取公开敏感词库失败: {path}, error={exc}")
        _cache_key = key
        _cache_words = ()
        return _cache_words

    words = sorted({word for word in raw_text.split() if word}, key=len, reverse=True)
    _cache_key = key
    _cache_words = tuple(words)
    return _cache_words


def mask_public_sensitive_words(content: str) -> str:
    text = str(content or "")
    if not text:
        return text
    masked = text
    for word in _load_sensitive_words():
        masked = masked.replace(word, "*" * len(word))
    return masked


def mask_public_workflow_inputs(input_data: dict[str, Any], user_input_field: str | None) -> dict[str, Any]:
    masked = dict(input_data or {})
    for field in ("__user__", user_input_field):
        if not field:
            continue
        value = masked.get(field)
        if isinstance(value, str):
            masked[field] = mask_public_sensitive_words(value)
    return masked

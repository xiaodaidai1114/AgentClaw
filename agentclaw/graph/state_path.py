"""Small helpers for reading and writing nested workflow state paths."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_MISSING = object()


def get_path(data: dict, path: str, default: Any = None) -> Any:
    """Read a dotted path from a nested dict."""
    if not path:
        return data

    value: Any = data
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return default
    return value


def set_path(data: dict, path: str, value: Any) -> dict:
    """Set a dotted path on a nested dict, creating intermediate dicts."""
    if not path:
        raise ValueError("path must not be empty")

    current = data
    parts = path.split(".")
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value
    return data


def delete_path(data: dict, path: str) -> bool:
    """Delete a dotted path from a nested dict. Returns True if deleted."""
    if not path:
        return False

    current = data
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    if isinstance(current, dict) and parts[-1] in current:
        del current[parts[-1]]
        return True
    return False


def merge_path(data: dict, path: str, value: Any, strategy: str = "replace") -> dict:
    """Merge a value into a nested path using a small set of strategies."""
    if strategy == "replace":
        return set_path(data, path, value)

    existing = get_path(data, path, _MISSING)

    if strategy == "append":
        if existing is _MISSING or existing is None:
            existing = []
        if not isinstance(existing, list):
            existing = [existing]
        existing.append(value)
        return set_path(data, path, existing)

    if strategy == "shallow_merge":
        if isinstance(existing, dict) and isinstance(value, dict):
            merged = {**existing, **value}
        else:
            merged = value
        return set_path(data, path, merged)

    if strategy == "deep_merge":
        if isinstance(existing, dict) and isinstance(value, dict):
            merged = _deep_merge(existing, value)
        else:
            merged = value
        return set_path(data, path, merged)

    raise ValueError(f"unsupported merge strategy: {strategy}")


def render_path_template(path: str, variables: dict[str, Any]) -> str:
    """Render a dotted path or field template with str.format semantics."""
    return path.format(**variables)


def _deep_merge(left: dict, right: dict) -> dict:
    result = deepcopy(left)
    for key, value in right.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result

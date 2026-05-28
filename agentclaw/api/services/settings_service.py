from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from agentclaw.logger.config import get_logger
from agentclaw.memory import MEMORY_CHAR_LIMIT, read_workflow_memory, write_workflow_memory
from agentclaw.node.types import ErrorStrategy

logger = get_logger(__name__)
GLOBAL_FIELDS = ("timeout", "recursion_limit", "max_tool_rounds", "max_context_messages", "tool_result_max_length", "max_message_length")
WORKFLOW_FIELDS = (
    "timeout",
    "recursion_limit",
    "cancel_on_disconnect",
    "auth_required",
    "allowed_roles",
    "rate_limit",
    "tracing",
    "description",
    "welcome",
    "chat_audio",
    "public_share_enabled",
    "public_share_token",
    "workflow_api_key",
    "public_conversation_limit",
    "public_message_limit",
    "inject_as_agentic_capability",
)
WORKFLOW_SECRET_MASK = "***"
BASE_NODE_FIELDS = ("description", "max_retries", "retry_delay", "output_to_user", "output_key", "fallback_value")
LLM_FIELDS = ("model_id", "use_fast_model", "stream", "output_format", "fallback_model_id", "auto_fallback", "fallback_threshold", "tool_choice", "max_tool_rounds", "enable_builtin_skills", "enable_builtin_tools", "agent_style", "use_context", "save_to_context", "max_context_messages", "enable_compression", "compression_threshold", "compression_model", "inject_files", "enable_memory")
HUMAN_FIELDS = ("feedback_field", "pending_status", "approval_mode", "timeout_seconds", "on_timeout", "save_to_context")
INFRA_FIELDS = {
    "database": ("host", "port", "user", "password", "database", "pool_min_size", "pool_max_size"),
    "redis": ("host", "port", "password", "pool_max_connections"),
    "upload": ("upload_dir", "max_size_mb", "minio_endpoint", "minio_access_key", "minio_secret_key", "minio_bucket", "minio_secure"),
    "auth": ("admin_token", "workflow_api_key"),
    "scheduler": ("enabled", "timezone", "max_workers", "coalesce", "max_instances"),
}
SECRET_MASKS = {"password", "admin_token", "workflow_api_key", "mcp_token", "minio_access_key", "minio_secret_key"}
MODEL_REFERENCE_FIELDS = ("default", "fallback", "fast", "vision", "speech2text", "tts", "tts_voice")
DEFAULT_CHAT_AUDIO_CONFIG = {
    "enabled": False,
    "speech_input_enabled": False,
    "tts_enabled": False,
    "speech2text_model_id": "",
    "tts_model_id": "",
    "tts_voice": "",
}
BUILTIN_CHAT_AUDIO_CONFIG = {
    **DEFAULT_CHAT_AUDIO_CONFIG,
    "enabled": True,
    "speech_input_enabled": True,
    "tts_enabled": True,
}
FALSEABLE_OVERRIDE_FIELDS = {
    "inject_as_agentic_capability",
    "public_share_enabled",
    "enabled",
    "speech_input_enabled",
    "tts_enabled",
}
NON_CONVERSATION_MODEL_TYPES = {"embedding", "rerank", "speech2text", "tts"}
MODEL_PARAM_FIELDS = ("temperature", "max_tokens", "top_p")
NODE_RESET_FIELDS = set(BASE_NODE_FIELDS) | set(LLM_FIELDS) | set(HUMAN_FIELDS) | {"on_error"} | set(MODEL_PARAM_FIELDS)
GLOBAL_ENV_FIELDS = {
    "timeout": "WORKFLOW_TIMEOUT",
    "recursion_limit": "WORKFLOW_RECURSION_LIMIT",
    "max_tool_rounds": "MAX_TOOL_ROUNDS",
    "max_context_messages": "MAX_CONTEXT_MESSAGES",
    "tool_result_max_length": "TOOL_RESULT_MAX_LENGTH",
    "max_message_length": "MAX_MESSAGE_LENGTH",
}
INFRA_ENV_FIELDS = {
    "database": {
        "host": "PG_HOST",
        "port": "PG_PORT",
        "user": "PG_USER",
        "password": "PG_PASSWORD",
        "database": "PG_DATABASE",
        "pool_min_size": "PG_POOL_MIN_SIZE",
        "pool_max_size": "PG_POOL_MAX_SIZE",
    },
    "redis": {
        "host": "REDIS_HOST",
        "port": "REDIS_PORT",
        "password": "REDIS_PASSWORD",
        "pool_max_connections": "REDIS_POOL_MAX_CONNECTIONS",
    },
    "upload": {
        "upload_dir": "UPLOAD_DIR",
        "max_size_mb": "MAX_UPLOAD_SIZE_MB",
        "minio_endpoint": "MINIO_ENDPOINT",
        "minio_access_key": "MINIO_ACCESS_KEY",
        "minio_secret_key": "MINIO_SECRET_KEY",
        "minio_bucket": "MINIO_BUCKET",
        "minio_secure": "MINIO_SECURE",
    },
    "auth": {
        "admin_token": "ADMIN_TOKEN",
        "workflow_api_key": "WORKFLOW_API_KEY",
    },
    "scheduler": {
        "enabled": "SCHEDULER_ENABLED",
        "timezone": "SCHEDULER_TIMEZONE",
        "max_workers": "SCHEDULER_MAX_WORKERS",
        "coalesce": "SCHEDULER_COALESCE",
        "max_instances": "SCHEDULER_MAX_INSTANCES",
    },
}
ENV_TO_GLOBAL_FIELD = {env_name: field for field, env_name in GLOBAL_ENV_FIELDS.items()}
ENV_TO_INFRA_FIELD = {
    env_name: (section, field)
    for section, fields in INFRA_ENV_FIELDS.items()
    for field, env_name in fields.items()
}
SECRET_ENV_KEYWORDS = ("PASSWORD", "TOKEN", "SECRET", "API_KEY", "ACCESS_KEY")
RESTART_ENV_NAMES = {
    "PORT",
    "HOST",
    "AGENTCLAW_URL",
    "AGENTCLAW_MAX_REQUEST_BODY_BYTES",
    "AGENTCLAW_CONTENT_SECURITY_POLICY",
    "AGENTCLAW_PUBLIC_SESSION_SECRET",
    "AGENTCLAW_DATA_DIR",
    "AGENTCLAW_DOCKER_STORAGE_TYPE",
    "AGENTCLAW_DOCKER_PGDATA_DIR",
    "AGENTCLAW_DOCKER_REDISDATA_DIR",
    "AGENTCLAW_DOCKER_ETCDDATA_DIR",
    "AGENTCLAW_DOCKER_MINIODATA_DIR",
    "AGENTCLAW_DOCKER_MILVUSDATA_DIR",
    "MINIO_API_PORT",
    "MINIO_CONSOLE_PORT",
    "AGENTCLAW_LOG_FILE",
    "LOG_CONSOLE_LEVEL",
    "KNOWLEDGEBASE_BACKEND",
    "MILVUS_URI",
    "MILVUS_PORT",
    "MILVUS_HTTP_PORT",
    "MILVUS_TOKEN",
    "MILVUS_COLLECTION_PREFIX",
    "ADMINER_PORT",
    "KNOWLEDGEBASE_DEFAULT_EMBEDDING_MODEL",
    "KNOWLEDGEBASE_DEFAULT_RERANK_MODEL",
    "KNOWLEDGEBASE_DEFAULT_LLM_MODEL",
    "AGENTCLAW_MCP_CONNECT_TIMEOUT",
    "AGENTCLAW_MCP_PROXY",
    "SEARXNG_BASE_URL",
    "CDP_PORT",
    "BROWSER_HEADLESS",
}
RECONNECT_ENV_NAMES = {
    "PG_HOST",
    "PG_PORT",
    "PG_DATABASE",
    "PG_USER",
    "PG_PASSWORD",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_PASSWORD",
    "REDIS_DB",
    "MINIO_ENDPOINT",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "MINIO_BUCKET",
    "MINIO_SECURE",
}
ENV_OPTIONS = {
    "LOG_CONSOLE_LEVEL": ("DEBUG", "INFO", "WARNING", "ERROR"),
    "KNOWLEDGEBASE_BACKEND": ("milvus",),
    "KNOWLEDGEBASE_RETRIEVAL_MODE": ("hybrid", "vector", "keyword"),
}
ADVANCED_ENV_EXCLUDED_NAMES = (
    set(GLOBAL_ENV_FIELDS.values())
    | {
        "UPLOAD_DIR",
        "MAX_UPLOAD_SIZE_MB",
        "MINIO_BUCKET",
        "MINIO_SECURE",
    }
    | set(INFRA_ENV_FIELDS["scheduler"].values())
)


def _env_spec_map() -> dict[str, Any]:
    from agentclaw.env_config import ENV_SECTIONS

    return {
        variable.name: {
            "name": variable.name,
            "default": variable.default,
            "description": variable.description,
            "visible": variable.show_in_env,
            "commented": variable.commented,
        }
        for section in ENV_SECTIONS
        for variable in section.variables
    }


def _read_project_env(project_dir: Path) -> dict[str, str]:
    env_file = project_dir / ".env"
    if not env_file.exists():
        return {}

    values: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped.removeprefix("export ").strip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _is_secret_env(name: str) -> bool:
    return any(keyword in name for keyword in SECRET_ENV_KEYWORDS)


def _env_value_type(name: str, default: str) -> str:
    if _is_secret_env(name):
        return "secret"
    normalized = str(default).strip().lower()
    if normalized in {"true", "false", "yes", "no"}:
        return "boolean"
    if normalized:
        try:
            float(normalized)
        except ValueError:
            pass
        else:
            return "number"
    return "string"


def _env_apply_scope(name: str) -> str:
    if name in RESTART_ENV_NAMES:
        return "restart"
    if name in RECONNECT_ENV_NAMES:
        return "reconnect"
    return "immediate"


def _env_label(name: str, description: str) -> str:
    if not description:
        return name
    for delimiter in ("；", "。", ";", "."):
        if delimiter in description:
            label = description.split(delimiter, 1)[0].strip()
            return label or name
    return description.strip() or name


def _normalize_env_display_value(name: str, value: str, value_type: str) -> Any:
    if value_type == "secret":
        return "***" if value else ""
    if value_type == "boolean":
        return value.strip().lower() in {"true", "1", "yes", "on"}
    if value_type == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return int(number) if number.is_integer() else number
    return value


def _coerce_env_setting_value(name: str, value: str) -> Any:
    value_type = _env_value_type(name, _env_spec_map().get(name, {}).get("default", ""))
    if value_type == "boolean":
        return value.strip().lower() in {"true", "1", "yes", "on"}
    if value_type == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            return value
        return int(number) if number.is_integer() else number
    return value


def _sync_legacy_settings(project_dir: Path, updates: dict[str, str]) -> None:
    store = _store_dir(project_dir)
    global_payload = _load_json(store / "settings.global.json")
    infra_payload = _load_json(store / "settings.infra.json")

    global_changed = False
    infra_changed = False
    for env_name, value in updates.items():
        if env_name in ENV_TO_GLOBAL_FIELD:
            global_payload[ENV_TO_GLOBAL_FIELD[env_name]] = _coerce_env_setting_value(env_name, value)
            global_changed = True
        if env_name in ENV_TO_INFRA_FIELD:
            section, field = ENV_TO_INFRA_FIELD[env_name]
            infra_payload.setdefault(section, {})[field] = _coerce_env_setting_value(env_name, value)
            infra_changed = True

    if global_changed:
        _save_json(store / "settings.global.json", _prune(global_payload))
    if infra_changed:
        _save_json(store / "settings.infra.json", _prune(infra_payload))


def _build_env_sections(project_dir: Path) -> list[dict[str, Any]]:
    from agentclaw.env_config import ENV_SECTIONS

    file_values = _read_project_env(project_dir)
    sections: list[dict[str, Any]] = []
    for section in ENV_SECTIONS:
        variables = []
        for variable in section.variables:
            if not variable.show_in_env:
                continue
            if variable.name in ADVANCED_ENV_EXCLUDED_NAMES:
                continue
            env_value = os.getenv(variable.name)
            file_value = file_values.get(variable.name)
            if file_value is not None and env_value == file_value:
                raw_value = file_value
                source = "project"
            elif env_value is not None:
                raw_value = env_value
                source = "environment"
            elif file_value is not None:
                raw_value = file_value
                source = "project"
            elif variable.commented:
                raw_value = ""
                source = "unset"
            else:
                raw_value = variable.default
                source = "default"

            value_type = _env_value_type(variable.name, variable.default)
            apply_scope = _env_apply_scope(variable.name)
            raw_display_value = "***" if value_type == "secret" and raw_value else raw_value
            raw_display_default = "***" if value_type == "secret" and variable.default else variable.default
            variables.append({
                "name": variable.name,
                "label": _env_label(variable.name, variable.description),
                "value": _normalize_env_display_value(variable.name, raw_value, value_type),
                "raw_value": raw_display_value,
                "has_value": bool(raw_value),
                "default": _normalize_env_display_value(variable.name, variable.default, value_type),
                "raw_default": raw_display_default,
                "description": variable.description,
                "type": value_type,
                "secret": value_type == "secret",
                "commented": variable.commented,
                "editable": True,
                "source": source,
                "apply_scope": apply_scope,
                "restart_required": apply_scope == "restart",
                "options": list(ENV_OPTIONS.get(variable.name, ())),
                "extra_comments": list(variable.extra_comments or ()),
            })

        if variables:
            sections.append({
                "title": section.title,
                "description": list(section.description or ()),
                "variables": variables,
            })
    return sections


def _pick_env_refs(mapping: dict[str, str], specs: dict[str, Any]) -> dict[str, Any]:
    return {
        field: specs[env_name]
        for field, env_name in mapping.items()
        if env_name in specs
    }


def get_settings_env_reference(project_dir: Path | None = None) -> dict[str, Any]:
    specs = _env_spec_map()
    payload = {
        "workflow": _pick_env_refs(GLOBAL_ENV_FIELDS, specs),
        "infra": {
            section: _pick_env_refs(fields, specs)
            for section, fields in INFRA_ENV_FIELDS.items()
        },
    }
    if project_dir is not None:
        payload["sections"] = _build_env_sections(project_dir)
    return payload


def _env_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "***":
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _collect_env_updates(data: dict[str, Any], mapping: dict[str, str]) -> dict[str, str]:
    updates: dict[str, str] = {}
    for field, env_name in mapping.items():
        if field not in data:
            continue
        value = _env_string(data[field])
        if value is not None:
            updates[env_name] = value
    return updates


def _write_env_updates(project_dir: Path, updates: dict[str, str], section_title: str) -> None:
    if not updates:
        return

    from agentclaw.env_config import render_env_file

    env_file = project_dir / ".env"
    if not env_file.exists():
        env_file.write_text(render_env_file(updates), encoding="utf-8")
    else:
        lines = env_file.read_text(encoding="utf-8").splitlines()
        written = set()

        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            uncommented = stripped[1:].strip() if stripped.startswith("#") else stripped
            if "=" not in uncommented:
                continue
            key = uncommented.split("=", 1)[0].strip()
            if key in updates:
                lines[index] = f"{key}={updates[key]}"
                written.add(key)

        missing = [key for key in updates if key not in written]
        if missing:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"# {section_title}")
            for key in missing:
                lines.append(f"{key}={updates[key]}")

        env_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    for key, value in updates.items():
        os.environ[key] = value


def _env_update_payload(data: dict[str, Any], project_dir: Path | None = None) -> dict[str, str]:
    from agentclaw.env_config import ENV_SECTIONS
    from agentclaw.env_config import build_data_dir_env_vars

    allowed = {
        variable.name
        for section in ENV_SECTIONS
        for variable in section.variables
        if variable.show_in_env
    }
    values = data.get("values") if isinstance(data, dict) else {}
    if not isinstance(values, dict):
        values = data if isinstance(data, dict) else {}

    updates: dict[str, str] = {}
    for key, raw_value in values.items():
        if key not in allowed:
            continue
        value = _env_string(raw_value)
        if value is not None:
            updates[key] = value
    data_dir = updates.get("AGENTCLAW_DATA_DIR", "").strip()
    if data_dir:
        updates.update(build_data_dir_env_vars(data_dir, project_dir=project_dir, include_docker=True))
    return updates


def _store_dir(project_dir: Path) -> Path:
    path = project_dir / ".agentclaw"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _workflow_settings_path(store: Path, workflow_id: str) -> Path:
    return store / f"{workflow_id.replace('/', '_').replace(chr(92), '_')}_settings.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"加载设置文件失败 {path}: {exc}")
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    if not data:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
        try:
            tmp_path.chmod(0o600)
        except Exception:
            pass
        os.replace(tmp_path, path)
        try:
            path.chmod(0o600)
        except Exception:
            pass
    finally:
        tmp_path.unlink(missing_ok=True)


def _save_required_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
        try:
            tmp_path.chmod(0o600)
        except Exception:
            pass
        os.replace(tmp_path, path)
        try:
            path.chmod(0o600)
        except Exception:
            pass
    finally:
        tmp_path.unlink(missing_ok=True)


def _models_config_path(config: Any) -> Path:
    path = getattr(config.project, "models_config", None)
    if path:
        return Path(path)
    return Path(config.project.project_dir) / "models.json"


def _load_models_config(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if not payload:
        return {**{field: "" for field in MODEL_REFERENCE_FIELDS}, "models": []}
    models = payload.get("models", [])
    if isinstance(models, dict):
        models = [
            {"id": model_id, **(model_data if isinstance(model_data, dict) else {"model": model_data})}
            for model_id, model_data in models.items()
        ]
    elif not isinstance(models, list):
        models = []
    payload = dict(payload)
    payload["models"] = [dict(item) for item in models if isinstance(item, dict)]
    for field in MODEL_REFERENCE_FIELDS:
        payload.setdefault(field, "")
    return payload


def _mask_models_config(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    result = {key: payload.get(key, "") for key in MODEL_REFERENCE_FIELDS}
    result["path"] = str(path)
    result["models"] = []
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        display = dict(item)
        api_key = str(display.get("api_key") or "")
        display["api_key_set"] = bool(api_key)
        display["api_key"] = WORKFLOW_SECRET_MASK if api_key else ""
        if "type" not in display and "model_type" in display:
            display["type"] = display.get("model_type")
        if str(display.get("type") or "").strip().lower() == "vision":
            display["type"] = "chat"
            display["supports_vision"] = True
        result["models"].append(display)
    return result


def _merge_model_secret(existing_models: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    merged = dict(model)
    model_id = str(merged.get("id") or "").strip()
    existing = next((item for item in existing_models if str(item.get("id") or "") == model_id), None)
    existing_key = existing.get("api_key") if existing else ""
    incoming_key = merged.get("api_key")
    if incoming_key == WORKFLOW_SECRET_MASK or (not incoming_key and existing_key):
        if existing_key:
            merged["api_key"] = existing_key
        else:
            merged.pop("api_key", None)
    merged.pop("api_key_set", None)
    if "model_type" in merged and "type" not in merged:
        merged["type"] = merged.pop("model_type")
    if str(merged.get("type") or "").strip().lower() == "vision":
        merged["type"] = "chat"
        merged["supports_vision"] = True
    return merged


def _sanitize_models_config(data: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in existing.items()
        if key not in {*MODEL_REFERENCE_FIELDS, "models", "path", "hot_reloaded"}
    }
    for field in MODEL_REFERENCE_FIELDS:
        value = data.get(field, "")
        if value is not None:
            payload[field] = str(value).strip()
    raw_models = data.get("models", [])
    if not isinstance(raw_models, list):
        raise ValueError("models must be a list")
    existing_models = existing.get("models", [])
    models = []
    for index, item in enumerate(raw_models):
        if not isinstance(item, dict):
            raise ValueError(f"models[{index}] must be an object")
        model = _merge_model_secret(existing_models, item)
        model_id = str(model.get("id") or "").strip()
        model_name = str(model.get("model") or "").strip()
        if not model_id:
            raise ValueError(f"models[{index}].id is required")
        if not model_name:
            raise ValueError(f"models[{index}].model is required")
        model["id"] = model_id
        model["model"] = model_name
        if "channel" in model:
            model["channel"] = str(model.get("channel") or "openai").strip() or "openai"
        if "type" in model:
            model["type"] = str(model.get("type") or "chat").strip() or "chat"
        if str(model.get("type") or "chat").strip().lower() != "chat":
            model["supports_vision"] = False
        models.append({key: value for key, value in model.items() if value is not None and value != ""})
    payload["models"] = models
    model_types = {str(item.get("id") or ""): str(item.get("type") or "chat").strip().lower() for item in models}
    model_vision = {str(item.get("id") or ""): bool(item.get("supports_vision")) for item in models}
    for field in ("default", "fallback", "fast"):
        model_id = str(payload.get(field) or "")
        if model_id and model_types.get(model_id) in NON_CONVERSATION_MODEL_TYPES:
            raise ValueError(f"{field} model cannot use non-conversation model '{model_id}'")
    vision_id = str(payload.get("vision") or "")
    if vision_id and vision_id in model_vision and not model_vision[vision_id]:
        raise ValueError(f"vision model must select a chat model with supports_vision enabled: '{vision_id}'")
    speech2text_id = str(payload.get("speech2text") or "")
    if speech2text_id and model_types.get(speech2text_id) != "speech2text":
        raise ValueError(f"speech2text model must select a speech2text model: '{speech2text_id}'")
    tts_id = str(payload.get("tts") or "")
    if tts_id and model_types.get(tts_id) != "tts":
        raise ValueError(f"tts model must select a tts model: '{tts_id}'")
    return payload


def _truthy_override(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip() != "***"
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            pruned = _prune(item)
            if key in FALSEABLE_OVERRIDE_FIELDS or _truthy_override(pruned):
                result[key] = pruned
        return result
    if isinstance(value, list):
        result = [_prune(item) for item in value]
        return [item for item in result if _truthy_override(item)]
    return value


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        elif key in FALSEABLE_OVERRIDE_FIELDS or _truthy_override(value):
            result[key] = value
    return result


def _pick(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(obj, field, None) for field in fields}


def _normalize_chat_audio(value: Any) -> dict[str, Any]:
    config = dict(DEFAULT_CHAT_AUDIO_CONFIG)
    if isinstance(value, dict):
        for key in config:
            if key in value:
                config[key] = value[key]
    for key in ("enabled", "speech_input_enabled", "tts_enabled"):
        config[key] = bool(config.get(key))
    for key in ("speech2text_model_id", "tts_model_id", "tts_voice"):
        config[key] = str(config.get(key) or "")
    return config


def _node_kind(node: Any) -> str:
    name = type(node).__name__.lower()
    if "llm" in name:
        return "llm"
    if "human" in name:
        return "human"
    return "base"


def _workflow_base(workflow: Any) -> dict[str, Any]:
    base = _pick(workflow, WORKFLOW_FIELDS)
    base.setdefault("allowed_roles", None)
    base.setdefault("description", "")
    base.setdefault("welcome", "")
    base["chat_audio"] = _normalize_chat_audio(base.get("chat_audio"))
    if _is_builtin_workflow(workflow) and not getattr(workflow, "_chat_audio_explicit", False):
        base["chat_audio"] = dict(BUILTIN_CHAT_AUDIO_CONFIG)
    base.setdefault("rate_limit", "")
    base["allowed_roles"] = ", ".join(base["allowed_roles"] or [])
    base["description"] = base["description"] or ""
    base["welcome"] = base["welcome"] or ""
    base["rate_limit"] = base["rate_limit"] or ""
    base["public_share_enabled"] = bool(base.get("public_share_enabled"))
    base["public_share_token"] = base.get("public_share_token") or ""
    base["workflow_api_key"] = base.get("workflow_api_key") or ""
    base["public_conversation_limit"] = base.get("public_conversation_limit") or 20
    base["public_message_limit"] = base.get("public_message_limit") or 200
    base["inject_as_agentic_capability"] = base.get("inject_as_agentic_capability") is not False
    return base


def _workflow_display(base: dict[str, Any]) -> dict[str, Any]:
    display = dict(base)
    workflow_api_key = str(display.get("workflow_api_key") or "")
    display["workflow_api_key_set"] = bool(workflow_api_key)
    display["workflow_api_key"] = WORKFLOW_SECRET_MASK if workflow_api_key else ""
    display["auth_reserved_notice"] = "auth_required and allowed_roles are reserved fields and do not affect current personal edition authorization."
    return display


def _workflow_with_memory(workflow: Any, project_dir: Path) -> dict[str, Any]:
    base = _workflow_display(_workflow_base(workflow))
    memory_content = read_workflow_memory(project_dir, workflow.id)
    base["memory_content"] = memory_content
    base["memory_chars"] = len(memory_content)
    base["memory_over_limit"] = len(memory_content) > MEMORY_CHAR_LIMIT
    return base


def _is_builtin_workflow(workflow: Any, workflow_id: str = "") -> bool:
    return (
        workflow_id == "__builtin__"
        or getattr(workflow, "id", None) == "__builtin__"
        or bool(getattr(workflow, "is_builtin", False))
    )


def _clear_public_share_fields(payload: dict[str, Any]) -> None:
    payload["public_share_enabled"] = False
    payload["public_share_token"] = ""


def _node_base(node: Any) -> dict[str, Any]:
    base = _pick(node, BASE_NODE_FIELDS)
    base["description"] = base["description"] or ""
    base["output_key"] = base["output_key"] or ""
    base["fallback_value"] = "" if base["fallback_value"] is None else base["fallback_value"]
    raw_error = getattr(node, "on_error", None)
    base["on_error"] = raw_error.name.upper() if hasattr(raw_error, "name") else str(raw_error or "ABORT").upper()
    if _node_kind(node) == "llm":
        params = getattr(node, "model_params", {}) or {}
        base.update(_pick(node, LLM_FIELDS))
        base.update({
            "temperature": params.get("temperature") if "temperature" in params else None,
            "max_tokens": params.get("max_tokens", 0),
            "top_p": params.get("top_p") if "top_p" in params else None,
        })
    if _node_kind(node) == "human":
        base.update(_pick(node, HUMAN_FIELDS))
    return base


def _apply_system_section(config: Any, section: str, override: dict[str, Any]) -> dict[str, Any]:
    from agentclaw.config import AuthConfig, DatabaseConfig, RedisConfig, SchedulerConfig, UploadConfig

    if not hasattr(config, "_settings_base_sections"):
        config._settings_base_sections = {name: _pick(getattr(config, name), fields) if getattr(config, name, None) else {} for name, fields in INFRA_FIELDS.items()}
        config._settings_base_workflow = _pick(config.workflow, GLOBAL_FIELDS)
    section_cls = {"database": DatabaseConfig, "redis": RedisConfig, "upload": UploadConfig, "auth": AuthConfig, "scheduler": SchedulerConfig}
    merged = _merge(config._settings_base_sections[section], override)
    current = getattr(config, section, None)
    if not merged and not config._settings_base_sections[section]:
        if section in {"database", "redis"}:
            setattr(config, section, None)
        target = section_cls[section]()
    elif merged or current is not None:
        target = current or section_cls[section]()
        for key, value in merged.items():
            setattr(target, key, value)
        setattr(config, section, target)
    else:
        target = section_cls[section]()
    display = dict(merged)
    if not display:
        display = _pick(target, INFRA_FIELDS[section])
    for key in SECRET_MASKS:
        if key in display:
            display[key] = "***" if display[key] else ""
    return display


def apply_saved_system_settings(config: Any) -> None:
    store = _store_dir(config.project.project_dir)
    global_override = _load_json(store / "settings.global.json")
    infra_override = _load_json(store / "settings.infra.json")
    if not hasattr(config, "_settings_base_workflow"):
        config._settings_base_workflow = _pick(config.workflow, GLOBAL_FIELDS)
    merged_workflow = _merge(config._settings_base_workflow, global_override)
    for key, value in merged_workflow.items():
        setattr(config.workflow, key, value)
    for section, fields in INFRA_FIELDS.items():
        _apply_system_section(config, section, _prune(infra_override.get(section, {})))


def apply_saved_workflow_settings(workflow: Any, project_dir: Path | None = None) -> None:
    project_dir = project_dir or workflow._candidate_base_dirs()[0]
    store = _store_dir(project_dir)
    config = _load_json(_workflow_settings_path(store, workflow.id))
    if not hasattr(workflow, "_settings_base_workflow"):
        workflow._settings_base_workflow = _workflow_base(workflow)
    merged_workflow = _merge(workflow._settings_base_workflow, _prune(config.get("workflow", {})))
    if _is_builtin_workflow(workflow):
        _clear_public_share_fields(merged_workflow)
    roles = merged_workflow.get("allowed_roles", "")
    if isinstance(roles, list):
        workflow.allowed_roles = [item.strip() for item in roles if str(item).strip()] or None
    else:
        workflow.allowed_roles = [item.strip() for item in str(roles).split(",") if item.strip()] or None
    for key, value in merged_workflow.items():
        if key != "allowed_roles":
            setattr(workflow, key, value)
    node_overrides = config.get("nodes", {})
    for node_id, node in getattr(workflow, "_nodes", {}).items():
        if not hasattr(node, "_settings_base_config"):
            node._settings_base_config = _node_base(node)
        merged = _merge(node._settings_base_config, _prune(node_overrides.get(node_id, {})))
        strategy = str(merged.get("on_error", "ABORT")).upper()
        node.on_error = ErrorStrategy[strategy] if strategy in ErrorStrategy.__members__ else ErrorStrategy.ABORT
        for key in BASE_NODE_FIELDS:
            setattr(node, key, merged.get(key) or None if key in {"description", "output_key", "fallback_value"} else merged.get(key))
        if _node_kind(node) == "llm":
            for key in LLM_FIELDS:
                setattr(node, key, merged.get(key))
            if isinstance(node.inject_files, str):
                node.inject_files = True if node.inject_files.lower() == "true" else None
            model_params = {}
            for key in MODEL_PARAM_FIELDS:
                value = merged.get(key)
                if value is None:
                    continue
                if key == "max_tokens" and value == 0:
                    continue
                model_params[key] = value
            node.model_params = model_params
        if _node_kind(node) == "human":
            for key in HUMAN_FIELDS:
                setattr(node, key, merged.get(key))


class SettingsService:
    def __init__(self, registry=None):
        from agentclaw.config import get_config
        self._registry = registry
        self._config = get_config()
        self._store = _store_dir(self._config.project.project_dir)
        apply_saved_system_settings(self._config)

    def get_global(self) -> dict[str, Any]:
        return {
            "workflow": _pick(self._config.workflow, GLOBAL_FIELDS),
            "env": get_settings_env_reference(self._config.project.project_dir),
            **{
                name: _apply_system_section(
                    self._config,
                    name,
                    _prune(_load_json(self._store / "settings.infra.json").get(name, {})),
                )
                for name in INFRA_FIELDS
            },
        }

    def get_env_reference(self) -> dict[str, Any]:
        return get_settings_env_reference(self._config.project.project_dir)

    def get_models_config(self) -> dict[str, Any]:
        path = _models_config_path(self._config)
        return _mask_models_config(_load_models_config(path), path)

    def _reload_models_config(self, path: Path) -> None:
        if not self._registry or not hasattr(self._registry, "list_all"):
            return
        try:
            workflows = self._registry.list_all()
        except Exception as exc:
            logger.debug(f"列出工作流以热更新模型配置失败: {exc}")
            return
        for workflow in workflows or []:
            manager = getattr(workflow, "_llm_manager", None)
            if not manager:
                continue
            try:
                manager.reload_models_config(str(path))
            except Exception as exc:
                logger.warning(f"热更新模型配置失败 workflow={getattr(workflow, 'id', '')}: {exc}")

    def update_models_config(self, data: dict[str, Any]) -> dict[str, Any]:
        path = _models_config_path(self._config)
        existing = _load_models_config(path)
        payload = _sanitize_models_config(data or {}, existing)
        _save_required_json(path, payload)
        self._config.project.models_config = path
        self._reload_models_config(path)
        result = _mask_models_config(payload, path)
        result["hot_reloaded"] = True
        return result

    def _refresh_env_backed_config(self, updates: dict[str, str]) -> None:
        if not updates:
            return
        from agentclaw.config import (
            AuthConfig,
            DatabaseConfig,
            KnowledgeBaseConfig,
            RedisConfig,
            SchedulerConfig,
            UploadConfig,
            WorkflowConfig,
        )

        if set(updates) & set(GLOBAL_ENV_FIELDS.values()):
            self._config.workflow = WorkflowConfig.from_env()
            self._config._settings_base_workflow = _pick(self._config.workflow, GLOBAL_FIELDS)
        if set(updates) & {"PG_HOST", "PG_PORT", "PG_USER", "PG_PASSWORD", "PG_DATABASE", "PG_POOL_MIN_SIZE", "PG_POOL_MAX_SIZE"}:
            self._config.database = DatabaseConfig.from_env()
        if set(updates) & {"REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "REDIS_DB", "REDIS_POOL_MAX_CONNECTIONS"}:
            self._config.redis = RedisConfig.from_env()
        if set(updates) & {"ADMIN_TOKEN", "WORKFLOW_API_KEY"}:
            self._config.auth = AuthConfig.from_env()
            try:
                from agentclaw.api.auth.token import AdminTokenManager, WorkflowAPIKeyManager
                AdminTokenManager.reset_instance()
                WorkflowAPIKeyManager.reset_instance()
            except Exception as exc:
                logger.debug(f"刷新认证 Token 管理器失败: {exc}")
        if "MCP_TOKEN" in updates:
            try:
                from agentclaw.mcp.token_manager import MCPTokenManager
                manager = MCPTokenManager.get_instance()
                manager._initialized = False
            except Exception as exc:
                logger.debug(f"刷新 MCP Token 管理器失败: {exc}")
        if set(updates) & {"UPLOAD_DIR", "MAX_UPLOAD_SIZE_MB", "MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET", "MINIO_SECURE"}:
            self._config.upload = UploadConfig.from_env()
        if any(key.startswith("KNOWLEDGEBASE_") or key.startswith("MILVUS_") or key == "DEFAULT_KNOWLEDGEBASE_ID" for key in updates):
            self._config.knowledgebase = KnowledgeBaseConfig.from_env()
        if any(key.startswith("SCHEDULER_") for key in updates):
            self._config.scheduler = SchedulerConfig.from_env()

        self._config._settings_base_sections = {
            name: _pick(getattr(self._config, name), fields) if getattr(self._config, name, None) else {}
            for name, fields in INFRA_FIELDS.items()
        }
        apply_saved_system_settings(self._config)

    def update_env(self, data: dict[str, Any]) -> dict[str, Any]:
        updates = _env_update_payload(data or {}, self._config.project.project_dir)
        _write_env_updates(
            self._config.project.project_dir,
            updates,
            "AgentClaw Settings",
        )
        _sync_legacy_settings(self._config.project.project_dir, updates)
        self._refresh_env_backed_config(updates)
        payload = self.get_env_reference()
        payload["updated"] = sorted(updates)
        payload["restart_required"] = any(_env_apply_scope(key) == "restart" for key in updates)
        payload["reconnect_required"] = any(_env_apply_scope(key) == "reconnect" for key in updates)
        return payload

    def update_global(self, data: dict[str, Any]) -> dict[str, Any]:
        data = data or {}
        _write_env_updates(
            self._config.project.project_dir,
            _collect_env_updates(data, GLOBAL_ENV_FIELDS),
            "Workflow Runtime",
        )
        _save_json(self._store / "settings.global.json", _prune(data))
        apply_saved_system_settings(self._config)
        return self.get_global()

    def get_infra(self, section: str) -> dict[str, Any]:
        return self.get_global()[section]

    def update_infra(self, section: str, data: dict[str, Any]) -> dict[str, Any]:
        data = data or {}
        _write_env_updates(
            self._config.project.project_dir,
            _collect_env_updates(data, INFRA_ENV_FIELDS.get(section, {})),
            f"{section} settings",
        )
        payload = _load_json(self._store / "settings.infra.json")
        payload[section] = _prune(data)
        _save_json(self._store / "settings.infra.json", _prune(payload))
        apply_saved_system_settings(self._config)
        return self.get_infra(section)

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        workflow = self._registry.get(workflow_id) if self._registry else None
        if not workflow:
            raise KeyError(workflow_id)
        apply_saved_workflow_settings(workflow, self._config.project.project_dir)
        return _workflow_with_memory(workflow, self._config.project.project_dir)

    def update_workflow(self, workflow_id: str, data: dict[str, Any]) -> dict[str, Any]:
        workflow = self._registry.get(workflow_id) if self._registry else None
        if not workflow:
            raise KeyError(workflow_id)
        settings_path = _workflow_settings_path(self._store, workflow_id)
        payload = _load_json(settings_path)
        data = dict(data or {})
        existing_workflow_key = str(getattr(workflow, "workflow_api_key", "") or "")
        if data.get("workflow_api_key") == WORKFLOW_SECRET_MASK:
            data.pop("workflow_api_key", None)
        elif "workflow_api_key" in data:
            data["workflow_api_key"] = str(data.get("workflow_api_key") or "").strip()
        if "memory_content" in data:
            write_workflow_memory(
                self._config.project.project_dir,
                workflow_id,
                str(data.pop("memory_content") or ""),
            )
        if "chat_audio" in data:
            data["chat_audio"] = _normalize_chat_audio(data.get("chat_audio"))
        if "allowed_roles" in data and isinstance(data["allowed_roles"], str):
            data["allowed_roles"] = [item.strip() for item in data["allowed_roles"].split(",") if item.strip()]
        if _is_builtin_workflow(workflow, workflow_id):
            _clear_public_share_fields(data)
        if data.get("public_share_enabled") and not str(data.get("public_share_token") or "").strip():
            data["public_share_token"] = str(getattr(workflow, "public_share_token", "") or "").strip() or secrets.token_urlsafe(24)
        for numeric_field, fallback in (
            ("public_conversation_limit", 20),
            ("public_message_limit", 200),
        ):
            if numeric_field in data:
                try:
                    value = int(data[numeric_field])
                except (TypeError, ValueError):
                    value = fallback
                data[numeric_field] = value if value > 0 else fallback
        workflow_payload = _prune(data)
        if existing_workflow_key and "workflow_api_key" not in workflow_payload:
            workflow_payload["workflow_api_key"] = existing_workflow_key
        payload["workflow"] = workflow_payload
        _save_json(settings_path, _prune(payload))
        return self.get_workflow(workflow_id)

    def reset_workflow_field(self, workflow_id: str, field: str) -> dict[str, Any]:
        workflow = self._registry.get(workflow_id) if self._registry else None
        if not workflow:
            raise KeyError(workflow_id)
        if field != "memory_content" and field not in WORKFLOW_FIELDS:
            raise ValueError(field)
        if field == "memory_content":
            write_workflow_memory(self._config.project.project_dir, workflow_id, "")
        else:
            settings_path = _workflow_settings_path(self._store, workflow_id)
            payload = _load_json(settings_path)
            workflow_payload = payload.get("workflow", {})
            if isinstance(workflow_payload, dict):
                workflow_payload.pop(field, None)
                if workflow_payload:
                    payload["workflow"] = workflow_payload
                else:
                    payload.pop("workflow", None)
                _save_json(settings_path, _prune(payload))
        return self.get_workflow(workflow_id)

    def get_node(self, workflow_id: str, node_id: str) -> dict[str, Any]:
        workflow = self._registry.get(workflow_id) if self._registry else None
        node = getattr(workflow, "_nodes", {}).get(node_id) if workflow else None
        if not node:
            raise KeyError(f"{workflow_id}:{node_id}")
        apply_saved_workflow_settings(workflow, self._config.project.project_dir)
        return _node_base(node)

    def update_node(self, workflow_id: str, node_id: str, data: dict[str, Any]) -> dict[str, Any]:
        workflow = self._registry.get(workflow_id) if self._registry else None
        if not workflow or node_id not in getattr(workflow, "_nodes", {}):
            raise KeyError(f"{workflow_id}:{node_id}")
        settings_path = _workflow_settings_path(self._store, workflow_id)
        payload = _load_json(settings_path)
        payload.setdefault("nodes", {})[node_id] = _prune(data or {})
        _save_json(settings_path, _prune(payload))
        return self.get_node(workflow_id, node_id)

    def reset_node_field(self, workflow_id: str, node_id: str, field: str) -> dict[str, Any]:
        workflow = self._registry.get(workflow_id) if self._registry else None
        if not workflow or node_id not in getattr(workflow, "_nodes", {}):
            raise KeyError(f"{workflow_id}:{node_id}")
        if field not in NODE_RESET_FIELDS:
            raise ValueError(field)
        settings_path = _workflow_settings_path(self._store, workflow_id)
        payload = _load_json(settings_path)
        nodes = payload.get("nodes", {})
        node_payload = nodes.get(node_id, {}) if isinstance(nodes, dict) else {}
        if isinstance(node_payload, dict):
            node_payload.pop(field, None)
            if node_payload:
                nodes[node_id] = node_payload
            else:
                nodes.pop(node_id, None)
            if nodes:
                payload["nodes"] = nodes
            else:
                payload.pop("nodes", None)
            _save_json(settings_path, _prune(payload))
        return self.get_node(workflow_id, node_id)


def get_settings_service() -> SettingsService:
    from agentclaw.api.registry import WorkflowRegistry
    return SettingsService(registry=WorkflowRegistry)

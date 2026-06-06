"""LLM-backed safety guard for anonymous public inputs."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from agentclaw.api.schemas.common import ErrorCode
from agentclaw.logger.config import get_logger
from agentclaw.model.manager import LLMResponse


logger = get_logger(__name__)

DEFAULT_SAFE_GUARD_PROMPT = """# Public Safety Guard

Classify public user content. Output only 0 or 1. Be permissive: flag only clear, direct, actionable violations.

## VIOLATES (1)
Clear requests or intent for illegal harm, violence, self-harm, sexual exploitation, hate/harassment, fraud, credential theft, privacy leaks, malware, or bypassing safety controls.

## SAFE (0)
Ambiguous, harmless, fictional, roleplay, educational, news, security discussion, normal chat, or safety/refusal content without actionable harm.

## EXTRA RULES
{RULES}

Content: {INPUT}
Answer (0 or 1):"""

MASKED_PUBLIC_CONTENT = "[已被安全围栏屏蔽]"


@dataclass(frozen=True)
class SafetyGuardResult:
    enabled: bool
    violated: bool = False


class SafetyGuardUnavailable(RuntimeError):
    """Raised when a configured safety guard cannot return a valid decision."""


def _unwrap_llm_manager(workflow: Any) -> Any:
    manager = getattr(workflow, "_llm_manager", None)
    if manager is None and hasattr(workflow, "_ensure_components"):
        try:
            workflow._ensure_components()
            manager = getattr(workflow, "_llm_manager", None)
        except Exception as exc:
            logger.warning(f"安全围栏初始化工作流组件失败: {exc}")
            return None
    if hasattr(manager, "llm_manager"):
        manager = manager.llm_manager
    return manager


def _guard_model_id(manager: Any) -> str:
    return str(getattr(manager, "safe_guard_id", "") or "").strip()


def _guard_rules(manager: Any) -> str:
    return str(getattr(manager, "safe_guard_rules", "") or "").strip()


def _guard_bool(manager: Any, name: str, default: bool) -> bool:
    value = getattr(manager, name, default)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
    return bool(value)


def _guard_enabled_for_surface(workflow: Any, surface: str) -> bool:
    if surface == "api":
        return _guard_bool(workflow, "safe_guard_apply_api", False)
    return _guard_bool(workflow, "safe_guard_apply_public", True)


def _render_prompt(template: str, *, rules: str, content: str) -> str:
    return template.replace("{RULES}", rules).replace("{INPUT}", content)


def _parse_guard_response(response: Any) -> bool:
    if isinstance(response, LLMResponse):
        text = response.content or ""
    else:
        text = str(response or "")
    normalized = text.strip()
    answer_matches = re.findall(
        r"(?:answer(?:\s*\(0\s*or\s*1\))?|答案)\s*[:：]\s*([01])(?=\D|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if answer_matches:
        return answer_matches[-1] == "1"
    matches = re.findall(r"(?<!\d)([01])(?!\d)", normalized)
    if not matches:
        raise SafetyGuardUnavailable("Safety guard returned an invalid decision")
    return matches[-1] == "1"


async def check_public_content_safety(workflow: Any, content: str, *, surface: str = "public") -> SafetyGuardResult:
    """Return a safety decision for workflow input content.

    No guard is applied when models.json does not select a safe_guard model
    or disables the requested surface.
    Once configured, invalid or failed guard calls fail closed.
    """

    normalized_content = str(content or "").strip()
    if not normalized_content:
        return SafetyGuardResult(enabled=False, violated=False)

    manager = _unwrap_llm_manager(workflow)
    model_id = _guard_model_id(manager)
    if not manager or not model_id:
        return SafetyGuardResult(enabled=False, violated=False)
    if not _guard_enabled_for_surface(workflow, surface):
        return SafetyGuardResult(enabled=False, violated=False)

    prompt = _render_prompt(
        DEFAULT_SAFE_GUARD_PROMPT,
        rules=_guard_rules(manager),
        content=normalized_content,
    )
    try:
        response = await manager.invoke(
            [{"role": "user", "content": prompt}],
            model_id=model_id,
            _call_type="safe_guard",
            _max_attempts=1,
            temperature=0,
        )
    except Exception as exc:
        logger.warning(f"安全围栏调用失败: model={model_id}, error={exc}")
        raise SafetyGuardUnavailable("Safety guard is unavailable") from exc

    return SafetyGuardResult(enabled=True, violated=_parse_guard_response(response))


def public_safety_guard_blocked_payload() -> dict[str, str]:
    return {
        "error": "Content violates public safety policy",
        "code": "SAFETY_GUARD_BLOCKED",
    }


def public_safety_guard_unavailable_payload() -> dict[str, str]:
    return {
        "error": "Safety guard is unavailable",
        "code": "SAFETY_GUARD_UNAVAILABLE",
    }


def public_safety_guard_error_payload(exc: Exception) -> tuple[int, dict[str, str]]:
    if isinstance(exc, SafetyGuardUnavailable):
        return 503, public_safety_guard_unavailable_payload()
    return 400, {"error": str(exc), "code": ErrorCode.INVALID_REQUEST}


def collect_public_user_input_content(
    *,
    user_value: Any,
    input_data: Any,
    user_input_field: str | None,
) -> str:
    if isinstance(user_value, str):
        return user_value.strip()
    if isinstance(input_data, dict) and user_input_field:
        value = input_data.get(user_input_field)
        if isinstance(value, str):
            return value.strip()
    return ""

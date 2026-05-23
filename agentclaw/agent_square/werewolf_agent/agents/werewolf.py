"""AgentClaw built-in Claw App entrypoint: AI 狼人杀主持人."""

from __future__ import annotations

try:
    from .werewolf_actor import ActorDecisionNode, actor_workflow, create_actor_workflow
    from .werewolf_actions import fallback_actor_action, normalize_actor_action
    from .werewolf_personas import generate_personas_node
    from .werewolf_prompts import WEREWOLF_PROMPT_KEYS, build_actor_prompt
    from .werewolf_views import build_actor_view
    from .werewolf_machine import *
    from .werewolf_machine import _build_actor_request
    from .werewolf_state import *
    from .werewolf_state import _new_game
    from .werewolf_workflow import (
        APP_DIR, OPENING_MESSAGE, _build_next_input_info, _render_game,
        _route_after_advance, _route_after_call_actors, _route_after_prepare,
        _streamable_public_line, create_werewolf_workflow, workflow,
    )
except ImportError:  # pragma: no cover - supports copied template direct import
    import sys
    from pathlib import Path

    _CURRENT_DIR = str(Path(__file__).resolve().parent)
    if _CURRENT_DIR not in sys.path:
        sys.path.insert(0, _CURRENT_DIR)

    from werewolf_actor import ActorDecisionNode, actor_workflow, create_actor_workflow  # type: ignore
    from werewolf_actions import fallback_actor_action, normalize_actor_action  # type: ignore
    from werewolf_personas import generate_personas_node  # type: ignore
    from werewolf_prompts import WEREWOLF_PROMPT_KEYS, build_actor_prompt  # type: ignore
    from werewolf_views import build_actor_view  # type: ignore
    from werewolf_machine import *  # type: ignore # noqa: F403
    from werewolf_machine import _build_actor_request  # type: ignore
    from werewolf_state import *  # type: ignore # noqa: F403
    from werewolf_state import _new_game  # type: ignore
    from werewolf_workflow import (  # type: ignore
        APP_DIR, OPENING_MESSAGE, _build_next_input_info, _render_game,
        _route_after_advance, _route_after_call_actors, _route_after_prepare,
        _streamable_public_line, create_werewolf_workflow, workflow,
    )


def _ensure_workflow_published() -> None:
    from agentclaw.api.registry import WorkflowRegistry

    if WorkflowRegistry.get(workflow.id) is None:
        workflow.publish()


_ensure_workflow_published()


__all__ = [
    "APP_DIR",
    "OPENING_MESSAGE",
    "ActorDecisionNode",
    "WEREWOLF_PROMPT_KEYS",
    "actor_workflow",
    "build_actor_prompt",
    "build_actor_view",
    "create_actor_workflow",
    "create_werewolf_workflow",
    "generate_personas_node",
    "fallback_actor_action",
    "normalize_actor_action",
    "workflow",
]

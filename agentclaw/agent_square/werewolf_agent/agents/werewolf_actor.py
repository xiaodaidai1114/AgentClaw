"""Actor child workflow for one AI Werewolf seat."""

from __future__ import annotations

import json
import re

from agentclaw import BaseNode, LLMNode, Workflow, output

try:
    from .werewolf_actions import ALLOWED_ACTION_KINDS_BY_REQUEST, fallback_actor_action, normalize_actor_action
    from .werewolf_prompts import build_actor_prompt
    from .werewolf_views import build_actor_view
except ImportError:  # pragma: no cover - supports copied template direct import
    from werewolf_actions import ALLOWED_ACTION_KINDS_BY_REQUEST, fallback_actor_action, normalize_actor_action  # type: ignore
    from werewolf_prompts import build_actor_prompt  # type: ignore
    from werewolf_views import build_actor_view  # type: ignore


class BuildActorViewNode(BaseNode):
    """Build the private/public view visible to one actor."""

    async def _do_execute(self, state: dict, context) -> dict:
        request = dict(state.get("request") or {})
        memory = dict(state.get("memory") or {})
        state["actor_view"] = build_actor_view(request, memory)
        return state


class ActorDecisionNode(BaseNode):
    """Provide a fallback actor decision when no upstream decision exists.

    The actor graph is intentionally shaped so an upstream parser can write
    ``raw_action`` before this step. When that happens, this node preserves the
    upstream decision and lets ``validate_action`` constrain it.
    """

    async def _do_execute(self, state: dict, context) -> dict:
        actor_view = dict(state.get("actor_view") or {})
        raw_action = state.get("raw_action")
        allowed_kinds = ALLOWED_ACTION_KINDS_BY_REQUEST.get(str(actor_view.get("kind") or ""), set())
        if (
            isinstance(raw_action, dict)
            and raw_action
            and str(raw_action.get("kind") or "") in allowed_kinds
        ):
            return state
        state["raw_action"] = fallback_actor_action(actor_view)
        return state


class BuildActorPromptNode(BaseNode):
    """Build the prompt asset composition for a future LLM decision node."""

    async def _do_execute(self, state: dict, context) -> dict:
        actor_view = dict(state.get("actor_view") or {})
        state["actor_prompt"] = build_actor_prompt(actor_view)
        return state


class BuildLLMDecisionInputNode(BaseNode):
    """Combine actor prompt references and actor view for model decision nodes."""

    async def _do_execute(self, state: dict, context) -> dict:
        actor_view = dict(state.get("actor_view") or {})
        kind = str(actor_view.get("kind") or "")
        speech_kinds = {
            "election_speech",
            "election_pk_speech",
            "day_speech",
            "day_pk_speech",
            "last_words",
        }
        output_hint = (
            '只输出一行紧凑 JSON，不要 Markdown，不要解释：{"kind":"speak","speech":"发言正文"}。'
            if kind in speech_kinds
            else (
                '只输出一行紧凑 JSON，不要 Markdown，不要理由，不要 speech 字段。'
                '救人格式为 {"kind":"witch_save"}；'
                '毒人格式为 {"kind":"witch_poison","target_seat":5}；'
                '不用药格式为 {"kind":"skip"}。'
            )
            if kind == "witch"
            else (
                '只输出一行紧凑 JSON，不要 Markdown，不要理由，不要 speech 字段。'
                '上警格式为 {"kind":"join_election"}；'
                '不上警格式为 {"kind":"skip_election"}。'
            )
            if kind == "election_join"
            else (
                '只输出一行紧凑 JSON，不要 Markdown，不要理由，不要 speech 字段。'
                '有目标时格式为 {"kind":"vote","target_seat":5}；'
                '无目标时格式为 {"kind":"skip"}；'
                'direction 阶段格式为 {"kind":"choose_direction","direction":"left"}。'
            )
        )
        state["llm_decision_input"] = (
            f"{state.get('actor_prompt') or ''}\n\n"
            "actor_view:\n"
            f"{json.dumps(actor_view, ensure_ascii=False, separators=(',', ':'))}\n\n"
            f"{output_hint}"
        )
        return state


class ParseLLMActionNode(BaseNode):
    """Parse the compact JSON action produced by the actor model."""

    async def _do_execute(self, state: dict, context) -> dict:
        text = str(state.get("llm_decision_text") or "").strip()
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return state
        try:
            action = json.loads(match.group(0))
        except json.JSONDecodeError:
            return state
        if isinstance(action, dict):
            state["raw_action"] = action
        return state


class RouteActorDecisionNode(BaseNode):
    """Choose model decision when an LLM manager is available, otherwise fallback."""

    async def _do_execute(self, state: dict, context) -> dict:
        state["decision_route"] = "model" if context and context.llm_manager else "fallback"
        return state


class ValidateActorActionNode(BaseNode):
    """Normalize and constrain actor output before returning it to the main workflow."""

    async def _do_execute(self, state: dict, context) -> dict:
        actor_view = dict(state.get("actor_view") or {})
        raw_action = state.get("raw_action") if isinstance(state.get("raw_action"), dict) else {}
        state["action"] = normalize_actor_action(actor_view, raw_action)
        return state


class StreamActorSpeechNode(BaseNode):
    """Stream public speech as soon as one actor decision is available."""

    async def _do_execute(self, state: dict, context) -> dict:
        actor_view = dict(state.get("actor_view") or {})
        action = dict(state.get("action") or {})
        if action.get("kind") != "speak":
            return state
        if str(actor_view.get("kind") or "") not in {
            "election_speech",
            "election_pk_speech",
            "day_speech",
            "day_pk_speech",
            "last_words",
        }:
            return state
        seat = int(action.get("seat") or actor_view.get("seat") or 0)
        speech = str(action.get("speech") or "").strip()
        if not seat or not speech:
            return state
        if str(actor_view.get("kind") or "") == "last_words":
            text = f"{seat}号遗言：{speech}\n\n"
        else:
            text = f"{seat}号玩家开始发言：\n{seat}号：{speech}\n\n"
        await output(text, node="actor_speech", save_to_context=False, stream=True)
        return state


class UpdateActorMemoryNode(BaseNode):
    """Update actor memory and emit the result expected by SubWorkflowNode."""

    async def _do_execute(self, state: dict, context) -> dict:
        memory = dict(state.get("memory") or {})
        actor_view = dict(state.get("actor_view") or {})
        action = dict(state.get("action") or {})
        seat = int(actor_view.get("seat") or action.get("seat") or 0)
        kind = str(actor_view.get("kind") or "")

        memory["last_thread_id"] = context.thread_id if context else ""
        memory["last_kind"] = kind
        memory["last_action_kind"] = action.get("kind")
        state["memory"] = memory
        state["actor_result"] = {
            "seat": seat,
            "request_kind": kind,
            "action": action,
        }
        return state


def create_actor_workflow(*, enable_model_decision: bool = False, model_id: str | None = None) -> Workflow:
    actor_workflow = Workflow(
        id="werewolf_actor",
        name="狼人杀角色子工作流",
        description="单个 AI 座位的隔离决策工作流。",
        tracing=False,
    )
    actor_workflow.register_state_field("request", dict)
    actor_workflow.register_state_field("memory", dict)
    actor_workflow.register_state_field("actor_view", dict)
    actor_workflow.register_state_field("actor_prompt", str)
    actor_workflow.register_state_field("llm_decision_input", str)
    actor_workflow.register_state_field("llm_decision_text", str)
    actor_workflow.register_state_field("decision_route", str)
    actor_workflow.register_state_field("raw_action", dict)
    actor_workflow.register_state_field("action", dict)
    actor_workflow.register_state_field("actor_result", dict)
    actor_workflow.add_node(BuildActorViewNode(
        id="build_view",
        output_to_user=False,
        description="构建角色可见视角",
    ))
    actor_workflow.add_node(ActorDecisionNode(
        id="decide",
        output_to_user=False,
        description="根据当前视角产出角色动作",
    ))
    actor_workflow.add_node(BuildActorPromptNode(
        id="build_prompt",
        output_to_user=False,
        description="组合角色决策提示词",
    ))
    if enable_model_decision:
        actor_workflow.add_node(RouteActorDecisionNode(
            id="route_decision",
            output_to_user=False,
            description="有模型配置则走模型决策，否则降级到本地兜底决策",
        ))
        actor_workflow.add_node(BuildLLMDecisionInputNode(
            id="build_llm_input",
            output_to_user=False,
            description="组合模型决策输入",
        ))
        actor_workflow.add_node(LLMNode(
            id="llm_decide",
            system_prompt="{llm_decision_input}",
            user_prompt="请给出当前角色的狼人杀动作。",
            output_key="llm_decision_text",
            output_to_user=False,
            save_to_context=False,
            model_id=model_id,
        ))
        actor_workflow.add_node(ParseLLMActionNode(
            id="parse_action",
            output_to_user=False,
            description="解析紧凑 JSON 动作",
        ))
    actor_workflow.add_node(ValidateActorActionNode(
        id="validate_action",
        output_to_user=False,
        description="校验并规范化角色动作",
    ))
    actor_workflow.add_node(StreamActorSpeechNode(
        id="stream_speech",
        output_to_user=False,
        description="流式输出公开发言",
    ))
    actor_workflow.add_node(UpdateActorMemoryNode(
        id="update_memory",
        output_to_user=False,
        description="更新角色记忆并输出动作",
    ))
    actor_workflow.add_edge("__start__", "build_view")
    actor_workflow.add_edge("build_view", "build_prompt")
    if enable_model_decision:
        actor_workflow.add_edge("build_prompt", "route_decision")
        actor_workflow.add_router(
            after="route_decision",
            routes={
                "model": "build_llm_input",
                "fallback": "decide",
            },
            condition="decision_route",
        )
        actor_workflow.add_edge("build_llm_input", "llm_decide")
        actor_workflow.add_edge("llm_decide", "parse_action")
        actor_workflow.add_edge("parse_action", "decide")
    else:
        actor_workflow.add_edge("build_prompt", "decide")
    actor_workflow.add_edge("decide", "validate_action")
    actor_workflow.add_edge("validate_action", "stream_speech")
    actor_workflow.add_edge("stream_speech", "update_memory")
    actor_workflow.add_edge("update_memory", "__end__")
    return actor_workflow


actor_workflow = create_actor_workflow()

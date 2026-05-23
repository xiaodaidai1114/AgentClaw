"""AgentClaw built-in Claw App: 海龟汤主持人.

The workflow keeps the full soup solution in state, shows only the surface to
the player, and asks the model to obey a strict state machine. It is intended
as a playable built-in app and as an inspectable workflow example.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from agentclaw import Input, LLMNode, Workflow, output

try:
    from . import turtle_soup_prompts as prompt_contracts
except ImportError:
    prompt_path = Path(__file__).with_name("turtle_soup_prompts.py")
    spec = importlib.util.spec_from_file_location(f"{__name__}_prompts", prompt_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load turtle soup prompt contracts: {prompt_path}")
    prompt_contracts = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = prompt_contracts
    spec.loader.exec_module(prompt_contracts)


APP_DIR = Path(__file__).resolve().parents[1]
REFERENCE_SOUPS_PATH = APP_DIR / "data" / "premium_turtle_soups.md"
SESSION_STATE_KEY = "turtle_soup_session"


@lru_cache(maxsize=1)
def _read_reference_soups() -> str:
    return REFERENCE_SOUPS_PATH.read_text(encoding="utf-8")


def _json_for_prompt(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _empty_session() -> dict[str, Any]:
    return {
        "phase": "choose_type",
        "soup_type": "",
        "difficulty": "",
        "soup_surface": "",
        "soup_solution": "",
        "truth_facts": [],
        "known_facts": [],
        "open_threads": [],
        "question_count": 0,
        "hint_count": 0,
        "answer_attempt_count": 0,
        "last_feedback": "",
        "turn_history": [],
    }


def _coerce_session(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}

    session = _empty_session()
    for key, value in raw.items():
        if key in session:
            session[key] = value
    if session.get("phase") not in {"choose_type", "await_soup_confirmation", "playing", "solved"}:
        session["phase"] = "choose_type"
    if not isinstance(session.get("turn_history"), list):
        session["turn_history"] = []
    session["turn_history"] = [
        item
        for item in session["turn_history"]
        if isinstance(item, dict) and str(item.get("user_input") or "").strip()
    ][-10:]
    return session


def _session_from_state(state: dict[str, Any]) -> dict[str, Any]:
    return _coerce_session(state.get(SESSION_STATE_KEY) or state.get("session"))


def _result_from_state(state: dict[str, Any]) -> Any:
    for key in prompt_contracts.PHASE_RESULT_KEYS:
        value = state.get(key)
        if value == prompt_contracts.CLEARED_PHASE_RESULT:
            continue
        if isinstance(value, dict):
            return value
    return None



def _normalize_phase_result(raw: Any, previous_session: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {
            "reply": "我刚才没有整理好这轮状态。你可以重新说一次想玩的类型、提问、给出答案，或者要一个提示。",
            "phase": previous_session.get("phase", "choose_type"),
            "intent": "irrelevant_reply",
            "question_judgement": None,
            "session": previous_session,
        }

    session = previous_session
    if isinstance(raw.get("session"), dict) or (isinstance(raw.get("session"), str) and raw.get("session").strip()):
        session = _coerce_session(raw.get("session"))
    phase = raw.get("phase") or session.get("phase") or previous_session.get("phase") or "choose_type"
    if phase not in {"choose_type", "await_soup_confirmation", "playing", "solved"}:
        phase = session.get("phase", "choose_type")
    session["phase"] = phase

    judgement = raw.get("question_judgement")
    if judgement is None:
        judgement = raw.get("verdict")
    if judgement not in prompt_contracts.QUESTION_JUDGEMENT_ALLOWED:
        judgement = None

    intent = str(raw.get("intent") or "irrelevant_reply")
    reply = str(raw.get("reply") or "").strip()
    if (intent == "question_judgement" or "verdict" in raw) and judgement:
        intent = "question_judgement"
        reply = judgement
    if not reply:
        reply = "你可以继续提问、给出答案，或者说“给我一点提示”。"

    return {
        "reply": reply,
        "phase": phase,
        "intent": intent,
        "question_judgement": judgement,
        "session": session,
    }


def _record_turn_history(
    session: dict[str, Any],
    user_input: Any,
    result: dict[str, Any],
) -> dict[str, Any]:
    # Single source of truth for per-turn bookkeeping.
    # Do not update turn_history or counters in LLM nodes.
    user_text = str(user_input or "").strip()
    if not user_text:
        return session

    history = session.get("turn_history")
    if not isinstance(history, list):
        history = []

    entry = {
        "user_input": user_text,
        "intent": str(result.get("intent") or ""),
        "reply": str(result.get("reply") or ""),
        "verdict": result.get("question_judgement"),
    }
    history.append(entry)
    session["turn_history"] = [
        item
        for item in history
        if isinstance(item, dict) and str(item.get("user_input") or "").strip()
    ][-10:]
    session["last_feedback"] = entry["reply"]
    if entry["intent"] == "question_judgement":
        try:
            session["question_count"] = int(session.get("question_count") or 0) + 1
        except (TypeError, ValueError):
            session["question_count"] = 1
    elif entry["intent"] == "hint_request":
        try:
            session["hint_count"] = int(session.get("hint_count") or 0) + 1
        except (TypeError, ValueError):
            session["hint_count"] = 1
    elif entry["intent"] == "answer_attempt":
        try:
            session["answer_attempt_count"] = int(session.get("answer_attempt_count") or 0) + 1
        except (TypeError, ValueError):
            session["answer_attempt_count"] = 1
    return session


def _route_after_prepare(state: dict[str, Any]) -> str:
    session = _session_from_state(state)
    phase = session.get("phase", "choose_type")
    if phase == "choose_type" and session.get("ready_to_draft"):
        return "soup_draft"
    if phase == "await_soup_confirmation":
        return "soup_confirmation_intent"
    if phase == "playing":
        return "game_intent_classifier"
    if phase == "solved":
        return "solved_turn"
    return "type_selection"


def _route_after_type_selection(state: dict[str, Any]) -> str:
    result = state.get("type_selection")
    if isinstance(result, dict) and result.get("ready_to_draft") is True:
        return "soup_draft"
    return "render_reply"


def _route_after_soup_confirmation_intent(state: dict[str, Any]) -> str:
    result = state.get("soup_confirmation_intent")
    intent = result.get("intent") if isinstance(result, dict) else ""
    return {
        "confirm_start": "confirm_soup_start",
        "revise_soup": "revise_soup",
        "regenerate_soup": "regenerate_soup",
        "clarify_confirmation": "clarify_soup_confirmation",
    }.get(intent, "clarify_soup_confirmation")


def _route_after_game_intent(state: dict[str, Any]) -> str:
    result = state.get("game_intent_classifier")
    intent = result.get("intent") if isinstance(result, dict) else ""
    return {
        "question_judgement": "judge_question",
        "hint_request": "generate_hint",
        "non_question": "classify_non_question",
    }.get(intent, "classify_non_question")


def _route_after_non_question_classifier(state: dict[str, Any]) -> str:
    result = state.get("classify_non_question")
    intent = result.get("intent") if isinstance(result, dict) else ""
    return "judge_answer" if intent == "answer_attempt" else "handle_irrelevant"


workflow = Workflow(
    id="turtle_soup",
    name="海龟汤主持人",
    description="生成原创海龟汤并主持多轮猜谜，严格保护汤底与判定输出。",
    welcome=prompt_contracts.OPENING_MESSAGE,
    inputs=[
        Input("user_input", str, required=True, description="玩家消息"),
    ],
    user_input="user_input",
)


@workflow.node(
    id="prepare_turn",
    description="整理海龟汤会话状态与精品参考",
    output_to_user=False,
)
def prepare_turn(state: dict[str, Any]) -> dict[str, Any]:
    session = _session_from_state(state)
    reference_soups = _read_reference_soups()
    return {
        **{key: prompt_contracts.CLEARED_PHASE_RESULT for key in prompt_contracts.PHASE_RESULT_KEYS},
        "soup_confirmation_intent": prompt_contracts.CLEARED_PHASE_RESULT,
        "game_intent_classifier": prompt_contracts.CLEARED_PHASE_RESULT,
        "classify_non_question": prompt_contracts.CLEARED_PHASE_RESULT,
        "session": session,
        SESSION_STATE_KEY: session,
        "reference_soups": reference_soups,
        "player_turn_context_json": _json_for_prompt(
            {
                "user_input": state.get("user_input", ""),
                "session": session,
                "reference_soups": reference_soups,
            }
        ),
    }


def _phase_llm_node(id: str, description: str, system_prompt: str, temperature: float = 0.4) -> LLMNode:
    return LLMNode(
        id=id,
        description=description,
        system_prompt=system_prompt,
        user_prompt=prompt_contracts.PHASE_NODE_USER_PROMPT,
        output_format="json",
        output_to_user=False,
        save_to_context=False,
        use_context=False,
        model_params={"temperature": temperature},
    )


for node_id, description, system_prompt, temperature in prompt_contracts.LLM_NODE_SPECS:
    workflow.add_node(_phase_llm_node(
        node_id,
        description,
        system_prompt,
        temperature=temperature,
    ))

@workflow.node(
    id="confirm_soup_start",
    description="确认使用候选汤并开始游戏",
    output_to_user=False,
)
def confirm_soup_start(state: dict[str, Any]) -> dict[str, Any]:
    session = _session_from_state(state)
    session["phase"] = "playing"
    session["last_feedback"] = "候选汤已确认，游戏开始。"

    soup_surface = str(session.get("soup_surface") or "").strip()
    if not soup_surface:
        soup_surface = "当前候选汤面缺失。请回复“重新生成”换一题，或重新描述想玩的类型。"

    reply = (
        "游戏开始。\n\n"
        f"汤面：\n{soup_surface}\n\n"
        "你可以开始提问，我只会回答：是 / 否 / 无关 / 部分正确。"
        "也可以说“给我提示”，或直接说“我猜答案是...”。"
    )
    result = {
        "reply": reply,
        "phase": "playing",
        "intent": "soup_confirm",
        "session": session,
    }
    return {
        "confirm_soup_start": result,
        "session": session,
        SESSION_STATE_KEY: session,
    }


@workflow.node(
    id="render_reply",
    description="向玩家输出主持人回复并返回最新会话目录",
    output_to_user=False,
)
async def render_reply(state: dict[str, Any]) -> dict[str, Any]:
    previous_session = _session_from_state(state)
    result = _normalize_phase_result(_result_from_state(state), previous_session)
    result["session"] = _record_turn_history(result["session"], state.get("user_input"), result)
    reply = result["reply"]
    await output(reply, node="render_reply", save_to_context=False, stream=False)
    return {
        "reply": reply,
        "phase": result["phase"],
        "intent": result["intent"],
        "question_judgement": result["question_judgement"],
        "session": result["session"],
        SESSION_STATE_KEY: result["session"],
        "session_dir": f"state.{SESSION_STATE_KEY}",
        "generated_app_dir": str(APP_DIR),
    }


workflow.add_edge("__start__", "prepare_turn")
workflow.add_router(
    after="prepare_turn",
    routes={
        "type_selection": "type_selection",
        "soup_draft": "soup_draft",
        "soup_confirmation_intent": "soup_confirmation_intent",
        "game_intent_classifier": "game_intent_classifier",
        "solved_turn": "solved_turn",
        "default": "type_selection",
    },
    condition=_route_after_prepare,
)
workflow.add_router(
    after="type_selection",
    routes={
        "soup_draft": "soup_draft",
        "render_reply": "render_reply",
        "default": "render_reply",
    },
    condition=_route_after_type_selection,
)
workflow.add_router(
    after="soup_confirmation_intent",
    routes={
        "confirm_soup_start": "confirm_soup_start",
        "revise_soup": "revise_soup",
        "regenerate_soup": "regenerate_soup",
        "clarify_soup_confirmation": "clarify_soup_confirmation",
        "default": "clarify_soup_confirmation",
    },
    condition=_route_after_soup_confirmation_intent,
)
workflow.add_router(
    after="game_intent_classifier",
    routes={
        "judge_question": "judge_question",
        "generate_hint": "generate_hint",
        "classify_non_question": "classify_non_question",
        "default": "classify_non_question",
    },
    condition=_route_after_game_intent,
)
workflow.add_router(
    after="classify_non_question",
    routes={
        "judge_answer": "judge_answer",
        "handle_irrelevant": "handle_irrelevant",
        "default": "handle_irrelevant",
    },
    condition=_route_after_non_question_classifier,
)
workflow.add_edge("soup_draft", "render_reply")
workflow.add_edge("confirm_soup_start", "render_reply")
workflow.add_edge("revise_soup", "render_reply")
workflow.add_edge("regenerate_soup", "render_reply")
workflow.add_edge("clarify_soup_confirmation", "render_reply")
workflow.add_edge("judge_question", "render_reply")
workflow.add_edge("generate_hint", "render_reply")
workflow.add_edge("judge_answer", "render_reply")
workflow.add_edge("handle_irrelevant", "render_reply")
workflow.add_edge("solved_turn", "render_reply")

workflow.publish()

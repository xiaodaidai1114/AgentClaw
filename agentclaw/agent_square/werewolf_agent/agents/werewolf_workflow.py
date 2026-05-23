"""AgentClaw workflow assembly for the AI Werewolf Claw App."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from agentclaw import HumanInput, HumanNode, Input, LLMNode, SubWorkflowNode, Workflow, output
from agentclaw.prompt import PromptManager

try:
    from .werewolf_actor import actor_workflow, create_actor_workflow
    from .werewolf_machine import (
        advance_state_machine,
        apply_actor_outputs,
        apply_user_input,
        review_context,
        set_post_game_choice_request,
    )
    from .werewolf_personas import generate_personas_node
    from .werewolf_prompts import PROMPTS_DIR
    from .werewolf_state import (
        SESSION_STATE_KEY,
        game_from_state,
        new_game,
        player,
        seat_key,
    )
except ImportError:  # pragma: no cover - supports copied template direct import
    from werewolf_actor import actor_workflow, create_actor_workflow  # type: ignore
    from werewolf_machine import (  # type: ignore
        advance_state_machine,
        apply_actor_outputs,
        apply_user_input,
        review_context,
        set_post_game_choice_request,
    )
    from werewolf_personas import generate_personas_node  # type: ignore
    from werewolf_prompts import PROMPTS_DIR  # type: ignore
    from werewolf_state import (  # type: ignore
        SESSION_STATE_KEY,
        game_from_state,
        new_game,
        player,
        seat_key,
    )


APP_DIR = Path(__file__).resolve().parents[1]
OPENING_MESSAGE = (
    "欢迎来到 AI 狼人杀。默认开启 12 人狼王守卫局。"
    "回复“开始游戏”即可开始。"
)


def _new_main_workflow() -> Workflow:
    workflow = Workflow(
        id="ai_werewolf",
        name="AI 狼人杀主持人",
        description="基于主工作流状态机和角色子工作流的 AI 狼人杀。",
        welcome=OPENING_MESSAGE,
        timeout=0,
        recursion_limit=0,
        inputs=[
            Input("user_input", str, required=False, description="玩家输入"),
            Input(SESSION_STATE_KEY, dict, required=False, description="狼人杀会话状态"),
            Input("debug_seed", int, required=False, description="测试用随机种子"),
            Input("debug_user_seat", int, required=False, description="测试用用户座位"),
            Input("debug_user_role", str, required=False, description="测试用用户身份"),
        ],
        user_input="user_input",
    )
    workflow.register_state_field(SESSION_STATE_KEY, dict)
    workflow.register_state_field("actor_requests", dict)
    workflow.register_state_field("actor_outputs", dict)
    workflow.register_state_field("actors", dict)
    workflow.register_state_field("next_input_info", dict)
    workflow.register_state_field("review_context", str)
    workflow.register_state_field("model_review_text", str)
    workflow.use(PromptManager(
        source="file",
        hot_reload=False,
        prompts_dir=str(PROMPTS_DIR),
    ))
    return workflow


def prepare_turn(state: dict[str, Any]) -> dict[str, Any]:
    game = game_from_state(state)
    state[SESSION_STATE_KEY] = game
    state["actors"] = game.get("actors", {})
    state["actor_requests"] = game.get("actor_requests", {})
    state["actor_outputs"] = game.get("actor_outputs", {})
    return {
        "session": game,
        SESSION_STATE_KEY: game,
        "actors": game.get("actors", {}),
        "actor_requests": game.get("actor_requests", {}),
        "actor_outputs": game.get("actor_outputs", {}),
    }


def _route_after_prepare(state: dict[str, Any]) -> str:
    game = game_from_state(state)
    if game.get("phase") == "LOBBY":
        return "setup_game"
    return "apply_user_input"


def setup_game(state: dict[str, Any]) -> dict[str, Any]:
    game = new_game(state)
    return {
        "session": game,
        SESSION_STATE_KEY: game,
        "actors": game.get("actors", {}),
        "actor_requests": game.get("actor_requests", {}),
        "actor_outputs": {},
    }


def apply_user_input_node(state: dict[str, Any]) -> dict[str, Any]:
    game = game_from_state(state)
    apply_user_input(game, str(state.get("user_input") or ""))
    game["stream_log_index"] = len(game.get("public_log", []))
    return {
        "session": game,
        SESSION_STATE_KEY: game,
        "actors": game.get("actors", {}),
        "actor_requests": game.get("actor_requests", {}),
        "actor_outputs": game.get("actor_outputs", {}),
    }


def advance_state(state: dict[str, Any]) -> dict[str, Any]:
    game = game_from_state(state)
    route = advance_state_machine(game)
    while route == "advance":
        route = advance_state_machine(game)
    return {
        "session": game,
        SESSION_STATE_KEY: game,
        "actors": game.get("actors", {}),
        "actor_requests": game.get("actor_requests", {}),
        "actor_outputs": game.get("actor_outputs", {}),
        "next_route": route,
    }


async def collect_actor_outputs(state: dict[str, Any]) -> dict[str, Any]:
    game = game_from_state(state)
    game["actors"] = deepcopy(state.get("actors") or game.get("actors") or {})
    game["actor_outputs"] = deepcopy(state.get("actor_outputs") or {})
    apply_actor_outputs(game)
    await stream_new_public_lines(game)
    return {
        "session": game,
        SESSION_STATE_KEY: game,
        "actors": game.get("actors", {}),
        "actor_requests": game.get("actor_requests", {}),
        "actor_outputs": game.get("actor_outputs", {}),
    }


def call_actors(state: dict[str, Any]) -> dict[str, Any]:
    return {}


def _route_after_call_actors(state: dict[str, Any]) -> str | list[str]:
    requests = state.get("actor_requests")
    if not isinstance(requests, dict) or not requests:
        return "collect_actor_outputs"
    return [
        f"call_actor_{actor_id}"
        for actor_id in sorted(requests)
        if actor_id.startswith("p")
    ] or "collect_actor_outputs"


def _route_after_advance(state: dict[str, Any]) -> str:
    game = game_from_state(state)
    if game.get("phase") == "MODEL_REVIEW" and game.get("review_pending"):
        return "model_review"
    route = state.get("next_route")
    if route == "actors":
        return "call_actors"
    if route == "advance":
        return "advance_state"
    return "render_reply"


def prepare_model_review(state: dict[str, Any]) -> dict[str, Any]:
    game = game_from_state(state)
    return {
        "session": game,
        SESSION_STATE_KEY: game,
        "actors": game.get("actors", {}),
        "actor_requests": game.get("actor_requests", {}),
        "actor_outputs": game.get("actor_outputs", {}),
        "review_context": review_context(game),
    }


def apply_model_review(state: dict[str, Any]) -> dict[str, Any]:
    game = game_from_state(state)
    review = str(state.get("model_review_text") or "").strip()
    if not review:
        review = "模型复盘暂时生成失败。身份复盘：" + "、".join(
            f"{int(item.get('seat') or 0)}号{item.get('role_name')}"
            for item in game.get("players", [])
            if isinstance(item, dict)
        )
    game["model_review"] = review
    game["review_pending"] = False
    game.setdefault("public_log", []).append(review)
    set_post_game_choice_request(game)
    return {
        "session": game,
        SESSION_STATE_KEY: game,
        "actors": game.get("actors", {}),
        "actor_requests": game.get("actor_requests", {}),
        "actor_outputs": game.get("actor_outputs", {}),
        "model_review_text": review,
    }


def _is_public_speech_start(line: str) -> bool:
    return "号玩家开始" in line and line.endswith("发言：")


def _is_public_speech_body(line: str) -> bool:
    prefix, _, _ = line.partition("：")
    return prefix.endswith("号") and prefix[:-1].isdigit()


def _format_public_lines(lines: list[Any]) -> str:
    cleaned = [str(line).strip() for line in lines if str(line).strip()]
    blocks: list[str] = []
    index = 0
    while index < len(cleaned):
        line = cleaned[index]
        if (
            _is_public_speech_start(line)
            and index + 1 < len(cleaned)
            and _is_public_speech_body(cleaned[index + 1])
        ):
            blocks.append(line + "\n" + cleaned[index + 1])
            index += 2
            continue
        blocks.append(line)
        index += 1
    return "\n\n".join(blocks)


def render_game(game: dict[str, Any], *, public_start: int | None = None) -> str:
    sections: list[str] = []
    user_seat = game.get("user_seat")
    if user_seat:
        user = player(game, int(user_seat))
        sections.append(f"你是 {user_seat} 号，身份：{user.get('role_name')}。")
    public_lines = game.get("public_log", [])
    if public_start is not None:
        public_lines = public_lines[public_start:]
    public_lines = public_lines[-20:]
    if public_lines:
        sections.append("公开信息：\n\n" + _format_public_lines(public_lines))
    private_lines = [
        str(line)
        for line in game.get("private_log", {}).get(str(user_seat), [])
        if isinstance(line, str) and not line.startswith("身份已发放。")
    ]
    if private_lines:
        sections.append("你的私有信息：\n" + "\n".join(private_lines[-10:]))
    request = game.get("pending_request")
    if isinstance(request, dict) and request.get("actor") == "user":
        sections.append(str(request.get("prompt") or "轮到你行动了。"))
    return "\n\n".join(section for section in sections if str(section).strip())


def _streamable_public_line(line: str) -> bool:
    text = str(line).strip()
    if not text or text.startswith("天黑请闭眼"):
        return False
    if "玩家开始发言" in text or "号：" in text or "号遗言：" in text:
        return False
    return True


async def stream_new_public_lines(game: dict[str, Any]) -> None:
    lines = [str(line) for line in game.get("public_log", []) if isinstance(line, str)]
    start = int(game.get("stream_log_index") or 0)
    if start < 0 or start > len(lines):
        start = 0
    new_lines = lines[start:]
    game["stream_log_index"] = len(lines)
    streamable = [line for line in new_lines if _streamable_public_line(line)]
    if streamable:
        await output(_format_public_lines(streamable) + "\n\n", node="actor_speech", save_to_context=False, stream=True)


def build_user_input_modes(state: dict[str, Any]) -> list[HumanInput]:
    game = state.get("session") or state.get(SESSION_STATE_KEY) or {}
    request = game.get("pending_request")
    if not isinstance(request, dict) or request.get("actor") != "user":
        return []

    kind = str(request.get("kind") or "")
    prompt = str(request.get("prompt") or "")
    modes: list[HumanInput] = []
    targets = [int(seat) for seat in request.get("target_seats") or []]

    if kind == "election_join":
        modes = [
            HumanInput.button("上警", value="上警"),
            HumanInput.button("不上警", value="不上警"),
        ]
    elif kind in {"night_kill", "seer_check", "guard", "election_vote", "election_pk_vote", "day_vote", "day_pk_vote"}:
        modes = [HumanInput.button(f"{seat}号", value=f"{seat}号") for seat in targets]
    elif kind == "day_order":
        modes = [
            HumanInput.button("警左", value="警左"),
            HumanInput.button("警右", value="警右"),
        ]
        modes.extend(HumanInput.button(f"从{seat}号开始", value=f"从{seat}号开始") for seat in targets)
    elif kind == "witch":
        modes = [HumanInput.button("不用药", value="不用药")]
        action_targets = request.get("action_targets") if isinstance(request.get("action_targets"), dict) else {}
        save_targets = [int(seat) for seat in action_targets.get("save") or []]
        poison_targets = [int(seat) for seat in action_targets.get("poison") or []]
        modes.extend(HumanInput.button(f"救{seat}号", value=f"救{seat}号") for seat in save_targets)
        modes.extend(HumanInput.button(f"毒{seat}号", value=f"毒{seat}号") for seat in poison_targets)
    elif kind == "hunter_status":
        modes = [HumanInput.button("知道了", value="知道了")]
    elif kind in {"hunter_shot", "wolf_king_shot"}:
        modes = [HumanInput.button("不开枪", value="不开枪")]
        modes.extend(HumanInput.button(f"带走{seat}号", value=f"带走{seat}号") for seat in targets)
    elif kind == "sheriff_badge":
        modes = [HumanInput.button("撕毁警徽", value="撕毁警徽")]
        modes.extend(HumanInput.button(f"给{seat}号", value=f"给{seat}号") for seat in targets)
    elif kind in {"day_speech", "election_speech", "election_pk_speech", "day_pk_speech"}:
        modes = [HumanInput.text(placeholder=prompt)]
        if kind == "election_speech":
            modes.append(HumanInput.button("退水", value='{"kind":"withdraw_election"}'))
        seat = int(request.get("seat") or game.get("user_seat") or 0)
        if seat and player(game, seat).get("role") in {"wolf", "wolf_king"}:
            modes.append(HumanInput.button("自爆", value='{"kind":"self_explode"}'))
    elif kind == "last_words":
        modes = [HumanInput.text(placeholder=prompt)]
    elif kind == "post_death_choice":
        modes = [
            HumanInput.button("继续旁观", value="继续旁观"),
            HumanInput.button("结束并复盘", value="结束游戏"),
        ]
    elif kind == "post_game_choice":
        modes = [
            HumanInput.button("开启下一轮", value="开启下一轮"),
            HumanInput.button("结束", value="结束"),
        ]

    if not modes:
        modes = [HumanInput.text(placeholder=prompt or None)]

    return modes


USER_INPUT_NODE = HumanNode(
    id="werewolf_user_input",
    feedback_field="user_input",
    input_modes=build_user_input_modes,
)


def build_next_input_info(game: dict[str, Any]) -> dict[str, Any] | None:
    request = game.get("pending_request")
    if not isinstance(request, dict) or request.get("actor") != "user":
        return None

    payload = USER_INPUT_NODE.build_interrupt_payload({
        "session": game,
        SESSION_STATE_KEY: game,
    })
    return {
        "waiting_for": payload.get("waiting_for", "user_input"),
        "input_modes": payload.get("input_modes", []),
    }


async def render_reply(state: dict[str, Any]) -> dict[str, Any]:
    game = game_from_state(state)
    public_start = int(game.get("stream_log_index") or 0)
    await stream_new_public_lines(game)
    reply = render_game(game, public_start=public_start)
    next_input_info = build_next_input_info(game)
    if reply.strip():
        await output(reply, node="render_reply", save_to_context=False, stream=False)
    result = {
        "reply": reply,
        "session": game,
        SESSION_STATE_KEY: game,
        "next_input_info": next_input_info or {},
        "session_dir": f"state.{SESSION_STATE_KEY}",
        "generated_app_dir": str(APP_DIR),
    }
    return result


def create_werewolf_workflow(
    *,
    actor: Workflow | None = None,
    enable_model_actor_decision: bool = False,
    actor_model_id: str | None = None,
    publish_workflow: bool = True,
) -> Workflow:
    selected_actor = actor or (
        create_actor_workflow(
            enable_model_decision=True,
            model_id=actor_model_id,
        )
        if enable_model_actor_decision
        else actor_workflow
    )
    workflow = _new_main_workflow()

    workflow.node(id="prepare_turn", description="整理狼人杀主状态", output_to_user=False)(prepare_turn)
    workflow.node(id="setup_game", description="初始化 12 人狼王守卫局", output_to_user=False)(setup_game)
    workflow.node(id="generate_personas", description="为非玩家生成差异化角色人格", output_to_user=False)(generate_personas_node)
    workflow.node(id="apply_user_input", description="应用用户当前阶段输入", output_to_user=False)(apply_user_input_node)
    workflow.node(id="advance_state", description="推进狼人杀主状态机", output_to_user=False)(advance_state)
    workflow.node(id="collect_actor_outputs", description="合并角色子工作流结果", output_to_user=False)(collect_actor_outputs)
    workflow.node(id="call_actors", description="并行调用所有 AI 角色子工作流", output_to_user=False)(call_actors)
    workflow.node(id="prepare_model_review", description="整理狼人杀模型复盘上下文", output_to_user=False)(prepare_model_review)
    workflow.add_node(LLMNode(
        id="model_review",
        description="生成狼人杀身份复盘与关键局势复盘",
        system_prompt=(
            "你是狼人杀复盘主持。根据 review_context 生成一份狼人杀复盘，"
            "必须按轮次概括所有出现过的夜晚和白天，每轮1句，重点提关键夜晚、警徽、放逐票型和阵营转折。"
            "再给身份复盘、双方主要失误与亮点。不要逐字复述长发言，不要编造 review_context 没有的信息。"
            "用中文，控制在600字以内，分段清楚，最后询问用户是否开启下一轮。"
        ),
        user_prompt="{review_context}",
        output_key="model_review_text",
        output_to_user=False,
        save_to_context=False,
        use_context=False,
        model_params={"temperature": 0.4},
    ))
    workflow.node(id="apply_model_review", description="写入狼人杀模型复盘", output_to_user=False)(apply_model_review)
    workflow.node(id="render_reply", description="输出狼人杀主持人回复", output_to_user=False)(render_reply)

    workflow.add_edge("__start__", "prepare_turn")
    workflow.add_router(
        after="prepare_turn",
        routes={
            "setup_game": "setup_game",
            "apply_user_input": "apply_user_input",
        },
        condition=_route_after_prepare,
    )
    workflow.add_edge("setup_game", "generate_personas")
    workflow.add_edge("generate_personas", "advance_state")
    workflow.add_edge("apply_user_input", "advance_state")

    actor_call_ids: list[str] = []
    for seat in range(1, 13):
        actor_id = seat_key(seat)
        node_id = f"call_actor_{actor_id}"
        actor_call_ids.append(node_id)
        workflow.add_node(SubWorkflowNode(
            id=node_id,
            workflow=selected_actor,
            instance_id=actor_id,
            thread_id_strategy="derived",
            readonly_input_map={
                "request": f"actor_requests.{actor_id}",
                "seat": f"actor_requests.{actor_id}.seat",
            },
            state_map={
                "memory": f"actors.{actor_id}.memory",
            },
            output_map={
                "actor_result": f"actor_outputs.{actor_id}",
            },
            merge_strategy={
                "actors": "deep_merge",
                "actor_outputs": "deep_merge",
            },
            stream_child_events=True,
            stream_child_node_events=False,
        ))

    workflow.add_router(
        after="advance_state",
        routes={
            "call_actors": "call_actors",
            "advance_state": "advance_state",
            "model_review": "prepare_model_review",
            "render_reply": "render_reply",
        },
        condition=_route_after_advance,
    )
    workflow.add_conditional_edge("call_actors", _route_after_call_actors)
    for node_id in actor_call_ids:
        workflow.add_edge(node_id, "collect_actor_outputs")
    workflow.add_edge("collect_actor_outputs", "advance_state")
    workflow.add_edge("prepare_model_review", "model_review")
    workflow.add_edge("model_review", "apply_model_review")
    workflow.add_edge("apply_model_review", "render_reply")
    workflow.add_edge("render_reply", "__end__")

    if publish_workflow:
        workflow.publish()
    return workflow


workflow = create_werewolf_workflow(enable_model_actor_decision=True)


_render_game = render_game
_build_next_input_info = build_next_input_info
_streamable_public_line = _streamable_public_line

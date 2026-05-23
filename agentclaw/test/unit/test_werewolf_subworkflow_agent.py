import importlib.util
import json
import re
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_DIR = PROJECT_ROOT / "agentclaw" / "agent_square" / "werewolf_agent"


class _FakeLLMResult:
    def __init__(self, content):
        self.content = content


class _FakeLLMManager:
    auto_fallback = False
    fallback_threshold = 0

    def __init__(self, responses=None, resolver=None):
        self.responses = list(responses or [])
        self.resolver = resolver
        self.messages = []

    async def invoke(self, messages, model_id=None, **params):
        self.messages.append(messages)
        if self.resolver:
            return _FakeLLMResult(self.resolver(messages))
        return _FakeLLMResult(self.responses.pop(0))


def _extract_mock_actor_view(messages):
    joined = "\n".join(str(message.get("content", "")) for message in messages)
    match = re.search(r"actor_view:\s*(\{.*?\})\s*只输出一行紧凑 JSON", joined, re.S)
    if not match:
        return None
    return json.loads(match.group(1))


def _werewolf_actor_decision_resolver(messages):
    actor_view = _extract_mock_actor_view(messages)
    if actor_view is None:
        source = str(messages[-1].get("content", ""))
        if source.strip().startswith("{"):
            return source
        return '{"kind":"skip"}'

    seat = int(actor_view.get("seat") or 0)
    kind = actor_view.get("kind")
    if kind == "night_kill":
        return '{"kind":"kill","target_seat":2}'
    if kind == "seer_check":
        return '{"kind":"check","target_seat":1}'
    if kind == "guard":
        return '{"kind":"guard","target_seat":12}'
    if kind == "witch":
        return '{"kind":"skip"}'
    if kind == "hunter_status":
        return '{"kind":"hunter_status"}'
    if kind == "election_join":
        join = seat in {5, 6, 8}
        action = "join_election" if join else "skip_election"
        return f'{{"kind":"{action}"}}'
    if kind == "election_speech":
        speeches = {
            5: "5号模型发言：我起跳预言家，昨夜验了1号金水，警徽流6、8。",
            6: "6号模型发言：我不上身份，重点听5和8的预言家视角。",
            8: "8号模型发言：我认为5号有完整警徽流，暂时偏信。",
        }
        return json.dumps(
            {"kind": "speak", "speech": speeches.get(seat, f"{seat}号模型发言。")},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return '{"kind":"skip"}'


def _patch_actor_subworkflows(parent_workflow, actor_workflow):
    for seat in range(1, 13):
        node = parent_workflow.get_node(f"call_actor_p{seat}")
        if node is not None:
            node.workflow = actor_workflow


def _workflow_with_mock_model_actor(module, resolver=_werewolf_actor_decision_resolver):
    model_actor = module.create_actor_workflow(enable_model_decision=True)
    model_actor._llm_manager = _FakeLLMManager(resolver=resolver)
    model_actor._components_initialized = True
    return module.create_werewolf_workflow(actor=model_actor, publish_workflow=False)


def _load_werewolf_module():
    from agentclaw.api.registry import WorkflowRegistry

    WorkflowRegistry.unregister("ai_werewolf")
    module_path = AGENT_DIR / "agents" / "werewolf.py"
    spec = importlib.util.spec_from_file_location("agent_square_werewolf_subworkflow", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_werewolf_agent_uses_main_workflow_and_actor_subworkflow_instances():
    module = _load_werewolf_module()

    assert module.workflow.id == "ai_werewolf"
    assert module.actor_workflow.id == "werewolf_actor"

    structure = module.workflow.get_structure()
    node_ids = {node["id"] for node in structure["nodes"]}
    actor_call_ids = {f"call_actor_p{seat}" for seat in range(1, 13)}

    assert actor_call_ids.issubset(node_ids)
    assert {"prepare_turn", "advance_state", "collect_actor_outputs", "render_reply"}.issubset(node_ids)
    assert all(
        module.workflow.get_node(node_id).thread_id_strategy == "derived"
        for node_id in actor_call_ids
    )


def test_werewolf_routes_only_actor_nodes_with_current_requests():
    module = _load_werewolf_module()

    assert module._route_after_call_actors({
        "actor_requests": {
            "p2": {"kind": "night_kill"},
            "p7": {"kind": "guard"},
        }
    }) == ["call_actor_p2", "call_actor_p7"]
    assert module._route_after_call_actors({"actor_requests": {}}) == "collect_actor_outputs"


def test_werewolf_actor_call_nodes_hide_child_runtime_events():
    module = _load_werewolf_module()

    for seat in range(1, 13):
        node = module.workflow.get_node(f"call_actor_p{seat}")
        assert node.stream_child_events is True


def test_werewolf_workflow_has_no_hard_timeout():
    module = _load_werewolf_module()

    assert module.workflow.timeout == 0


def test_werewolf_new_game_does_not_hardcode_personas_before_model_generation():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })

    assert set(game["actors"]) == {f"p{seat}" for seat in range(2, 13)}
    assert all(actor["persona"] == {} for actor in game["actors"].values())


@pytest.mark.asyncio
async def test_werewolf_personas_can_be_generated_by_llm_and_saved_to_actor_state():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    manager = _FakeLLMManager([
        json.dumps({
            "p2": {
                "temperament": "急躁但会找补",
                "speech_style": "短句、口语、有停顿",
                "strategic_bias": "容易先冲，压力大时转倒钩",
                "table_habits": "不爱完整复读警下名单，只抓一个矛盾猛打",
            },
            "p3": {
                "temperament": "谨慎慢热",
                "speech_style": "先保留，再给轻压力",
                "strategic_bias": "好人时重视听感，狼人时偏潜伏",
                "table_habits": "喜欢用前后发言变化做判断",
            },
        }, ensure_ascii=False)
    ])
    context = WorkflowContext(thread_id="werewolf-persona-gen")
    context.llm_manager = manager
    context.prompt_manager = module.workflow._prompt_manager
    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })

    result = await module.generate_personas_node({module.SESSION_STATE_KEY: game}, context)
    updated = result[module.SESSION_STATE_KEY]

    assert updated["actors"]["p2"]["persona"]["temperament"] == "急躁但会找补"
    assert updated["actors"]["p2"]["persona"]["strategic_bias"] == "容易先冲，压力大时转倒钩"
    assert updated["actors"]["p3"]["persona"]["speech_style"] == "先保留，再给轻压力"
    assert updated["actors"]["p4"]["persona"] == {}
    assert "非用户座位" in manager.messages[0][0]["content"]
    assert "真实网杀/线下狼人杀玩家" in manager.messages[0][0]["content"]


def test_werewolf_decision_phases_create_parallel_actor_requests_but_speech_stays_single_seat():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "ELECTION_AI_JOIN"
    assert module.prepare_election_ai_choices(game) is True
    assert len(game["actor_requests"]) == 11
    assert set(module._route_after_call_actors(game)) == {f"call_actor_p{seat}" for seat in range(2, 13)}

    game["election"]["speech_queue"] = [5, 6, 8]
    game["phase"] = "ELECTION_AI_SPEECH"
    assert module.prepare_current_ai_speech(game) is True
    assert list(game["actor_requests"]) == ["p5"]
    assert module._route_after_call_actors(game) == ["call_actor_p5"]


def test_werewolf_ai_vote_phase_without_pending_actor_requests_advances_to_resolution():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_AI_VOTE"
    for seat in module.alive_seats(game):
        if seat != 1:
            module.record_vote(game, seat, 1, "day_vote")

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "DAY_RESOLVE_VOTE"


def test_werewolf_day_vote_does_not_reuse_previous_day_user_vote():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 10,
        "debug_user_role": "witch",
    })
    game["day"] = 2
    game["phase"] = "DAY_VOTE"
    game["votes"] = [
        {"from": 10, "to": 1, "phase": "day_vote"},
        {"from": 4, "to": 1, "phase": "day_vote"},
    ]

    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["pending_request"]["kind"] == "day_vote"
    assert game["pending_request"]["seat"] == 10


def test_werewolf_day_vote_result_ignores_previous_day_votes():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 10,
        "debug_user_role": "witch",
    })
    game["day"] = 2
    game["votes"] = [
        {"from": 1, "to": 3, "phase": "day_vote"},
        {"from": 7, "to": 3, "phase": "day_vote"},
    ]
    module.record_vote(game, 10, 12, "day_vote")

    assert module.vote_winners(game, "day_vote", module.alive_seats(game)) == [12]


def test_werewolf_day_pk_ai_vote_phase_without_pending_actor_requests_advances_to_resolution():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_VOTE_PK_AI_VOTE"
    game["day_vote"] = {
        "pk_candidates": [2, 3],
        "pk_voters": [1, 4, 5],
    }
    for seat in [4, 5]:
        module.record_vote(game, seat, 2, "day_pk_vote")

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "DAY_VOTE_PK_RESOLVE"


def test_werewolf_advance_state_collapses_consecutive_internal_transitions():
    module = _load_werewolf_module()
    workflow = module.create_werewolf_workflow(publish_workflow=False)
    advance_node = workflow.get_node("advance_state")
    calls = []

    def fake_advance_state_machine(game):
        calls.append(str(game.get("phase")))
        if len(calls) < 5:
            game["phase"] = f"AUTO_{len(calls)}"
            return "advance"
        return "render"

    original = advance_node.handler.__globals__["advance_state_machine"]
    advance_node.handler.__globals__["advance_state_machine"] = fake_advance_state_machine
    try:
        result = advance_node.handler({module.SESSION_STATE_KEY: module.empty_game()})
    finally:
        advance_node.handler.__globals__["advance_state_machine"] = original

    assert calls == ["LOBBY", "AUTO_1", "AUTO_2", "AUTO_3", "AUTO_4"]
    assert result["next_route"] == "render"


def test_werewolf_streams_public_state_announcements_not_only_speeches():
    module = _load_werewolf_module()

    assert module._streamable_public_line("警长竞选名单已确定。")
    assert module._streamable_public_line("本轮上警玩家：5号、8号。")
    assert module._streamable_public_line("警长投票结果：5号3票、8号2票。")
    assert module._streamable_public_line("昨夜死亡：1号。")
    assert not module._streamable_public_line("5号玩家开始发言：")
    assert not module._streamable_public_line("5号：我起跳预言家。")


@pytest.mark.asyncio
async def test_werewolf_parallel_vote_actor_calls_start_together():
    import asyncio

    from agentclaw import BaseNode, Workflow
    from agentclaw.graph.context import WorkflowContext

    module = _load_werewolf_module()
    starts: dict[int, float] = {}

    class SlowVoteActorNode(BaseNode):
        async def _do_execute(self, state, context):
            seat = int(state.get("seat") or state.get("request", {}).get("seat") or 0)
            starts[seat] = time.perf_counter()
            await asyncio.sleep(0.2)
            state["actor_result"] = {
                "seat": seat,
                "request_kind": "day_vote",
                "action": {"seat": seat, "kind": "vote", "target_seat": 1},
            }
            return state

    actor = Workflow(id="slow_vote_actor", name="Slow Vote Actor", tracing=False)
    actor.register_state_field("request", dict)
    actor.register_state_field("seat", int)
    actor.register_state_field("actor_result", dict)
    actor.add_node(SlowVoteActorNode(id="act", output_to_user=False))
    actor.add_edge("__start__", "act")
    actor.add_edge("act", "__end__")

    workflow = module.create_werewolf_workflow(actor=actor, publish_workflow=False)
    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_AI_VOTE"
    module.prepare_day_ai_votes(game)

    begin = time.perf_counter()
    result = await workflow.run(
        {module.SESSION_STATE_KEY: game},
        WorkflowContext(thread_id="werewolf-parallel-vote"),
        thread_id="werewolf-parallel-vote",
    )
    elapsed = time.perf_counter() - begin
    state = result["state"][module.SESSION_STATE_KEY]

    assert len(starts) >= 8
    assert max(starts.values()) - min(starts.values()) < 0.08
    assert elapsed < 0.5
    assert any(vote.get("phase") == "day_vote" for vote in state["votes"])


@pytest.mark.asyncio
async def test_werewolf_streams_ai_speech_without_child_internal_node_events():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext
    from agentclaw.runtime.streaming.context import OutputChannel

    model_actor = module.create_actor_workflow(enable_model_decision=True)
    model_actor._llm_manager = _FakeLLMManager(resolver=_werewolf_actor_decision_resolver)
    model_actor._components_initialized = True
    workflow = module.create_werewolf_workflow(actor=model_actor, publish_workflow=False)

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "ELECTION_AI_SPEECH"
    game["election"]["speech_queue"] = [5]
    game["election"]["candidates"] = [5]
    game["election"]["voters"] = [1, 2, 3]
    game["stream_log_index"] = len(game["public_log"])
    module.prepare_current_ai_speech(game)

    async with OutputChannel(workflow_id=workflow.id, thread_id="werewolf-stream-speech", stream_mode=True) as channel:
        result = await workflow.run(
            {module.SESSION_STATE_KEY: game},
            WorkflowContext(thread_id="werewolf-stream-speech"),
            thread_id="werewolf-stream-speech",
        )
        events = []
        while not channel.queue.empty():
            events.append(await channel.queue.get())

    messages = [event.get("answer", "") for event in events if event.get("event") == "message"]
    node_ids = [
        event.get("data", {}).get("node_id")
        for event in events
        if event.get("event") in {"node_started", "node_finished"}
    ]

    assert any("5号模型发言" in message for message in messages)
    assert "call_actor_p5" in node_ids
    assert "build_view" not in node_ids
    assert "stream_speech" not in node_ids
    assert "llm_decide" not in node_ids
    assert result["state"][module.SESSION_STATE_KEY]["phase"] == "ELECTION_VOTE"


@pytest.mark.asyncio
async def test_werewolf_actor_subworkflow_isolated_memory_maps_back_to_main_state():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    result = await module.workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 7,
            "debug_user_seat": 1,
            "debug_user_role": "villager",
        },
        WorkflowContext(thread_id="werewolf-subworkflow-test"),
        thread_id="werewolf-subworkflow-test",
    )
    state = result["state"]
    game = state[module.SESSION_STATE_KEY]

    assert game["phase"] == "ELECTION_JOIN"
    assert game["pending_request"]["actor"] == "user"
    assert game["pending_request"]["kind"] == "election_join"
    assert game["day"] == 1
    assert len(game["players"]) == 12
    assert any("天黑请闭眼" in line for line in game["public_log"])
    assert any("天亮了" in line for line in game["public_log"])
    assert game["actors"]
    assert any(
        actor_state.get("memory", {}).get("last_thread_id", "").endswith(":actor:p2")
        for actor_state in game["actors"].values()
    )
    assert state["__call_actor_p2_metadata__"]["sub_workflow_id"] == "werewolf_actor"
    assert state["__call_actor_p2_metadata__"]["thread_id"] == "werewolf-subworkflow-test:actor:p2"
    assert "actor_outputs" not in game or not game["actor_outputs"]
    assert state["next_input_info"]["input_modes"] == [
        {"type": "button", "label": "上警", "value": "上警", "confirm": False},
        {"type": "button", "label": "不上警", "value": "不上警", "confirm": False},
    ]


@pytest.mark.asyncio
async def test_werewolf_user_wolf_gets_first_night_kill_request_before_ai_night_continues():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    context = WorkflowContext(thread_id="werewolf-user-wolf-night")
    result = await module.workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 11,
            "debug_user_seat": 1,
            "debug_user_role": "wolf",
        },
        context,
        thread_id="werewolf-user-wolf-night",
    )
    game = result["state"][module.SESSION_STATE_KEY]

    assert game["phase"] == "NIGHT_WOLF"
    assert game["pending_request"]["actor"] == "user"
    assert game["pending_request"]["kind"] == "night_kill"
    assert game["pending_request"]["seat"] == 1
    assert all(
        game["players"][seat - 1]["camp"] != "wolf"
        for seat in game["pending_request"]["target_seats"]
    )
    assert any("天黑请闭眼" in line for line in game["public_log"])
    assert not any("天亮了" in line for line in game["public_log"])


def test_werewolf_render_exposes_buttons_for_user_election_choice():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["pending_request"] = {
        "kind": "election_join",
        "actor": "user",
        "seat": 1,
        "prompt": "你可以回复“上警”参加警长竞选，也可以回复“不上警”留在警下。",
    }

    next_input_info = module._build_next_input_info(game)

    assert next_input_info == {
        "waiting_for": "user_input",
        "input_modes": [
            {"type": "button", "label": "上警", "value": "上警", "confirm": False},
            {"type": "button", "label": "不上警", "value": "不上警", "confirm": False},
        ],
    }


def test_werewolf_render_exposes_text_and_self_explode_button_for_user_wolf_speech():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf",
    })
    game["pending_request"] = {
        "kind": "day_speech",
        "actor": "user",
        "seat": 2,
        "prompt": "轮到你发表白天发言。",
    }

    next_input_info = module._build_next_input_info(game)

    assert next_input_info == {
        "waiting_for": "user_input",
        "input_modes": [
            {"type": "text", "placeholder": "轮到你发表白天发言。"},
            {"type": "button", "label": "自爆", "value": '{"kind":"self_explode"}', "confirm": False},
        ],
    }


def test_werewolf_render_exposes_self_explode_button_for_user_wolf_election_speech():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf",
    })
    game["pending_request"] = {
        "kind": "election_speech",
        "actor": "user",
        "seat": 2,
        "prompt": "轮到你发表警上发言。",
    }

    next_input_info = module._build_next_input_info(game)

    assert next_input_info == {
        "waiting_for": "user_input",
        "input_modes": [
            {"type": "text", "placeholder": "轮到你发表警上发言。"},
            {"type": "button", "label": "退水", "value": '{"kind":"withdraw_election"}', "confirm": False},
            {"type": "button", "label": "自爆", "value": '{"kind":"self_explode"}', "confirm": False},
        ],
    }


def test_werewolf_render_exposes_left_right_buttons_for_sheriff_day_order():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 3,
        "debug_user_role": "villager",
    })
    game["pending_request"] = {
        "kind": "day_order",
        "actor": "user",
        "seat": 3,
        "target_seats": [1, 2, 4],
        "prompt": "你是警长，请选择发言方向。",
    }

    next_input_info = module._build_next_input_info(game)

    assert next_input_info == {
        "waiting_for": "user_input",
        "input_modes": [
            {"type": "button", "label": "警左", "value": "警左", "confirm": False},
            {"type": "button", "label": "警右", "value": "警右", "confirm": False},
            {"type": "button", "label": "从1号开始", "value": "从1号开始", "confirm": False},
            {"type": "button", "label": "从2号开始", "value": "从2号开始", "confirm": False},
            {"type": "button", "label": "从4号开始", "value": "从4号开始", "confirm": False},
        ],
    }


def test_werewolf_next_input_info_uses_human_node_payload_builder(monkeypatch):
    module = _load_werewolf_module()
    called = {}

    class FakeHumanNode:
        def __init__(self, *, id, feedback_field, input_modes):
            called["id"] = id
            called["feedback_field"] = feedback_field
            called["input_modes"] = input_modes

        def build_interrupt_payload(self, state):
            called["state"] = state
            feedback_field = called["feedback_field"]
            return {
                "waiting_for": feedback_field,
                "input_modes": [{"type": "button", "label": "fake", "value": feedback_field, "confirm": False}],
                "node": called["id"],
    }

    fake_node = FakeHumanNode(
        id="werewolf_user_input",
        feedback_field="user_input",
        input_modes=module._build_next_input_info.__globals__["build_user_input_modes"],
    )
    monkeypatch.setitem(module._build_next_input_info.__globals__, "USER_INPUT_NODE", fake_node)
    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["pending_request"] = {
        "kind": "election_join",
        "actor": "user",
        "seat": 1,
        "prompt": "你可以回复“上警”参加警长竞选，也可以回复“不上警”留在警下。",
    }

    next_input_info = module._build_next_input_info(game)

    assert called["id"] == "werewolf_user_input"
    assert called["feedback_field"] == "user_input"
    assert callable(called["input_modes"])
    assert called["state"]["session"] is game
    assert next_input_info == {
        "waiting_for": "user_input",
        "input_modes": [{"type": "button", "label": "fake", "value": "user_input", "confirm": False}],
    }


@pytest.mark.asyncio
async def test_werewolf_user_wolf_action_records_kill_then_continues_to_election_join():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    context = WorkflowContext(thread_id="werewolf-user-wolf-continue")
    first = await module.workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 13,
            "debug_user_seat": 1,
            "debug_user_role": "wolf",
        },
        context,
        thread_id="werewolf-user-wolf-continue",
    )
    game = first["state"][module.SESSION_STATE_KEY]
    target = game["pending_request"]["target_seats"][0]

    second = await module.workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": f"{target}号"},
        context,
        thread_id="werewolf-user-wolf-continue",
    )
    game = second["state"][module.SESSION_STATE_KEY]

    assert game["night"]["wolf_target"] == target
    assert game["phase"] == "ELECTION_JOIN"
    assert game["pending_request"]["kind"] == "election_join"
    assert any("天亮了" in line for line in game["public_log"])


@pytest.mark.asyncio
async def test_werewolf_user_seer_pauses_after_ai_wolf_and_before_guard():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    result = await module.workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 17,
            "debug_user_seat": 1,
            "debug_user_role": "seer",
        },
        WorkflowContext(thread_id="werewolf-user-seer-night"),
        thread_id="werewolf-user-seer-night",
    )
    game = result["state"][module.SESSION_STATE_KEY]

    assert game["phase"] == "NIGHT_SEER"
    assert game["pending_request"]["kind"] == "seer_check"
    assert game["pending_request"]["actor"] == "user"
    assert game["night"]["wolf_target"] is not None
    assert "guard_target" not in game["night"]


def test_werewolf_user_seer_check_records_private_alignment_result():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "seer",
    })
    wolf_target = next(item["seat"] for item in game["players"] if item["camp"] == "wolf" and item["seat"] != 1)
    game["phase"] = "NIGHT_SEER"
    game["pending_request"] = {
        "kind": "seer_check",
        "actor": "user",
        "seat": 1,
        "target_seats": [wolf_target],
        "prompt": "预言家请查验。",
    }

    module.apply_user_input(game, f"查验{wolf_target}号")

    assert game["night"]["seer_checks"]["1"] == wolf_target
    assert game["private_log"]["1"][-1] == f"第1晚查验：{wolf_target}号是狼人。"


def test_werewolf_ai_seer_check_result_enters_actor_private_view():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    seer_seat = next(item["seat"] for item in game["players"] if item["role"] == "seer")
    good_target = next(
        item["seat"]
        for item in game["players"]
        if item["camp"] == "good" and item["seat"] != seer_seat
    )
    game["phase"] = "NIGHT_SEER"
    actor_id = f"p{seer_seat}"
    game["actor_requests"] = {
        actor_id: module._build_actor_request(game, seer_seat, "seer_check", [good_target])
    }
    game["actor_outputs"] = {
        actor_id: {
            "action": {
                "seat": seer_seat,
                "kind": "check",
                "target_seat": good_target,
            }
        }
    }

    module.apply_actor_outputs(game)
    speech_request = module._build_actor_request(game, seer_seat, "election_speech", [])
    view = module.build_actor_view(speech_request, {})

    assert game["night"]["seer_checks"][str(seer_seat)] == good_target
    assert game["private_log"][str(seer_seat)][-1] == f"第1晚查验：{good_target}号是好人。"
    assert view["private_info"]["seer_checks"] == [
        {"day": 1, "target_seat": good_target, "alignment": "good", "result_name": "好人"}
    ]


def test_werewolf_closed_eye_speech_view_hides_private_night_summary():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "hunter",
    })
    closed_eye_seat = next(
        item["seat"]
        for item in game["players"]
        if item["role"] in {"villager", "idiot", "hunter"} and item["seat"] != 2
    )
    game["phase"] = "ELECTION_NEXT_SPEECH"
    game["night"] = {
        "wolf_target": 1,
        "witch_saved": True,
        "guard_target": 8,
        "seer_checks": {"9": 3},
    }
    game["public_log"] = [
        "天黑请闭眼。",
        "天亮了。",
        "警长竞选名单已确定。",
    ]

    request = module._build_actor_request(game, closed_eye_seat, "election_speech", [])
    view = module.build_actor_view(request, {})
    serialized = json.dumps(view, ensure_ascii=False)

    assert view["night_summary"] == {}
    assert "wolf_target" not in serialized
    assert "witch_saved" not in serialized
    assert "guard_target" not in serialized
    assert "seer_checks" not in serialized


def test_werewolf_seer_speech_view_hides_other_private_night_actions():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "hunter",
    })
    seer_seat = next(item["seat"] for item in game["players"] if item["role"] == "seer")
    check_target = next(item["seat"] for item in game["players"] if item["camp"] == "good" and item["seat"] != seer_seat)
    game["night"] = {
        "wolf_target": 1,
        "witch_saved": True,
        "guard_target": 8,
        "seer_checks": {str(seer_seat): check_target},
    }
    game["seer_private_checks"] = {
        str(seer_seat): [
            {
                "day": 1,
                "target_seat": check_target,
                "alignment": "good",
                "result_name": "好人",
            }
        ]
    }

    request = module._build_actor_request(game, seer_seat, "election_speech", [])
    view = module.build_actor_view(request, {})
    serialized = json.dumps(view, ensure_ascii=False)

    assert view["private_info"]["seer_checks"] == [
        {"day": 1, "target_seat": check_target, "alignment": "good", "result_name": "好人"}
    ]
    assert view["night_summary"] == {}
    assert "wolf_target" not in serialized
    assert "witch_saved" not in serialized
    assert "guard_target" not in serialized


def test_werewolf_witch_night_view_keeps_own_kill_target_private_info():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "hunter",
    })
    witch_seat = next(item["seat"] for item in game["players"] if item["role"] == "witch")
    game["phase"] = "NIGHT_WITCH"
    game["night"] = {"wolf_target": 1}

    request = module._build_actor_request(game, witch_seat, "witch", [1])
    view = module.build_actor_view(request, {})

    assert view["night_summary"] == {}
    assert view["private_info"]["night_kill_target"] == 1
    assert view["private_info"]["witch_save_target"] == 1
    assert view["private_info"]["witch_can_save"] is True


def test_werewolf_hunter_status_view_includes_private_shot_status():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    hunter_seat = next(item["seat"] for item in game["players"] if item["role"] == "hunter")
    game["phase"] = "NIGHT_HUNTER"
    game["night"]["witch_poison_target"] = hunter_seat

    request = module._build_actor_request(game, hunter_seat, "hunter_status", [])
    view = module.build_actor_view(request, {})

    assert view["private_info"]["hunter_can_shoot"] is False
    assert view["private_info"]["hunter_cannot_shoot_reason"] == "poison"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "phase", "request_kind"),
    [
        ("guard", "NIGHT_GUARD", "guard"),
        ("witch", "NIGHT_WITCH", "witch"),
        ("hunter", "NIGHT_HUNTER", "hunter_status"),
    ],
)
async def test_werewolf_user_later_night_roles_pause_at_their_own_stage(role, phase, request_kind):
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    result = await module.workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 19,
            "debug_user_seat": 1,
            "debug_user_role": role,
        },
        WorkflowContext(thread_id=f"werewolf-user-{role}-night"),
        thread_id=f"werewolf-user-{role}-night",
    )
    game = result["state"][module.SESSION_STATE_KEY]

    assert game["phase"] == phase
    assert game["pending_request"]["kind"] == request_kind
    assert game["pending_request"]["actor"] == "user"
    assert game["night"]["wolf_target"] is not None


def test_werewolf_hunter_night_status_prompt_reflects_poisoned_status():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "hunter",
    })
    game["phase"] = "NIGHT_HUNTER"
    game["night"]["witch_poison_target"] = 2

    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["pending_request"]["kind"] == "hunter_status"
    assert "不能开枪" in game["pending_request"]["prompt"]


def test_werewolf_user_hunter_status_after_witch_poison_input_says_cannot_shoot():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "hunter",
    })
    for item in game["players"]:
        if item["seat"] == 10:
            item["role"] = "witch"
            item["role_name"] = "女巫"
            item["camp"] = "good"
    game["phase"] = "NIGHT_WITCH"
    game["night"]["wolf_target"] = 3
    game["pending_request"] = {
        "kind": "witch",
        "actor": "user",
        "seat": 10,
        "target_seats": [2, 3],
        "prompt": "女巫请睁眼。你可以选择救人、毒人或不使用药。",
    }

    module.apply_user_input(game, "毒2号")
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["pending_request"]["kind"] == "hunter_status"
    assert game["pending_request"]["seat"] == 2
    assert "不能开枪" in game["pending_request"]["prompt"]


@pytest.mark.asyncio
async def test_werewolf_first_night_death_waits_until_after_sheriff_election():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    result = await module.workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 23,
            "debug_user_seat": 1,
            "debug_user_role": "villager",
        },
        WorkflowContext(thread_id="werewolf-night-death"),
        thread_id="werewolf-night-death",
    )
    game = result["state"][module.SESSION_STATE_KEY]
    wolf_target = game["night"]["wolf_target"]

    assert game["phase"] == "ELECTION_JOIN"
    assert game["death_queue"] == [wolf_target]
    assert game["players"][wolf_target - 1]["alive"] is True
    assert not any("昨夜死亡" in line for line in game["public_log"])


def test_werewolf_death_announce_reveals_night_death_and_sets_last_words_return_phase():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["day"] = 1
    game["death_queue"] = [2]

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "SHERIFF_BADGE_CHECK"
    route = module.advance_state_machine(game)
    assert route == "advance"
    assert game["phase"] == "HUNTER_CHECK"
    route = module.advance_state_machine(game)
    assert route == "advance"
    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["dead"] == [2]
    assert game["death_queue"] == []
    assert game["players"][1]["alive"] is False
    assert game["last_words_queue"] == [2]
    assert game["after_last_words_phase"] == "DAY_DISCUSS_ORDER"
    assert any("昨夜死亡：2号。" in line for line in game["public_log"])


def test_werewolf_first_night_user_last_words_returns_to_day_discussion():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["day"] = 1
    game["death_queue"] = [2]

    module.advance_state_machine(game)
    module.advance_state_machine(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)
    assert route == "render"
    assert game["pending_request"]["kind"] == "last_words"

    module.apply_user_input(game, "我首夜遗言是看警徽票型。")

    assert game["phase"] == "DAY_DISCUSS_ORDER"
    assert game["last_words_queue"] == []
    assert any("2号遗言：我首夜遗言是看警徽票型。" in line for line in game["public_log"])


def test_werewolf_dead_user_gets_spectate_or_end_choice_after_death_flow():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["day"] = 1
    game["death_queue"] = [2]

    module.advance_state_machine(game)
    module.advance_state_machine(game)
    module.advance_state_machine(game)
    module.advance_state_machine(game)
    module.apply_user_input(game, "我首夜遗言是看警徽票型。")
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "POST_DEATH_CHOICE"
    assert game["pending_request"] == {
        "kind": "post_death_choice",
        "actor": "user",
        "seat": 2,
        "target_seats": [],
        "prompt": "你已出局。可以选择继续旁观，或结束游戏并查看身份复盘。",
    }


def test_werewolf_dead_user_end_choice_requests_model_review():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["phase"] = "POST_DEATH_CHOICE"
    game["pending_request"] = {
        "kind": "post_death_choice",
        "actor": "user",
        "seat": 2,
        "prompt": "你已出局。可以选择继续旁观，或结束游戏并查看身份复盘。",
    }

    module.apply_user_input(game, "结束游戏")

    assert game["phase"] == "MODEL_REVIEW"
    assert game["winner"] == "ended_by_user"
    assert game["pending_request"] is None
    assert any("玩家选择结束游戏" in line for line in game["public_log"])
    assert game["review_pending"] is True


@pytest.mark.asyncio
async def test_werewolf_dead_user_end_choice_uses_model_review_and_asks_next_round():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    workflow = module.create_werewolf_workflow(publish_workflow=False)
    workflow._llm_manager = _FakeLLMManager([
        "模型复盘：本局关键在于警徽流和票型暴露。身份复盘：1号白痴、2号平民。是否开启下一轮？",
    ])
    workflow._components_initialized = True
    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["phase"] = "POST_DEATH_CHOICE"
    game["players"][1]["alive"] = False
    game["pending_request"] = {
        "kind": "post_death_choice",
        "actor": "user",
        "seat": 2,
        "prompt": "你已出局。可以选择继续旁观，或结束游戏并查看身份复盘。",
    }

    result = await workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": "结束并复盘"},
        WorkflowContext(thread_id="werewolf-model-review"),
        thread_id="werewolf-model-review",
    )
    game = result["state"][module.SESSION_STATE_KEY]

    assert game["phase"] == "POST_GAME_CHOICE"
    assert game["winner"] == "ended_by_user"
    assert game["pending_request"]["kind"] == "post_game_choice"
    assert game["pending_request"]["prompt"] == "复盘已生成。是否开启下一轮？"
    assert any("模型复盘" in line for line in game["public_log"])
    assert result["state"]["next_input_info"]["input_modes"] == [
        {"type": "button", "label": "开启下一轮", "value": "开启下一轮", "confirm": False},
        {"type": "button", "label": "结束", "value": "结束", "confirm": False},
    ]
    assert workflow._llm_manager.messages
    prompt = "\n".join(str(message["content"]) for message in workflow._llm_manager.messages[0])
    assert "生成一份狼人杀复盘" in prompt
    assert "按轮次" in prompt
    assert "控制在600字以内" in prompt
    assert "不要逐字复述长发言" in prompt
    assert "players" in prompt
    assert "round_events" in prompt


def test_werewolf_review_context_keeps_all_round_markers_without_long_speeches():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["day"] = 3
    game["public_log"] = [
        "天黑请闭眼。",
        "天亮了。",
        "警长投票结果：8号7票、9号0票。",
        "票型：2号投8号、3号投8号。",
        "1号玩家开始发言：",
        "1号：" + "长发言" * 80,
        "放逐投票结果：1号7票、8号1票。",
        "白天结束，进入下一晚。",
        "天亮了。",
        "昨夜死亡：8号。",
        "2号玩家开始发言：",
        "2号：" + "第二天长发言" * 80,
        "放逐投票平票：4号、9号，进入PK发言。",
        "PK投票仍然平票，本日无人出局。",
        "白天结束，进入下一晚。",
        "天亮了。",
        "昨夜平安夜。",
        "放逐投票结束，9号出局。",
    ]

    payload = json.loads(module.review_context(game))

    assert payload["day"] == 3
    assert "round_events" in payload
    joined = "\n".join(payload["round_events"])
    assert "第1夜" in joined
    assert "第1天" in joined
    assert "第2夜" in joined
    assert "第2天" in joined
    assert "第3夜" in joined
    assert "第3天" in joined
    assert "警长投票结果：8号7票、9号0票。" in joined
    assert "放逐投票结束，9号出局。" in joined
    assert "长发言" not in joined


@pytest.mark.asyncio
async def test_werewolf_natural_game_over_uses_model_review_and_asks_next_round():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    workflow = module.create_werewolf_workflow(publish_workflow=False)
    workflow._llm_manager = _FakeLLMManager([
        "模型复盘：第1天好人放逐最后狼人，身份和票型信息已归纳。是否开启下一轮？",
    ])
    workflow._components_initialized = True
    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    for item in game["players"]:
        if item["camp"] == "wolf":
            item["alive"] = False
    game["phase"] = "DAY_END"
    game["public_log"].extend([
        "天亮了。",
        "放逐投票结果：9号7票、1号1票。",
        "票型：1号投9号、2号投9号。",
        "放逐投票结束，9号出局。",
    ])

    result = await workflow.run(
        {module.SESSION_STATE_KEY: game},
        WorkflowContext(thread_id="werewolf-natural-model-review"),
        thread_id="werewolf-natural-model-review",
    )
    game = result["state"][module.SESSION_STATE_KEY]

    assert game["phase"] == "POST_GAME_CHOICE"
    assert game["winner"] == "good"
    assert game["pending_request"]["kind"] == "post_game_choice"
    assert any("好人阵营胜利" in line for line in game["public_log"])
    assert any("模型复盘" in line for line in game["public_log"])
    prompt = "\n".join(str(message["content"]) for message in workflow._llm_manager.messages[0])
    assert "round_events" in prompt
    assert "放逐投票结束，9号出局。" in prompt


def test_werewolf_dead_user_can_spectate_and_skip_future_user_turns():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["players"][1]["alive"] = False
    game["phase"] = "POST_DEATH_CHOICE"
    game["pending_request"] = {
        "kind": "post_death_choice",
        "actor": "user",
        "seat": 2,
        "prompt": "你已出局。可以选择继续旁观，或结束游戏并查看身份复盘。",
    }
    game["after_last_words_phase"] = "DAY_DISCUSS_ORDER"

    module.apply_user_input(game, "继续旁观")

    assert game["user_spectating"] is True
    assert game["phase"] == "DAY_DISCUSS_ORDER"
    assert game["pending_request"] is None
    assert any("你已选择继续旁观" in line for line in game["public_log"])

    game["phase"] = "DAY_VOTE"
    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "DAY_AI_VOTE"
    assert game["pending_request"] is None


def test_werewolf_later_night_death_has_no_last_words_and_enters_day_discussion():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["day"] = 2
    game["death_queue"] = [2]
    game["death_causes"] = {"2": "night"}

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "SHERIFF_BADGE_CHECK"
    assert game["last_words_queue"] == []
    assert game["after_last_words_phase"] == "DAY_DISCUSS_ORDER"
    assert game["players"][1]["alive"] is False
    assert any("昨夜死亡：2号。" in line for line in game["public_log"])


def test_werewolf_dead_user_sheriff_transfers_badge_before_death_skill():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["sheriff_seat"] = 2
    game["players"][1]["is_sheriff"] = True
    game["death_queue"] = [2]
    game["death_causes"] = {"2": "night"}

    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "SHERIFF_BADGE"
    assert game["pending_request"]["kind"] == "sheriff_badge"
    assert game["pending_request"]["target_seats"] == [seat for seat in range(1, 13) if seat != 2]
    assert game["hunter_check_queue"] == [2]


def test_werewolf_user_sheriff_badge_transfer_updates_new_sheriff():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["phase"] = "SHERIFF_BADGE"
    game["sheriff_seat"] = 2
    game["players"][1]["is_sheriff"] = True
    game["pending_request"] = {
        "kind": "sheriff_badge",
        "actor": "user",
        "seat": 2,
        "target_seats": [1, 3],
        "prompt": "请选择警徽移交目标，或回复撕毁警徽。",
    }

    module.apply_user_input(game, "警徽给3号")

    assert game["phase"] == "HUNTER_CHECK"
    assert game["sheriff_seat"] == 3
    assert game["players"][1]["is_sheriff"] is False
    assert game["players"][2]["is_sheriff"] is True
    assert any("2号警长将警徽移交给3号" in line for line in game["public_log"])


def test_werewolf_user_sheriff_can_destroy_badge():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["phase"] = "SHERIFF_BADGE"
    game["sheriff_seat"] = 2
    game["players"][1]["is_sheriff"] = True
    game["pending_request"] = {
        "kind": "sheriff_badge",
        "actor": "user",
        "seat": 2,
        "target_seats": [1, 3],
        "prompt": "请选择警徽移交目标，或回复撕毁警徽。",
    }

    module.apply_user_input(game, "撕毁警徽")

    assert game["phase"] == "HUNTER_CHECK"
    assert game["sheriff_seat"] is None
    assert not any(item.get("is_sheriff") for item in game["players"])
    assert any("2号警长撕毁警徽" in line for line in game["public_log"])


def test_werewolf_dead_ai_sheriff_uses_actor_request_for_badge():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["sheriff_seat"] = 3
    game["players"][2]["is_sheriff"] = True
    game["death_queue"] = [3]
    game["death_causes"] = {"3": "night"}

    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "actors"
    assert game["phase"] == "SHERIFF_BADGE_AI"
    assert game["actor_requests"]["p3"]["kind"] == "sheriff_badge"
    assert 3 not in game["actor_requests"]["p3"]["target_seats"]
    assert game["hunter_check_queue"] == [3]


def test_werewolf_dead_user_hunter_can_shoot_before_last_words_when_not_poisoned():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "hunter",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["death_queue"] = [2]
    game["death_causes"] = {"2": "night"}

    route = module.advance_state_machine(game)
    assert route == "advance"
    assert game["phase"] == "SHERIFF_BADGE_CHECK"
    route = module.advance_state_machine(game)
    assert route == "advance"
    assert game["phase"] == "HUNTER_CHECK"
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "HUNTER_SHOT"
    assert game["pending_request"]["kind"] == "hunter_shot"
    assert game["pending_request"]["target_seats"] == [seat for seat in range(1, 13) if seat != 2]
    assert game["last_words_queue"] == [2]


def test_werewolf_poisoned_hunter_cannot_shoot_and_goes_to_last_words():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "hunter",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["death_queue"] = [2]
    game["death_causes"] = {"2": "poison"}

    route = module.advance_state_machine(game)
    assert route == "advance"
    assert game["phase"] == "SHERIFF_BADGE_CHECK"
    route = module.advance_state_machine(game)
    assert route == "advance"
    assert game["phase"] == "HUNTER_CHECK"
    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "LAST_WORDS_NEXT"
    route = module.advance_state_machine(game)
    assert route == "render"
    assert game["pending_request"]["kind"] == "last_words"
    assert any("2号猎人被毒，不能开枪" in line for line in game["public_log"])


def test_werewolf_hunter_poisoned_and_killed_same_night_cannot_shoot():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "hunter",
    })
    game["day"] = 2
    game["phase"] = "DAYBREAK"
    game["night"]["wolf_target"] = 2
    game["night"]["witch_poison_target"] = 2
    game["night"]["guard_target"] = 12
    game["night"]["witch_saved"] = False

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["death_queue"] == [2]
    assert game["death_causes"]["2"] == "poison"

    route = module.advance_state_machine(game)
    assert route == "advance"
    route = module.advance_state_machine(game)
    assert route == "advance"
    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "DAY_DISCUSS_ORDER"
    assert game["pending_request"] is None
    assert "hunter_shot" not in str(game.get("actor_requests") or {})
    assert any("2号猎人被毒，不能开枪" in line for line in game["public_log"])


def test_werewolf_user_hunter_shot_adds_target_to_death_announce_before_last_words():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "hunter",
    })
    game["phase"] = "HUNTER_SHOT"
    game["pending_request"] = {
        "kind": "hunter_shot",
        "actor": "user",
        "seat": 2,
        "target_seats": [1, 3],
        "prompt": "猎人请选择是否开枪带走一名玩家。",
    }
    game["last_words_queue"] = [2]
    game["after_last_words_phase"] = "DAY_DISCUSS_ORDER"

    module.apply_user_input(game, "开枪带1号")

    assert game["phase"] == "DEATH_ANNOUNCE"
    assert game["death_queue"] == [1]
    assert game["death_causes"] == {"1": "hunter_shot"}
    assert game["pending_request"] is None


def test_werewolf_dead_ai_hunter_uses_actor_request_for_shot():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["players"][2]["role"] = "hunter"
    game["players"][2]["role_name"] = "猎人"
    game["players"][2]["camp"] = "good"
    game["death_queue"] = [3]
    game["death_causes"] = {"3": "night"}

    route = module.advance_state_machine(game)
    assert route == "advance"
    assert game["phase"] == "SHERIFF_BADGE_CHECK"
    route = module.advance_state_machine(game)
    assert route == "advance"
    assert game["phase"] == "HUNTER_CHECK"
    route = module.advance_state_machine(game)

    assert route == "actors"
    assert game["phase"] == "HUNTER_SHOT_AI"
    assert game["actor_requests"]["p3"]["kind"] == "hunter_shot"
    assert 3 not in game["actor_requests"]["p3"]["target_seats"]


def test_werewolf_dead_user_wolf_king_can_shoot_before_last_words_when_not_poisoned():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf_king",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["death_queue"] = [2]
    game["death_causes"] = {"2": "night"}

    module.advance_state_machine(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "WOLF_KING_SHOT"
    assert game["pending_request"]["kind"] == "wolf_king_shot"
    assert game["pending_request"]["target_seats"] == [seat for seat in range(1, 13) if seat != 2]
    assert game["last_words_queue"] == [2]


def test_werewolf_poisoned_wolf_king_cannot_shoot_and_goes_to_last_words():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf_king",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["death_queue"] = [2]
    game["death_causes"] = {"2": "poison"}

    module.advance_state_machine(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "LAST_WORDS_NEXT"
    assert any("2号狼王被毒，不能开枪" in line for line in game["public_log"])


def test_werewolf_day_exiled_last_wolf_king_gets_last_words_before_shot_and_game_over():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf_king",
    })
    for item in game["players"]:
        if item["camp"] == "wolf" and item["seat"] != 2:
            item["alive"] = False
    game["phase"] = "DEATH_ANNOUNCE"
    game["death_queue"] = [2]
    game["death_causes"] = {"2": "exile"}

    module.advance_state_machine(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["pending_request"]["kind"] == "last_words"
    assert game["winner"] == ""
    assert not any("好人阵营胜利" in line for line in game["public_log"])

    module.apply_user_input(game, "最后一狼遗言后再开枪。")
    module.advance_state_machine(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "WOLF_KING_SHOT"
    assert game["pending_request"]["kind"] == "wolf_king_shot"
    assert game["winner"] == ""
    assert not any("好人阵营胜利" in line for line in game["public_log"])


def test_werewolf_day_exiled_last_hunter_gets_last_words_before_shot_and_wolves_win():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "hunter",
    })
    for item in game["players"]:
        if item["role"] in {"seer", "witch", "guard", "idiot"}:
            item["alive"] = False
    game["phase"] = "DEATH_ANNOUNCE"
    game["death_queue"] = [2]
    game["death_causes"] = {"2": "exile"}

    module.advance_state_machine(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["pending_request"]["kind"] == "last_words"
    assert game["winner"] == ""
    assert not any("狼人阵营屠神胜利" in line for line in game["public_log"])

    module.apply_user_input(game, "最后神职遗言后再开枪。")
    module.advance_state_machine(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "HUNTER_SHOT"
    assert game["pending_request"]["kind"] == "hunter_shot"
    assert game["winner"] == ""
    assert not any("狼人阵营屠神胜利" in line for line in game["public_log"])


def test_werewolf_user_wolf_king_shot_adds_target_to_death_announce_before_last_words():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf_king",
    })
    game["phase"] = "WOLF_KING_SHOT"
    game["pending_request"] = {
        "kind": "wolf_king_shot",
        "actor": "user",
        "seat": 2,
        "target_seats": [1, 3],
        "prompt": "狼王请选择是否开枪带走一名玩家。",
    }
    game["last_words_queue"] = [2]
    game["after_last_words_phase"] = "DAY_DISCUSS_ORDER"

    module.apply_user_input(game, "带走3号")

    assert game["phase"] == "DEATH_ANNOUNCE"
    assert game["death_queue"] == [3]
    assert game["death_causes"] == {"3": "wolf_king_shot"}
    assert game["pending_request"] is None


def test_werewolf_user_wolf_king_shot_logs_status_and_returns_to_day_end():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf_king",
    })
    game["phase"] = "WOLF_KING_SHOT"
    game["pending_request"] = {
        "kind": "wolf_king_shot",
        "actor": "user",
        "seat": 2,
        "target_seats": [1, 5],
        "prompt": "狼王请选择是否开枪带走一名玩家。",
    }
    game["last_words_queue"] = [2]
    game["after_last_words_phase"] = "DAY_END"

    module.apply_user_input(game, "带走5号")

    assert any("2号狼王开枪带走5号。" in line for line in game["public_log"])
    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "SHERIFF_BADGE_CHECK"
    assert game["after_last_words_phase"] == "DAY_END"
    assert any("出局玩家：5号。" in line for line in game["public_log"])

    while game["phase"] != "DAY_END":
        route = module.advance_state_machine(game)
        assert route in {"advance", "render"}

    assert game["phase"] == "DAY_END"


def test_werewolf_dead_ai_wolf_king_uses_actor_request_for_shot():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DEATH_ANNOUNCE"
    game["players"][2]["role"] = "wolf_king"
    game["players"][2]["role_name"] = "狼王"
    game["players"][2]["camp"] = "wolf"
    game["death_queue"] = [3]
    game["death_causes"] = {"3": "night"}

    module.advance_state_machine(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "actors"
    assert game["phase"] == "WOLF_KING_SHOT_AI"
    assert game["actor_requests"]["p3"]["kind"] == "wolf_king_shot"
    assert 3 not in game["actor_requests"]["p3"]["target_seats"]


def test_werewolf_user_guard_cannot_guard_same_target_on_consecutive_nights():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "guard",
    })
    game["phase"] = "NIGHT_GUARD"
    game["guard_last_target"] = 5

    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["pending_request"]["kind"] == "guard"
    assert 5 not in game["pending_request"]["target_seats"]


def test_werewolf_ai_guard_request_excludes_previous_guard_target():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "NIGHT_GUARD"
    game["guard_last_target"] = 5

    route = module.advance_state_machine(game)

    assert route == "actors"
    guard_request = next(
        request for request in game["actor_requests"].values()
        if request["kind"] == "guard"
    )
    assert 5 not in guard_request["target_seats"]


def test_werewolf_same_guard_and_witch_save_kills_wolf_target():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["night"] = {
        "wolf_target": 5,
        "guard_target": 5,
        "witch_saved": True,
    }

    deaths = module.calculate_night_deaths(game)

    assert deaths == [5]
    assert game["death_queue"] == [5]
    assert game["players"][4]["alive"] is True


def test_werewolf_user_witch_without_save_potion_cannot_save_wolf_target():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "witch",
    })
    game["phase"] = "NIGHT_WITCH"
    game["night"]["wolf_target"] = 6
    game["witch_save_available"] = False

    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["pending_request"]["kind"] == "witch"
    assert game["pending_request"]["private_info"]["witch_can_save"] is False
    assert game["pending_request"]["private_info"]["night_kill_target"] == 6
    assert game["pending_request"]["private_info"]["witch_save_target"] == 6
    assert 6 not in game["pending_request"]["action_targets"]["save"]
    assert 6 in game["pending_request"]["action_targets"]["poison"]
    assert "昨夜被刀目标：6号" in game["pending_request"]["prompt"]
    assert "解药已用" in game["pending_request"]["prompt"]


def test_werewolf_first_night_user_witch_can_save_self():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "witch",
    })
    game["phase"] = "NIGHT_WITCH"
    game["night"]["wolf_target"] = 1

    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["pending_request"]["kind"] == "witch"
    assert game["pending_request"]["private_info"]["witch_can_save"] is True
    assert game["pending_request"]["private_info"]["witch_save_target"] == 1
    assert game["pending_request"]["action_targets"]["save"] == [1]

    module.apply_user_input(game, "救1号")

    assert game["night"]["witch_saved"] is True
    assert game["witch_save_available"] is False


def test_werewolf_user_witch_poison_consumes_poison_and_ignores_save_same_night():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "witch",
    })
    game["pending_request"] = {
        "kind": "witch",
        "actor": "user",
        "seat": 1,
        "target_seats": [2, 6],
        "prompt": "女巫请行动。",
    }
    game["night"]["wolf_target"] = 6

    module.apply_user_input(game, "救6号并毒2号")

    assert game["phase"] == "NIGHT_HUNTER"
    assert game["night"]["witch_saved"] is True
    assert "witch_poison_target" not in game["night"]
    assert game["witch_save_available"] is False
    assert game["witch_poison_available"] is True


def test_werewolf_ai_witch_without_poison_potion_cannot_receive_poison_targets():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "NIGHT_WITCH"
    game["night"]["wolf_target"] = 6
    game["witch_poison_available"] = False

    route = module.advance_state_machine(game)

    assert route == "actors"
    witch_request = next(
        request for request in game["actor_requests"].values()
        if request["kind"] == "witch"
    )
    assert witch_request["target_seats"] == [6]
    assert witch_request["private_info"]["night_kill_target"] == 6
    assert witch_request["private_info"]["witch_save_target"] == 6
    assert witch_request["private_info"]["witch_can_poison"] is False


@pytest.mark.asyncio
async def test_werewolf_user_election_choice_triggers_parallel_actor_campaign_and_speech_pause():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    workflow = _workflow_with_mock_model_actor(module)
    context = WorkflowContext(thread_id="werewolf-election-test")
    first = await workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 9,
            "debug_user_seat": 1,
            "debug_user_role": "villager",
        },
        context,
        thread_id="werewolf-election-test",
    )
    game = first["state"][module.SESSION_STATE_KEY]
    assert game["pending_request"]["kind"] == "election_join"

    second = await workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": "不上警"},
        context,
        thread_id="werewolf-election-test",
    )
    game = second["state"][module.SESSION_STATE_KEY]

    assert game["phase"] in {"ELECTION_SPEECH", "ELECTION_VOTE"}
    assert game["election"]["choices"]["1"] == "skip"
    assert game["election"]["candidates"]
    assert any("警长竞选名单已确定" in line for line in game["public_log"])
    assert game["pending_request"] is None or game["pending_request"]["actor"] == "user"


def test_werewolf_no_sheriff_candidates_skips_user_vote_request():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "ELECTION_VOTE"
    game["election"]["candidates"] = []
    game["election"]["voters"] = list(range(1, 13))
    game["pending_request"] = None

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "ELECTION_RESOLVE"
    assert game["pending_request"] is None


def test_werewolf_no_sheriff_candidates_does_not_announce_vote_stage():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "ELECTION_NEXT_SPEECH"
    game["election"]["candidates"] = []
    game["election"]["speech_queue"] = []

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "ELECTION_RESOLVE"
    assert not any("进入警长投票" in line for line in game["public_log"])


@pytest.mark.asyncio
async def test_werewolf_all_sheriff_candidates_speak_once_despite_stale_actor_outputs():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    workflow = _workflow_with_mock_model_actor(module)
    context = WorkflowContext(thread_id="werewolf-all-candidates-speak")
    first = await workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 37,
            "debug_user_seat": 1,
            "debug_user_role": "villager",
        },
        context,
        thread_id="werewolf-all-candidates-speak",
    )
    game = first["state"][module.SESSION_STATE_KEY]
    second = await workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": "不上警"},
        context,
        thread_id="werewolf-all-candidates-speak",
    )
    game = second["state"][module.SESSION_STATE_KEY]

    candidates = game["election"]["candidates"]
    assert candidates == [5, 6, 8]
    for seat in candidates:
        assert any(f"{seat}号玩家开始发言：" == line for line in game["public_log"])
    assert game["public_log"].count("5号玩家开始发言：") == 1


@pytest.mark.asyncio
async def test_werewolf_sheriff_speech_queue_uses_seeded_random_start_order():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    workflow = _workflow_with_mock_model_actor(module)
    context = WorkflowContext(thread_id="werewolf-election-random-start")
    first = await workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 1,
            "debug_user_seat": 1,
            "debug_user_role": "villager",
        },
        context,
        thread_id="werewolf-election-random-start",
    )
    game = first["state"][module.SESSION_STATE_KEY]
    second = await workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": "不上警"},
        context,
        thread_id="werewolf-election-random-start",
    )
    game = second["state"][module.SESSION_STATE_KEY]

    assert game["election"]["candidates"] == [5, 6, 8]
    spoken = [
        int(line.removesuffix("号玩家开始发言："))
        for line in game["public_log"]
        if line.endswith("号玩家开始发言：")
    ]
    assert spoken == [6, 8, 5]
    assert any("随机起点为6号" in line for line in game["public_log"])


def test_werewolf_user_can_withdraw_from_sheriff_campaign_during_speech():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["pending_request"] = {
        "kind": "election_speech",
        "actor": "user",
        "seat": 2,
        "prompt": "轮到你发表警上发言。",
    }
    game["election"]["candidates"] = [2, 5]
    game["election"]["voters"] = [1, 3, 4]
    game["election"]["speech_queue"] = [2, 5]

    module.apply_user_input(game, '{"kind":"withdraw_election"}')

    assert game["phase"] == "ELECTION_NEXT_SPEECH"
    assert game["election"]["candidates"] == [5]
    assert 2 in game["election"]["voters"]
    assert game["election"]["speech_queue"] == [5]
    assert any("2号退水" in line for line in game["public_log"])


def test_werewolf_user_mentioning_other_players_withdraw_does_not_withdraw_self():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 10,
        "debug_user_role": "wolf_king",
    })
    game["pending_request"] = {
        "kind": "election_speech",
        "actor": "user",
        "seat": 10,
        "prompt": "轮到你发表警上发言。",
    }
    game["election"]["candidates"] = [1, 7, 10, 12]
    game["election"]["voters"] = [2, 3, 4, 5, 6, 8, 9, 11]
    game["election"]["speech_queue"] = [10]

    module.apply_user_input(game, "12号、1号是退水的好人牌，7号是悍跳狼，警徽给我。")
    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "ELECTION_VOTE"
    assert 10 in game["election"]["candidates"]
    assert 10 not in game["election"]["voters"]
    assert game["pending_request"] is None
    assert not any("10号退水" in line for line in game["public_log"])


def test_werewolf_user_wolf_can_self_explode_by_explicit_button_during_election_speech():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf",
    })
    game["pending_request"] = {
        "kind": "election_speech",
        "actor": "user",
        "seat": 2,
        "prompt": "轮到你发表警上发言。",
    }
    game["election"]["candidates"] = [2, 5]
    game["election"]["speech_queue"] = [2, 5]

    module.apply_user_input(game, '{"kind":"self_explode"}')

    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["players"][1]["alive"] is False
    assert 2 in game["dead"]
    assert game["election"]["speech_queue"] == []
    assert game["last_words_queue"] == [2]
    assert game["after_last_words_phase"] == "DAY_END"
    assert game["pending_request"] is None
    assert any("2号狼人自爆" in line and "白天立即结束" in line for line in game["public_log"])


def test_werewolf_user_wolf_mentioning_self_explode_during_election_speech_is_only_logged():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf",
    })
    game["pending_request"] = {
        "kind": "election_speech",
        "actor": "user",
        "seat": 2,
        "prompt": "轮到你发表警上发言。",
    }
    game["election"]["candidates"] = [2, 5]
    game["election"]["voters"] = [1, 3, 4]
    game["election"]["speech_queue"] = [2, 5]

    module.apply_user_input(game, "我说7号像准备自爆，不是我自爆。")

    assert game["phase"] == "ELECTION_NEXT_SPEECH"
    assert game["players"][1]["alive"] is True
    assert 2 in game["election"]["candidates"]
    assert game["election"]["speech_queue"] == [5]
    assert any("2号：我说7号像准备自爆" in line for line in game["public_log"])
    assert not any("2号狼人自爆" in line for line in game["public_log"])


def test_werewolf_sheriff_self_explosion_destroys_badge_and_gets_last_words():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf",
    })
    game["phase"] = "DAY_NEXT_SPEECH"
    game["sheriff_seat"] = 2
    game["players"][1]["is_sheriff"] = True
    game["day_speech_queue"] = [2, 3, 4]
    game["pending_request"] = {
        "kind": "day_speech",
        "actor": "user",
        "seat": 2,
        "prompt": "轮到你发表白天发言。",
    }

    module.apply_user_input(game, '{"kind":"self_explode"}')

    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["sheriff_seat"] is None
    assert not any(item.get("is_sheriff") for item in game["players"])
    assert game["last_words_queue"] == [2]
    assert game["after_last_words_phase"] == "DAY_END"
    assert any("2号警长自爆，警徽撕毁" in line for line in game["public_log"])


def test_werewolf_sheriff_vote_result_includes_public_vote_breakdown():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["election"]["candidates"] = [2, 5]
    module.record_vote(game, 1, 2, "election_vote")
    module.record_vote(game, 3, 5, "election_vote")
    module.record_vote(game, 4, 5, "election_vote")

    module.resolve_election_vote(game)

    assert any("警长投票结果：" in line and "5号2票" in line and "2号1票" in line for line in game["public_log"])
    assert any("票型：" in line and "1号投2号" in line and "3号投5号" in line and "4号投5号" in line for line in game["public_log"])
    assert game["sheriff_seat"] == 5


@pytest.mark.asyncio
async def test_werewolf_election_vote_pauses_for_user_when_user_is_off_sheriff():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    workflow = _workflow_with_mock_model_actor(module)
    context = WorkflowContext(thread_id="werewolf-election-vote-user")
    first = await workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 31,
            "debug_user_seat": 1,
            "debug_user_role": "villager",
        },
        context,
        thread_id="werewolf-election-vote-user",
    )
    game = first["state"][module.SESSION_STATE_KEY]
    second = await workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": "不上警"},
        context,
        thread_id="werewolf-election-vote-user",
    )
    game = second["state"][module.SESSION_STATE_KEY]

    assert game["phase"] == "ELECTION_VOTE"
    assert game["pending_request"]["actor"] == "user"
    assert game["pending_request"]["kind"] == "election_vote"
    assert game["pending_request"]["target_seats"] == game["election"]["candidates"]
    assert 1 in game["election"]["voters"]
    assert any("警上发言结束，进入警长投票。" in line for line in game["public_log"])


@pytest.mark.asyncio
async def test_werewolf_user_sheriff_vote_then_ai_votes_elect_sheriff():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    workflow = _workflow_with_mock_model_actor(module)
    context = WorkflowContext(thread_id="werewolf-election-vote-resolve")
    first = await workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 37,
            "debug_user_seat": 1,
            "debug_user_role": "villager",
        },
        context,
        thread_id="werewolf-election-vote-resolve",
    )
    game = first["state"][module.SESSION_STATE_KEY]
    second = await workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": "不上警"},
        context,
        thread_id="werewolf-election-vote-resolve",
    )
    game = second["state"][module.SESSION_STATE_KEY]
    target = game["election"]["candidates"][0]

    third = await workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": f"投{target}号"},
        context,
        thread_id="werewolf-election-vote-resolve",
    )
    game = third["state"][module.SESSION_STATE_KEY]

    assert game["phase"] == "DAY_NEXT_SPEECH"
    assert game["pending_request"]["actor"] == "user"
    assert game["pending_request"]["kind"] == "day_speech"
    assert game["sheriff_seat"] == target
    assert game["players"][target - 1]["is_sheriff"] is True
    assert {"from": 1, "to": target, "phase": "election_vote"} in game["votes"]
    assert any(
        f"警长投票结束，{target}号当选警长。" in line
        for line in game["public_log"]
    )
    assert any(f"{target}号警长选择警右发言，警长最后归票。" in line for line in game["public_log"])


@pytest.mark.asyncio
async def test_werewolf_day_speech_after_user_speaks_continues_to_exile_vote():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    workflow = _workflow_with_mock_model_actor(module)
    context = WorkflowContext(thread_id="werewolf-day-speech-to-vote")
    first = await workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 37,
            "debug_user_seat": 1,
            "debug_user_role": "villager",
        },
        context,
        thread_id="werewolf-day-speech-to-vote",
    )
    game = first["state"][module.SESSION_STATE_KEY]
    second = await workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": "不上警"},
        context,
        thread_id="werewolf-day-speech-to-vote",
    )
    game = second["state"][module.SESSION_STATE_KEY]
    sheriff_target = game["election"]["candidates"][0]
    third = await workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": f"投{sheriff_target}号"},
        context,
        thread_id="werewolf-day-speech-to-vote",
    )
    game = third["state"][module.SESSION_STATE_KEY]
    if game["pending_request"]["kind"] == "day_order":
        fourth = await workflow.run(
            {module.SESSION_STATE_KEY: game, "user_input": f"从{game['pending_request']['target_seats'][0]}号开始"},
            context,
            thread_id="werewolf-day-speech-to-vote",
        )
        game = fourth["state"][module.SESSION_STATE_KEY]
    assert game["pending_request"]["kind"] == "day_speech"

    fifth = await workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": "我先听预言家和警长归票，今天重点看票型。"},
        context,
        thread_id="werewolf-day-speech-to-vote",
    )
    game = fifth["state"][module.SESSION_STATE_KEY]

    assert game["phase"] == "DAY_VOTE"
    assert game["pending_request"]["actor"] == "user"
    assert game["pending_request"]["kind"] == "day_vote"
    assert game["pending_request"]["target_seats"]
    assert any("1号：我先听预言家和警长归票" in line for line in game["public_log"])
    assert any("所有玩家发言结束，进入放逐投票。" in line for line in game["public_log"])


def test_werewolf_user_wolf_can_self_explode_during_day_speech_and_end_day():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf",
    })
    game["phase"] = "DAY_NEXT_SPEECH"
    game["day_speech_queue"] = [2, 3, 4]
    game["pending_request"] = {
        "kind": "day_speech",
        "actor": "user",
        "seat": 2,
        "prompt": "轮到你发表白天发言。",
    }

    module.apply_user_input(game, '{"kind":"self_explode"}')

    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["players"][1]["alive"] is False
    assert 2 in game["dead"]
    assert game["day_speech_queue"] == []
    assert game["last_words_queue"] == [2]
    assert game["after_last_words_phase"] == "DAY_END"
    assert game["pending_request"] is None
    assert any("2号狼人自爆" in line and "白天立即结束" in line for line in game["public_log"])


def test_werewolf_ai_wolf_self_explosion_during_day_speech_ends_day():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_AI_SPEECH"
    game["day_speech_queue"] = [3, 4, 5]
    game["players"][2]["role"] = "wolf"
    game["players"][2]["role_name"] = "狼人"
    game["players"][2]["camp"] = "wolf"
    game["actor_requests"] = {
        "p3": module._build_actor_request(game, 3, "day_speech", [])
    }
    game["actor_outputs"] = {
        "p3": {
            "action": {
                "seat": 3,
                "kind": "self_explode",
                "speech": "我自爆，晚上见。",
            }
        }
    }

    module.apply_actor_outputs(game)

    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["players"][2]["alive"] is False
    assert 3 in game["dead"]
    assert game["day_speech_queue"] == []
    assert game["last_words_queue"] == [3]
    assert game["after_last_words_phase"] == "DAY_END"
    assert game["actor_requests"] == {}
    assert game["actor_outputs"] == {}
    assert any("3号狼人自爆" in line and "白天立即结束" in line for line in game["public_log"])


def test_werewolf_good_player_saying_self_explode_is_only_logged_as_speech():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_NEXT_SPEECH"
    game["day_speech_queue"] = [2, 3, 4]
    game["pending_request"] = {
        "kind": "day_speech",
        "actor": "user",
        "seat": 2,
        "prompt": "轮到你发表白天发言。",
    }

    module.apply_user_input(game, "我说他们像自爆，不是我要自爆。")

    assert game["phase"] == "DAY_NEXT_SPEECH"
    assert game["players"][1]["alive"] is True
    assert 2 not in game["dead"]
    assert game["day_speech_queue"] == [3, 4]
    assert any("2号：我说他们像自爆" in line for line in game["public_log"])
    assert not any("2号平民自爆" in line for line in game["public_log"])


def test_werewolf_wolf_king_self_explosion_does_not_enter_shot_interrupt():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf_king",
    })
    game["phase"] = "DAY_NEXT_SPEECH"
    game["day_speech_queue"] = [2, 3, 4]
    game["pending_request"] = {
        "kind": "day_speech",
        "actor": "user",
        "seat": 2,
        "prompt": "轮到你发表白天发言。",
    }

    module.apply_user_input(game, '{"kind":"self_explode"}')

    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["hunter_check_queue"] == []
    assert game["last_words_queue"] == [2]
    assert game["pending_request"] is None
    assert not any("开枪" in line for line in game["public_log"])


@pytest.mark.asyncio
async def test_werewolf_second_day_skips_sheriff_election_and_goes_to_day_speech():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["day"] = 2
    game["phase"] = "DAYBREAK"
    game["night"] = {}
    game["public_log"] = ["白天结束，进入下一晚。"]

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "DEATH_ANNOUNCE"
    route = module.advance_state_machine(game)
    assert route == "advance"
    assert game["phase"] == "DAY_DISCUSS_ORDER"
    assert game["pending_request"] is None
    assert not any("上警" in line or "警长竞选" in line for line in game["public_log"])


def test_werewolf_win_condition_good_wins_when_all_wolves_are_dead():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    for item in game["players"]:
        if item["camp"] == "wolf":
            item["alive"] = False
    game["phase"] = "DAY_END"

    assert module.check_win_condition(game) is True
    assert game["phase"] == "MODEL_REVIEW"
    assert game["winner"] == "good"
    assert game["review_pending"] is True
    assert any("好人阵营胜利" in line for line in game["public_log"])
    assert not any("身份复盘：" in line for line in game["public_log"])


def test_werewolf_win_condition_wolves_win_by_slaughtering_villagers():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    for item in game["players"]:
        if item["role"] == "villager":
            item["alive"] = False
    game["phase"] = "DAY_END"

    assert module.check_win_condition(game) is True
    assert game["phase"] == "MODEL_REVIEW"
    assert game["winner"] == "wolf"
    assert game["review_pending"] is True
    assert any("狼人阵营屠民胜利" in line for line in game["public_log"])


def test_werewolf_day_vote_result_includes_public_vote_breakdown():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    module.record_vote(game, 1, 2, "day_vote")
    module.record_vote(game, 3, 2, "day_vote")
    module.record_vote(game, 4, 5, "day_vote")

    module.resolve_day_vote(game)

    assert any("放逐投票结果：" in line and "2号2票" in line and "5号1票" in line for line in game["public_log"])
    assert any("票型：" in line and "1号投2号" in line and "3号投2号" in line and "4号投5号" in line for line in game["public_log"])


def test_werewolf_day_vote_tie_enters_pk_speech():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_RESOLVE_VOTE"
    module.record_vote(game, 1, 2, "day_vote")
    module.record_vote(game, 4, 3, "day_vote")

    module.resolve_day_vote(game)

    assert game["phase"] == "DAY_VOTE_PK_NEXT_SPEECH"
    assert game["day_vote"]["pk_candidates"] == [2, 3]
    assert game["day_vote"]["pk_speech_queue"] == [2, 3]
    assert 2 not in game["day_vote"]["pk_voters"]
    assert 3 not in game["day_vote"]["pk_voters"]
    assert any("放逐投票平票" in line and "进入PK发言" in line for line in game["public_log"])


def test_werewolf_day_exile_gets_last_words_before_unified_death_chain():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["sheriff_seat"] = 2
    game["players"][1]["is_sheriff"] = True
    module.record_vote(game, 1, 2, "day_vote")
    module.record_vote(game, 4, 2, "day_vote")

    module.resolve_day_vote(game)

    assert game["phase"] == "DEATH_ANNOUNCE"
    assert game["death_queue"] == [2]
    assert game["death_causes"] == {"2": "exile"}
    assert game["players"][1]["alive"] is True

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["players"][1]["alive"] is False
    assert game["dead"] == [2]
    assert game["after_last_words_phase"] == "DAY_END"
    assert game["sheriff_check_queue"] == [2]
    assert game["hunter_check_queue"] == [2]

    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["pending_request"]["kind"] == "last_words"

    module.apply_user_input(game, "我是警长，先留遗言。")
    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "SHERIFF_BADGE_CHECK"

    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "SHERIFF_BADGE"
    assert game["pending_request"]["kind"] == "sheriff_badge"


def test_werewolf_day_exiled_hunter_gets_last_words_before_shot():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "hunter",
    })
    module.record_vote(game, 1, 2, "day_vote")
    module.record_vote(game, 4, 2, "day_vote")

    module.resolve_day_vote(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["pending_request"]["kind"] == "last_words"
    assert game["last_words_queue"] == [2]

    module.apply_user_input(game, "我白天出局先留遗言。")
    route = module.advance_state_machine(game)
    assert route == "advance"
    assert game["phase"] == "SHERIFF_BADGE_CHECK"
    route = module.advance_state_machine(game)
    assert route == "advance"
    assert game["phase"] == "HUNTER_CHECK"
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "HUNTER_SHOT"
    assert game["pending_request"]["kind"] == "hunter_shot"
    assert any("2号遗言：我白天出局先留遗言。" in line for line in game["public_log"])


def test_werewolf_day_exiled_wolf_king_gets_last_words_before_shot():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf_king",
    })
    module.record_vote(game, 1, 2, "day_vote")
    module.record_vote(game, 4, 2, "day_vote")

    module.resolve_day_vote(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["pending_request"]["kind"] == "last_words"
    assert game["last_words_queue"] == [2]

    module.apply_user_input(game, "狼王先留遗言再开枪。")
    module.advance_state_machine(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "WOLF_KING_SHOT"
    assert game["pending_request"]["kind"] == "wolf_king_shot"
    assert any("2号遗言：狼王先留遗言再开枪。" in line for line in game["public_log"])


def test_werewolf_day_vote_pk_second_tie_skips_exile():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_VOTE_PK_RESOLVE"
    game["day_vote"]["pk_candidates"] = [2, 3]
    module.record_vote(game, 1, 2, "day_pk_vote")
    module.record_vote(game, 4, 3, "day_pk_vote")

    module.resolve_day_pk_vote(game)

    assert game["phase"] == "DAY_END"
    assert game["players"][1]["alive"] is True
    assert game["players"][2]["alive"] is True
    assert any("票型：" in line and "1号投2号" in line and "4号投3号" in line for line in game["public_log"])
    assert any("PK投票仍然平票" in line for line in game["public_log"])


def test_werewolf_day_vote_idiot_flips_and_loses_vote_instead_of_dying():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["players"][1]["role"] = "idiot"
    game["players"][1]["role_name"] = "白痴"
    game["players"][1]["camp"] = "good"
    module.record_vote(game, 1, 2, "day_vote")
    module.record_vote(game, 4, 2, "day_vote")

    module.resolve_day_vote(game)

    assert game["phase"] == "DAY_END"
    assert game["players"][1]["alive"] is True
    assert game["players"][1]["can_vote"] is False
    assert 2 not in game.get("dead", [])
    assert game.get("last_words_queue", []) == []
    assert any("2号白痴翻牌免死" in line and "失去后续投票权" in line for line in game["public_log"])


def test_werewolf_day_vote_pk_idiot_flips_and_loses_vote_instead_of_dying():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_VOTE_PK_RESOLVE"
    game["players"][2]["role"] = "idiot"
    game["players"][2]["role_name"] = "白痴"
    game["players"][2]["camp"] = "good"
    game["day_vote"]["pk_candidates"] = [2, 3]
    module.record_vote(game, 1, 3, "day_pk_vote")
    module.record_vote(game, 4, 3, "day_pk_vote")

    module.resolve_day_pk_vote(game)

    assert game["phase"] == "DAY_END"
    assert game["players"][2]["alive"] is True
    assert game["players"][2]["can_vote"] is False
    assert 3 not in game.get("dead", [])
    assert game.get("last_words_queue", []) == []
    assert any("3号白痴翻牌免死" in line and "失去后续投票权" in line for line in game["public_log"])


def test_werewolf_day_vote_requests_skip_flipped_idiot_voters():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "idiot",
    })
    game["players"][1]["can_vote"] = False
    game["phase"] = "DAY_VOTE"

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "DAY_AI_VOTE"
    assert game.get("pending_request") is None
    assert module.prepare_day_ai_votes(game) is True
    assert "p2" not in game["actor_requests"]


def test_werewolf_day_pk_vote_requests_skip_flipped_idiot_voters():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "idiot",
    })
    game["players"][1]["can_vote"] = False
    game["phase"] = "DAY_VOTE_PK_VOTE"
    game["day_vote"]["pk_candidates"] = [3, 4]
    game["day_vote"]["pk_voters"] = [1, 2, 5]

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "DAY_VOTE_PK_AI_VOTE"
    assert game.get("pending_request") is None
    assert module.prepare_day_pk_ai_votes(game) is True
    assert "p2" not in game["actor_requests"]


def test_werewolf_user_sheriff_decides_day_speech_first_seat():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 3,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_DISCUSS_ORDER"
    game["sheriff_seat"] = 3
    game["players"][2]["is_sheriff"] = True

    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["phase"] == "DAY_ORDER"
    assert game["pending_request"]["kind"] == "day_order"
    assert game["pending_request"]["target_seats"] == [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12]

    module.apply_user_input(game, "从4号开始")

    assert game["phase"] == "DAY_NEXT_SPEECH"
    assert game["day_speech_queue"] == [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
    assert any("3号警长决定从4号开始发言" in line for line in game["public_log"])


def test_werewolf_user_sheriff_decides_left_or_right_and_speaks_last():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 3,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_ORDER"
    game["sheriff_seat"] = 3
    game["players"][2]["is_sheriff"] = True
    game["pending_request"] = {
        "kind": "day_order",
        "actor": "user",
        "seat": 3,
        "target_seats": [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "prompt": "你是警长，请选择发言方向。",
    }

    module.apply_user_input(game, "警左")

    assert game["day_speech_queue"] == [2, 1, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3]
    assert any("3号警长选择警左发言，警长最后归票" in line for line in game["public_log"])

    game["phase"] = "DAY_ORDER"
    game["pending_request"] = {
        "kind": "day_order",
        "actor": "user",
        "seat": 3,
        "target_seats": [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "prompt": "你是警长，请选择发言方向。",
    }
    game["public_log"] = []

    module.apply_user_input(game, "警右")

    assert game["day_speech_queue"] == [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
    assert any("3号警长选择警右发言，警长最后归票" in line for line in game["public_log"])


def test_werewolf_ai_sheriff_uses_actor_request_for_day_speech_order():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_DISCUSS_ORDER"
    game["sheriff_seat"] = 3
    game["players"][2]["is_sheriff"] = True

    route = module.advance_state_machine(game)

    assert route == "actors"
    assert game["phase"] == "DAY_ORDER_AI"
    assert game["actor_requests"]["p3"]["kind"] == "day_order"
    assert game["actor_requests"]["p3"]["target_seats"] == [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12]


def test_werewolf_day_vote_pk_pauses_for_user_pk_speech():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_VOTE_PK_NEXT_SPEECH"
    game["day_vote"]["pk_candidates"] = [2, 3]
    game["day_vote"]["pk_speech_queue"] = [2, 3]
    game["day_vote"]["pk_voters"] = [1, 4]

    route = module.advance_state_machine(game)

    assert route == "render"
    assert game["pending_request"]["kind"] == "day_pk_speech"
    assert "PK" in game["pending_request"]["prompt"]


def test_werewolf_day_exile_user_gets_last_words_before_day_end():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    module.record_vote(game, 1, 2, "day_vote")
    module.record_vote(game, 4, 2, "day_vote")

    module.resolve_day_vote(game)
    module.advance_state_machine(game)
    module.advance_state_machine(game)
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["last_words_queue"] == [2]
    assert route == "render"
    assert game["pending_request"]["kind"] == "last_words"
    assert "遗言" in game["pending_request"]["prompt"]


def test_werewolf_user_last_words_are_logged_then_day_ends():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "villager",
    })
    module.record_vote(game, 1, 2, "day_vote")
    module.record_vote(game, 4, 2, "day_vote")
    module.resolve_day_vote(game)
    module.advance_state_machine(game)
    module.advance_state_machine(game)
    module.advance_state_machine(game)
    module.advance_state_machine(game)

    module.apply_user_input(game, "我遗言是回看1和4的票。")

    assert game["phase"] == "LAST_WORDS_NEXT"
    assert game["last_words_queue"] == []
    assert any("2号遗言：我遗言是回看1和4的票。" in line for line in game["public_log"])

    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "SHERIFF_BADGE_CHECK"
    module.advance_state_machine(game)
    route = module.advance_state_machine(game)

    assert route == "advance"
    assert game["phase"] == "DAY_END"


def test_werewolf_ai_last_words_uses_actor_subworkflow_request():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    module.record_vote(game, 1, 2, "day_vote")
    module.record_vote(game, 4, 2, "day_vote")
    module.resolve_day_vote(game)
    module.advance_state_machine(game)
    module.advance_state_machine(game)
    module.advance_state_machine(game)

    route = module.advance_state_machine(game)

    assert route == "actors"
    assert game["phase"] == "LAST_WORDS_AI"
    assert game["actor_requests"]["p2"]["kind"] == "last_words"


def test_werewolf_election_vote_tie_enters_pk_speech():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "ELECTION_RESOLVE"
    game["election"]["candidates"] = [2, 3]
    game["election"]["voters"] = [1, 4]
    module.record_vote(game, 1, 2, "election_vote")
    module.record_vote(game, 4, 3, "election_vote")

    module.resolve_election_vote(game)

    assert game["phase"] == "ELECTION_PK_NEXT_SPEECH"
    assert game["election"]["pk_candidates"] == [2, 3]
    assert game["election"]["pk_speech_queue"] == [2, 3]
    assert 2 not in game["election"]["pk_voters"]
    assert 3 not in game["election"]["pk_voters"]
    assert 1 in game["election"]["pk_voters"]
    assert 4 in game["election"]["pk_voters"]
    assert any("警长投票平票" in line and "进入PK发言" in line for line in game["public_log"])


def test_werewolf_election_pk_second_tie_has_no_sheriff():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "ELECTION_PK_RESOLVE"
    game["election"]["pk_candidates"] = [2, 3]
    module.record_vote(game, 1, 2, "election_pk_vote")
    module.record_vote(game, 4, 3, "election_pk_vote")

    module.resolve_election_pk_vote(game)

    assert game["phase"] == "DEATH_ANNOUNCE"
    assert game["sheriff_seat"] is None
    assert not any(item.get("is_sheriff") for item in game["players"])
    assert any("票型：" in line and "1号投2号" in line and "4号投3号" in line for line in game["public_log"])
    assert any("警长PK投票仍然平票" in line for line in game["public_log"])


def test_werewolf_template_library_manifest_points_to_new_workflow_file():
    manifest_path = AGENT_DIR / "claw_app.json"
    assert manifest_path.is_file()
    assert (AGENT_DIR / "agents" / "werewolf.py").is_file()


def test_werewolf_render_does_not_repeat_initial_private_deal_after_game_has_public_state():
    module = _load_werewolf_module()
    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["public_log"].append("天亮了。")

    reply = module._render_game(game)

    assert "身份已发放" not in reply
    assert "你是 1 号，身份：平民。" in reply


def test_werewolf_render_shows_user_private_info_without_internal_fields():
    module = _load_werewolf_module()
    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "seer",
    })
    game["private_log"]["1"].append("第1晚查验：5号是狼人。")
    game["public_log"].append("天亮了。")

    reply = module._render_game(game)

    assert "你的私有信息：\n第1晚查验：5号是狼人。" in reply
    assert "private_log" not in reply
    assert "seer_private_checks" not in reply
    assert "身份已发放" not in reply


def test_werewolf_render_groups_public_speeches_as_readable_blocks():
    module = _load_werewolf_module()
    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["public_log"] = [
        "警长投票结果：2号3票、3号2票。",
        "2号玩家开始发言：",
        "2号：我先回应前面的点，今天重点看票型。",
        "3号玩家开始发言：",
        "3号：我觉得2号这轮解释可以听，但不能直接放。",
    ]

    reply = module._render_game(game)

    assert "警长投票结果：2号3票、3号2票。\n\n2号玩家开始发言：" in reply
    assert "2号玩家开始发言：\n2号：我先回应前面的点" in reply
    assert "。\n\n3号玩家开始发言：\n3号：我觉得2号这轮解释可以听" in reply


def test_werewolf_user_wolf_private_log_lists_wolf_teammates():
    module = _load_werewolf_module()

    game = module._new_game({
        "debug_seed": 37,
        "debug_user_seat": 2,
        "debug_user_role": "wolf",
    })
    wolf_teammates = [
        item["seat"]
        for item in game["players"]
        if item["camp"] == "wolf" and item["seat"] != 2
    ]

    assert wolf_teammates
    assert game["private_log"]["2"][-1] == "你的狼队友：" + "、".join(f"{seat}号" for seat in wolf_teammates) + "。"


def test_werewolf_entrypoint_stays_thin_and_logic_is_split_into_modules():
    entry_path = AGENT_DIR / "agents" / "werewolf.py"
    assert entry_path.is_file()
    assert len(entry_path.read_text(encoding="utf-8").splitlines()) <= 80

    expected_modules = {
        "werewolf_actions.py",
        "werewolf_actor.py",
        "werewolf_input.py",
        "werewolf_machine.py",
        "werewolf_prompts.py",
        "werewolf_rules.py",
        "werewolf_state.py",
        "werewolf_views.py",
        "werewolf_votes.py",
        "werewolf_workflow.py",
    }
    actual_modules = {
        path.name
        for path in (AGENT_DIR / "agents").glob("werewolf_*.py")
    }
    assert expected_modules.issubset(actual_modules)


def test_werewolf_actor_workflow_uses_view_action_and_memory_steps():
    module = _load_werewolf_module()

    structure = module.actor_workflow.get_structure()
    node_ids = {node["id"] for node in structure["nodes"]}

    assert {"build_view", "build_prompt", "decide", "validate_action", "update_memory"}.issubset(node_ids)
    assert {"source": "__start__", "target": "build_view", "type": "normal"} in structure["edges"]
    assert {"source": "build_view", "target": "build_prompt", "type": "normal"} in structure["edges"]
    assert {"source": "build_prompt", "target": "decide", "type": "normal"} in structure["edges"]
    assert {"source": "decide", "target": "validate_action", "type": "normal"} in structure["edges"]
    assert {"source": "validate_action", "target": "stream_speech", "type": "normal"} in structure["edges"]
    assert {"source": "stream_speech", "target": "update_memory", "type": "normal"} in structure["edges"]


def test_werewolf_default_actor_workflow_keeps_model_nodes_disabled_for_import_safety():
    module = _load_werewolf_module()

    node_ids = {node["id"] for node in module.actor_workflow.get_structure()["nodes"]}

    assert "llm_decide" not in node_ids
    assert "parse_action" not in node_ids


def test_werewolf_actor_workflow_can_be_created_with_agentclaw_model_decision_nodes():
    module = _load_werewolf_module()

    model_actor = module.create_actor_workflow(enable_model_decision=True)
    structure = model_actor.get_structure()
    node_ids = {node["id"] for node in structure["nodes"]}

    assert {
        "build_view",
        "build_prompt",
        "route_decision",
        "build_llm_input",
        "llm_decide",
        "parse_action",
        "decide",
        "validate_action",
        "update_memory",
    }.issubset(node_ids)
    assert {"source": "build_prompt", "target": "route_decision", "type": "normal"} in structure["edges"]
    assert {"source": "build_llm_input", "target": "llm_decide", "type": "normal"} in structure["edges"]
    assert {"source": "llm_decide", "target": "parse_action", "type": "normal"} in structure["edges"]
    assert {"source": "parse_action", "target": "decide", "type": "normal"} in structure["edges"]


def test_werewolf_main_workflow_can_be_created_with_custom_actor_workflow():
    module = _load_werewolf_module()

    model_actor = module.create_actor_workflow(enable_model_decision=True)
    custom_workflow = module.create_werewolf_workflow(actor=model_actor, publish_workflow=False)

    assert custom_workflow.id == "ai_werewolf"
    assert custom_workflow.get_node("call_actor_p7").workflow is model_actor
    assert module.workflow.get_node("call_actor_p7").workflow is not model_actor


def test_werewolf_main_workflow_can_enable_model_actor_decisions_without_manual_actor():
    module = _load_werewolf_module()

    workflow = module.create_werewolf_workflow(
        enable_model_actor_decision=True,
        actor_model_id="werewolf_actor_model",
        publish_workflow=False,
    )
    actor = workflow.get_node("call_actor_p7").workflow
    node_ids = {node["id"] for node in actor.get_structure()["nodes"]}

    assert {"llm_decide", "parse_action"}.issubset(node_ids)
    assert actor.get_node("llm_decide").model_id == "werewolf_actor_model"


def test_werewolf_published_workflow_uses_model_actor_decision_by_default():
    module = _load_werewolf_module()

    actor = module.workflow.get_node("call_actor_p7").workflow
    node_ids = {node["id"] for node in actor.get_structure()["nodes"]}

    assert {"llm_decide", "parse_action"}.issubset(node_ids)
    assert actor is not module.actor_workflow


@pytest.mark.asyncio
async def test_werewolf_model_actor_workflow_parses_short_llm_decision_into_validated_action():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    model_actor = module.create_actor_workflow(enable_model_decision=True)
    model_actor._llm_manager = _FakeLLMManager([
        '{"kind":"vote","target_seat":7}',
    ])
    model_actor._components_initialized = True

    result = await model_actor.run(
        {
            "request": {
                "kind": "election_vote",
                "seat": 4,
                "role": "villager",
                "role_name": "平民",
                "day": 1,
                "target_seats": [2, 7],
            },
        },
        WorkflowContext(thread_id="werewolf-model-actor"),
        thread_id="werewolf-model-actor",
    )
    state = result["state"]

    assert state["raw_action"] == {"kind": "vote", "target_seat": 7}
    assert state["action"] == {"kind": "vote", "target_seat": 7, "seat": 4}
    assert state["actor_result"]["action"]["target_seat"] == 7
    assert any("actor_view" in message["content"] for message in model_actor._llm_manager.messages[0])


@pytest.mark.asyncio
async def test_werewolf_model_actor_non_speech_prompt_rejects_unnecessary_output_fields():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    model_actor = module.create_actor_workflow(enable_model_decision=True)
    model_actor._llm_manager = _FakeLLMManager(['{"kind":"vote","target_seat":7}'])
    model_actor._components_initialized = True

    await model_actor.run(
        {
            "request": {
                "kind": "election_vote",
                "seat": 4,
                "role": "villager",
                "role_name": "平民",
                "day": 1,
                "target_seats": [2, 7],
            },
        },
        WorkflowContext(thread_id="werewolf-model-actor-compact-prompt"),
        thread_id="werewolf-model-actor-compact-prompt",
    )

    prompt = "\n".join(str(message["content"]) for message in model_actor._llm_manager.messages[0])
    assert "actor_view:" in prompt
    assert "不要理由" in prompt
    assert "不要 speech 字段" in prompt
    assert '{"kind":"vote","target_seat":5}' in prompt


@pytest.mark.asyncio
async def test_werewolf_model_actor_witch_prompt_lists_witch_action_formats():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    model_actor = module.create_actor_workflow(enable_model_decision=True)
    model_actor._llm_manager = _FakeLLMManager(['{"kind":"witch_save"}'])
    model_actor._components_initialized = True

    result = await model_actor.run(
        {
            "request": {
                "kind": "witch",
                "seat": 4,
                "role": "witch",
                "role_name": "女巫",
                "day": 1,
                "target_seats": [2, 7],
                "private_info": {
                    "night_kill_target": 2,
                    "witch_save_target": 2,
                    "witch_can_save": True,
                    "witch_can_poison": True,
                },
            },
        },
        WorkflowContext(thread_id="werewolf-model-actor-witch-prompt"),
        thread_id="werewolf-model-actor-witch-prompt",
    )

    prompt = "\n".join(str(message["content"]) for message in model_actor._llm_manager.messages[0])
    assert '{"kind":"witch_save"}' in prompt
    assert '{"kind":"witch_poison","target_seat":5}' in prompt
    assert result["state"]["action"]["kind"] == "witch_save"


@pytest.mark.asyncio
async def test_werewolf_model_actor_election_join_prompt_uses_valid_action_kinds():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    model_actor = module.create_actor_workflow(enable_model_decision=True)
    model_actor._llm_manager = _FakeLLMManager(['{"kind":"join_election"}'])
    model_actor._components_initialized = True

    result = await model_actor.run(
        {
            "request": {
                "kind": "election_join",
                "seat": 4,
                "role": "seer",
                "role_name": "预言家",
                "day": 1,
            },
        },
        WorkflowContext(thread_id="werewolf-model-actor-election-join"),
        thread_id="werewolf-model-actor-election-join",
    )

    prompt = "\n".join(str(message["content"]) for message in model_actor._llm_manager.messages[0])
    assert "join_election" in prompt
    assert "skip_election" in prompt
    assert '{"kind":"skip"}' not in prompt
    assert result["state"]["action"] == {"kind": "join_election", "seat": 4}


@pytest.mark.asyncio
async def test_werewolf_wolf_actor_prompt_demands_deceptive_team_strategy():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    model_actor = module.create_actor_workflow(enable_model_decision=True)
    model_actor._llm_manager = _FakeLLMManager(['{"kind":"vote","target_seat":7}'])
    model_actor._components_initialized = True

    await model_actor.run(
        {
            "request": {
                "kind": "election_vote",
                "seat": 4,
                "role": "wolf",
                "role_name": "狼人",
                "camp": "wolf",
                "day": 1,
                "target_seats": [2, 7],
                "private_info": {"wolf_team": [4, 5, 9, 12]},
                "public_log": [
                    "2号玩家开始发言：",
                    "2号：我起跳预言家，验7号金水，警徽流4、9。",
                    "7号玩家开始发言：",
                    "7号：我也起跳预言家，验1号金水，警徽流5、10。",
                ],
            },
        },
        WorkflowContext(thread_id="werewolf-wolf-strategy-prompt"),
        thread_id="werewolf-wolf-strategy-prompt",
    )

    prompt = "\n".join(str(message["content"]) for message in model_actor._llm_manager.messages[0])
    assert "狼队策略约束" in prompt
    assert "悍跳预言家时必须先像真预言家" in prompt
    assert "不要让所有狼人警徽票都投给狼队友" in prompt
    assert "上警狼队友不要默认给悍跳狼打冲锋" in prompt
    assert "倒钩、垫飞、切割、潜伏" in prompt


@pytest.mark.asyncio
async def test_werewolf_model_actor_workflow_falls_back_without_llm_manager():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    model_actor = module.create_actor_workflow(enable_model_decision=True)

    result = await model_actor.run(
        {
            "request": {
                "kind": "election_vote",
                "seat": 4,
                "role": "villager",
                "role_name": "平民",
                "day": 1,
                "target_seats": [2, 7],
            },
        },
        WorkflowContext(thread_id="werewolf-model-actor-no-llm"),
        thread_id="werewolf-model-actor-no-llm",
    )
    state = result["state"]

    assert state["decision_route"] == "fallback"
    assert state["action"] == {"seat": 4, "kind": "vote", "target_seat": 2}
    assert "llm_decision_text" not in state or not state["llm_decision_text"]


@pytest.mark.asyncio
async def test_werewolf_main_workflow_can_use_mocked_model_actor_subworkflow_end_to_end():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    model_actor = module.create_actor_workflow(enable_model_decision=True)
    model_actor._llm_manager = _FakeLLMManager(resolver=_werewolf_actor_decision_resolver)
    model_actor._components_initialized = True
    _patch_actor_subworkflows(module.workflow, model_actor)

    context = WorkflowContext(thread_id="werewolf-main-model-mock")
    first = await module.workflow.run(
        {
            "user_input": "开始游戏",
            "debug_seed": 37,
            "debug_user_seat": 1,
            "debug_user_role": "villager",
        },
        context,
        thread_id="werewolf-main-model-mock",
    )
    game = first["state"][module.SESSION_STATE_KEY]
    assert game["phase"] == "ELECTION_JOIN"
    assert game["night"]["wolf_target"] == 2

    second = await module.workflow.run(
        {module.SESSION_STATE_KEY: game, "user_input": "不上警"},
        context,
        thread_id="werewolf-main-model-mock",
    )
    game = second["state"][module.SESSION_STATE_KEY]

    assert game["phase"] == "ELECTION_VOTE"
    assert game["election"]["candidates"] == [5, 6, 8]
    assert any("5号模型发言" in line for line in game["public_log"])
    assert any("6号模型发言" in line for line in game["public_log"])
    assert any("8号模型发言" in line for line in game["public_log"])
    assert not any("我先按警上格局发言" in line for line in game["public_log"])
    decision_calls = [
        messages
        for messages in model_actor._llm_manager.messages
        if any("actor_view:" in message["content"] for message in messages)
    ]
    extract_calls = [
        messages
        for messages in model_actor._llm_manager.messages
        if any("You extract structured state" in message["content"] for message in messages)
    ]
    assert len(decision_calls) == 19
    assert len(extract_calls) == 0


@pytest.mark.asyncio
async def test_werewolf_actor_decision_preserves_external_raw_action_before_validation():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    request = {
        "kind": "election_vote",
        "seat": 4,
        "role": "villager",
        "role_name": "平民",
        "day": 1,
        "target_seats": [2, 7],
        "players": [
            {"seat": 2, "alive": True, "is_sheriff": False, "can_vote": True},
            {"seat": 4, "alive": True, "is_sheriff": False, "can_vote": True},
            {"seat": 7, "alive": True, "is_sheriff": False, "can_vote": True},
        ],
    }

    result = await module.actor_workflow.run(
        {
            "request": request,
            "raw_action": {"seat": 4, "kind": "vote", "target_seat": 7},
        },
        WorkflowContext(thread_id="werewolf-actor-external-action"),
        thread_id="werewolf-actor-external-action",
    )
    state = result["state"]

    assert state["raw_action"] == {"seat": 4, "kind": "vote", "target_seat": 7}
    assert state["action"] == {"seat": 4, "kind": "vote", "target_seat": 7}
    assert state["actor_result"]["action"] == {"seat": 4, "kind": "vote", "target_seat": 7}


@pytest.mark.asyncio
async def test_werewolf_actor_decision_falls_back_when_external_raw_action_is_missing():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    result = await module.actor_workflow.run(
        {
            "request": {
                "kind": "election_vote",
                "seat": 4,
                "role": "villager",
                "role_name": "平民",
                "day": 1,
                "target_seats": [2, 7],
            },
        },
        WorkflowContext(thread_id="werewolf-actor-fallback-action"),
        thread_id="werewolf-actor-fallback-action",
    )
    state = result["state"]

    assert state["raw_action"] == {"seat": 4, "kind": "vote", "target_seat": 2}
    assert state["action"] == {"seat": 4, "kind": "vote", "target_seat": 2}


@pytest.mark.asyncio
async def test_werewolf_actor_recomputes_raw_action_when_request_kind_changes_on_same_thread():
    module = _load_werewolf_module()
    from agentclaw.graph.context import WorkflowContext

    context = WorkflowContext(thread_id="werewolf-actor-reused-thread")
    first = await module.actor_workflow.run(
        {
            "request": {
                "kind": "election_join",
                "seat": 6,
                "role": "seer",
                "role_name": "预言家",
                "day": 1,
                "target_seats": [],
            },
        },
        context,
        thread_id="werewolf-actor-reused-thread",
    )
    assert first["state"]["action"]["kind"] == "skip_election"

    second = await module.actor_workflow.run(
        {
            "request": {
                "kind": "election_speech",
                "seat": 6,
                "role": "seer",
                "role_name": "预言家",
                "day": 1,
                "target_seats": [],
            },
        },
        context,
        thread_id="werewolf-actor-reused-thread",
    )

    assert second["state"]["raw_action"]["kind"] == "speak"
    assert second["state"]["action"]["kind"] == "speak"
    assert second["state"]["actor_result"]["request_kind"] == "election_speech"


def test_werewolf_prompts_are_split_into_assets_for_actor_phases():
    module = _load_werewolf_module()
    prompt_file = AGENT_DIR / "prompts" / "werewolf.yaml"

    assert prompt_file.is_file()
    assert {
        "werewolf_terms",
        "werewolf_actor_policy",
        "werewolf_persona_generation",
        "werewolf_night_action",
        "werewolf_sheriff_join",
        "werewolf_sheriff_speech",
        "werewolf_sheriff_vote",
        "werewolf_day_speech",
        "werewolf_day_vote",
    }.issubset(set(module.WEREWOLF_PROMPT_KEYS))

    prompt = module.build_actor_prompt({
        "kind": "election_speech",
        "seat": 7,
        "role_name": "预言家",
        "target_seats": [],
        "public_log": ["游戏开始。"],
        "private_info": {},
    })

    assert "{@werewolf_terms}" in prompt
    assert "{@werewolf_actor_policy}" in prompt
    assert "{@werewolf_sheriff_speech}" in prompt
    assert "actor_view" in prompt


def test_werewolf_workflow_loads_prompt_assets_from_yaml_without_python_duplication():
    module = _load_werewolf_module()
    prompt_manager = module.workflow._prompt_manager

    assert prompt_manager is not None
    for key in module.WEREWOLF_PROMPT_KEYS:
        assert prompt_manager.has_prompt(key)

    prompts_py = (AGENT_DIR / "agents" / "werewolf_prompts.py").read_text(encoding="utf-8")
    personas_py = (AGENT_DIR / "agents" / "werewolf_personas.py").read_text(encoding="utf-8")
    assert "金水：预言家查验为好人阵营的玩家" not in prompts_py
    assert "WEREWOLF_TERMS_PROMPT" not in prompts_py
    assert "降低发言模板化" not in personas_py
    assert "模拟真人" not in personas_py
    persona_prompt = prompt_manager.get_prompt("werewolf_persona_generation")
    assert "牌桌人物设定" in persona_prompt
    assert "口头禅" in persona_prompt
    assert "情绪触发点" in persona_prompt
    assert "被打时的防守方式" in persona_prompt
    assert "每个字段都写成可直接驱动发言的行为提示" in persona_prompt
    assert "可以写口癖、反应方式、桌面小习惯" in persona_prompt
    actor_policy = prompt_manager.get_prompt("werewolf_actor_policy")
    assert "speech 字段务必像真人玩家现场说话" in actor_policy
    assert "用现场口语直接说判断" in actor_policy
    assert "如果当前动作不是发言类动作，仍然只输出合法短 JSON" in actor_policy
    assert "警长投票不是放逐票" in actor_policy
    assert "信息足够时给清楚立场" in actor_policy
    assert "普通发言通常控制在 80 到 180 个汉字" in actor_policy
    assert "夜里行动理由只能来自夜里已经知道的信息" in actor_policy
    assert "不要说“因为TA在警下所以昨晚验TA”" in actor_policy
    assert "也不要换成“TA在警下，我验TA是因为警下票关键”" in actor_policy
    assert "先讲昨夜为什么选这个座位，再讲今天发现TA在警下后的收益" in actor_policy
    assert "发言生成前自检一遍验人心路" in actor_policy
    assert "如果草稿里出现“在警下所以验”“警下票关键所以验”" in actor_policy
    assert "闭眼牌在警上不知道昨夜刀口" in actor_policy
    assert "直接报刀口、银水或救人结果" in actor_policy
    assert "先主动找前置发言里最硬的逻辑漏洞" in actor_policy
    assert "时间线错误、视角越界、验人心路倒置" in actor_policy
    assert "强势发言先看爆点、票型和行为收益" in actor_policy
    sheriff_speech = prompt_manager.get_prompt("werewolf_sheriff_speech")
    assert "警上要主动抓对跳和点评位的逻辑漏洞" in sheriff_speech
    assert "不要无视已经出现的爆点" in sheriff_speech
    assert "预言家起跳时，验人心路和白天收益必须拆开讲" in sheriff_speech
    assert "狼人悍跳也要编符合时间线的心路" in sheriff_speech
    assert "不能说“我验他是因为他在警下”" in sheriff_speech
    assert "可以说“昨晚我按座位/熟悉度/信息价值摸他，今天看到他在警下，这个金水能压票”" in sheriff_speech
    day_speech = prompt_manager.get_prompt("werewolf_day_speech")
    assert "警长票投给后来死亡的真预言家通常不是投错票" in day_speech
    assert "好人要敢给压力" in day_speech
    assert "不要人人都说“先听后置”" in day_speech
    assert "每天发言先处理场上最硬的爆点" in day_speech
    assert "前后矛盾、票型收益不匹配、身份视角不成立" in day_speech
    assert "警下票一边倒支持某个预言家" in day_speech
    assert "不要反复用“太满”" in day_speech
    night_action = prompt_manager.get_prompt("werewolf_night_action")
    assert "AI 女巫不要长期默认跳过用药" in night_action


def test_werewolf_wolf_strategy_prompt_requires_team_role_split():
    module = _load_werewolf_module()
    prompt = module.build_actor_prompt({
        "kind": "election_speech",
        "seat": 9,
        "role": "wolf",
        "role_name": "狼人",
        "target_seats": [],
        "private_info": {"wolf_team": [1, 4, 9, 12]},
    })

    assert "狼队不要全员挤在同一种位置" in prompt
    assert "悍跳狼、冲锋狼、倒钩狼、深水狼要拉开距离" in prompt
    assert "不要所有狼都上警" in prompt


def test_werewolf_actor_view_hides_real_roles_except_wolf_team():
    module = _load_werewolf_module()
    game = module._new_game({
        "debug_seed": 41,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    wolf_seat = next(player["seat"] for player in game["players"] if player["camp"] == "wolf")
    villager_seat = next(player["seat"] for player in game["players"] if player["camp"] == "good")

    wolf_request = module._build_actor_request(game, wolf_seat, "election_speech", [])
    wolf_view = module.build_actor_view(wolf_request, {})
    wolf_allies = set(wolf_view["private_info"]["wolf_team"])
    expected_allies = {
        player["seat"]
        for player in game["players"]
        if player["camp"] == "wolf"
    }
    assert wolf_allies == expected_allies
    assert "players" not in wolf_view

    villager_request = module._build_actor_request(game, villager_seat, "election_speech", [])
    villager_view = module.build_actor_view(villager_request, {})
    assert villager_view["private_info"].get("wolf_team") == []
    assert "players" not in villager_view
    assert all("role" not in item for item in villager_view["public_players"])


def test_werewolf_actor_view_contains_complete_visible_context_and_memory_snapshot():
    module = _load_werewolf_module()
    game = module._new_game({
        "debug_seed": 41,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    game["phase"] = "DAY_VOTE"
    game["sheriff_seat"] = 3
    game["public_log"].extend(["3号警长选择警右发言，警长最后归票。", "4号：我站边3号。"])
    module.record_vote(game, 2, 3, "election_vote")
    seer_seat = next(player["seat"] for player in game["players"] if player["role"] == "seer")
    game["seer_private_checks"] = {
        str(seer_seat): [{"day": 1, "target_seat": 4, "alignment": "good", "result_name": "好人"}]
    }
    request = module._build_actor_request(game, seer_seat, "day_vote", [4, 5])

    view = module.build_actor_view(request, {
        "observations": ["我警上报过4号金水。"],
        "last_action": {"kind": "speak", "speech": "4号是我的金水。"},
    })

    assert view["phase"] == "DAY_VOTE"
    assert view["sheriff_seat"] == 3
    assert view["votes"] == [{"from": 2, "to": 3, "phase": "election_vote"}]
    assert view["private_info"]["seer_checks"] == [
        {"day": 1, "target_seat": 4, "alignment": "good", "result_name": "好人"}
    ]
    assert view["memory"]["observations"] == ["我警上报过4号金水。"]
    assert "players" not in view
    assert all("role" not in item for item in view["public_players"])


def test_werewolf_actor_view_explains_vote_phase_semantics():
    module = _load_werewolf_module()
    game = module._new_game({
        "debug_seed": 41,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    module.record_vote(game, 3, 7, "election_vote")
    module.record_vote(game, 8, 7, "election_pk_vote")
    module.record_vote(game, 9, 12, "day_vote")
    module.record_vote(game, 10, 12, "day_pk_vote")

    request = module._build_actor_request(game, 3, "day_speech", [])
    view = module.build_actor_view(request, {})

    assert "支持其当选警长" in view["vote_phase_notes"]["election_vote"]
    assert "不表示放逐" in view["vote_phase_notes"]["election_vote"]
    assert "希望其出局" in view["vote_phase_notes"]["day_vote"]
    assert view["vote_records"] == [
        {
            "from": 3,
            "to": 7,
            "phase": "election_vote",
            "meaning": "3号在警长投票中支持7号当选警长，不表示放逐或攻击7号。",
        },
        {
            "from": 8,
            "to": 7,
            "phase": "election_pk_vote",
            "meaning": "8号在警长PK投票中支持7号当选警长，不表示放逐或攻击7号。",
        },
        {
            "from": 9,
            "to": 12,
            "phase": "day_vote",
            "meaning": "9号在白天放逐投票中投12号出局。",
        },
        {
            "from": 10,
            "to": 12,
            "phase": "day_pk_vote",
            "meaning": "10号在白天PK放逐投票中投12号出局。",
        },
    ]


def test_werewolf_actor_view_includes_persona_without_public_role_leakage():
    module = _load_werewolf_module()
    game = module._new_game({
        "debug_seed": 41,
        "debug_user_seat": 1,
        "debug_user_role": "villager",
    })
    actor_id = next(iter(game["actors"]))
    seat = int(actor_id.removeprefix("p"))
    persona = {
        "temperament": "嘴硬但会观察",
        "speech_style": "口语化、偶尔停顿",
        "strategic_bias": "狼人时偏倒钩，好人时爱抓视角漏洞",
        "table_habits": "不复读完整名单，只抓两个重点位",
    }
    game["actors"][actor_id]["persona"] = persona

    request = module._build_actor_request(game, seat, "day_speech", [])
    view = module.build_actor_view(request, {})

    assert view["persona"] == persona
    assert "role" not in view["persona"]
    assert "players" not in view


def test_werewolf_action_schema_rejects_wrong_phase_action_kind_and_bad_target():
    module = _load_werewolf_module()
    actor_view = {
        "kind": "election_vote",
        "seat": 4,
        "target_seats": [2, 7],
    }

    action = module.normalize_actor_action(actor_view, {
        "seat": 99,
        "kind": "kill",
        "target_seat": 12,
    })

    assert action == {"seat": 4, "kind": "vote", "target_seat": 2}


def test_werewolf_actor_fallback_does_not_generate_strategy_or_template_speech():
    module = _load_werewolf_module()

    election_join = module.fallback_actor_action({
        "kind": "election_join",
        "seat": 5,
        "role": "seer",
        "target_seats": [],
    })
    speech = module.fallback_actor_action({
        "kind": "day_speech",
        "seat": 8,
        "role": "villager",
        "target_seats": [],
    })

    assert election_join == {"seat": 5, "kind": "skip_election"}
    assert speech == {"seat": 8, "kind": "speak", "speech": ""}


def test_werewolf_normalize_actor_action_keeps_empty_speech_empty():
    module = _load_werewolf_module()

    action = module.normalize_actor_action(
        {"kind": "day_speech", "seat": 8, "target_seats": []},
        {"kind": "speak"},
    )

    assert action == {"kind": "speak", "seat": 8, "speech": ""}


def test_werewolf_action_schema_supports_day_speech_and_day_vote():
    module = _load_werewolf_module()

    speech = module.normalize_actor_action(
        {"kind": "day_speech", "seat": 8, "target_seats": []},
        {"seat": 8, "kind": "speak", "speech": "  今天先看警长归票，再看票型。  "},
    )
    vote = module.normalize_actor_action(
        {"kind": "day_vote", "seat": 8, "target_seats": [3, 6]},
        {"seat": 8, "kind": "vote", "target_seat": 12},
    )

    assert speech == {"seat": 8, "kind": "speak", "speech": "今天先看警长归票，再看票型。"}
    assert vote == {"seat": 8, "kind": "vote", "target_seat": 3}


def test_imported_werewolf_template_uses_project_local_subworkflow_module(tmp_path, monkeypatch):
    import importlib
    import sys

    from agentclaw.agent_square import import_claw_app_to_project
    from agentclaw.api.registry import WorkflowRegistry

    import_claw_app_to_project("ai_werewolf", tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    WorkflowRegistry.unregister("ai_werewolf")
    for module_name in list(sys.modules):
        if module_name == "agents" or module_name.startswith("agents.ai_werewolf"):
            sys.modules.pop(module_name, None)

    module = importlib.import_module("agents.ai_werewolf.agents.werewolf")

    assert module.workflow.id == "ai_werewolf"
    assert module.actor_workflow.id == "werewolf_actor"
    assert module.APP_DIR == tmp_path / "agents" / "ai_werewolf"
    actor = module.workflow.get_node("call_actor_p7").workflow
    assert actor.id == "werewolf_actor"
    assert {"llm_decide", "parse_action"}.issubset({node["id"] for node in actor.get_structure()["nodes"]})

    WorkflowRegistry.unregister("ai_werewolf")

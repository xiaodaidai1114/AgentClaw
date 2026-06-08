import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.unit


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_SQUARE_DIR = PROJECT_ROOT / "agentclaw" / "agent_square"
AGENT_DIR = AGENT_SQUARE_DIR / "turtle_soup_agent"


def _load_turtle_soup_module():
    from agentclaw.api.registry import WorkflowRegistry

    WorkflowRegistry.unregister("turtle_soup")
    module_path = AGENT_DIR / "agents" / "turtle_soup.py"
    spec = importlib.util.spec_from_file_location("agent_square_turtle_soup", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_turtle_soup_agent_square_project_structure():
    expected_files = [
        "__init__.py",
        "README.md",
        "claw_app.json",
        "agents/__init__.py",
        "agents/turtle_soup.py",
        "agents/turtle_soup_prompts.py",
        "data/premium_turtle_soups.md",
    ]

    for relative_path in expected_files:
        assert (AGENT_DIR / relative_path).is_file(), relative_path

    for removed_project_file in ["server.py", ".env.example", "models.json.example"]:
        assert not (AGENT_DIR / removed_project_file).exists()

    assert not (PROJECT_ROOT / "agent_square" / "turtle_soup_agent").exists()


def test_turtle_soup_workflow_metadata_and_prompts():
    module = _load_turtle_soup_module()

    assert module.workflow.id == "turtle_soup"
    assert "海龟汤" in module.workflow.name
    structure = module.workflow.get_structure()
    assert structure["welcome"] == module.prompt_contracts.OPENING_MESSAGE
    assert structure["user_input_field"] == "user_input"
    assert [field["name"] for field in structure["form_config"]] == ["user_input"]
    assert "开场" in module.prompt_contracts.OPENING_MESSAGE
    assert "是" in module.prompt_contracts.QUESTION_JUDGEMENT_ALLOWED
    assert "否" in module.prompt_contracts.QUESTION_JUDGEMENT_ALLOWED
    assert "无关" in module.prompt_contracts.QUESTION_JUDGEMENT_ALLOWED
    assert "部分正确" in module.prompt_contracts.QUESTION_JUDGEMENT_ALLOWED
    assert "不要泄露汤底" in module.prompt_contracts.HINT_SYSTEM_PROMPT
    assert "仅能输出" in module.prompt_contracts.QUESTION_JUDGEMENT_SYSTEM_PROMPT
    assert "answer_attempt" in module.prompt_contracts.INTENT_CLASSIFIER_SYSTEM_PROMPT


def test_turtle_soup_prompts_are_schema_driven_and_professional():
    module = _load_turtle_soup_module()
    source = (AGENT_DIR / "agents" / "turtle_soup.py").read_text(encoding="utf-8")
    prompts_source = (AGENT_DIR / "agents" / "turtle_soup_prompts.py").read_text(encoding="utf-8")

    for constant_name in [
        "PHASES",
        "INTENTS",
        "PLAYER_TURN_CONTEXT_SCHEMA",
        "SESSION_STATE_SCHEMA",
        "TYPE_SELECTION_OUTPUT_SCHEMA",
        "SOUP_DRAFT_OUTPUT_SCHEMA",
        "SOUP_CONFIRMATION_INTENT_SCHEMA",
        "CONFIRM_SOUP_START_OUTPUT_SCHEMA",
        "SOUP_REVISION_OUTPUT_SCHEMA",
        "GAME_INTENT_SCHEMA",
        "HINT_OUTPUT_SCHEMA",
        "ANSWER_JUDGEMENT_OUTPUT_SCHEMA",
        "IRRELEVANT_REPLY_OUTPUT_SCHEMA",
        "SOLVED_TURN_OUTPUT_SCHEMA",
        "QUESTION_JUDGEMENT_OUTPUT_SCHEMA",
    ]:
        assert hasattr(module.prompt_contracts, constant_name), constant_name

    assert "from . import turtle_soup_prompts as prompt_contracts" in source
    assert "prompt_contracts.OPENING_MESSAGE" in source
    assert "prompt_contracts.LLM_NODE_SPECS" in source
    assert "globals()[" not in source
    assert "getattr(_PROMPT_CONTRACTS" not in source
    assert "from .turtle_soup_prompts import (" not in source
    assert "TYPE_SELECTION_OUTPUT_SCHEMA = {" not in source
    assert "TYPE_SELECTION_OUTPUT_SCHEMA" in prompts_source
    assert "QUESTION_JUDGEMENT_SYSTEM_PROMPT = f" not in source
    assert "QUESTION_JUDGEMENT_SYSTEM_PROMPT" in prompts_source
    assert "Do not update turn_history or counters in LLM nodes" in source

    assert "playing" in module.prompt_contracts.PHASES
    assert "answer_attempt" in module.prompt_contracts.INTENTS
    assert module.prompt_contracts.GAME_INTENT_SCHEMA["properties"]["intent"]["enum"] == [
        "question_judgement",
        "hint_request",
        "non_question",
    ]
    assert module.prompt_contracts.SOUP_CONFIRMATION_INTENT_SCHEMA["properties"]["intent"]["enum"] == [
        "confirm_start",
        "revise_soup",
        "regenerate_soup",
        "clarify_confirmation",
    ]
    assert module.prompt_contracts.QUESTION_JUDGEMENT_OUTPUT_SCHEMA["properties"]["verdict"]["enum"] == list(module.prompt_contracts.QUESTION_JUDGEMENT_ALLOWED)

    for schema in [
        module.prompt_contracts.PLAYER_TURN_CONTEXT_SCHEMA,
        module.prompt_contracts.SESSION_STATE_SCHEMA,
        module.prompt_contracts.TYPE_SELECTION_OUTPUT_SCHEMA,
        module.prompt_contracts.SOUP_DRAFT_OUTPUT_SCHEMA,
        module.prompt_contracts.SOUP_CONFIRMATION_INTENT_SCHEMA,
        module.prompt_contracts.CONFIRM_SOUP_START_OUTPUT_SCHEMA,
        module.prompt_contracts.SOUP_REVISION_OUTPUT_SCHEMA,
        module.prompt_contracts.GAME_INTENT_SCHEMA,
        module.prompt_contracts.HINT_OUTPUT_SCHEMA,
        module.prompt_contracts.ANSWER_JUDGEMENT_OUTPUT_SCHEMA,
        module.prompt_contracts.IRRELEVANT_REPLY_OUTPUT_SCHEMA,
        module.prompt_contracts.SOLVED_TURN_OUTPUT_SCHEMA,
        module.prompt_contracts.QUESTION_JUDGEMENT_OUTPUT_SCHEMA,
    ]:
        json.dumps(schema, ensure_ascii=False)

    prompts = [
        module.prompt_contracts.TYPE_SELECTION_SYSTEM_PROMPT,
        module.prompt_contracts.SOUP_DRAFT_SYSTEM_PROMPT,
        module.prompt_contracts.SOUP_CONFIRMATION_INTENT_SYSTEM_PROMPT,
        module.prompt_contracts.CONFIRM_SOUP_START_SYSTEM_PROMPT,
        module.prompt_contracts.SOUP_REVISION_SYSTEM_PROMPT,
        module.prompt_contracts.GAME_INTENT_SYSTEM_PROMPT,
        module.prompt_contracts.QUESTION_JUDGEMENT_SYSTEM_PROMPT,
        module.prompt_contracts.HINT_SYSTEM_PROMPT,
        module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT,
        module.prompt_contracts.IRRELEVANT_REPLY_SYSTEM_PROMPT,
        module.prompt_contracts.SOLVED_TURN_SYSTEM_PROMPT,
    ]
    for prompt in prompts:
        for section in ["<ROLE>", "<TASK>", "<CONTEXT_CONTRACT>", "<OUTPUT_CONTRACT>"]:
            assert section in prompt
        assert "必须输出合法 JSON" in prompt

    assert "TYPE_SELECTION_OUTPUT_SCHEMA" in module.prompt_contracts.TYPE_SELECTION_SYSTEM_PROMPT
    assert "SOUP_DRAFT_OUTPUT_SCHEMA" in module.prompt_contracts.SOUP_DRAFT_SYSTEM_PROMPT
    assert "SOUP_CONFIRMATION_INTENT_SCHEMA" in module.prompt_contracts.SOUP_CONFIRMATION_INTENT_SYSTEM_PROMPT
    assert "CONFIRM_SOUP_START_OUTPUT_SCHEMA" in module.prompt_contracts.CONFIRM_SOUP_START_SYSTEM_PROMPT
    assert "SOUP_REVISION_OUTPUT_SCHEMA" in module.prompt_contracts.SOUP_REVISION_SYSTEM_PROMPT
    assert "GAME_INTENT_SCHEMA" in module.prompt_contracts.GAME_INTENT_SYSTEM_PROMPT
    assert "QUESTION_JUDGEMENT_OUTPUT_SCHEMA" in module.prompt_contracts.QUESTION_JUDGEMENT_SYSTEM_PROMPT
    assert "HINT_OUTPUT_SCHEMA" in module.prompt_contracts.HINT_SYSTEM_PROMPT
    assert "ANSWER_JUDGEMENT_OUTPUT_SCHEMA" in module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT
    assert "IRRELEVANT_REPLY_OUTPUT_SCHEMA" in module.prompt_contracts.IRRELEVANT_REPLY_SYSTEM_PROMPT
    assert "SOLVED_TURN_OUTPUT_SCHEMA" in module.prompt_contracts.SOLVED_TURN_SYSTEM_PROMPT
    for prompt_name, prompt in [
        ("GAME_INTENT_SYSTEM_PROMPT", module.prompt_contracts.GAME_INTENT_SYSTEM_PROMPT),
        ("QUESTION_JUDGEMENT_SYSTEM_PROMPT", module.prompt_contracts.QUESTION_JUDGEMENT_SYSTEM_PROMPT),
        ("HINT_SYSTEM_PROMPT", module.prompt_contracts.HINT_SYSTEM_PROMPT),
        ("NON_QUESTION_CLASSIFIER_SYSTEM_PROMPT", module.prompt_contracts.NON_QUESTION_CLASSIFIER_SYSTEM_PROMPT),
        ("ANSWER_JUDGEMENT_SYSTEM_PROMPT", module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT),
        ("IRRELEVANT_REPLY_SYSTEM_PROMPT", module.prompt_contracts.IRRELEVANT_REPLY_SYSTEM_PROMPT),
    ]:
        assert "turn_history" in prompt, prompt_name
    assert "避免重复玩家已经确认的事实" in module.prompt_contracts.HINT_SYSTEM_PROMPT
    assert "连续作答" in module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT
    assert "不要求逐条命中 truth_facts" in module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT
    assert "核心反转" in module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT
    assert "关键证据" in module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT
    assert "主要因果链" in module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT
    assert "结局原因" in module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT
    assert "合理推出或自然蕴含" in module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT
    assert "不要仅因缺少主动报警的心理策略" in module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT
    assert "不要要求玩家逐步复述警方核查流程" in module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT
    assert "不要要求题面或汤底未明确展开的旧案细节" in module.prompt_contracts.ANSWER_JUDGEMENT_SYSTEM_PROMPT
    assert "故事逻辑自检" in module.prompt_contracts.SOUP_GENERATION_SYSTEM_PROMPT
    assert "关键线索必须有清楚的信息获取路径" in module.prompt_contracts.SOUP_GENERATION_SYSTEM_PROMPT
    assert "不能让角色知道自己无法观察、听见、收到或合理推断的信息" in module.prompt_contracts.SOUP_GENERATION_SYSTEM_PROMPT
    assert "事件时序必须闭合" in module.prompt_contracts.SOUP_GENERATION_SYSTEM_PROMPT
    assert "行动动机必须由当时已经获得的信息触发" in module.prompt_contracts.SOUP_GENERATION_SYSTEM_PROMPT
    assert "汤面中的异常必须能被汤底解释" in module.prompt_contracts.SOUP_GENERATION_SYSTEM_PROMPT
    for story_specific_marker in ["外卖", "小票", "门外"]:
        assert story_specific_marker not in module.prompt_contracts.SOUP_GENERATION_SYSTEM_PROMPT
    assert "上一轮" in module.prompt_contracts.NON_QUESTION_CLASSIFIER_SYSTEM_PROMPT
    assert "最近对话" in module.prompt_contracts.IRRELEVANT_REPLY_SYSTEM_PROMPT
    assert "reply 必须只包含 verdict 本身" in module.prompt_contracts.QUESTION_JUDGEMENT_SYSTEM_PROMPT
    assert "不要在 reply 中泄露 soup_solution" in module.prompt_contracts.SOUP_DRAFT_SYSTEM_PROMPT
    assert '"reference_soups"' in module.prompt_contracts.PHASE_NODE_USER_PROMPT
    assert '"user_input"' in module.prompt_contracts.PHASE_NODE_USER_PROMPT
    assert '"session"' in module.prompt_contracts.PHASE_NODE_USER_PROMPT


def test_turtle_soup_example_avoids_story_specific_keyword_heuristics():
    source = (AGENT_DIR / "agents" / "turtle_soup.py").read_text(encoding="utf-8")

    assert "_looks_like_fact_hypothesis" not in source
    assert "LLM_NODE_SPECS" in source
    assert "for node_id, description, system_prompt, temperature in prompt_contracts.LLM_NODE_SPECS" in source
    assert "reference_soups = _read_reference_soups()" in source
    assert source.count("_read_reference_soups()") == 2
    for story_marker in ["男人", "女人", "母亲", "父亲", "护士", "警察", "医院", "门外"]:
        assert story_marker not in source


def test_turtle_soup_workflow_uses_phase_specific_nodes():
    module = _load_turtle_soup_module()

    expected_nodes = {
        "prepare_turn",
        "type_selection",
        "soup_draft",
        "soup_confirmation_intent",
        "confirm_soup_start",
        "revise_soup",
        "regenerate_soup",
        "clarify_soup_confirmation",
        "game_intent_classifier",
        "judge_question",
        "generate_hint",
        "classify_non_question",
        "judge_answer",
        "handle_irrelevant",
        "solved_turn",
        "render_reply",
    }

    assert expected_nodes.issubset(module.workflow._nodes)
    assert "game_master" not in module.workflow._nodes
    assert module.workflow._start_node == "prepare_turn"
    assert "prepare_turn" in module.workflow._conditional_edges

    router_targets = set(module.workflow._conditional_edges["prepare_turn"]["targets"].values())
    assert {"type_selection", "soup_confirmation_intent", "game_intent_classifier", "solved_turn"}.issubset(router_targets)

    confirm_targets = set(module.workflow._conditional_edges["soup_confirmation_intent"]["targets"].values())
    assert {"confirm_soup_start", "revise_soup", "regenerate_soup", "clarify_soup_confirmation"}.issubset(confirm_targets)

    game_targets = set(module.workflow._conditional_edges["game_intent_classifier"]["targets"].values())
    assert {"judge_question", "generate_hint", "classify_non_question"}.issubset(game_targets)

    non_question_targets = set(module.workflow._conditional_edges["classify_non_question"]["targets"].values())
    assert {"judge_answer", "handle_irrelevant"}.issubset(non_question_targets)

    for node_id in expected_nodes - {"prepare_turn", "confirm_soup_start", "render_reply"}:
        node = module.workflow._nodes[node_id]
        assert node.output_format == "json"
        assert node.user_prompt == module.prompt_contracts.PHASE_NODE_USER_PROMPT

    assert not hasattr(module.workflow._nodes["confirm_soup_start"], "output_format")


def test_turtle_soup_state_helpers_follow_schema_contract():
    module = _load_turtle_soup_module()

    session = module._coerce_session({"phase": "playing", "key_facts": ["旧字段"], "misleading_points": ["旧误导"]})

    assert session["phase"] == "playing"
    for field in module.prompt_contracts.SESSION_STATE_SCHEMA["required"]:
        assert field in session
    assert "key_facts" not in session
    assert "misleading_points" not in session
    assert "turn_history" in session

    normalized = module._normalize_phase_result(
        {
            "reply": "我解释一下：是",
            "phase": "playing",
            "intent": "question_judgement",
            "question_judgement": "是",
            "session": session,
        },
        session,
    )

    assert normalized["reply"] == "是"
    assert normalized["session"]["phase"] == "playing"


def test_turtle_soup_choose_type_fallback_keeps_player_in_type_selection():
    module = _load_turtle_soup_module()
    session = module._coerce_session({"phase": "choose_type"})

    normalized = module._normalize_phase_result(
        {
            "reply": "",
            "phase": "choose_type",
            "intent": "irrelevant_reply",
            "ready_to_draft": False,
            "session": session,
        },
        session,
    )

    assert normalized["phase"] == "choose_type"
    assert normalized["intent"] == "irrelevant_reply"
    assert "想玩什么类型" in normalized["reply"]
    assert "继续提问" not in normalized["reply"]
    assert "给出答案" not in normalized["reply"]


def test_turtle_soup_prepare_turn_includes_recent_turn_history():
    module = _load_turtle_soup_module()

    session = module._coerce_session({
        "phase": "playing",
        "turn_history": [
            {
                "user_input": "故事里的关键人物是3人以上吗（包括3人）",
                "intent": "question_judgement",
                "reply": "是",
                "verdict": "是",
            }
        ],
    })

    prepared = module.prepare_turn({
        "user_input": "是三人吗",
        module.SESSION_STATE_KEY: session,
    })
    context = json.loads(prepared["player_turn_context_json"])

    assert context["user_input"] == "是三人吗"
    assert context["session"]["turn_history"][-1]["user_input"] == "故事里的关键人物是3人以上吗（包括3人）"
    assert context["session"]["turn_history"][-1]["verdict"] == "是"


def test_turtle_soup_internal_session_is_not_a_public_input():
    module = _load_turtle_soup_module()

    state = {
        "user_input": "开始",
        "turtle_soup_session": {"phase": "await_soup_confirmation", "soup_surface": "汤面"},
        "session": {"phase": "choose_type"},
    }

    prepared = module.prepare_turn(state)
    route = module._route_after_prepare(prepared)

    assert route == "soup_confirmation_intent"
    assert prepared["session"]["phase"] == "await_soup_confirmation"
    assert '"session"' in prepared["player_turn_context_json"]


@pytest.mark.asyncio
async def test_turtle_soup_render_reply_outputs_current_terminal_result(monkeypatch):
    module = _load_turtle_soup_module()
    emitted: list[tuple[str, dict]] = []

    async def fake_output(content, **kwargs):
        emitted.append((content, kwargs))

    monkeypatch.setattr(module, "output", fake_output)
    session = module._coerce_session({"phase": "choose_type"})
    soup_session = module._coerce_session({
        "phase": "await_soup_confirmation",
        "soup_type": "反转",
        "difficulty": "中等",
        "soup_surface": "汤面：一个人看见门口的伞后，立刻报警。",
        "soup_solution": "完整汤底",
        "truth_facts": ["伞是关键线索"],
    })
    state = {
        "session": soup_session,
        "type_selection": {
            "reply": "收到，想玩反转类海龟汤。",
            "phase": "choose_type",
            "intent": "type_choice",
            "session": session,
        },
        "soup_draft": {
            "reply": "汤面：一个人看见门口的伞后，立刻报警。\n\n要使用这题吗？",
            "phase": "await_soup_confirmation",
            "intent": "type_choice",
            "session": soup_session,
        },
    }

    result = await module.render_reply(state)

    assert emitted == [(
        "汤面：一个人看见门口的伞后，立刻报警。\n\n要使用这题吗？",
        {"node": "render_reply", "save_to_context": False, "stream": False},
    )]
    assert result["reply"].startswith("汤面：")


def test_turtle_soup_prepare_turn_clears_stale_node_results():
    module = _load_turtle_soup_module()

    prepared = module.prepare_turn({
        "user_input": "开始",
        "type_selection": {"reply": "旧类型选择"},
        "soup_draft": {"reply": "旧汤面"},
        "judge_question": {"verdict": "是"},
    })

    assert prepared["type_selection"] == module.prompt_contracts.CLEARED_PHASE_RESULT
    assert prepared["soup_draft"] == module.prompt_contracts.CLEARED_PHASE_RESULT
    assert prepared["judge_question"] == module.prompt_contracts.CLEARED_PHASE_RESULT


def test_turtle_soup_prepare_turn_puts_stable_reference_before_dynamic_turn_data():
    module = _load_turtle_soup_module()

    prepared = module.prepare_turn({"user_input": "我想玩反转强一点的"})
    context_json = prepared["player_turn_context_json"]

    assert context_json.index('"reference_soups"') < context_json.index('"session"')
    assert context_json.index('"session"') < context_json.index('"user_input"')
    parsed = json.loads(context_json)
    assert list(parsed.keys()) == ["reference_soups", "session", "user_input"]


@pytest.mark.asyncio
async def test_turtle_soup_render_reply_ignores_cleared_stale_answer(monkeypatch):
    module = _load_turtle_soup_module()
    emitted: list[str] = []

    async def fake_output(content, **kwargs):
        emitted.append(content)

    monkeypatch.setattr(module, "output", fake_output)
    session = module._coerce_session({
        "phase": "playing",
        "soup_surface": "汤面",
        "soup_solution": "汤底",
    })

    result = await module.render_reply({
        "session": session,
        "judge_answer": module.prompt_contracts.CLEARED_PHASE_RESULT,
        "generate_hint": {
            "reply": "提示：注意男人为什么会主动报警。",
            "phase": "playing",
            "intent": "hint_request",
            "session": session,
        },
    })

    assert emitted == ["提示：注意男人为什么会主动报警。"]
    assert result["reply"] == "提示：注意男人为什么会主动报警。"


@pytest.mark.asyncio
async def test_turtle_soup_render_reply_records_user_turn_history(monkeypatch):
    module = _load_turtle_soup_module()

    async def fake_output(content, **kwargs):
        return None

    monkeypatch.setattr(module, "output", fake_output)
    session = module._coerce_session({
        "phase": "playing",
        "turn_history": [
            {
                "user_input": "故事里的关键人物是3人以上吗（包括3人）",
                "intent": "question_judgement",
                "reply": "是",
                "verdict": "是",
            }
        ],
    })

    result = await module.render_reply({
        "user_input": "是三人吗",
        "session": session,
        "judge_question": {"verdict": "否"},
    })
    history = result[module.SESSION_STATE_KEY]["turn_history"]

    assert history[-2]["user_input"] == "故事里的关键人物是3人以上吗（包括3人）"
    assert history[-1]["user_input"] == "是三人吗"
    assert history[-1]["intent"] == "question_judgement"
    assert history[-1]["verdict"] == "否"
    assert history[-1]["reply"] == "否"
    assert result[module.SESSION_STATE_KEY]["last_feedback"] == "否"
    assert result[module.SESSION_STATE_KEY]["question_count"] == 1


@pytest.mark.asyncio
async def test_turtle_soup_render_reply_clears_old_round_when_restarting_after_solved(monkeypatch):
    module = _load_turtle_soup_module()

    async def fake_output(content, **kwargs):
        return None

    monkeypatch.setattr(module, "output", fake_output)
    solved_session = module._coerce_session({
        "phase": "solved",
        "soup_type": "旧类型",
        "difficulty": "困难",
        "soup_surface": "旧汤面",
        "soup_solution": "旧汤底",
        "truth_facts": ["旧真相"],
        "known_facts": ["旧已知"],
        "open_threads": ["旧线索"],
        "question_count": 7,
        "hint_count": 2,
        "answer_attempt_count": 3,
        "last_feedback": "旧反馈",
        "turn_history": [
            {
                "user_input": "旧问题",
                "intent": "question_judgement",
                "reply": "是",
                "verdict": "是",
            }
        ],
    })

    result = await module.render_reply({
        "user_input": "再来一题，想玩校园反转",
        "session": solved_session,
        "solved_turn": {
            "reply": "可以，下一题想玩什么类型？",
            "phase": "choose_type",
            "intent": "restart",
            "session": solved_session,
        },
    })
    next_session = result[module.SESSION_STATE_KEY]

    assert next_session["phase"] == "choose_type"
    assert next_session["difficulty"] == ""
    assert next_session["soup_surface"] == ""
    assert next_session["soup_solution"] == ""
    assert next_session["truth_facts"] == []
    assert next_session["known_facts"] == []
    assert next_session["open_threads"] == []
    assert next_session["question_count"] == 0
    assert next_session["hint_count"] == 0
    assert next_session["answer_attempt_count"] == 0
    assert [item["user_input"] for item in next_session["turn_history"]] == [
        "再来一题，想玩校园反转",
    ]


@pytest.mark.asyncio
async def test_turtle_soup_render_reply_records_hint_and_answer_counts(monkeypatch):
    module = _load_turtle_soup_module()

    async def fake_output(content, **kwargs):
        return None

    monkeypatch.setattr(module, "output", fake_output)
    session = module._coerce_session({"phase": "playing"})

    hinted = await module.render_reply({
        "user_input": "给个提示",
        "session": session,
        "generate_hint": {
            "reply": "提示：回想一下他为什么第一反应是报警。",
            "phase": "playing",
            "intent": "hint_request",
            "session": session,
        },
    })
    assert hinted[module.SESSION_STATE_KEY]["hint_count"] == 1
    assert hinted[module.SESSION_STATE_KEY]["turn_history"][-1]["intent"] == "hint_request"

    answered = await module.render_reply({
        "user_input": "我猜答案是母亲没死",
        "session": hinted[module.SESSION_STATE_KEY],
        "judge_answer": {
            "reply": "还不完整。",
            "phase": "playing",
            "intent": "answer_attempt",
            "is_correct": False,
            "session": hinted[module.SESSION_STATE_KEY],
        },
    })
    assert answered[module.SESSION_STATE_KEY]["answer_attempt_count"] == 1
    assert answered[module.SESSION_STATE_KEY]["turn_history"][-1]["intent"] == "answer_attempt"


def test_turtle_soup_routes_only_by_model_intent_without_story_keyword_fallbacks():
    module = _load_turtle_soup_module()

    assert module._route_after_game_intent({
        "user_input": "某个事实假设",
        "game_intent_classifier": {"intent": "question_judgement"},
    }) == "judge_question"
    assert module._route_after_game_intent({
        "user_input": "某个事实假设",
        "game_intent_classifier": {"intent": "non_question"},
    }) == "classify_non_question"
    assert "简短事实假设" in module.prompt_contracts.GAME_INTENT_SYSTEM_PROMPT


def test_turtle_soup_confirm_start_does_not_repeat_confirmation_prompt():
    module = _load_turtle_soup_module()
    session = module._coerce_session({
        "phase": "await_soup_confirmation",
        "soup_type": "反转悬疑",
        "difficulty": "困难",
        "soup_surface": "男人每天都到医院，给昏迷的妻子读同一本童话书。",
        "soup_solution": "完整汤底不能提前泄露。",
        "truth_facts": ["男人知道童话书里藏着真相"],
    })

    result = module.confirm_soup_start({
        "user_input": "可以",
        module.SESSION_STATE_KEY: session,
        "session": session,
    })
    confirmation = result["confirm_soup_start"]

    assert confirmation["phase"] == "playing"
    assert confirmation["intent"] == "soup_confirm"
    assert confirmation["session"]["phase"] == "playing"
    assert confirmation["session"]["soup_solution"] == "完整汤底不能提前泄露。"
    assert "游戏开始" in confirmation["reply"]
    assert "你可以开始提问" in confirmation["reply"]
    assert "是否使用这题" not in confirmation["reply"]
    assert "完整汤底" not in confirmation["reply"]


def test_turtle_soup_sample_references_are_structured():
    text = (AGENT_DIR / "data" / "premium_turtle_soups.md").read_text(encoding="utf-8")

    assert text.count("## 示例") >= 25
    for marker in ["类型：", "汤面：", "汤底："]:
        assert marker in text
    for generated_marker in ["核心反转：", "误导点：", "设计技巧："]:
        assert generated_marker not in text
    for classic in ["海龟汤", "火车", "牛吃草", "手机", "楼梯"]:
        assert classic in text
    for original_detail in ["門鎖辨識失敗", "牛吃草的聲音", "下樓時我數了階梯"]:
        assert original_detail in text


def test_agent_square_is_packaged_with_agentclaw():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"agent_square/**/*"' in pyproject


def test_agent_square_registry_discovers_turtle_soup_app():
    from agentclaw.agent_square import get_claw_app, list_claw_apps, register_claw_app_workflows
    from agentclaw.api.registry import WorkflowRegistry

    WorkflowRegistry.unregister("turtle_soup")

    apps = list_claw_apps()
    turtle_soup = get_claw_app("turtle_soup")

    assert any(app["id"] == "turtle_soup" for app in apps)
    assert turtle_soup is not None
    assert turtle_soup["name"] == "海龟汤主持人"
    assert turtle_soup["workflow_path"].endswith("agents/turtle_soup.py")
    assert Path(turtle_soup["workflow_path"]).is_file()
    assert turtle_soup["entry"] == "agents/turtle_soup.py"
    assert turtle_soup["registered"] is False

    result = register_claw_app_workflows()
    assert "turtle_soup" in result["registered_workflow_ids"]
    workflow = WorkflowRegistry.get("turtle_soup")
    assert workflow is not None
    assert getattr(workflow, "agent_square_app_id", "") == "turtle_soup"
    assert getattr(workflow, "recommended_input", "") == turtle_soup["recommended_input"]

    registered_app = get_claw_app("turtle_soup")
    assert registered_app is not None
    assert registered_app["registered"] is True


def test_template_import_copies_turtle_soup_into_project(tmp_path):
    from agentclaw.agent_square import get_claw_app_import_status, import_claw_app_to_project

    result = import_claw_app_to_project("turtle_soup", tmp_path)

    target_dir = tmp_path / "agents" / "turtle_soup"
    workflow_file = target_dir / "agents" / "turtle_soup.py"
    agents_init = tmp_path / "agents" / "__init__.py"

    assert result["workflow_id"] == "turtle_soup"
    assert Path(result["target_dir"]) == target_dir
    assert Path(result["workflow_file"]) == workflow_file
    assert workflow_file.is_file()
    assert (target_dir / "data" / "premium_turtle_soups.md").is_file()
    assert agents_init.is_file()
    assert "# AgentClaw template import: turtle_soup" in agents_init.read_text(encoding="utf-8")
    assert "from .turtle_soup.agents.turtle_soup import workflow as turtle_soup_workflow" in agents_init.read_text(encoding="utf-8")

    status = get_claw_app_import_status("turtle_soup", tmp_path)
    assert status["imported"] is True
    assert status["workflow_file"] == str(workflow_file)


def test_agent_square_workflows_use_project_runtime_config(monkeypatch, tmp_path):
    from agentclaw.agent_square import register_claw_app_workflows
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.config import AgentClawConfig, ProjectConfig

    models_path = tmp_path / "models.json"
    mcp_path = tmp_path / "mcp.json"
    skills_dir = tmp_path / "skills"
    models_path.write_text('{"models": []}', encoding="utf-8")
    mcp_path.write_text("{}", encoding="utf-8")
    skills_dir.mkdir()

    previous_config = AgentClawConfig._instance
    AgentClawConfig._instance = AgentClawConfig(
        project=ProjectConfig(
            project_dir=tmp_path,
            skills_dir=skills_dir,
            mcp_config=mcp_path,
            models_config=models_path,
        )
    )

    WorkflowRegistry.unregister("turtle_soup")
    try:
        result = register_claw_app_workflows("turtle_soup")
        workflow = WorkflowRegistry.get("turtle_soup")
    finally:
        WorkflowRegistry.unregister("turtle_soup")
        AgentClawConfig._instance = previous_config

    assert result["failed_apps"] == []
    assert workflow is not None
    assert workflow._models_config == str(models_path)
    assert workflow._mcp_config == str(mcp_path)
    assert workflow._skills_dir == str(skills_dir)

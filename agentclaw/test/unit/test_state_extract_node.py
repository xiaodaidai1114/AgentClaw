import pytest


class FakeLLMResult:
    def __init__(self, content):
        self.content = content


class FakeLLMManager:
    def __init__(self, content):
        self.content = content
        self.messages = None
        self.model_id = None

    async def invoke(self, messages, model_id=None, **params):
        self.messages = messages
        self.model_id = model_id
        return FakeLLMResult(self.content)


class FailingLLMManager:
    def __init__(self):
        self.calls = 0
        self.auto_fallback = True
        self.fallback_threshold = 3
        self.fallback_id = "backup"

    async def invoke(self, messages, model_id=None, **params):
        self.calls += 1
        raise RuntimeError("primary model failed")


@pytest.mark.asyncio
async def test_state_extract_node_supports_simple_usage_and_business_requirements():
    from agentclaw.graph.context import WorkflowContext
    from agentclaw.node import StateExtractNode

    node = StateExtractNode(
        id="extract_vote",
        target_key="pending_action",
        schema={
            "action": {"description": "vote | abstain | unknown", "default": "unknown"},
            "target": {"description": "玩家编号，无法确定时填 null", "default": None},
            "reason": {"description": "用户给出的理由，没有则为空字符串", "default": ""},
        },
        requirements=(
            "target 只能是 1-12 的玩家编号；无法确定时填 null。\n"
            "用户说过、弃票、不投时 action=abstain。"
        ),
        examples=[
            {"input": "投9号", "data": {"action": "vote", "target": 9, "reason": ""}},
            {"input": "弃票", "data": {"action": "abstain", "target": None, "reason": ""}},
        ],
    )

    state = {"user_input": "投9号"}
    context = WorkflowContext(user_input_field="user_input")
    context.llm_manager = FakeLLMManager(
        '{"action": "vote", "target": 9}'
    )

    result = await node.execute(state, context)

    assert result["pending_action"] == {"action": "vote", "target": 9, "reason": ""}
    assert result["extract_vote"] == {"action": "vote", "target": 9, "reason": ""}
    system_prompt = context.llm_manager.messages[0]["content"]
    assert "target 只能是 1-12" in system_prompt
    assert "投9号" in system_prompt
    assert '"action"' in system_prompt
    assert "ok" not in system_prompt
    assert "confidence" not in system_prompt
    assert "missing" not in system_prompt
    assert "ambiguous" not in system_prompt


@pytest.mark.asyncio
async def test_state_extract_node_extracts_text_and_writes_nested_state_paths():
    from agentclaw.graph.context import WorkflowContext
    from agentclaw.node import StateExtractNode

    node = StateExtractNode(
        id="extract_vote",
        source_key="user_input",
        instruction="从用户输入中提取投票动作。",
        fields={
            "action": "vote | abstain | unknown",
            "target": "玩家编号，无法确定时为 null",
            "reason": "理由",
        },
        write_to={
            "pending_action": "$",
            "current_turn.vote_target": "$.target",
        },
        output_key="vote_extract",
    )

    state = {"user_input": "我投9号，因为他发言像狼"}
    context = WorkflowContext()
    context.llm_manager = FakeLLMManager(
        """
        {
          "action": "vote",
          "target": 9,
          "reason": "发言像狼"
        }
        """
    )

    result = await node.execute(state, context)

    assert result["vote_extract"] == {"action": "vote", "target": 9, "reason": "发言像狼"}
    assert result["pending_action"] == {"action": "vote", "target": 9, "reason": "发言像狼"}
    assert result["current_turn"]["vote_target"] == 9
    assert any("JSON" in message["content"] for message in context.llm_manager.messages)


@pytest.mark.asyncio
async def test_state_extract_node_uses_schema_defaults_when_json_is_not_object():
    from agentclaw.graph.context import WorkflowContext
    from agentclaw.node import StateExtractNode

    node = StateExtractNode(
        id="extract_unknown",
        source_key="user_input",
        instruction="提取动作。",
        schema={
            "action": {"description": "动作", "default": "unknown"},
            "target": {"description": "目标", "default": None},
        },
        output_key="extract_result",
    )

    state = {"user_input": "随便吧"}
    context = WorkflowContext()
    context.llm_manager = FakeLLMManager("not json")

    result = await node.execute(state, context)

    assert result["extract_result"] == {"action": "unknown", "target": None}


@pytest.mark.asyncio
async def test_state_extract_target_key_survives_workflow_langgraph_between_nodes():
    from agentclaw.graph import Workflow
    from agentclaw.graph.context import WorkflowContext
    from agentclaw.node import StateExtractNode

    workflow = Workflow(id="state_extract_schema_test", name="State Extract Schema Test")
    workflow.add_node(StateExtractNode(
        id="extract_task",
        target_key="extracted_task",
        schema={
            "intent": {"description": "用户意图", "default": "chat"},
            "target": {"description": "目标", "default": ""},
        },
    ))

    @workflow.node(id="read_target", output_key="reply")
    def read_target(state):
        extracted = state.get("extracted_task") or {}
        return {"reply": f"{extracted.get('intent', '')}:{extracted.get('target', '')}"}

    workflow.add_edge("__start__", "extract_task")
    workflow.add_edge("extract_task", "read_target")
    workflow.add_edge("read_target", "__end__")

    context = WorkflowContext(thread_id="state-extract-schema-test", user_input_field="user_input")
    workflow._llm_manager = FakeLLMManager('{"intent": "remind", "target": "张三"}')
    workflow._components_initialized = True

    result = await workflow.run(
        {"user_input": "提醒张三"},
        context,
        thread_id="state-extract-schema-test",
    )
    state = result.get("state", result)

    assert state["extract_task"] == {"intent": "remind", "target": "张三"}
    assert state["extracted_task"] == {"intent": "remind", "target": "张三"}
    assert state["reply"] == "remind:张三"


@pytest.mark.asyncio
async def test_state_extract_node_does_not_force_zero_threshold_fallback():
    from agentclaw.graph.context import WorkflowContext
    from agentclaw.node import StateExtractNode

    node = StateExtractNode(
        id="extract_task",
        source_key="user_input",
        schema={
            "intent": {"description": "用户意图", "default": "chat"},
        },
    )
    context = WorkflowContext()
    context.llm_manager = FailingLLMManager()

    with pytest.raises(Exception, match="primary model failed"):
        await node.execute({"user_input": "提醒我"}, context)

    assert context.llm_manager.calls == 1

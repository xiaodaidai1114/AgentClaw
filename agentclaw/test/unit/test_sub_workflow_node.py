import pytest
import time


def _extract_state(result):
    return result.get("state", result)


def _build_echo_child_workflow():
    from agentclaw import Workflow

    child = Workflow(id="child_echo", name="Child Echo", tracing=False)

    @child.node(id="answer", output_fields=["answer"])
    async def answer(state, context):
        return {
            "answer": f"{state.get('query')}:{context.thread_id}",
        }

    child.add_edge("__start__", "answer")
    child.add_edge("answer", "__end__")
    return child


@pytest.mark.asyncio
async def test_workflow_builtin_direct_conditional_list_runs_targets_in_parallel():
    import asyncio
    from agentclaw import Workflow
    from agentclaw.graph.context import WorkflowContext

    starts = {}
    parent = Workflow(id="parent_builtin_dynamic_parallel", name="Parent Builtin Dynamic Parallel", tracing=False)
    parent.register_state_field("route", str)
    parent.register_state_field("a_done", bool)
    parent.register_state_field("b_done", bool)

    @parent.node(id="start", output_to_user=False)
    def start(state):
        return {"route": "both"}

    @parent.node(id="a", output_to_user=False)
    async def a(state):
        starts["a"] = time.perf_counter()
        await asyncio.sleep(0.2)
        return {"a_done": True}

    @parent.node(id="b", output_to_user=False)
    async def b(state):
        starts["b"] = time.perf_counter()
        await asyncio.sleep(0.2)
        return {"b_done": True}

    @parent.node(id="join", output_to_user=False)
    def join(state):
        return {"joined": True}

    parent.add_edge("__start__", "start")
    parent.add_conditional_edge("start", lambda state: ["a", "b"])
    parent.add_edge("a", "join")
    parent.add_edge("b", "join")
    parent.add_edge("join", "__end__")

    begin = time.perf_counter()
    result = await parent.run({}, WorkflowContext())
    elapsed = time.perf_counter() - begin
    state = _extract_state(result)

    assert state["a_done"] is True
    assert state["b_done"] is True
    assert state["joined"] is True
    assert abs(starts["a"] - starts["b"]) < 0.08
    assert elapsed < 0.35


@pytest.mark.asyncio
async def test_sub_workflow_node_can_hide_child_runtime_events_from_parent_stream():
    from agentclaw import SubWorkflowNode, Workflow
    from agentclaw.graph.context import WorkflowContext
    from agentclaw.runtime.streaming.context import OutputChannel

    child = Workflow(id="child_hidden_events", name="Child Hidden Events", tracing=False)

    @child.node(id="child_step_one", output_to_user=False)
    def child_step_one(state):
        return {"mid": "ok"}

    @child.node(id="child_step_two", output_to_user=False)
    def child_step_two(state):
        return {"answer": state.get("mid")}

    child.add_edge("__start__", "child_step_one")
    child.add_edge("child_step_one", "child_step_two")
    child.add_edge("child_step_two", "__end__")

    parent = Workflow(id="parent_hidden_child_events", name="Parent Hidden Child Events", tracing=False)
    parent.add_node(SubWorkflowNode(
        id="call_child",
        workflow=child,
        output_map={"answer": "child_answer"},
        stream_child_events=False,
    ))
    parent.add_edge("__start__", "call_child")
    parent.add_edge("call_child", "__end__")

    async with OutputChannel(workflow_id=parent.id, thread_id="parent-hidden-events", stream_mode=True) as channel:
        result = await parent.run(
            {},
            WorkflowContext(thread_id="parent-hidden-events"),
            thread_id="parent-hidden-events",
        )
        events = []
        while not channel.queue.empty():
            events.append(await channel.queue.get())

    state = _extract_state(result)
    node_events = [
        event.get("data", {}).get("node_id")
        for event in events
        if event.get("event") in {"node_started", "node_finished"}
    ]

    assert state["child_answer"] == "ok"
    assert "call_child" in node_events
    assert "child_step_one" not in node_events
    assert "child_step_two" not in node_events


@pytest.mark.asyncio
async def test_sub_workflow_node_keeps_legacy_input_and_output_map_usage():
    from agentclaw import SubWorkflowNode, Workflow
    from agentclaw.graph.context import WorkflowContext

    child = _build_echo_child_workflow()
    parent = Workflow(id="parent_legacy", name="Parent Legacy", tracing=False)
    parent.add_node(SubWorkflowNode(
        id="call_child",
        workflow=child,
        input_map={"query": "user_input"},
        output_map={"answer": "sub_answer"},
    ))
    parent.add_edge("__start__", "call_child")
    parent.add_edge("call_child", "__end__")

    result = await parent.run(
        {"user_input": "hello"},
        WorkflowContext(thread_id="parent-thread", user_id="u1"),
    )
    state = _extract_state(result)

    assert state["sub_answer"] == "hello:parent-thread"
    assert state["__call_child_metadata__"]["sub_workflow_id"] == "child_echo"


@pytest.mark.asyncio
async def test_sub_workflow_node_supports_nested_output_paths_and_derived_thread_id():
    from agentclaw import SubWorkflowNode, Workflow
    from agentclaw.graph.context import WorkflowContext

    child = _build_echo_child_workflow()
    parent = Workflow(id="parent_nested", name="Parent Nested", tracing=False)
    parent.add_node(SubWorkflowNode(
        id="call_p7",
        workflow=child,
        instance_id="p7",
        thread_id_strategy="derived",
        input_map={"query": "current_request.text"},
        output_map={"answer": "actor_outputs.p7.answer"},
    ))
    parent.add_edge("__start__", "call_p7")
    parent.add_edge("call_p7", "__end__")

    result = await parent.run(
        {"current_request": {"text": "speak"}},
        WorkflowContext(thread_id="game-1", user_id="u1"),
    )
    state = _extract_state(result)

    assert state["actor_outputs"]["p7"]["answer"] == "speak:game-1:actor:p7"


@pytest.mark.asyncio
async def test_sub_workflow_node_maps_private_child_state_back_to_parent_state():
    from agentclaw import SubWorkflowNode, Workflow
    from agentclaw.graph.context import WorkflowContext

    child = Workflow(id="child_memory", name="Child Memory", tracing=False)

    @child.node(id="remember", output_fields=["memory", "summary"])
    def remember(state):
        memory = dict(state.get("memory") or {})
        public_log = list(state.get("public_log") or [])
        memory["seen"] = public_log[-1] if public_log else ""
        return {
            "memory": memory,
            "summary": f"memory:{memory['seen']}",
        }

    child.add_edge("__start__", "remember")
    child.add_edge("remember", "__end__")

    parent = Workflow(id="parent_memory", name="Parent Memory", tracing=False)
    parent.add_node(SubWorkflowNode(
        id="call_p7_memory",
        workflow=child,
        instance_id="p7",
        readonly_input_map={"public_log": "public_log"},
        state_map={"memory": "actors.p7.memory"},
        output_map={"summary": "actor_outputs.p7.summary"},
    ))
    parent.add_edge("__start__", "call_p7_memory")
    parent.add_edge("call_p7_memory", "__end__")

    result = await parent.run(
        {
            "public_log": ["day starts", "p3 spoke"],
            "actors": {"p7": {"memory": {"trust": {"p3": 1}}}},
        },
        WorkflowContext(thread_id="game-2"),
    )
    state = _extract_state(result)

    assert state["actors"]["p7"]["memory"] == {
        "trust": {"p3": 1},
        "seen": "p3 spoke",
    }
    assert state["actor_outputs"]["p7"]["summary"] == "memory:p3 spoke"


@pytest.mark.asyncio
async def test_sub_workflow_node_uses_merge_strategy_for_state_map_writeback():
    from agentclaw import SubWorkflowNode, Workflow
    from agentclaw.graph.context import WorkflowContext

    child = Workflow(id="child_merge", name="Child Merge", tracing=False)

    @child.node(id="patch_memory", output_fields=["memory"])
    def patch_memory(state):
        return {"memory": {"nested": {"b": 2}, "new": 3}}

    child.add_edge("__start__", "patch_memory")
    child.add_edge("patch_memory", "__end__")

    parent = Workflow(id="parent_merge", name="Parent Merge", tracing=False)
    parent.add_node(SubWorkflowNode(
        id="call_merge",
        workflow=child,
        state_map={"memory": "actors.p7.memory"},
        merge_strategy={"memory": "deep_merge"},
    ))
    parent.add_edge("__start__", "call_merge")
    parent.add_edge("call_merge", "__end__")

    result = await parent.run(
        {"actors": {"p7": {"memory": {"old": 1, "nested": {"a": 1}}}}},
        WorkflowContext(thread_id="game-3"),
    )
    state = _extract_state(result)

    assert state["actors"]["p7"]["memory"] == {
        "old": 1,
        "nested": {"a": 1, "b": 2},
        "new": 3,
    }


@pytest.mark.asyncio
async def test_sub_workflow_node_can_call_same_child_workflow_as_isolated_instances():
    from agentclaw import SubWorkflowNode, Workflow
    from agentclaw.graph.context import WorkflowContext

    child = Workflow(id="child_actor", name="Child Actor", tracing=False)

    @child.node(id="act", output_fields=["memory", "action"])
    async def act(state, context):
        memory = dict(state.get("memory") or {})
        memory["thread_id"] = context.thread_id
        return {
            "memory": memory,
            "action": {
                "actor": state.get("actor_id"),
                "thread_id": context.thread_id,
            },
        }

    child.add_edge("__start__", "act")
    child.add_edge("act", "__end__")

    parent = Workflow(id="parent_instances", name="Parent Instances", tracing=False)
    parent.add_node(SubWorkflowNode(
        id="call_p1",
        workflow=child,
        instance_id="p1",
        thread_id_strategy="derived",
        readonly_input_map={"actor_id": "requests.p1.actor_id"},
        state_map={"memory": "actors.p1.memory"},
        output_map={"action": "actor_outputs.p1.action"},
    ))
    parent.add_node(SubWorkflowNode(
        id="call_p2",
        workflow=child,
        instance_id="p2",
        thread_id_strategy="derived",
        readonly_input_map={"actor_id": "requests.p2.actor_id"},
        state_map={"memory": "actors.p2.memory"},
        output_map={"action": "actor_outputs.p2.action"},
    ))
    parent.add_edge("__start__", "call_p1")
    parent.add_edge("call_p1", "call_p2")
    parent.add_edge("call_p2", "__end__")

    result = await parent.run(
        {
            "requests": {
                "p1": {"actor_id": "p1"},
                "p2": {"actor_id": "p2"},
            },
            "actors": {
                "p1": {"memory": {"seed": 1}},
                "p2": {"memory": {"seed": 2}},
            },
        },
        WorkflowContext(thread_id="game-4"),
    )
    state = _extract_state(result)

    assert state["actors"]["p1"]["memory"]["thread_id"] == "game-4:actor:p1"
    assert state["actors"]["p2"]["memory"]["thread_id"] == "game-4:actor:p2"
    assert state["actor_outputs"]["p1"]["action"] == {
        "actor": "p1",
        "thread_id": "game-4:actor:p1",
    }
    assert state["actor_outputs"]["p2"]["action"] == {
        "actor": "p2",
        "thread_id": "game-4:actor:p2",
    }


@pytest.mark.asyncio
async def test_sub_workflow_node_nested_parallel_outputs_are_deep_merged():
    from agentclaw import SubWorkflowNode, Workflow
    from agentclaw.graph.context import WorkflowContext

    child = Workflow(id="child_parallel_actor", name="Child Parallel Actor", tracing=False)

    @child.node(id="act", output_fields=["action"])
    async def act(state, context):
        actor_id = state.get("actor_id")
        return {
            "action": {
                "actor": actor_id,
                "thread_id": context.thread_id,
            },
        }

    child.add_edge("__start__", "act")
    child.add_edge("act", "__end__")

    parent = Workflow(id="parent_parallel_instances", name="Parent Parallel Instances", tracing=False)
    parent.register_state_field("requests", dict)
    parent.add_node(SubWorkflowNode(
        id="call_p1_parallel",
        workflow=child,
        instance_id="p1",
        thread_id_strategy="derived",
        readonly_input_map={"actor_id": "requests.p1.actor_id"},
        output_map={"action": "actor_outputs.p1.action"},
    ))
    parent.add_node(SubWorkflowNode(
        id="call_p2_parallel",
        workflow=child,
        instance_id="p2",
        thread_id_strategy="derived",
        readonly_input_map={"actor_id": "requests.p2.actor_id"},
        output_map={"action": "actor_outputs.p2.action"},
    ))
    parent.add_edge("__start__", ["call_p1_parallel", "call_p2_parallel"])

    result = await parent.run(
        {
            "requests": {
                "p1": {"actor_id": "p1"},
                "p2": {"actor_id": "p2"},
            },
        },
        WorkflowContext(thread_id="game-5"),
        thread_id="game-5",
    )
    state = _extract_state(result)

    assert state["actor_outputs"]["p1"]["action"] == {
        "actor": "p1",
        "thread_id": "game-5:actor:p1",
    }
    assert state["actor_outputs"]["p2"]["action"] == {
        "actor": "p2",
        "thread_id": "game-5:actor:p2",
    }


@pytest.mark.asyncio
async def test_sub_workflow_node_parallel_outputs_are_merged_in_builtin_engine():
    from agentclaw import SubWorkflowNode, Workflow
    from agentclaw.graph.context import WorkflowContext

    child = Workflow(id="child_builtin_parallel_actor", name="Child Builtin Parallel Actor", tracing=False)

    @child.node(id="act", output_fields=["action"])
    async def act(state, context):
        actor_id = state.get("actor_id")
        return {
            "action": {
                "actor": actor_id,
                "thread_id": context.thread_id,
            },
        }

    child.add_edge("__start__", "act")
    child.add_edge("act", "__end__")

    parent = Workflow(id="parent_builtin_parallel_instances", name="Parent Builtin Parallel Instances", tracing=False)
    parent.register_state_field("requests", dict)
    parent.add_node(SubWorkflowNode(
        id="call_p1_builtin_parallel",
        workflow=child,
        instance_id="p1",
        thread_id_strategy="derived",
        readonly_input_map={"actor_id": "requests.p1.actor_id"},
        output_map={"action": "actor_outputs.p1.action"},
    ))
    parent.add_node(SubWorkflowNode(
        id="call_p2_builtin_parallel",
        workflow=child,
        instance_id="p2",
        thread_id_strategy="derived",
        readonly_input_map={"actor_id": "requests.p2.actor_id"},
        output_map={"action": "actor_outputs.p2.action"},
    ))
    parent.add_edge("__start__", ["call_p1_builtin_parallel", "call_p2_builtin_parallel"])

    result = await parent.run(
        {
            "requests": {
                "p1": {"actor_id": "p1"},
                "p2": {"actor_id": "p2"},
            },
        },
        WorkflowContext(thread_id="game-6"),
    )
    state = _extract_state(result)

    assert state["actor_outputs"]["p1"]["action"] == {
        "actor": "p1",
        "thread_id": "game-6:actor:p1",
    }
    assert state["actor_outputs"]["p2"]["action"] == {
        "actor": "p2",
        "thread_id": "game-6:actor:p2",
    }


@pytest.mark.asyncio
async def test_sub_workflow_node_can_call_workflow_instantiated_from_template():
    from agentclaw import BaseNode, SubWorkflowNode, Workflow, WorkflowTemplate
    from agentclaw.graph.context import WorkflowContext

    class TemplateActorNode(BaseNode):
        def __init__(self, id, *, actor_label="", output_key=None):
            super().__init__(id=id, output_key=output_key)
            self.actor_label = actor_label

        async def _do_execute(self, state, context):
            memory = dict(state.get("memory") or {})
            memory["label"] = self.actor_label
            memory["thread_id"] = context.thread_id
            state["memory"] = memory
            state[self.get_output_key()] = {
                "label": self.actor_label,
                "topic": state.get("topic"),
                "thread_id": context.thread_id,
            }
            return state

    template = WorkflowTemplate(
        id="template_actor",
        name="{actor_id} actor template",
        variables={"actor_id": "p1", "actor_label": "1号"},
    )
    template.add_node(TemplateActorNode(
        id="{actor_id}__act",
        actor_label="{actor_label}",
        output_key="action",
    ))
    template.add_edge("__start__", "{actor_id}__act")
    template.add_edge("{actor_id}__act", "__end__")

    actor_workflow = template.instantiate(
        id="template_actor_p7",
        name="7号角色子工作流",
        variables={"actor_id": "p7", "actor_label": "7号"},
        tracing=False,
    )

    parent = Workflow(id="parent_template_actor", name="Parent Template Actor", tracing=False)
    parent.register_state_field("requests", dict)
    parent.add_node(SubWorkflowNode(
        id="call_template_p7",
        workflow=actor_workflow,
        instance_id="p7",
        thread_id_strategy="derived",
        readonly_input_map={"topic": "requests.p7.topic"},
        state_map={"memory": "actors.p7.memory"},
        output_map={"action": "actor_outputs.p7.action"},
    ))
    parent.add_edge("__start__", "call_template_p7")
    parent.add_edge("call_template_p7", "__end__")

    result = await parent.run(
        {"requests": {"p7": {"topic": "模板生成的角色子工作流"}}},
        WorkflowContext(thread_id="game-7"),
    )
    state = _extract_state(result)

    assert state["actors"]["p7"]["memory"] == {
        "label": "7号",
        "thread_id": "game-7:actor:p7",
    }
    assert state["actor_outputs"]["p7"]["action"] == {
        "label": "7号",
        "topic": "模板生成的角色子工作流",
        "thread_id": "game-7:actor:p7",
    }


def _build_child_workflow_with_human_node():
    from agentclaw import HumanNode, Input, Workflow

    child = Workflow(
        id="child_human_review",
        name="Child Human Review",
        inputs=[
            Input("human_feedback", str, required=False, description="Human feedback for the child workflow"),
        ],
        user_input="human_feedback",
        tracing=False,
    )
    child.add_node(HumanNode(
        id="ask_human",
        feedback_field="human_feedback",
        output_to_user=False,
    ))

    @child.node(id="finish_review", output_fields=["answer", "memory"])
    def finish_review(state):
        memory = dict(state.get("memory") or {})
        memory["feedback"] = state.get("human_feedback")
        return {
            "memory": memory,
            "answer": f"child received: {state.get('human_feedback')}",
        }

    child.add_edge("__start__", "ask_human")
    child.add_edge("ask_human", "finish_review")
    child.add_edge("finish_review", "__end__")
    return child


@pytest.mark.asyncio
async def test_sub_workflow_node_propagates_child_human_interrupt_to_parent():
    from agentclaw import Input, SubWorkflowNode, Workflow
    from agentclaw.graph.context import WorkflowContext

    child = _build_child_workflow_with_human_node()
    parent = Workflow(
        id="parent_child_human_interrupt",
        name="Parent Child Human Interrupt",
        inputs=[
            Input("user_input", str, required=False, description="User feedback for child workflow"),
        ],
        user_input="user_input",
        tracing=False,
    )
    parent.add_node(SubWorkflowNode(
        id="call_child_human",
        workflow=child,
        instance_id="p7",
        thread_id_strategy="derived",
        state_map={"memory": "actors.p7.memory"},
        output_map={"answer": "actor_outputs.p7.answer"},
    ))
    parent.add_edge("__start__", "call_child_human")
    parent.add_edge("call_child_human", "__end__")

    result = await parent.run(
        {"actors": {"p7": {"memory": {"seed": 1}}}},
        WorkflowContext(thread_id="human-parent-1", user_input_field="user_input"),
        thread_id="human-parent-1",
    )
    state = _extract_state(result)

    assert state["__interrupted__"] is True
    assert state["__status__"] == "waiting_for_input"
    assert state["__interrupt_info__"]["node"] == "ask_human"
    assert state["__subworkflow_interrupt__"] == {
        "node_id": "call_child_human",
        "sub_workflow_id": "child_human_review",
        "thread_id": "human-parent-1:actor:p7",
        "input_field": "human_feedback",
    }


@pytest.mark.asyncio
async def test_sub_workflow_node_resumes_interrupted_child_workflow_from_parent_input():
    from agentclaw import Input, SubWorkflowNode, Workflow
    from agentclaw.graph.context import WorkflowContext

    child = _build_child_workflow_with_human_node()
    parent = Workflow(
        id="parent_child_human_resume",
        name="Parent Child Human Resume",
        inputs=[
            Input("user_input", str, required=False, description="User feedback for child workflow"),
        ],
        user_input="user_input",
        tracing=False,
    )
    parent.add_node(SubWorkflowNode(
        id="call_child_human",
        workflow=child,
        instance_id="p7",
        thread_id_strategy="derived",
        state_map={"memory": "actors.p7.memory"},
        output_map={"answer": "actor_outputs.p7.answer"},
    ))
    parent.add_edge("__start__", "call_child_human")
    parent.add_edge("call_child_human", "__end__")

    context = WorkflowContext(thread_id="human-parent-2", user_input_field="user_input")
    first = await parent.run(
        {"actors": {"p7": {"memory": {"seed": 1}}}},
        context,
        thread_id="human-parent-2",
    )
    first_state = _extract_state(first)
    assert first_state["__interrupted__"] is True

    second = await parent.run(
        {"user_input": "同意这个子流程结果"},
        context,
        thread_id="human-parent-2",
    )
    second_state = _extract_state(second)

    assert second_state.get("__interrupted__") is not True
    assert second_state["actors"]["p7"]["memory"] == {
        "seed": 1,
        "feedback": "同意这个子流程结果",
    }
    assert second_state["actor_outputs"]["p7"]["answer"] == "child received: 同意这个子流程结果"


@pytest.mark.asyncio
async def test_sub_workflow_node_builtin_parent_returns_child_interrupt_without_recursing():
    from agentclaw import Input, SubWorkflowNode, Workflow
    from agentclaw.graph.context import WorkflowContext

    child = _build_child_workflow_with_human_node()
    parent = Workflow(
        id="parent_child_human_builtin_interrupt",
        name="Parent Child Human Builtin Interrupt",
        inputs=[
            Input("user_input", str, required=False, description="User feedback for child workflow"),
        ],
        user_input="user_input",
        tracing=False,
    )
    parent._checkpointer_initialized = True
    parent._checkpointer = None
    parent.add_node(SubWorkflowNode(
        id="call_child_human",
        workflow=child,
        instance_id="p7",
        thread_id_strategy="derived",
        state_map={"memory": "actors.p7.memory"},
        output_map={"answer": "actor_outputs.p7.answer"},
    ))
    parent.add_edge("__start__", "call_child_human")
    parent.add_edge("call_child_human", "__end__")

    result = await parent.run(
        {"actors": {"p7": {"memory": {"seed": 1}}}},
        WorkflowContext(thread_id="human-parent-builtin", user_input_field="user_input"),
        thread_id="human-parent-builtin",
    )
    state = _extract_state(result)

    assert state["__interrupted__"] is True
    assert state["__status__"] == "waiting_for_input"
    assert state["__interrupt_info__"]["node"] == "ask_human"
    assert state["__subworkflow_interrupt__"] == {
        "node_id": "call_child_human",
        "sub_workflow_id": "child_human_review",
        "thread_id": "human-parent-builtin:actor:p7",
        "input_field": "human_feedback",
    }

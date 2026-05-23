from __future__ import annotations

import pytest

from agentclaw.node.human import HumanInput, HumanNode, normalize_input_modes


def test_human_input_button_defaults_value_to_label():
    modes = normalize_input_modes([HumanInput.button("上警")])

    assert modes == [
        {
            "type": "button",
            "label": "上警",
            "value": "上警",
            "confirm": False,
        }
    ]


def test_human_input_button_uses_explicit_value():
    modes = normalize_input_modes([HumanInput.button("袭击 9 号", value=9)])

    assert modes == [
        {
            "type": "button",
            "label": "袭击 9 号",
            "value": 9,
            "confirm": False,
        }
    ]


def test_human_input_text_and_button_modes_are_explicit():
    modes = normalize_input_modes([
        HumanInput.text(placeholder="请输入发言"),
        HumanInput.button("自爆"),
    ])

    assert modes == [
        {
            "type": "text",
            "placeholder": "请输入发言",
        },
        {
            "type": "button",
            "label": "自爆",
            "value": "自爆",
            "confirm": False,
        },
    ]


def test_human_node_structured_button_resume_writes_value_to_feedback_field():
    node = HumanNode(id="sheriff_campaign", feedback_field="sheriff_choice")
    state = {}

    node._process_resume_input(state, {
        "__human_input__": {
            "kind": "button",
            "label": "上警",
            "value": "join",
            "field": "sheriff_choice",
        }
    })

    assert state["sheriff_choice"] == "join"
    assert state["__human_input__"] == {
        "kind": "button",
        "label": "上警",
        "value": "join",
        "field": "sheriff_choice",
    }
    assert state["status"] == "completed"


def test_human_node_approval_mode_normalizes_legacy_buttons_when_no_input_modes():
    node = HumanNode(id="review", feedback_field="feedback", approval_mode=True)

    assert normalize_input_modes(node.input_modes, approval_mode=node.approval_mode) == [
        {
            "type": "text",
            "placeholder": None,
        },
        {
            "type": "button",
            "label": "通过",
            "value": "approve",
            "confirm": False,
        },
        {
            "type": "button",
            "label": "驳回",
            "value": "reject",
            "confirm": False,
        },
    ]


def test_human_node_supports_false_button_values():
    node = HumanNode(id="review", feedback_field="approved")
    state = {}

    node._process_resume_input(state, {
        "__human_input__": {
            "kind": "button",
            "label": "驳回",
            "value": False,
            "field": "approved",
        }
    })

    assert state["approved"] is False
    assert state["status"] == "completed"


def test_human_node_interrupt_payload_includes_input_modes():
    node = HumanNode(
        id="sheriff_campaign",
        feedback_field="sheriff_choice",
        input_modes=[
            HumanInput.button("上警"),
            HumanInput.button("不上警"),
        ],
    )

    assert node.build_interrupt_payload({}) == {
        "node": "sheriff_campaign",
        "waiting_for": "sheriff_choice",
        "__messages__": [],
        "status": "waiting_for_input",
        "input_modes": [
            {
                "type": "button",
                "label": "上警",
                "value": "上警",
                "confirm": False,
            },
            {
                "type": "button",
                "label": "不上警",
                "value": "不上警",
                "confirm": False,
            },
        ],
    }


def test_human_node_interrupt_payload_accepts_state_based_input_modes():
    node = HumanNode(
        id="night_target",
        feedback_field="user_input",
        input_modes=lambda state: [
            HumanInput.button(f"{seat}号", value=f"{seat}号")
            for seat in state["targets"]
        ],
    )

    assert node.build_interrupt_payload({"targets": [3, 7]})["input_modes"] == [
        {
            "type": "button",
            "label": "3号",
            "value": "3号",
            "confirm": False,
        },
        {
            "type": "button",
            "label": "7号",
            "value": "7号",
            "confirm": False,
        },
    ]


def test_workflow_resume_value_preserves_button_value_without_stringifying():
    from agentclaw.graph.workflow import Workflow

    workflow = Workflow(id="human_resume_value", name="Human Resume Value")
    resume_value = workflow._build_human_resume_value({"approved": False}, "approved")

    assert resume_value is False


def test_workflow_resume_value_accepts_structured_human_input():
    from agentclaw.graph.workflow import Workflow

    workflow = Workflow(id="human_resume_structured", name="Human Resume Structured")
    resume_value = workflow._build_human_resume_value({
        "sheriff_choice": "join",
        "__human_input__": {
            "kind": "button",
            "label": "上警",
            "value": "join",
            "field": "sheriff_choice",
        },
    }, "user_input")

    assert resume_value == {
        "__human_input__": {
            "kind": "button",
            "label": "上警",
            "value": "join",
            "field": "sheriff_choice",
        }
    }


@pytest.mark.asyncio
async def test_human_node_processes_false_resume_value_from_langgraph(monkeypatch):
    from agentclaw.graph.context import WorkflowContext
    import langgraph.types

    monkeypatch.setattr(langgraph.types, "interrupt", lambda _payload: False)

    node = HumanNode(id="review", feedback_field="approved")
    state = {}

    await node._do_execute(state, WorkflowContext())

    assert state["approved"] is False
    assert state["status"] == "completed"


@pytest.mark.asyncio
async def test_human_node_builtin_resume_accepts_false_feedback_value(monkeypatch):
    from agentclaw.graph.context import WorkflowContext
    import langgraph.types

    def raise_outside_context(_payload):
        raise RuntimeError("get_config called outside runnable context")

    monkeypatch.setattr(langgraph.types, "interrupt", raise_outside_context)

    node = HumanNode(id="review", feedback_field="approved")
    state = {"approved": False}

    await node._do_execute(state, WorkflowContext())

    assert state["approved"] is False
    assert state["status"] == "completed"

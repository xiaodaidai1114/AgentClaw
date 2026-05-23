def test_demo2_human_input_modes_demo_is_registered_with_expected_modes():
    from demo2.agents.human_input_modes_demo import workflow

    collect = workflow.get_node("collect_message")
    choose = workflow.get_node("choose_result")

    assert workflow.id == "human_input_modes_demo"
    assert workflow.get_user_input_field() == "demo_start"
    assert collect.feedback_field == "demo_message"
    assert collect.input_modes[0].type == "text"
    assert collect.input_modes[1].label == "跳过发言"
    assert collect.input_modes[1].value == {"kind": "skip_speech"}
    assert choose.feedback_field == "demo_choice"
    assert [mode.label for mode in choose.input_modes] == ["同意", "拒绝", "再考虑"]
    assert [mode.value for mode in choose.input_modes] == [True, False, "pending"]


def test_demo2_human_input_modes_demo_structure_exposes_human_modes():
    from demo2.agents.human_input_modes_demo import workflow

    structure = workflow.get_structure()
    collect = next(node for node in structure["nodes"] if node["id"] == "collect_message")
    choose = next(node for node in structure["nodes"] if node["id"] == "choose_result")

    assert collect["interrupt"] is True
    assert collect["feedback_field"] == "demo_message"
    assert choose["interrupt"] is True
    assert choose["feedback_field"] == "demo_choice"


def test_demo2_multi_role_review_demo_tracing_is_enabled_for_stats():
    from demo2.agents.multi_role_review_demo import (
        architecture_workflow,
        product_workflow,
        risk_workflow,
        workflow,
    )

    assert workflow.id == "multi_role_review_demo"
    assert workflow.tracing is True
    assert architecture_workflow.tracing is True
    assert product_workflow.tracing is True
    assert risk_workflow.tracing is True


def test_demo2_subworkflow_demo_tracing_is_enabled_for_stats():
    from demo2.agents.subworkflow_demo import actor_workflow, workflow

    assert workflow.id == "subworkflow_demo"
    assert workflow.tracing is True
    assert actor_workflow.tracing is True

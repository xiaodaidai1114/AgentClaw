import pytest


def test_workflow_template_instantiates_plain_workflow_with_rendered_node_fields():
    from agentclaw import LLMNode, Workflow, WorkflowTemplate
    from agentclaw.graph import WorkflowTemplate as GraphWorkflowTemplate

    assert GraphWorkflowTemplate is WorkflowTemplate

    template = WorkflowTemplate(
        id="player_template",
        name="Player Template",
        variables={
            "actor_id": "p1",
            "role_prompt": "你是1号玩家。",
        },
    )

    template.add_node(LLMNode(
        id="{actor_id}__speak",
        system_prompt="{role_prompt}",
        user_prompt="公开信息：{public_log}",
        output_key="{actor_id}_speech",
        model_id="{model_id}",
    ))
    template.add_node(LLMNode(
        id="{actor_id}__summarize",
        system_prompt="总结 {actor_id} 的发言",
        user_prompt="{{{actor_id}_speech}}",
        output_key="{actor_id}_summary",
    ))
    template.add_edge("__start__", "{actor_id}__speak")
    template.add_edge("{actor_id}__speak", "{actor_id}__summarize")
    template.add_edge("{actor_id}__summarize", "__end__")

    workflow = template.instantiate(
        id="player_p7",
        name="Player 7",
        variables={
            "actor_id": "p7",
            "role_prompt": "你是7号玩家。",
            "model_id": "fast",
        },
    )

    assert isinstance(workflow, Workflow)
    assert workflow.id == "player_p7"
    assert workflow.name == "Player 7"

    speak = workflow.get_node("p7__speak")
    summarize = workflow.get_node("p7__summarize")
    assert speak.system_prompt == "你是7号玩家。"
    assert speak.user_prompt == "公开信息：{public_log}"
    assert speak.output_key == "p7_speech"
    assert speak.model_id == "fast"
    assert summarize.user_prompt == "{p7_speech}"

    structure = workflow.get_structure()
    assert {"source": "__start__", "target": "p7__speak", "type": "normal"} in structure["edges"]
    assert {"source": "p7__speak", "target": "p7__summarize", "type": "normal"} in structure["edges"]


def test_workflow_template_rejects_missing_variables():
    from agentclaw import LLMNode, WorkflowTemplate

    template = WorkflowTemplate(id="missing_var_template", name="Missing Var")
    template.add_node(LLMNode(id="{actor_id}__speak", system_prompt="{role_prompt}"))

    with pytest.raises(KeyError, match="role_prompt"):
        template.instantiate(
            id="bad_instance",
            variables={"actor_id": "p1"},
        )

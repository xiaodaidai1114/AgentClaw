from pathlib import Path


def test_workflow_model_config_discovery_includes_global_project_dir(monkeypatch, tmp_path):
    from agentclaw.config import AgentClawConfig, ProjectConfig
    from agentclaw.graph.workflow import Workflow

    project_dir = tmp_path / "demo_project"
    nested_workflow_dir = project_dir / "agents" / "ai_werewolf" / "agents"
    project_dir.mkdir()
    nested_workflow_dir.mkdir(parents=True)
    models_path = project_dir / "models.json"
    models_path.write_text('{"models": []}', encoding="utf-8")

    previous_config = AgentClawConfig._instance
    AgentClawConfig._instance = AgentClawConfig(
        project=ProjectConfig(
            project_dir=project_dir,
            models_config=models_path,
        )
    )
    try:
        workflow = Workflow(id="nested_template", name="Nested Template")
        monkeypatch.setattr(workflow, "_definition_file", nested_workflow_dir / "werewolf.py")

        assert workflow._find_models_config_path() == models_path.resolve()
    finally:
        AgentClawConfig._instance = previous_config


def test_workflow_treats_legacy_examples_path_as_framework_internal():
    from agentclaw.graph.workflow import Workflow

    legacy_example_file = Path(__file__).resolve().parents[2] / "examples" / "agents" / "hello_world.py"

    assert Workflow._is_framework_internal_file(legacy_example_file) is True


def test_workflow_default_recursion_limit_is_unlimited_at_agentclaw_layer():
    from agentclaw.graph.workflow import Workflow

    workflow = Workflow(id="default_recursion", name="Default Recursion")

    assert workflow.recursion_limit == 0


def test_workflow_langgraph_config_maps_unlimited_to_large_runtime_limit():
    from agentclaw.graph.workflow import Workflow

    workflow = Workflow(id="unlimited_recursion", name="Unlimited Recursion", recursion_limit=0)
    config = workflow._build_langgraph_config("thread-1")

    assert config["configurable"] == {"thread_id": "thread-1"}
    assert config["recursion_limit"] >= 1_000_000


def test_workflow_langgraph_config_includes_positive_recursion_limit():
    from agentclaw.graph.workflow import Workflow

    workflow = Workflow(id="limited_recursion", name="Limited Recursion", recursion_limit=80)
    config = workflow._build_langgraph_config("thread-1")

    assert config["recursion_limit"] == 80

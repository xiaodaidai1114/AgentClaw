import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_SQUARE_DIR = PROJECT_ROOT / "agentclaw" / "agent_square"

EXAMPLE_TEMPLATE_IDS = {
    "hello_world",
    "router",
    "tool_agent",
    "approval",
    "parallel",
    "gif_agent",
    "mcp_agent",
    "custom_demo",
    "weekly_report",
    "doc_analyzer",
    "kb_rag",
}


def test_example_workflows_are_packaged_as_template_library_apps():
    from agentclaw.agent_square import get_claw_app, list_claw_apps

    apps = {app["id"]: app for app in list_claw_apps()}

    assert EXAMPLE_TEMPLATE_IDS.issubset(apps)
    assert "smart_agent" not in apps
    for app_id in EXAMPLE_TEMPLATE_IDS:
        app = get_claw_app(app_id)
        assert app is not None, app_id
        assert app["category"] == "example"
        assert app["copyable"] is True
        assert app["inspectable"] is True
        assert app["recommended_input"]
        assert app["workflow_id"]
        assert Path(app["workflow_path"]).is_file()
        assert Path(app["entry_path"]).is_file()
        assert "示例" in app["tags"] or "Example" in app["tags"]
        assert not (Path(app["app_dir"]) / "server.py").exists()
        assert not (Path(app["app_dir"]) / "models.json").exists()
        assert not (Path(app["app_dir"]) / ".env").exists()


def test_legacy_examples_project_has_been_removed():
    assert not (PROJECT_ROOT / "agentclaw" / "examples").exists()


def test_example_template_manifests_have_unique_workflow_ids():
    workflow_ids: dict[str, str] = {}
    for manifest_path in AGENT_SQUARE_DIR.glob("*/claw_app.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        workflow_id = str(manifest.get("workflow_id") or manifest.get("id") or "")
        assert workflow_id not in workflow_ids, f"{workflow_id} duplicated by {manifest_path} and {workflow_ids.get(workflow_id)}"
        workflow_ids[workflow_id] = str(manifest_path)


def test_example_templates_expose_a_chat_launch_path():
    from agentclaw.agent_square import register_claw_app_workflows
    from agentclaw.api.registry import WorkflowRegistry

    registered_ids: list[str] = []
    try:
        for app_id in EXAMPLE_TEMPLATE_IDS:
            result = register_claw_app_workflows(app_id)
            registered_ids.extend(result["registered_workflow_ids"])
            workflow_id = result["registered_workflow_ids"][0]
            workflow = WorkflowRegistry.get(workflow_id)
            structure = workflow.get_structure()
            form_config = structure.get("form_config") or []
            user_input_field = structure.get("user_input_field")

            assert user_input_field or form_config, f"{app_id} has no user input or form start fields"
            if user_input_field:
                assert any(field["name"] == user_input_field for field in form_config), app_id

        weekly = WorkflowRegistry.get("weekly_report").get_structure()
        custom = WorkflowRegistry.get("custom_demo").get_structure()
        doc = WorkflowRegistry.get("doc_analyzer").get_structure()
        assert weekly["user_input_field"] == "user_input"
        assert custom["user_input_field"] == "user_input"
        assert doc["user_input_field"] is None
        assert {field["name"] for field in doc["form_config"]} == {"documents", "question"}
    finally:
        for workflow_id in registered_ids:
            WorkflowRegistry.unregister(workflow_id)


def test_agent_square_workflow_module_name_preserves_package_context():
    from agentclaw.agent_square import _workflow_module_name

    assert (
        _workflow_module_name(
            {"app_dir": str(AGENT_SQUARE_DIR / "werewolf_agent"), "workflow": "agents/werewolf.py"}
        )
        == "agentclaw.agent_square.werewolf_agent.agents.werewolf"
    )


def test_importing_resource_backed_example_templates_copies_support_files(tmp_path):
    from agentclaw.agent_square import import_claw_app_to_project

    gif_import = import_claw_app_to_project("gif_agent", tmp_path)
    gif_target = Path(gif_import["target_dir"])
    assert gif_import["workflow_id"] == "gif_agent"
    assert (gif_target / "agents" / "gif_agent.py").is_file()
    assert (gif_target / "skills" / "slack-gif-creator" / "SKILL.md").is_file()
    assert (gif_target / "skills" / "slack-gif-creator" / "core" / "gif_builder.py").is_file()

    mcp_import = import_claw_app_to_project("mcp_agent", tmp_path)
    mcp_target = Path(mcp_import["target_dir"])
    assert mcp_import["workflow_id"] == "mcp_agent"
    assert (mcp_target / "agents" / "mcp_agent.py").is_file()
    assert (mcp_target / "mcps" / "example_tools.py").is_file()
    assert (mcp_target / "mcp.json").is_file()

    agents_init = tmp_path / "agents" / "__init__.py"
    init_text = agents_init.read_text(encoding="utf-8")
    assert "AgentClaw template import: gif_agent" in init_text
    assert "AgentClaw template import: mcp_agent" in init_text


def test_imported_gif_agent_discovers_its_packaged_skill(tmp_path, monkeypatch):
    from agentclaw.agent_square import import_claw_app_to_project
    from agentclaw.config import get_config

    import_result = import_claw_app_to_project("gif_agent", tmp_path)
    workflow_file = Path(import_result["workflow_file"])
    monkeypatch.setattr(get_config().project, "project_dir", tmp_path)

    namespace: dict[str, object] = {"__file__": str(workflow_file)}
    code = workflow_file.read_text(encoding="utf-8")
    exec(compile(code, str(workflow_file), "exec"), namespace)
    workflow = namespace["workflow"]

    assert workflow._find_skills_dir() == workflow_file.parent.parent / "skills"


def test_example_templates_register_workflows_without_cross_publishing():
    from agentclaw.agent_square import register_claw_app_workflows
    from agentclaw.api.registry import WorkflowRegistry

    for workflow_id in EXAMPLE_TEMPLATE_IDS:
        WorkflowRegistry.unregister(workflow_id)
    for workflow_id in ["turtle_soup", "ai_werewolf"]:
        WorkflowRegistry.unregister(workflow_id)

    gif_result = register_claw_app_workflows("gif_agent")
    assert gif_result["registered_workflow_ids"] == ["gif_agent"]
    assert WorkflowRegistry.get("gif_agent") is not None

    mcp_result = register_claw_app_workflows("mcp_agent")
    assert mcp_result["registered_workflow_ids"] == ["mcp_agent"]
    assert WorkflowRegistry.get("mcp_agent") is not None

    for workflow_id in EXAMPLE_TEMPLATE_IDS:
        WorkflowRegistry.unregister(workflow_id)

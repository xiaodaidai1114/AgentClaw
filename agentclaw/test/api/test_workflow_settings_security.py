from types import SimpleNamespace

from agentclaw.api.services.settings_service import SettingsService
from agentclaw.config import AgentClawConfig, ProjectConfig


class FakeLLMNode:
    def __init__(self, **kwargs):
        self.description = kwargs.get("description", "")
        self.max_retries = kwargs.get("max_retries", 3)
        self.retry_delay = kwargs.get("retry_delay", 1.0)
        self.output_to_user = kwargs.get("output_to_user", True)
        self.output_key = kwargs.get("output_key", "")
        self.fallback_value = kwargs.get("fallback_value")
        self.on_error = kwargs.get("on_error", "ABORT")
        self.model_id = kwargs.get("model_id")
        self.use_fast_model = kwargs.get("use_fast_model", False)
        self.stream = kwargs.get("stream", True)
        self.output_format = kwargs.get("output_format", "text")
        self.fallback_model_id = kwargs.get("fallback_model_id")
        self.auto_fallback = kwargs.get("auto_fallback", False)
        self.fallback_threshold = kwargs.get("fallback_threshold", 3)
        self.tool_choice = kwargs.get("tool_choice", "auto")
        self.max_tool_rounds = kwargs.get("max_tool_rounds", 0)
        self.enable_builtin_skills = kwargs.get("enable_builtin_skills", True)
        self.enable_builtin_tools = kwargs.get("enable_builtin_tools", True)
        self.agent_style = kwargs.get("agent_style", "agentic")
        self.use_context = kwargs.get("use_context", True)
        self.save_to_context = kwargs.get("save_to_context", True)
        self.max_context_messages = kwargs.get("max_context_messages", 30)
        self.enable_compression = kwargs.get("enable_compression", True)
        self.compression_threshold = kwargs.get("compression_threshold", 100000)
        self.compression_model = kwargs.get("compression_model")
        self.inject_files = kwargs.get("inject_files")
        self.enable_memory = kwargs.get("enable_memory", True)
        self.model_params = kwargs.get("model_params", {})


def make_builtin_workflow(tmp_path, node=None):
    return SimpleNamespace(
        id="__builtin__",
        name="AgentClaw",
        timeout=300,
        recursion_limit=50,
        cancel_on_disconnect=True,
        auth_required=False,
        allowed_roles=None,
        rate_limit=None,
        tracing=True,
        description="",
        welcome="",
        public_share_enabled=False,
        public_share_token="",
        workflow_api_key="",
        public_conversation_limit=20,
        public_message_limit=200,
        inject_as_agentic_capability=True,
        is_builtin=True,
        _nodes={"agent": node or FakeLLMNode()},
        _candidate_base_dirs=lambda: [tmp_path],
    )


def test_workflow_settings_default_to_private_and_mask_workflow_api_key(tmp_path):
    class Registry:
        @classmethod
        def get(cls, workflow_id):
            if workflow_id != "wf-1":
                return None
            return SimpleNamespace(
                id="wf-1",
                name="Workflow 1",
                timeout=300,
                recursion_limit=50,
                cancel_on_disconnect=True,
                auth_required=False,
                allowed_roles=None,
                rate_limit=None,
                tracing=True,
                description="",
                welcome="",
                public_share_enabled=False,
                public_share_token="share-token",
                workflow_api_key="wf-secret",
                public_conversation_limit=20,
                public_message_limit=200,
                inject_as_agentic_capability=True,
                _candidate_base_dirs=lambda: [tmp_path],
            )

    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    service = SettingsService(registry=Registry)

    settings = service.get_workflow("wf-1")

    assert settings["public_share_enabled"] is False
    assert settings["public_share_token"] == "share-token"
    assert settings["workflow_api_key"] == "***"
    assert settings["workflow_api_key_set"] is True
    assert settings["public_conversation_limit"] == 20
    assert settings["public_message_limit"] == 200
    assert settings["inject_as_agentic_capability"] is True


def test_workflow_settings_default_agentic_capability_injection_when_missing(tmp_path):
    class Registry:
        @classmethod
        def get(cls, workflow_id):
            if workflow_id != "wf-legacy":
                return None
            return SimpleNamespace(
                id="wf-legacy",
                name="Legacy Workflow",
                timeout=300,
                recursion_limit=50,
                cancel_on_disconnect=True,
                auth_required=False,
                allowed_roles=None,
                rate_limit=None,
                tracing=True,
                description="",
                welcome="",
                public_share_enabled=False,
                public_share_token="",
                workflow_api_key="",
                public_conversation_limit=20,
                public_message_limit=200,
                _candidate_base_dirs=lambda: [tmp_path],
            )

    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    service = SettingsService(registry=Registry)

    settings = service.get_workflow("wf-legacy")

    assert settings["inject_as_agentic_capability"] is True


def test_enabling_public_share_generates_token_and_preserves_masked_api_key(tmp_path):
    saved_path = tmp_path / ".agentclaw" / "wf-1_settings.json"
    workflow = SimpleNamespace(
        id="wf-1",
        name="Workflow 1",
        timeout=300,
        recursion_limit=50,
        cancel_on_disconnect=True,
        auth_required=False,
        allowed_roles=None,
        rate_limit=None,
        tracing=True,
        description="",
        welcome="",
        public_share_enabled=False,
        public_share_token="",
        workflow_api_key="wf-secret",
        public_conversation_limit=20,
        public_message_limit=200,
        inject_as_agentic_capability=True,
        _candidate_base_dirs=lambda: [tmp_path],
    )

    class Registry:
        @classmethod
        def get(cls, workflow_id):
            return workflow if workflow_id == "wf-1" else None

    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    service = SettingsService(registry=Registry)

    updated = service.update_workflow(
        "wf-1",
        {
            "public_share_enabled": True,
            "public_share_token": "",
            "workflow_api_key": "***",
            "rate_limit": "10/min",
            "public_conversation_limit": 3,
            "public_message_limit": 7,
        },
    )

    assert updated["public_share_enabled"] is True
    assert len(updated["public_share_token"]) >= 24
    assert updated["workflow_api_key"] == "***"
    assert workflow.workflow_api_key == "wf-secret"
    assert updated["rate_limit"] == "10/min"
    assert updated["public_conversation_limit"] == 3
    assert updated["public_message_limit"] == 7
    assert saved_path.exists()


def test_square_publish_requires_public_share_and_generates_share_token(tmp_path):
    workflow = SimpleNamespace(
        id="wf-1",
        name="Workflow 1",
        timeout=300,
        recursion_limit=50,
        cancel_on_disconnect=True,
        auth_required=False,
        allowed_roles=None,
        rate_limit=None,
        tracing=True,
        description="",
        welcome="",
        public_share_enabled=False,
        public_share_token="",
        publish_to_square=False,
        workflow_api_key="",
        public_conversation_limit=20,
        public_message_limit=200,
        inject_as_agentic_capability=True,
        _candidate_base_dirs=lambda: [tmp_path],
    )

    class Registry:
        @classmethod
        def get(cls, workflow_id):
            return workflow if workflow_id == "wf-1" else None

    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    service = SettingsService(registry=Registry)

    enabled = service.update_workflow(
        "wf-1",
        {
            "public_share_enabled": True,
            "public_share_token": "",
            "publish_to_square": True,
        },
    )

    assert enabled["public_share_enabled"] is True
    assert enabled["publish_to_square"] is True
    assert len(enabled["public_share_token"]) >= 24

    disabled = service.update_workflow(
        "wf-1",
        {
            "public_share_enabled": False,
            "publish_to_square": True,
        },
    )

    assert disabled["public_share_enabled"] is False
    assert disabled["publish_to_square"] is False


def test_builtin_workflow_cannot_be_published_from_settings_api(tmp_path):
    workflow = SimpleNamespace(
        id="__builtin__",
        name="AgentClaw",
        timeout=300,
        recursion_limit=50,
        cancel_on_disconnect=True,
        auth_required=False,
        allowed_roles=None,
        rate_limit=None,
        tracing=True,
        description="",
        welcome="",
        public_share_enabled=False,
        public_share_token="",
        workflow_api_key="",
        public_conversation_limit=20,
        public_message_limit=200,
        inject_as_agentic_capability=True,
        _candidate_base_dirs=lambda: [tmp_path],
    )

    class Registry:
        @classmethod
        def get(cls, workflow_id):
            return workflow if workflow_id == "__builtin__" else None

    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    service = SettingsService(registry=Registry)

    updated = service.update_workflow(
        "__builtin__",
        {
            "public_share_enabled": True,
            "public_share_token": "should-not-stick",
            "publish_to_square": True,
            "rate_limit": "1/min",
        },
    )

    assert updated["public_share_enabled"] is False
    assert updated["public_share_token"] == ""
    assert updated["publish_to_square"] is False
    assert workflow.public_share_enabled is False
    assert workflow.public_share_token == ""


def test_builtin_agent_model_params_default_to_unset_temperature_and_top_p(tmp_path):
    workflow = make_builtin_workflow(tmp_path)

    class Registry:
        @classmethod
        def get(cls, workflow_id):
            return workflow if workflow_id == "__builtin__" else None

    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    service = SettingsService(registry=Registry)

    node_settings = service.get_node("__builtin__", "agent")

    assert node_settings["temperature"] is None
    assert node_settings["top_p"] is None
    assert workflow._nodes["agent"].model_params == {}


def test_builtin_agent_settings_can_save_false_and_zero_values(tmp_path):
    workflow = make_builtin_workflow(tmp_path)

    class Registry:
        @classmethod
        def get(cls, workflow_id):
            return workflow if workflow_id == "__builtin__" else None

    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    service = SettingsService(registry=Registry)

    updated = service.update_node(
        "__builtin__",
        "agent",
        {
            "temperature": 0,
            "top_p": 0.9,
            "max_tokens": 0,
            "stream": False,
            "enable_memory": False,
        },
    )

    assert updated["temperature"] == 0
    assert updated["top_p"] == 0.9
    assert updated["max_tokens"] == 0
    assert updated["stream"] is False
    assert updated["enable_memory"] is False
    assert workflow._nodes["agent"].model_params == {"temperature": 0, "top_p": 0.9}


def test_builtin_agent_settings_reset_node_field_restores_default(tmp_path):
    workflow = make_builtin_workflow(tmp_path)

    class Registry:
        @classmethod
        def get(cls, workflow_id):
            return workflow if workflow_id == "__builtin__" else None

    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    service = SettingsService(registry=Registry)
    service.update_node("__builtin__", "agent", {"temperature": 0.4, "top_p": 0.8, "enable_memory": False})

    temperature_reset = service.reset_node_field("__builtin__", "agent", "temperature")
    top_p_reset = service.reset_node_field("__builtin__", "agent", "top_p")

    assert temperature_reset["temperature"] is None
    assert top_p_reset["top_p"] is None
    assert workflow._nodes["agent"].model_params == {}
    assert service.get_node("__builtin__", "agent")["enable_memory"] is False


def test_builtin_agent_settings_reset_workflow_memory_clears_memory(tmp_path):
    workflow = make_builtin_workflow(tmp_path)

    class Registry:
        @classmethod
        def get(cls, workflow_id):
            return workflow if workflow_id == "__builtin__" else None

    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    service = SettingsService(registry=Registry)
    service.update_workflow("__builtin__", {"memory_content": "saved builtin memory"})

    reset = service.reset_workflow_field("__builtin__", "memory_content")

    assert reset["memory_content"] == ""
    assert reset["memory_chars"] == 0


def test_workflow_settings_can_disable_agentic_capability_injection(tmp_path):
    workflow = SimpleNamespace(
        id="wf-1",
        name="Workflow 1",
        timeout=300,
        recursion_limit=50,
        cancel_on_disconnect=True,
        auth_required=False,
        allowed_roles=None,
        rate_limit=None,
        tracing=True,
        description="",
        welcome="",
        public_share_enabled=False,
        public_share_token="",
        workflow_api_key="",
        public_conversation_limit=20,
        public_message_limit=200,
        inject_as_agentic_capability=True,
        _candidate_base_dirs=lambda: [tmp_path],
    )

    class Registry:
        @classmethod
        def get(cls, workflow_id):
            return workflow if workflow_id == "wf-1" else None

    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    service = SettingsService(registry=Registry)

    updated = service.update_workflow(
        "wf-1",
        {
            "inject_as_agentic_capability": False,
        },
    )

    assert updated["inject_as_agentic_capability"] is False
    assert workflow.inject_as_agentic_capability is False


def test_workflow_settings_can_save_unlimited_recursion_limit(tmp_path):
    workflow = SimpleNamespace(
        id="wf-1",
        name="Workflow 1",
        timeout=300,
        recursion_limit=50,
        cancel_on_disconnect=True,
        auth_required=False,
        allowed_roles=None,
        rate_limit=None,
        tracing=True,
        description="",
        welcome="",
        public_share_enabled=False,
        public_share_token="",
        workflow_api_key="",
        public_conversation_limit=20,
        public_message_limit=200,
        inject_as_agentic_capability=True,
        _candidate_base_dirs=lambda: [tmp_path],
    )

    class Registry:
        @classmethod
        def get(cls, workflow_id):
            return workflow if workflow_id == "wf-1" else None

    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    service = SettingsService(registry=Registry)

    updated = service.update_workflow("wf-1", {"recursion_limit": 0})

    assert updated["recursion_limit"] == 0
    assert workflow.recursion_limit == 0


def test_builtin_workflow_info_never_exposes_public_share_state():
    from agentclaw.api.services.workflow_service import WorkflowService

    workflow = SimpleNamespace(
        id="__builtin__",
        name="AgentClaw",
        version="1.0",
        description="",
        public_share_enabled=True,
        public_share_token="stale-token",
        rate_limit="1/min",
        public_conversation_limit=1,
        public_message_limit=2,
        workflow_api_key="wf-key",
        _nodes={},
    )

    info = WorkflowService()._to_info(workflow)

    assert info["is_builtin"] is True
    assert info["public_share_enabled"] is False
    assert info["public_share_token"] == ""

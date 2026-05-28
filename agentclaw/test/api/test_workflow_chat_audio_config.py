from __future__ import annotations

from types import SimpleNamespace

from agentclaw.api.services.settings_service import SettingsService, apply_saved_workflow_settings
from agentclaw.config import AgentClawConfig, ProjectConfig
from agentclaw.graph.workflow import Workflow


def _service(tmp_path, workflow):
    class Registry:
        @classmethod
        def get(cls, workflow_id):
            return workflow if workflow_id == workflow.id else None

        @classmethod
        def list_all(cls):
            return [workflow]

    AgentClawConfig._instance = AgentClawConfig(
        project=ProjectConfig(project_dir=tmp_path),
    )
    return SettingsService(registry=Registry)


def test_workflow_structure_includes_default_chat_audio_config():
    workflow = Workflow(id="chat_audio_default", name="Chat Audio Default")

    structure = workflow.get_structure()

    assert structure["chat_audio"] == {
        "enabled": False,
        "speech_input_enabled": False,
        "tts_enabled": False,
        "speech2text_model_id": "",
        "tts_model_id": "",
        "tts_voice": "",
    }


def test_builtin_workflow_structure_enables_chat_audio_by_default():
    workflow = Workflow(id="__builtin__", name="AgentClaw")

    structure = workflow.get_structure()

    assert structure["is_builtin"] is True
    assert structure["chat_audio"] == {
        "enabled": True,
        "speech_input_enabled": True,
        "tts_enabled": True,
        "speech2text_model_id": "",
        "tts_model_id": "",
        "tts_voice": "",
    }


def test_workflow_settings_preserve_chat_audio_false_values(tmp_path):
    workflow = Workflow(
        id="chat_audio_settings",
        name="Chat Audio Settings",
        chat_audio={
            "enabled": True,
            "speech_input_enabled": True,
            "tts_enabled": True,
            "speech2text_model_id": "asr-default",
            "tts_model_id": "tts-default",
            "tts_voice": "alloy",
        },
    )
    service = _service(tmp_path, workflow)

    updated = service.update_workflow(
        workflow.id,
        {
            "chat_audio": {
                "enabled": True,
                "speech_input_enabled": False,
                "tts_enabled": False,
                "speech2text_model_id": "asr-custom",
                "tts_model_id": "tts-custom",
                "tts_voice": "nova",
            }
        },
    )

    assert updated["chat_audio"]["enabled"] is True
    assert updated["chat_audio"]["speech_input_enabled"] is False
    assert updated["chat_audio"]["tts_enabled"] is False
    assert updated["chat_audio"]["speech2text_model_id"] == "asr-custom"
    assert updated["chat_audio"]["tts_model_id"] == "tts-custom"
    assert updated["chat_audio"]["tts_voice"] == "nova"

    apply_saved_workflow_settings(workflow, tmp_path)

    assert workflow.chat_audio["speech_input_enabled"] is False
    assert workflow.chat_audio["tts_enabled"] is False


def test_settings_workflow_response_defaults_chat_audio(tmp_path):
    workflow = SimpleNamespace(
        id="chat_audio_response",
        timeout=300,
        recursion_limit=0,
        cancel_on_disconnect=True,
        auth_required=False,
        allowed_roles=None,
        rate_limit="",
        tracing=True,
        description="",
        welcome="",
        public_share_enabled=False,
        public_share_token="",
        workflow_api_key="",
        public_conversation_limit=20,
        public_message_limit=200,
        inject_as_agentic_capability=True,
        _nodes={},
    )
    service = _service(tmp_path, workflow)

    payload = service.get_workflow(workflow.id)

    assert payload["chat_audio"]["enabled"] is False
    assert payload["chat_audio"]["speech_input_enabled"] is False
    assert payload["chat_audio"]["tts_enabled"] is False

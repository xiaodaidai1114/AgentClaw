from types import SimpleNamespace

import pytest

from agentclaw.test.conftest import auth_header


pytestmark = pytest.mark.api


def test_public_workflow_catalog_requires_auth(public_api_client):
    response = public_api_client.get("/api/workflows")

    assert response.status_code == 401


def test_public_workflow_catalog_accepts_workflow_key(public_api_client, monkeypatch, auth_tokens):
    from agentclaw.api.registry import WorkflowRegistry

    monkeypatch.setattr(
        WorkflowRegistry,
        "list_info",
        classmethod(lambda cls: [{"id": "wf-1", "name": "Workflow 1"}]),
    )

    response = public_api_client.get(
        "/api/workflows",
        headers=auth_header(auth_tokens.workflow),
    )

    assert response.status_code == 200
    assert response.json()["workflows"] == [{"id": "wf-1", "name": "Workflow 1"}]


def test_anonymous_public_workflow_detail_returns_runtime_metadata(public_api_client, monkeypatch):
    from agentclaw.api.registry import WorkflowRegistry

    class FakeWorkflow:
        id = "wf-public"
        name = "Public workflow"
        public_share_enabled = True
        public_share_token = "share-test"
        description = "Talk to the public agent"
        welcome = "Welcome!"
        form_config = [{"name": "topic", "type": "text", "required": True}]
        input_schema = {
            "inputs": {
                "topic": {"type": "text", "required": True, "label": "Topic"},
                "question": {"type": "textarea", "required": True, "label": "Question"},
            }
        }

        def get_user_input_field(self):
            return "question"

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )

    response = public_api_client.get("/api/public/workflows/wf-public?share_token=share-test")

    assert response.status_code == 200
    assert response.json() == {
        "workflow": {
            "id": "wf-public",
            "name": "Public workflow",
            "description": "Talk to the public agent",
            "welcome": "Welcome!",
            "form_config": [{"name": "topic", "type": "text", "required": True}],
            "input_schema": {
                "inputs": {
                    "topic": {"type": "text", "required": True, "label": "Topic"},
                    "question": {"type": "textarea", "required": True, "label": "Question"},
                }
            },
            "user_input_field": "question",
            "chat_audio": {
                "enabled": False,
                "speech_input_enabled": False,
                "tts_enabled": False,
                "max_audio_bytes": 10485760,
                "max_tts_chars": 2000,
            },
        }
    }


def test_anonymous_public_workflow_detail_rejects_builtin_workflow(public_api_client, monkeypatch):
    from agentclaw.api.registry import WorkflowRegistry

    class BuiltinWorkflow:
        id = "__builtin__"
        name = "AgentClaw"
        is_builtin = True

        def get_user_input_field(self):
            return "question"

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: BuiltinWorkflow() if workflow_id == "__builtin__" else None),
    )

    response = public_api_client.get("/api/public/workflows/__builtin__")

    assert response.status_code == 404
    assert response.json()["code"] == "WORKFLOW_NOT_FOUND"


def test_public_square_lists_only_published_public_workflows(public_api_client, monkeypatch):
    from agentclaw.api.registry import WorkflowRegistry

    class PublishedWorkflow:
        id = "wf-published"
        name = "Published workflow"
        description = "Visible in the public square"
        recommended_input = "Start here"
        public_share_enabled = True
        public_share_token = "share-published"
        publish_to_square = True
        chat_audio = {
            "enabled": True,
            "speech_input_enabled": True,
            "tts_enabled": False,
        }

    class PrivateShareWorkflow:
        id = "wf-private-share"
        name = "Private share workflow"
        description = "Has a token but is not in the square"
        public_share_enabled = True
        public_share_token = "share-private"
        publish_to_square = False

    class DisabledWorkflow:
        id = "wf-disabled"
        name = "Disabled workflow"
        public_share_enabled = False
        public_share_token = "share-disabled"
        publish_to_square = True

    class BuiltinWorkflow:
        id = "__builtin__"
        name = "Builtin"
        is_builtin = True
        public_share_enabled = True
        public_share_token = "share-builtin"
        publish_to_square = True

    monkeypatch.setattr(
        WorkflowRegistry,
        "list_all",
        classmethod(lambda cls: [PublishedWorkflow(), PrivateShareWorkflow(), DisabledWorkflow(), BuiltinWorkflow()]),
    )

    response = public_api_client.get("/api/public/square/workflows")

    assert response.status_code == 200
    assert response.json() == {
        "workflows": [
            {
                "id": "wf-published",
                "name": "Published workflow",
                "description": "Visible in the public square",
                "recommended_input": "Start here",
                "chat_audio": {
                    "enabled": True,
                    "speech_input_enabled": True,
                    "tts_enabled": False,
                },
            }
        ]
    }
    assert "wf-private-share" not in response.text
    assert "share-published" not in response.text
    assert "share-private" not in response.text
    assert "share-disabled" not in response.text
    assert "share-builtin" not in response.text


def test_workflow_run_requires_auth(public_api_client):
    response = public_api_client.post("/api/workflow/run", json={"workflow_id": "wf-1"})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_workflow_run_validates_required_workflow_id(public_api_client, auth_tokens):
    response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={"inputs": {}},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_upload_status_accepts_workflow_key(public_api_client, monkeypatch, auth_tokens):
    import agentclaw.database

    monkeypatch.setattr(agentclaw.database, "get_file_storage", lambda: None)

    response = public_api_client.get(
        "/api/upload/status",
        headers=auth_header(auth_tokens.workflow),
    )

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["max_size"] > 0


def test_upload_list_requires_admin_not_workflow_key(public_api_client, auth_tokens):
    response = public_api_client.get(
        "/api/upload/list",
        headers=auth_header(auth_tokens.workflow),
    )

    assert response.status_code == 403


def test_upload_list_returns_empty_without_database_for_admin(public_api_client, monkeypatch, auth_tokens):
    import agentclaw.database

    monkeypatch.setattr(agentclaw.database, "get_file_storage", lambda: None)

    response = public_api_client.get(
        "/api/upload/list",
        headers=auth_header(auth_tokens.admin),
    )

    assert response.status_code == 200
    assert response.json() == {"files": []}


def test_file_download_requires_auth_or_signed_token(public_api_client, monkeypatch):
    from agentclaw.api.routers.public import files as files_router

    class FakeStorage:
        async def find_by_id(self, file_id):
            return SimpleNamespace(mime_type="text/plain", original_name="secret.txt")

        async def get_file_bytes(self, file_id):
            return b"secret"

    monkeypatch.setattr(files_router, "get_file_storage", lambda: FakeStorage())

    response = public_api_client.get("/api/files/file-1")

    assert response.status_code == 401

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agentclaw.test.conftest import auth_header


pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _reset_public_session_state():
    from agentclaw.api.routers.public.session import reset_public_user_state

    reset_public_user_state()


def _parse_sse_events(raw_text: str) -> list[dict]:
    events: list[dict] = []
    for block in raw_text.split("\n\n"):
        data_lines = [
            line.removeprefix("data: ")
            for line in block.splitlines()
            if line.startswith("data: ")
        ]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


def _public_page_headers() -> dict[str, str]:
    return {
        "origin": "http://testserver",
        "sec-fetch-site": "same-origin",
        "x-agentclaw-public-session": "1",
    }


def _open_public_session(public_api_client, workflow_id: str):
    return public_api_client.post(
        f"/api/public/workflows/{workflow_id}/session?share_token=share-test",
        headers={
            "origin": "http://testserver",
            "sec-fetch-site": "same-origin",
        },
    )


def _open_public_session_client(public_api_client, workflow_id: str):
    session = _open_public_session(public_api_client, workflow_id)
    assert session.status_code == 200
    return public_api_client


class FakeSafetyGuardManager:
    safe_guard_id = "guard"
    safe_guard_prompt = "This custom prompt must be ignored"
    safe_guard_rules = "block unsafe content"

    def __init__(self, decision: str):
        self.decision = decision
        self.calls: list[tuple[list[dict], dict]] = []

    async def invoke(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.decision


def test_workflow_run_rejects_invalid_json_after_auth(public_api_client, auth_tokens):
    response = public_api_client.post(
        "/api/workflow/run",
        headers={**auth_header(auth_tokens.workflow), "content-type": "application/json"},
        content=b'{"workflow_id":',
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_JSON"


def test_workflow_run_returns_404_for_missing_workflow(public_api_client, monkeypatch, auth_tokens):
    from agentclaw.api.registry import WorkflowRegistry

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: None))

    response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "missing", "inputs": {}},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "WORKFLOW_NOT_FOUND"


def test_workflow_run_accepts_workflow_specific_api_key(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    class FakeWorkflow:
        id = "wf-specific-key"
        _input_schema = None
        workflow_api_key = "wf-local-key"

        def get_user_input_field(self):
            return "prompt"

        async def run(self, *, inputs, context, thread_id):
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["prompt"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-specific-key" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header("wf-local-key"),
        json={
            "workflow_id": "wf-specific-key",
            "response_mode": "blocking",
            "user": "hello",
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "hello"


def test_workflow_specific_api_key_requires_api_published(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    run_calls = 0

    class FakeWorkflow:
        id = "wf-api-disabled"
        _input_schema = None
        api_published = False
        workflow_api_key = "wf-local-key"

        def get_user_input_field(self):
            return "prompt"

        async def run(self, *, inputs, context, thread_id):
            nonlocal run_calls
            run_calls += 1
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["prompt"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    workflow = FakeWorkflow()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: workflow if workflow_id == "wf-api-disabled" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    workflow_key_response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header("wf-local-key"),
        json={
            "workflow_id": "wf-api-disabled",
            "response_mode": "blocking",
            "user": "hello",
        },
    )
    global_key_response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={
            "workflow_id": "wf-api-disabled",
            "response_mode": "blocking",
            "user": "hello",
        },
    )

    assert workflow_key_response.status_code == 401
    assert workflow_key_response.json()["code"] == "unauthorized"
    assert global_key_response.status_code == 200
    assert global_key_response.json()["answer"] == "hello"
    assert run_calls == 1


def test_workflow_specific_api_key_does_not_grant_catalog_access(public_api_client):
    response = public_api_client.get(
        "/api/workflows",
        headers=auth_header("wf-local-key"),
    )

    assert response.status_code == 401


def test_workflow_run_validates_user_and_inputs_before_execution(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    from agentclaw.api.registry import WorkflowRegistry

    class FakeWorkflow:
        _input_schema = None

        def get_user_input_field(self):
            return "prompt"

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FakeWorkflow()))

    non_object_inputs = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "wf-1", "inputs": ["bad"]},
    )
    non_string_user = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "wf-1", "user": {"bad": True}, "inputs": {}},
    )
    non_string_user_id = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "wf-1", "user_id": 123, "inputs": {}},
    )
    conflicting_user = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={
            "workflow_id": "wf-1",
            "user": "top-level",
            "inputs": {"prompt": "different"},
        },
    )

    assert non_object_inputs.status_code == 400
    assert non_object_inputs.json()["error"] == "'inputs' must be an object"
    assert non_string_user.status_code == 400
    assert non_string_user.json()["error"] == "'user' must be a string when provided"
    assert non_string_user_id.status_code == 400
    assert non_string_user_id.json()["error"] == "'user_id' must be a string when provided"
    assert conflicting_user.status_code == 400
    assert "conflict between top-level 'user'" in conflicting_user.json()["error"]


def test_workflow_run_blocking_mode_normalizes_user_and_returns_answer(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    captured: dict[str, object] = {}

    class FakeWorkflow:
        id = "wf-1"
        _input_schema = None

        def get_user_input_field(self):
            return "prompt"

        async def run(self, *, inputs, context, thread_id):
            captured["inputs"] = inputs
            captured["context_thread_id"] = context.thread_id
            captured["thread_id"] = thread_id
            return {
                "state": {
                    "__messages__": [
                        {"role": "assistant", "content": f"echo::{inputs['prompt']}"},
                    ],
                    "__status__": "completed",
                },
                "metadata": {"trace_id": "trace-1"},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        captured["workflow_inputs"] = workflow_inputs
        return input_data

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FakeWorkflow()))
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={
            "workflow_id": "wf-1",
            "response_mode": "blocking",
            "conversation_id": "conv-1",
            "user": "hello",
            "inputs": {},
            "user_id": "user-1",
            "files": [{"id": "file-1"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "echo::hello"
    assert payload["conversation_id"] == "conv-1"
    assert payload["metadata"]["trace_id"] == "trace-1"
    assert payload["metadata"]["status"] == "completed"
    assert captured["thread_id"] == "conv-1"
    assert captured["context_thread_id"] == "conv-1"
    assert captured["inputs"] == {
        "__user__": "hello",
        "prompt": "hello",
        "__files__": [{"id": "file-1"}],
    }


def test_workflow_run_safety_guard_is_api_scoped(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    guard_manager = FakeSafetyGuardManager("Answer: 1")
    run_calls = 0

    class FakeWorkflow:
        id = "wf-api-guard"
        _input_schema = None
        _llm_manager = guard_manager
        safe_guard_apply_api = False

        def get_user_input_field(self):
            return "prompt"

        async def run(self, *, inputs, context, thread_id):
            nonlocal run_calls
            run_calls += 1
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["prompt"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    workflow = FakeWorkflow()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: workflow if workflow_id == "wf-api-guard" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    default_response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "wf-api-guard", "response_mode": "blocking", "user": "unsafe"},
    )
    assert default_response.status_code == 200
    assert default_response.json()["answer"] == "unsafe"
    assert run_calls == 1
    assert guard_manager.calls == []

    workflow.safe_guard_apply_api = True
    blocked_response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "wf-api-guard", "response_mode": "blocking", "user": "unsafe"},
    )
    assert blocked_response.status_code == 403
    assert blocked_response.json()["code"] == "SAFETY_GUARD_BLOCKED"
    assert run_calls == 1
    assert len(guard_manager.calls) == 1


def test_authenticated_builtin_workflow_run_remains_allowed_after_public_share_block(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    class BuiltinWorkflow:
        id = "__builtin__"
        _input_schema = None
        is_builtin = True

        def get_user_input_field(self):
            return "prompt"

        async def run(self, *, inputs, context, thread_id):
            return {
                "state": {
                    "__messages__": [
                        {"role": "assistant", "content": f"builtin::{inputs['prompt']}"},
                    ],
                    "__status__": "completed",
                },
                "metadata": {"trace_id": "trace-builtin"},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: BuiltinWorkflow() if workflow_id == "__builtin__" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={
            "workflow_id": "__builtin__",
            "response_mode": "blocking",
            "conversation_id": "conv-builtin",
            "user": "hello builtin",
            "inputs": {"prompt": "hello builtin"},
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "builtin::hello builtin"


def test_anonymous_public_workflow_run_uses_path_workflow_without_auth(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    captured: dict[str, object] = {}

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            captured["inputs"] = dict(inputs)
            captured["thread_id"] = thread_id
            captured["context_user_id"] = context.user_id
            captured["context_workflow_id"] = context.workflow_id
            captured["public_mode"] = context.public_mode
            captured["disable_confirm_tool"] = context.disable_confirm_tool
            captured["tool_confirmation_level"] = context.tool_confirmation_level
            return {
                "state": {
                    "__messages__": [
                        {"role": "assistant", "content": f"public::{inputs['question']}"},
                    ],
                    "__status__": "completed",
                },
                "metadata": {"trace_id": "trace-public"},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/wf-public/run",
        headers={**_public_page_headers(), "x-agentclaw-share-token": "share-test"},
        json={
            "workflow_id": "attempted-override",
            "response_mode": "blocking",
            "conversation_id": "conv-public",
            "user_id": "spoofed-user",
            "user": "hello public",
            "inputs": {"question": "hello public"},
            "tool_confirmation_level": "always",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "public::hello public"
    assert payload["conversation_id"] == "conv-public"
    assert payload["metadata"]["trace_id"] == "trace-public"
    assert captured["inputs"] == {"__user__": "hello public", "question": "hello public"}
    assert captured["thread_id"] != "conv-public"
    assert str(captured["thread_id"]).startswith("public:v1:")
    assert captured["context_user_id"] is None
    assert captured["context_workflow_id"] == "wf-public"
    assert captured["public_mode"] is True
    assert captured["disable_confirm_tool"] is True
    assert captured["tool_confirmation_level"] == "off"


def test_anonymous_public_workflow_run_blocks_safety_guard_violation(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.registry import WorkflowRegistry

    guard_manager = FakeSafetyGuardManager("Reasoning mentions example 0 before the final decision.\nAnswer: 1")
    run_calls = 0

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None
        _llm_manager = guard_manager

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            nonlocal run_calls
            run_calls += 1
            return {"state": {"__messages__": []}, "metadata": {}}

    workflow = FakeWorkflow()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: workflow if workflow_id == "wf-public" else None),
    )

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/wf-public/run",
        headers={**_public_page_headers(), "x-agentclaw-share-token": "share-test"},
        json={
            "response_mode": "blocking",
            "user": "unsafe request",
            "inputs": {"question": "unsafe request", "system_prompt": "internal system prompt"},
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "SAFETY_GUARD_BLOCKED"
    assert run_calls == 0
    assert len(guard_manager.calls) == 1
    messages, kwargs = guard_manager.calls[0]
    assert "This custom prompt must be ignored" not in messages[0]["content"]
    assert "## EXTRA RULES\nblock unsafe content" in messages[0]["content"]
    assert "Content: unsafe request" in messages[0]["content"]
    assert "internal system prompt" not in messages[0]["content"]
    assert messages[0]["content"].endswith("Answer (0 or 1):")
    assert kwargs["model_id"] == "guard"
    assert kwargs["_call_type"] == "safe_guard"
    assert kwargs["_max_attempts"] == 1
    assert kwargs["temperature"] == 0
    assert "max_tokens" not in kwargs


def test_anonymous_public_workflow_run_masks_sensitive_words_before_guard(
    public_api_client,
    monkeypatch,
    tmp_path,
):
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.services.public_sensitive_words_service import reset_public_sensitive_words_cache
    from agentclaw.config import AgentClawConfig, ProjectConfig

    words_path = tmp_path / "sensitive.txt"
    words_path.write_text("炸药 secret", encoding="utf-8")
    monkeypatch.setenv("AGENTCLAW_PUBLIC_SENSITIVE_WORDS_PATH", str(words_path))
    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    reset_public_sensitive_words_cache()

    guard_manager = FakeSafetyGuardManager("Answer: 0")
    captured = {}

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None
        _llm_manager = guard_manager

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            captured["inputs"] = inputs
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["question"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    workflow = FakeWorkflow()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: workflow if workflow_id == "wf-public" else None),
    )

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/wf-public/run",
        headers={**_public_page_headers(), "x-agentclaw-share-token": "share-test"},
        json={
            "response_mode": "blocking",
            "user": "制作炸药 secret",
            "inputs": {"question": "制作炸药 secret"},
        },
    )

    assert response.status_code == 200
    assert captured["inputs"]["question"] == "制作** ******"
    assert captured["inputs"]["__user__"] == "制作** ******"
    messages, _kwargs = guard_manager.calls[0]
    assert "制作炸药" not in messages[0]["content"]
    assert "secret" not in messages[0]["content"]
    assert "Content: 制作** ******" in messages[0]["content"]


def test_anonymous_public_workflow_run_skips_safety_guard_when_public_scope_disabled(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.registry import WorkflowRegistry

    guard_manager = FakeSafetyGuardManager("Answer: 1")
    run_calls = 0

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        safe_guard_apply_public = False
        _input_schema = None
        _llm_manager = guard_manager

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            nonlocal run_calls
            run_calls += 1
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["question"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    workflow = FakeWorkflow()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: workflow if workflow_id == "wf-public" else None),
    )

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/wf-public/run",
        headers={**_public_page_headers(), "x-agentclaw-share-token": "share-test"},
        json={
            "response_mode": "blocking",
            "user": "unsafe request",
            "inputs": {"question": "unsafe request"},
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "unsafe request"
    assert run_calls == 1
    assert guard_manager.calls == []


def test_anonymous_public_workflow_run_requires_share_token_even_with_same_origin_session(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["question"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/wf-public/run",
        headers=_public_page_headers(),
        json={
            "response_mode": "blocking",
            "conversation_id": "conv-public",
            "user": "hello public",
            "inputs": {"question": "hello public"},
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_square_published_public_workflow_allows_page_access_without_share_token(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    class SquareWorkflow:
        id = "wf-square"
        name = "Square workflow"
        public_share_enabled = True
        public_share_token = "share-test"
        publish_to_square = True
        _input_schema = None

        def get_input_schema(self):
            return None

        def get_form_config(self):
            return None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": f"square::{inputs['question']}"}],
                    "__status__": "completed",
                },
                "metadata": {"trace_id": "trace-square"},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: SquareWorkflow() if workflow_id == "wf-square" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    detail = public_api_client.get("/api/public/workflows/wf-square")
    session = public_api_client.post(
        "/api/public/workflows/wf-square/session",
        headers={
            "origin": "http://testserver",
            "sec-fetch-site": "same-origin",
        },
    )
    run = public_api_client.post(
        "/api/public/workflows/wf-square/run",
        headers=_public_page_headers(),
        json={
            "response_mode": "blocking",
            "conversation_id": "conv-square",
            "user": "hello square",
            "inputs": {"question": "hello square"},
        },
    )

    assert detail.status_code == 200
    assert detail.json()["workflow"]["id"] == "wf-square"
    assert session.status_code == 200
    assert run.status_code == 200
    assert run.json()["answer"] == "square::hello square"


def test_anonymous_public_workflow_run_rejects_other_users_conversation_id(
    public_api_client,
    monkeypatch,
):
    from fastapi.testclient import TestClient
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    captured_threads: list[str] = []

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            captured_threads.append(thread_id)
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["question"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    first_client = _open_public_session_client(public_api_client, "wf-public")
    second_client = TestClient(public_api_client.app)
    _open_public_session_client(second_client, "wf-public")

    body = {
        "response_mode": "blocking",
        "conversation_id": "conv-shared",
        "user": "hello public",
        "inputs": {"question": "hello public"},
    }
    first = first_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json=body,
    )
    second = second_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json=body,
    )

    assert first.status_code == 200
    assert second.status_code == 404
    assert second.json()["code"] == "NOT_FOUND"
    assert len(captured_threads) == 1
    assert captured_threads[0] != "conv-shared"
    assert captured_threads[0].startswith("public:v1:")


def test_anonymous_public_workflow_metadata_requires_share_token_even_with_same_origin_session(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.registry import WorkflowRegistry

    class FakeWorkflow:
        id = "wf-public"
        name = "Public Turtle Soup"
        description = "Guess the story"
        welcome = "Ask yes/no questions"
        public_share_enabled = True
        public_share_token = "share-test"

        def get_input_schema(self):
            return None

        def get_form_config(self):
            return None

        def get_user_input_field(self):
            return "question"

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    response = public_api_client.get(
        "/api/public/workflows/wf-public",
        headers=_public_page_headers(),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_anonymous_public_workflow_run_requires_same_origin_page_session(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.registry import WorkflowRegistry

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            raise AssertionError("public run must require a page session before execution")

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )

    missing_session = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json={
            "response_mode": "blocking",
            "conversation_id": "conv-public",
            "user": "hello public",
            "inputs": {"question": "hello public"},
        },
    )
    cross_site_session = public_api_client.post(
        "/api/public/workflows/wf-public/session?share_token=share-test",
        headers={"origin": "https://evil.example", "sec-fetch-site": "cross-site"},
    )

    assert missing_session.status_code == 403
    assert missing_session.json()["code"] == "FORBIDDEN"
    assert cross_site_session.status_code == 403
    assert cross_site_session.json()["code"] == "FORBIDDEN"

    no_page_origin_session = public_api_client.post(
        "/api/public/workflows/wf-public/session?share_token=share-test",
        headers={"sec-fetch-site": "same-origin"},
    )
    assert no_page_origin_session.status_code == 403
    assert no_page_origin_session.json()["code"] == "FORBIDDEN"


def test_anonymous_public_workflow_session_does_not_trust_forwarded_host_by_default(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.registry import WorkflowRegistry

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None

    monkeypatch.delenv("AGENTCLAW_TRUST_PROXY_HEADERS", raising=False)
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )

    response = public_api_client.post(
        "/api/public/workflows/wf-public/session?share_token=share-test",
        headers={
            "origin": "https://evil.example",
            "referer": "https://evil.example/agent/wf-public?share_token=share-test",
            "sec-fetch-site": "same-origin",
            "x-forwarded-proto": "https",
            "x-forwarded-host": "evil.example",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_anonymous_public_workflow_session_survives_process_local_cache_miss(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public import execution as execution_router

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            return {
                "state": {
                    "__messages__": [
                        {"role": "assistant", "content": f"public::{inputs['question']}"},
                    ],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    getattr(execution_router, "_public_sessions", {}).clear()

    response = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json={
            "response_mode": "blocking",
            "conversation_id": "conv-public",
            "user": "hello public",
            "inputs": {"question": "hello public"},
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "public::hello public"


def test_anonymous_public_workflow_run_rejects_builtin_workflow_before_execution(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.registry import WorkflowRegistry

    class BuiltinWorkflow:
        id = "__builtin__"
        name = "AgentClaw"
        _input_schema = None
        is_builtin = True

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            raise AssertionError("builtin workflow must not run through the anonymous public endpoint")

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: BuiltinWorkflow() if workflow_id == "__builtin__" else None),
    )

    response = public_api_client.post(
        "/api/public/workflows/__builtin__/run",
        json={
            "response_mode": "blocking",
            "conversation_id": "conv-public",
            "user": "hello",
            "inputs": {"question": "hello"},
        },
    )

    assert response.status_code == 404


def test_public_workflow_run_rejects_checkpoint_expired_conversation(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public.session import public_owner_id_from_user_id
    from agentclaw.api.routers.public import session as public_session
    from agentclaw.api.services import conversation_service

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        public_conversation_limit = 10
        public_message_limit = 100
        rate_limit = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            raise AssertionError("expired checkpoint conversations must not run")

    class FakeConversationService:
        async def is_checkpoint_expired(self, workflow_id, conversation_id, source=None, owner_id=None):
            return True

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(conversation_service, "get_conversation_service", lambda: FakeConversationService())

    session = _open_public_session(public_api_client, "wf-public")
    public_user_cookie = session.cookies.get(public_session.PUBLIC_USER_COOKIE)
    public_user_id = public_session.public_user_id_from_cookie(public_user_cookie)
    owner_id = public_owner_id_from_user_id(public_user_id)
    public_session.bind_public_conversation_owner("wf-public", "conv-expired", owner_id)

    response = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json={
            "conversation_id": "conv-expired",
            "user": "hello public",
            "inputs": {"question": "hello public"},
        },
    )

    assert response.status_code == 410
    assert response.json()["code"] == "CHECKPOINT_EXPIRED"


def test_anonymous_public_workflow_requires_explicit_publish_and_share_token(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.registry import WorkflowRegistry

    class PrivateWorkflow:
        id = "wf-private"
        name = "Private"
        public_share_enabled = False
        public_share_token = "share-test"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            raise AssertionError("unpublished workflow must not run through public API")

    class PublicWorkflow:
        id = "wf-public"
        name = "Public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            raise AssertionError("wrong or missing share token must not execute")

    workflows = {
        "wf-private": PrivateWorkflow(),
        "wf-public": PublicWorkflow(),
    }
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: workflows.get(workflow_id)),
    )

    unpublished_detail = public_api_client.get(
        "/api/public/workflows/wf-private?share_token=share-test"
    )
    missing_token_detail = public_api_client.get("/api/public/workflows/wf-public")
    wrong_token_session = public_api_client.post(
        "/api/public/workflows/wf-public/session?share_token=wrong",
        headers={"origin": "http://testserver", "sec-fetch-site": "same-origin"},
    )
    unicode_token_detail = public_api_client.get(
        "/api/public/workflows/wf-public?share_token=中文"
    )
    missing_token_run = public_api_client.post(
        "/api/public/workflows/wf-public/run",
        headers=_public_page_headers(),
        json={"response_mode": "blocking", "user": "hello", "inputs": {"question": "hello"}},
    )

    assert unpublished_detail.status_code == 404
    assert unpublished_detail.json()["code"] == "WORKFLOW_NOT_FOUND"
    assert missing_token_detail.status_code == 403
    assert missing_token_detail.json()["code"] == "FORBIDDEN"
    assert wrong_token_session.status_code == 403
    assert wrong_token_session.json()["code"] == "FORBIDDEN"
    assert unicode_token_detail.status_code == 403
    assert unicode_token_detail.json()["code"] == "FORBIDDEN"
    assert missing_token_run.status_code == 403
    assert missing_token_run.json()["code"] == "FORBIDDEN"


def test_anonymous_public_workflow_run_is_rate_limited(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public import access as public_access

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        rate_limit = "1/min"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["question"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    public_access.reset_public_rate_limiter()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    body = {
        "response_mode": "blocking",
        "conversation_id": "conv-public",
        "user": "hello public",
        "inputs": {"question": "hello public"},
    }
    first = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json=body,
    )
    second = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json=body,
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


def test_anonymous_public_workflow_uses_default_rate_limit_when_workflow_has_none(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public import access as public_access

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        rate_limit = None
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["question"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setenv("AGENTCLAW_PUBLIC_DEFAULT_RATE_LIMIT", "1/min")
    public_access.reset_public_rate_limiter()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    body = {
        "response_mode": "blocking",
        "conversation_id": "conv-public",
        "user": "hello public",
        "inputs": {"question": "hello public"},
    }
    first = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json=body,
    )
    second = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json=body,
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


def test_anonymous_public_workflow_uses_builtin_default_rate_limit_when_env_unset(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public import access as public_access

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        rate_limit = None
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["question"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.delenv("AGENTCLAW_PUBLIC_DEFAULT_RATE_LIMIT", raising=False)
    monkeypatch.setattr(public_access, "time", SimpleNamespace(monotonic=lambda: 1000.0, time=lambda: 1000.0))
    public_access.reset_public_rate_limiter()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    body = {
        "response_mode": "blocking",
        "conversation_id": "conv-public",
        "user": "hello public",
        "inputs": {"question": "hello public"},
    }

    responses = [
        public_api_client.post(
            "/api/public/workflows/wf-public/run?share_token=share-test",
            headers=_public_page_headers(),
            json=body,
        )
        for _ in range(31)
    ]

    assert [response.status_code for response in responses[:30]] == [200] * 30
    assert responses[30].status_code == 429
    assert responses[30].json()["code"] == "RATE_LIMITED"


def test_public_rate_limit_can_use_redis_backend(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public import access as public_access

    class FakeRedis:
        def __init__(self):
            self.items: dict[str, list[float]] = {}
            self.expirations: dict[str, int] = {}

        def zremrangebyscore(self, key, _min_score, max_score):
            self.items[key] = [
                value for value in self.items.get(key, []) if value > float(max_score)
            ]

        def zcard(self, key):
            return len(self.items.get(key, []))

        def zadd(self, key, mapping):
            self.items.setdefault(key, []).extend(float(score) for score in mapping.values())

        def expire(self, key, seconds):
            self.expirations[key] = int(seconds)

    class FakeDb:
        def __init__(self, redis):
            self.redis = redis

        def is_redis_available(self):
            return True

        def get_sync_redis_client(self):
            return self.redis

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        rate_limit = "1/min"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["question"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    redis = FakeRedis()
    monkeypatch.setenv("AGENTCLAW_PUBLIC_RATE_LIMIT_BACKEND", "redis")
    public_access.reset_public_rate_limiter()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(public_access, "get_database", lambda: FakeDb(redis), raising=False)
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    body = {
        "response_mode": "blocking",
        "conversation_id": "conv-public",
        "user": "hello public",
        "inputs": {"question": "hello public"},
    }
    first = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json=body,
    )
    second = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json=body,
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"
    assert redis.items


def test_public_rate_limit_uses_connection_host_not_spoofed_forwarded_for_by_default(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public import access as public_access

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        rate_limit = "1/min"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": inputs["question"]}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.delenv("AGENTCLAW_TRUST_PROXY_HEADERS", raising=False)
    public_access.reset_public_rate_limiter()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    body = {
        "response_mode": "blocking",
        "conversation_id": "conv-public",
        "user": "hello public",
        "inputs": {"question": "hello public"},
    }
    first = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers={**_public_page_headers(), "x-forwarded-for": "198.51.100.10"},
        json=body,
    )
    second = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers={**_public_page_headers(), "x-forwarded-for": "203.0.113.20"},
        json=body,
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


def test_anonymous_public_workflow_run_rejects_file_payloads_before_storage(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    class Image:
        pass

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = SimpleNamespace(
            inputs={
                "image": SimpleNamespace(name="image", type=Image),
            }
        )

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            raise AssertionError("public file payload should be rejected before execution")

    async def process_file_inputs(input_data, workflow_inputs):
        raise AssertionError("public file payload should be rejected before storage processing")

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json={
            "response_mode": "blocking",
            "conversation_id": "conv-public",
            "user": "hello public",
            "inputs": {
                "question": "hello public",
                "image": "data:image/png;base64,AAAA",
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert "File inputs are not supported" in response.json()["error"]


def test_anonymous_public_workflow_rejects_oversized_message_before_execution(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            raise AssertionError("oversized public input must be rejected before execution")

    async def process_file_inputs(input_data, workflow_inputs):
        raise AssertionError("oversized public input must not reach storage processing")

    monkeypatch.setenv("AGENTCLAW_PUBLIC_MAX_MESSAGE_LENGTH", "10")
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json={
            "response_mode": "blocking",
            "conversation_id": "conv-public",
            "user": "this message is too long",
            "inputs": {"question": "this message is too long"},
        },
    )

    assert response.status_code == 413
    assert response.json()["code"] == "REQUEST_TOO_LARGE"
    assert "Public message is too large" in response.json()["error"]


def test_anonymous_public_workflow_rejects_oversized_request_body_before_execution(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            raise AssertionError("oversized public request body must be rejected before execution")

    async def process_file_inputs(input_data, workflow_inputs):
        raise AssertionError("oversized public request body must not reach storage processing")

    monkeypatch.setenv("AGENTCLAW_PUBLIC_MAX_INPUT_BYTES", "120")
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json={
            "response_mode": "blocking",
            "conversation_id": "conv-public",
            "user": "ok",
            "inputs": {
                "question": "ok",
                "nested": {"items": ["x" * 20, "y" * 20, "z" * 20]},
            },
        },
    )

    assert response.status_code == 413
    assert response.json()["code"] == "REQUEST_TOO_LARGE"
    assert "Public request body is too large" in response.json()["error"]


def test_anonymous_public_workflow_run_rejects_empty_files_field(
    public_api_client,
    monkeypatch,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        _input_schema = None

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            raise AssertionError("public files key must be rejected even when empty")

    async def process_file_inputs(input_data, workflow_inputs):
        raise AssertionError("public files key must not reach storage processing")

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/wf-public/run?share_token=share-test",
        headers=_public_page_headers(),
        json={
            "response_mode": "blocking",
            "conversation_id": "conv-public",
            "user": "hello public",
            "inputs": {"question": "hello public"},
            "files": [],
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert "File attachments are not supported" in response.json()["error"]


def test_workflow_run_ignores_non_list_files_field_and_unknown_mode_is_blocking(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    captured: dict[str, object] = {}

    class FakeWorkflow:
        id = "wf-files"
        _input_schema = None

        def get_user_input_field(self):
            return "prompt"

        async def run(self, *, inputs, context, thread_id):
            captured["inputs"] = dict(inputs)
            captured["request_stream"] = context.request_stream
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": "blocking fallback"}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FakeWorkflow()))
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={
            "workflow_id": "wf-files",
            "response_mode": "mystery-mode",
            "user": "hello",
            "files": {"not": "a-list"},
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "blocking fallback"
    assert captured["request_stream"] is False
    assert captured["inputs"] == {"__user__": "hello", "prompt": "hello"}


def test_upload_file_success_returns_stored_file_metadata(public_api_client, monkeypatch, auth_tokens):
    import agentclaw.database

    saved: dict[str, object] = {}

    class FakeStorage:
        db = SimpleNamespace(pg_pool=object())

        async def save(self, data, original_name, content_type):
            saved["data"] = data
            saved["original_name"] = original_name
            saved["content_type"] = content_type
            return SimpleNamespace(
                id="file-1",
                original_name=original_name,
                file_path="uploads/file-1.txt",
                mime_type=content_type,
                size=len(data),
            )

    monkeypatch.setattr(agentclaw.database, "get_file_storage", lambda: FakeStorage())

    response = public_api_client.post(
        "/api/upload",
        headers=auth_header(auth_tokens.workflow),
        files={"file": ("hello.txt", b"hello upload", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": "file-1",
        "original_name": "hello.txt",
        "file_path": "uploads/file-1.txt",
        "mime_type": "text/plain",
        "size": 12,
    }
    assert saved == {
        "data": b"hello upload",
        "original_name": "hello.txt",
        "content_type": "text/plain",
    }


def test_upload_list_returns_database_rows_for_admin(public_api_client, monkeypatch, auth_tokens):
    import agentclaw.database

    class FakeDB:
        pg_pool = object()

        async def pg_fetch(self, query):
            assert "FROM files" in query
            return [
                {
                    "id": "file-1",
                    "original_name": "hello.txt",
                    "file_path": "uploads/file-1.txt",
                    "mime_type": "text/plain",
                    "size": 12,
                }
            ]

    monkeypatch.setattr(
        agentclaw.database,
        "get_file_storage",
        lambda: SimpleNamespace(db=FakeDB()),
    )

    response = public_api_client.get(
        "/api/upload/list",
        headers=auth_header(auth_tokens.admin),
    )

    assert response.status_code == 200
    assert response.json()["files"] == [
        {
            "id": "file-1",
            "original_name": "hello.txt",
            "file_path": "uploads/file-1.txt",
            "mime_type": "text/plain",
            "size": 12,
        }
    ]


def test_admin_bearer_can_download_file_without_signed_url(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    from agentclaw.api.routers.public import files as files_router

    class FakeStorage:
        async def find_by_id(self, file_id):
            return SimpleNamespace(mime_type="text/plain", original_name="hello.txt")

        async def get_file_bytes(self, file_id):
            return b"hello"

    monkeypatch.setattr(files_router, "get_file_storage", lambda: FakeStorage())

    response = public_api_client.get(
        "/api/files/file-1",
        headers=auth_header(auth_tokens.admin),
    )

    assert response.status_code == 200
    assert response.content == b"hello"
    assert "filename=" in response.headers["content-disposition"]


def test_workflow_run_streaming_emits_ordered_sse_events_and_context(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    captured: dict[str, object] = {}

    class FakeWorkflow:
        id = "wf-stream"
        _input_schema = None

        def get_user_input_field(self):
            return "prompt"

        async def run(self, *, inputs, context, stream=False, thread_id=None):
            from agentclaw.runtime.streaming.context import get_output_channel

            captured["inputs"] = dict(inputs)
            captured["request_stream"] = context.request_stream
            captured["thread_id"] = thread_id
            captured["context_thread_id"] = context.thread_id
            captured["user_id"] = context.user_id
            captured["from_channel"] = context.from_channel
            captured["disable_confirm_tool"] = context.disable_confirm_tool
            captured["tool_confirmation_required"] = context.tool_confirmation_required
            captured["tool_confirmation_level"] = context.tool_confirmation_level
            captured["stream_kwarg"] = stream

            channel = get_output_channel()
            await channel.push_node_started("node-1", "llm", inputs={"prompt": inputs["prompt"]})
            await channel.push_message("hello ", "node-1")
            await channel.push_message("stream", "node-1")
            await channel.push_message_end(
                {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
                context_tokens=7,
            )
            await channel.push_node_finished("node-1", outputs={"answer": "hello stream"})
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": "fallback answer"}],
                },
                "metadata": {"trace_id": "trace-stream"},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FakeWorkflow()))
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={
            "workflow_id": "wf-stream",
            "response_mode": "streaming",
            "conversation_id": "conv-stream",
            "user": "hello",
            "inputs": {},
            "user_id": "user-1",
            "from_channel": True,
            "disable_confirm_tool": True,
            "tool_confirmation_required": True,
            "tool_confirmation_level": "medium",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(response.text)
    event_names = [event["event"] for event in events]
    assert event_names == [
        "workflow_started",
        "node_started",
        "message",
        "message",
        "message_end",
        "node_finished",
        "workflow_finished",
    ]
    assert events[0]["data"]["workflow_id"] == "wf-stream"
    assert events[2]["answer"] == "hello "
    assert events[4]["metadata"]["usage"]["total_tokens"] == 5
    assert events[-1]["data"]["status"] == "succeeded"
    assert events[-1]["data"]["outputs"]["answer"] == "hello stream"
    assert events[-1]["data"]["outputs"]["trace_id"] == "trace-stream"
    assert captured == {
        "inputs": {"__user__": "hello", "prompt": "hello"},
        "request_stream": True,
        "thread_id": "conv-stream",
        "context_thread_id": "conv-stream",
        "user_id": "user-1",
        "from_channel": True,
        "disable_confirm_tool": True,
        "tool_confirmation_required": True,
        "tool_confirmation_level": "medium",
        "stream_kwarg": False,
    }


def test_workflow_run_streaming_failure_emits_error_and_failed_finish(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    class FailingWorkflow:
        id = "wf-failing-stream"
        _input_schema = None

        def get_user_input_field(self):
            return "prompt"

        async def run(self, **_kwargs):
            raise RuntimeError("stream exploded")

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FailingWorkflow()))
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={
            "workflow_id": "wf-failing-stream",
            "response_mode": "streaming",
            "conversation_id": "conv-failing",
            "user": "hello",
        },
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert [event["event"] for event in events] == [
        "workflow_started",
        "error",
        "workflow_finished",
    ]
    assert events[1]["message"] == "stream exploded"
    assert events[2]["data"]["status"] == "failed"
    assert events[2]["data"]["error"] == "stream exploded"


def test_workflow_run_blocking_exception_returns_dify_error_payload(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    class FailingWorkflow:
        id = "wf-failing-blocking"
        _input_schema = None

        def get_user_input_field(self):
            return "prompt"

        async def run(self, **_kwargs):
            raise ValueError("blocking exploded")

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FailingWorkflow()))
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={
            "workflow_id": "wf-failing-blocking",
            "response_mode": "blocking",
            "conversation_id": "conv-failing",
            "user": "hello",
        },
    )

    assert response.status_code == 500
    payload = response.json()
    assert payload["event"] == "error"
    assert payload["code"] == "WORKFLOW_EXECUTION_ERROR"
    assert payload["message"] == "blocking exploded"
    assert payload["task_id"]
    assert payload["message_id"]


@pytest.mark.parametrize(
    ("selected_model", "model_type", "expected_runtime_model"),
    [
        ("chat-model", "chat", "chat-model"),
        ("embed-model", "embedding", None),
        ("rerank-model", "rerank", None),
    ],
)
def test_workflow_run_request_model_selection_is_scoped_to_chat_models(
    public_api_client,
    monkeypatch,
    auth_tokens,
    selected_model,
    model_type,
    expected_runtime_model,
):
    import agentclaw.database
    from agentclaw.api.registry import WorkflowRegistry

    captured: dict[str, object] = {}

    class FakeWorkflow:
        id = "wf-model"
        _input_schema = None
        _llm_manager = SimpleNamespace(
            _models_cache={
                selected_model: SimpleNamespace(model_type=model_type),
            }
        )

        def get_user_input_field(self):
            return "prompt"

        def _ensure_components(self):
            captured["ensure_components_called"] = True

        async def run(self, *, inputs, context, thread_id):
            captured["runtime_model_id"] = context.runtime_model_id
            captured["inputs"] = dict(inputs)
            return {
                "state": {
                    "__messages__": [{"role": "assistant", "content": "ok"}],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    async def process_file_inputs(input_data, workflow_inputs):
        return input_data

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FakeWorkflow()))
    monkeypatch.setattr(agentclaw.database, "process_file_inputs", process_file_inputs)

    response = public_api_client.post(
        "/api/workflow/run",
        headers=auth_header(auth_tokens.workflow),
        json={
            "workflow_id": "wf-model",
            "response_mode": "blocking",
            "user": "hello",
            "inputs": {"model": selected_model},
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "ok"
    assert captured["ensure_components_called"] is True
    assert captured["runtime_model_id"] == expected_runtime_model
    assert captured["inputs"]["model"] == selected_model


def test_confirm_action_requires_admin_and_resolves_sudo_confirmation(
    public_api_client,
    auth_tokens,
):
    from agentclaw.api.services.confirm_service import get_confirmation_manager

    manager = get_confirmation_manager()
    manager._pending.clear()
    confirmation = manager.create(
        "confirm-1",
        action="delete-file",
        description="Delete a generated file",
        require_sudo=True,
    )

    workflow_key_response = public_api_client.post(
        "/api/confirm/confirm-1",
        headers=auth_header(auth_tokens.workflow),
        json={"approved": True, "sudo_password": "test-password"},
    )
    admin_response = public_api_client.post(
        "/api/confirm/confirm-1",
        headers=auth_header(auth_tokens.admin),
        json={"approved": True, "sudo_password": "test-password"},
    )
    missing_response = public_api_client.post(
        "/api/confirm/missing",
        headers=auth_header(auth_tokens.admin),
        json={"approved": False},
    )

    assert workflow_key_response.status_code == 403
    assert admin_response.status_code == 200
    assert admin_response.json() == {
        "success": True,
        "confirm_id": "confirm-1",
        "approved": True,
        "require_sudo": True,
        "sudo_received": True,
        "status": "resolved",
        "message": "approved",
    }
    assert confirmation.result is True
    assert confirmation.sudo_password == "test-password"
    assert missing_response.status_code == 404

    manager._pending.clear()


def test_confirm_action_rejects_and_prevents_duplicate_resolution_mutation(
    public_api_client,
    auth_tokens,
):
    from agentclaw.api.services.confirm_service import get_confirmation_manager

    manager = get_confirmation_manager()
    manager._pending.clear()
    confirmation = manager.create(
        "confirm-reject",
        action="run-command",
        description="Run a high-risk command",
        require_sudo=False,
    )

    reject_response = public_api_client.post(
        "/api/confirm/confirm-reject",
        headers=auth_header(auth_tokens.admin),
        json={"approved": False},
    )
    duplicate_response = public_api_client.post(
        "/api/confirm/confirm-reject",
        headers=auth_header(auth_tokens.admin),
        json={"approved": True},
    )

    assert reject_response.status_code == 200
    assert reject_response.json() == {
        "success": True,
        "confirm_id": "confirm-reject",
        "approved": False,
        "require_sudo": False,
        "sudo_received": False,
        "status": "resolved",
        "message": "rejected",
    }
    assert confirmation.result is False
    assert duplicate_response.status_code == 404
    assert confirmation.result is False

    manager._pending.clear()


def test_truncate_messages_requires_admin_and_updates_checkpoint_state(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    from agentclaw.api.registry import WorkflowRegistry

    captured: dict[str, object] = {}
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "second answer"},
    ]

    class FakeSnapshot:
        values = {"__messages__": messages}

    class FakeGraph:
        async def aget_state(self, config):
            captured["get_config"] = config
            return FakeSnapshot()

        async def aupdate_state(self, config, state):
            captured["update_config"] = config
            captured["updated_messages"] = state["__messages__"]

    class FakeWorkflow:
        _checkpointer = object()

        async def _ensure_checkpointer(self):
            captured["ensure_checkpointer_called"] = True

        def _compile_to_langgraph(self):
            return FakeGraph()

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FakeWorkflow()))

    workflow_key_response = public_api_client.post(
        "/api/workflow/truncate",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "wf-1", "conversation_id": "conv-1", "keep_count": 2},
    )
    admin_response = public_api_client.post(
        "/api/workflow/truncate",
        headers=auth_header(auth_tokens.admin),
        json={"workflow_id": "wf-1", "conversation_id": "conv-1", "keep_count": 2},
    )

    assert workflow_key_response.status_code == 403
    assert admin_response.status_code == 200
    assert admin_response.json() == {
        "success": True,
        "truncated": True,
        "message_count": 2,
    }
    assert captured["ensure_checkpointer_called"] is True
    assert captured["get_config"] == {"configurable": {"thread_id": "conv-1"}}
    assert captured["update_config"] == {"configurable": {"thread_id": "conv-1"}}
    assert len(captured["updated_messages"]) == 3
    assert captured["updated_messages"][1:] == messages[:2]


def test_truncate_messages_reports_missing_state_without_updating_checkpoint(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    from agentclaw.api.registry import WorkflowRegistry

    captured = {"updated": False}

    class EmptyGraph:
        async def aget_state(self, config):
            return SimpleNamespace(values={})

        async def aupdate_state(self, config, state):
            captured["updated"] = True

    class FakeWorkflow:
        _checkpointer = object()

        async def _ensure_checkpointer(self):
            return None

        def _compile_to_langgraph(self):
            return EmptyGraph()

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FakeWorkflow()))

    response = public_api_client.post(
        "/api/workflow/truncate",
        headers=auth_header(auth_tokens.admin),
        json={"workflow_id": "wf-1", "conversation_id": "missing", "keep_count": 1},
    )

    assert response.status_code == 404
    assert "No conversation state found" in response.json()["error"]
    assert captured["updated"] is False


def test_truncate_messages_missing_workflow_and_checkpointer_errors(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    from agentclaw.api.registry import WorkflowRegistry

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: None))
    missing_workflow = public_api_client.post(
        "/api/workflow/truncate",
        headers=auth_header(auth_tokens.admin),
        json={"workflow_id": "missing", "conversation_id": "conv-1", "keep_count": 1},
    )

    class NoCheckpointerWorkflow:
        _checkpointer = None

        async def _ensure_checkpointer(self):
            return None

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: NoCheckpointerWorkflow()),
    )
    no_checkpointer = public_api_client.post(
        "/api/workflow/truncate",
        headers=auth_header(auth_tokens.admin),
        json={"workflow_id": "wf-1", "conversation_id": "conv-1", "keep_count": 1},
    )

    assert missing_workflow.status_code == 404
    assert "Workflow 'missing' not found" in missing_workflow.json()["error"]
    assert no_checkpointer.status_code == 500
    assert no_checkpointer.json()["error"] == "Checkpointer not available"


def test_truncate_messages_returns_noop_when_keep_count_exceeds_user_messages(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    from agentclaw.api.registry import WorkflowRegistry

    captured = {"updated": False}
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "first answer"},
    ]

    class FakeGraph:
        async def aget_state(self, config):
            return SimpleNamespace(values={"__messages__": messages})

        async def aupdate_state(self, config, state):
            captured["updated"] = True

    class FakeWorkflow:
        _checkpointer = object()

        async def _ensure_checkpointer(self):
            return None

        def _compile_to_langgraph(self):
            return FakeGraph()

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FakeWorkflow()))

    response = public_api_client.post(
        "/api/workflow/truncate",
        headers=auth_header(auth_tokens.admin),
        json={"workflow_id": "wf-1", "conversation_id": "conv-1", "keep_count": 5},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "truncated": False,
        "message_count": 2,
    }
    assert captured["updated"] is False


def test_compress_context_allows_workflow_key_and_syncs_checkpoint_and_conversation(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.services import conversation_service
    from agentclaw.runtime import context_compressor as compressor_module

    captured: dict[str, object] = {}
    original_messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
    compressed_messages = [
        {"role": "assistant", "content": "summary text", "is_summary": True},
    ]

    class FakeSnapshot:
        values = {"__messages__": original_messages}

    class FakeGraph:
        async def aget_state(self, config):
            captured["get_config"] = config
            return FakeSnapshot()

        async def aupdate_state(self, config, state):
            captured["update_config"] = config
            captured["checkpoint_messages"] = state["__messages__"]

    class FakeWorkflow:
        _checkpointer = object()
        _llm_manager = "llm-manager"

        async def _ensure_checkpointer(self):
            captured["ensure_checkpointer_called"] = True

        def _ensure_components(self):
            captured["ensure_components_called"] = True

        def _compile_to_langgraph(self):
            return FakeGraph()

    class FakeCompressor:
        async def compress(self, messages, llm_manager=None):
            captured["compress_messages"] = list(messages)
            captured["compress_llm_manager"] = llm_manager
            return compressed_messages, {
                "compressed": True,
                "original_count": 2,
                "compressed_count": 1,
                "compressed_message_count": 2,
                "summary_length": 12,
                "has_system": False,
                "has_welcome": False,
                "used_llm": True,
                "context_tokens": 42,
            }

        async def generate_memory_update(self, summary_text, llm_manager=None):
            captured["memory_summary_text"] = summary_text
            captured["memory_llm_manager"] = llm_manager
            return ""

    class FakeConversationService:
        async def get_conversation(self, workflow_id, conversation_id):
            captured["conversation_get"] = (workflow_id, conversation_id)
            return {
                "id": conversation_id,
                "workflow_id": workflow_id,
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "world"},
                ],
            }

        async def update_conversation(self, workflow_id, conversation_id, messages):
            captured["conversation_update"] = (workflow_id, conversation_id, messages)
            return {"id": conversation_id, "messages": messages}

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FakeWorkflow()))
    monkeypatch.setattr(compressor_module, "ContextCompressor", FakeCompressor)
    monkeypatch.setattr(
        conversation_service,
        "get_conversation_service",
        lambda: FakeConversationService(),
    )

    response = public_api_client.post(
        "/api/workflow/compress",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "wf-1", "conversation_id": "conv-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["compressed"] is True
    assert payload["summary"] == "summary text"
    assert payload["compressed_count"] == 1
    assert payload["compressed_message_count"] == 2
    assert payload["used_llm"] is True
    assert payload["context_tokens"] == 42
    assert captured["ensure_checkpointer_called"] is True
    assert captured["ensure_components_called"] is True
    assert captured["get_config"] == {"configurable": {"thread_id": "conv-1"}}
    assert captured["update_config"] == {"configurable": {"thread_id": "conv-1"}}
    assert captured["checkpoint_messages"][1:] == compressed_messages
    assert captured["compress_messages"] == original_messages
    assert captured["compress_llm_manager"] == "llm-manager"
    assert captured["memory_summary_text"] == "summary text"
    assert captured["memory_llm_manager"] == "llm-manager"

    workflow_id, conversation_id, db_messages = captured["conversation_update"]
    assert (workflow_id, conversation_id) == ("wf-1", "conv-1")
    assert all(message["compressed_out"] is True for message in db_messages[:-1])
    assert db_messages[-1]["is_summary"] is True
    assert db_messages[-1]["content"] == "summary text"
    assert db_messages[-1]["original_message_count"] == 2


def test_compress_context_returns_not_compressed_for_empty_checkpoint_messages(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.runtime import context_compressor as compressor_module

    captured = {"updated": False}

    class EmptyGraph:
        async def aget_state(self, config):
            return SimpleNamespace(values={"__messages__": []})

        async def aupdate_state(self, config, state):
            captured["updated"] = True

    class FakeWorkflow:
        _checkpointer = object()

        async def _ensure_checkpointer(self):
            return None

        def _compile_to_langgraph(self):
            return EmptyGraph()

    class ShouldNotRunCompressor:
        async def compress(self, messages, llm_manager=None):
            raise AssertionError("compressor should not run when checkpoint has no messages")

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: FakeWorkflow()))
    monkeypatch.setattr(compressor_module, "ContextCompressor", ShouldNotRunCompressor)

    response = public_api_client.post(
        "/api/workflow/compress",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "wf-1", "conversation_id": "conv-empty"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "workflow_id": "wf-1",
        "conversation_id": "conv-empty",
        "compressed": False,
        "original_count": 0,
        "compressed_count": 0,
        "compressed_message_count": 0,
        "summary_length": 0,
        "summary": "",
        "has_system": False,
        "has_welcome": False,
        "used_llm": False,
        "context_tokens": 0,
        "memory_updated": False,
        "memory_path": "",
    }
    assert captured["updated"] is False


def test_compress_context_validates_required_fields_and_workflow_state(
    public_api_client,
    monkeypatch,
    auth_tokens,
):
    from agentclaw.api.registry import WorkflowRegistry

    missing_workflow_id = public_api_client.post(
        "/api/workflow/compress",
        headers=auth_header(auth_tokens.workflow),
        json={"conversation_id": "conv-1"},
    )
    missing_conversation_id = public_api_client.post(
        "/api/workflow/compress",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "wf-1"},
    )

    monkeypatch.setattr(WorkflowRegistry, "get", classmethod(lambda cls, workflow_id: None))
    missing_workflow = public_api_client.post(
        "/api/workflow/compress",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "missing", "conversation_id": "conv-1"},
    )

    class NoCheckpointerWorkflow:
        _checkpointer = None

        async def _ensure_checkpointer(self):
            return None

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: NoCheckpointerWorkflow()),
    )
    no_checkpointer = public_api_client.post(
        "/api/workflow/compress",
        headers=auth_header(auth_tokens.workflow),
        json={"workflow_id": "wf-1", "conversation_id": "conv-1"},
    )

    assert missing_workflow_id.status_code == 400
    assert missing_workflow_id.json()["code"] == "INVALID_REQUEST"
    assert missing_conversation_id.status_code == 400
    assert missing_conversation_id.json()["code"] == "INVALID_REQUEST"
    assert missing_workflow.status_code == 404
    assert missing_workflow.json()["code"] == "WORKFLOW_NOT_FOUND"
    assert no_checkpointer.status_code == 500
    assert no_checkpointer.json()["code"] == "OPERATION_FAILED"

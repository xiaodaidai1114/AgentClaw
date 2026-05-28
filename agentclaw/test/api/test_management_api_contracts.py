from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentclaw.test.conftest import auth_header


pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _reset_public_session_state():
    from agentclaw.api.routers.public.session import reset_public_user_state

    reset_public_user_state()


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


def test_admin_model_management_routes_use_model_service(admin_api_client, auth_tokens):
    from agentclaw.api.routers.admin import models as models_router

    model = {
        "id": "model-1",
        "provider": "openai",
        "model": "gpt-test",
        "model_type": "chat",
        "temperature": 0.1,
        "max_tokens": 1024,
        "timeout": 30,
        "status": "primary",
        "is_current": True,
    }
    fallback_state = {
        "is_fallback": False,
        "fallback_reason": None,
        "fallback_until": None,
        "failure_count": 0,
        "current_model_id": "model-1",
        "default_model_id": "model-1",
        "fallback_model_id": "model-2",
    }
    calls: list[tuple] = []

    class FakeModelService:
        def list_available_models(self):
            calls.append(("list_available",))
            return {"models": [model], "default_model_id": "model-1"}

        def list_models(self):
            calls.append(("list",))
            return {"models": [model], "fallback_state": fallback_state}

        def get_model(self, model_id):
            calls.append(("get", model_id))
            return model if model_id == "model-1" else None

        def update_model(self, model_id, **params):
            calls.append(("update", model_id, params))
            return {**model, **params} if model_id == "model-1" else None

        def force_fallback(self, model_id, reason):
            calls.append(("fallback", model_id, reason))
            return {**fallback_state, "is_fallback": True, "fallback_reason": reason}

        def force_primary(self, model_id):
            calls.append(("recover", model_id))
            return fallback_state

    admin_api_client.app.dependency_overrides[
        models_router.get_model_service
    ] = lambda: FakeModelService()
    headers = auth_header(auth_tokens.admin)

    available = admin_api_client.get("/admin/models/available", headers=headers)
    listing = admin_api_client.get("/admin/models", headers=headers)
    detail = admin_api_client.get("/admin/models/model-1", headers=headers)
    updated = admin_api_client.put(
        "/admin/models/model-1",
        headers=headers,
        json={"temperature": 0.2, "max_tokens": 2048},
    )
    fallback = admin_api_client.post(
        "/admin/models/model-1/fallback",
        headers=headers,
        json={"reason": "contract-test"},
    )
    recovered = admin_api_client.post("/admin/models/model-1/recover", headers=headers)
    assert available.status_code == 200
    assert available.json()["default_model_id"] == "model-1"
    assert listing.status_code == 200
    assert listing.json()["fallback_state"]["current_model_id"] == "model-1"
    assert detail.status_code == 200
    assert detail.json()["id"] == "model-1"
    assert updated.status_code == 200
    assert updated.json()["temperature"] == 0.2
    assert updated.json()["max_tokens"] == 2048
    assert fallback.status_code == 200
    assert fallback.json()["is_fallback"] is True
    assert recovered.status_code == 200
    assert recovered.json()["is_fallback"] is False
    assert ("update", "model-1", {"temperature": 0.2, "max_tokens": 2048}) in calls
    assert ("fallback", "model-1", "contract-test") in calls


def test_admin_prompt_routes_cover_update_reset_history_rollback_and_preview(
    admin_api_client,
    auth_tokens,
):
    from agentclaw.api.routers.admin import prompts as prompts_router

    base_prompt = {
        "workflow_id": "wf-1",
        "prompt_key": "system",
        "content": "Hello {name}",
        "default_content": "Hello {name}",
        "is_custom": False,
        "version": 1,
        "created_at": None,
        "updated_by": None,
        "variables": ["name"],
    }
    calls: list[tuple] = []

    class FakePromptService:
        def list_prompts(self, workflow_id):
            calls.append(("list", workflow_id))
            return [base_prompt]

        def get_prompt(self, workflow_id, prompt_key):
            calls.append(("get", workflow_id, prompt_key))
            return base_prompt if prompt_key == "system" else None

        async def update_prompt(self, workflow_id, prompt_key, content, updated_by):
            calls.append(("update", workflow_id, prompt_key, content, updated_by))
            return {**base_prompt, "content": content, "is_custom": True, "version": 2}

        async def reset_prompt(self, workflow_id, prompt_key, updated_by):
            calls.append(("reset", workflow_id, prompt_key, updated_by))
            return base_prompt

        async def get_history(self, workflow_id, prompt_key, limit):
            calls.append(("history", workflow_id, prompt_key, limit))
            return [
                {"version": 2, "content": "Hi {name}", "created_at": None, "updated_by": "admin"},
                {"version": 1, "content": "Hello {name}", "created_at": None, "updated_by": None},
            ]

        async def rollback(self, workflow_id, prompt_key, version, updated_by):
            calls.append(("rollback", workflow_id, prompt_key, version, updated_by))
            return {**base_prompt, "version": version, "updated_by": updated_by}

        def preview_prompt(self, workflow_id, content, variables):
            calls.append(("preview", workflow_id, content, variables))
            return content.format(**variables)

    admin_api_client.app.dependency_overrides[
        prompts_router.get_prompt_service
    ] = lambda: FakePromptService()
    headers = auth_header(auth_tokens.admin)

    listed = admin_api_client.get("/admin/prompts/wf-1", headers=headers)
    detail = admin_api_client.get("/admin/prompts/wf-1/system", headers=headers)
    updated = admin_api_client.put(
        "/admin/prompts/wf-1/system",
        headers=headers,
        json={"content": "Hi {name}"},
    )
    reset = admin_api_client.post("/admin/prompts/wf-1/system/reset", headers=headers)
    history = admin_api_client.get(
        "/admin/prompts/wf-1/system/history?limit=2",
        headers=headers,
    )
    rollback = admin_api_client.post(
        "/admin/prompts/wf-1/system/rollback",
        headers=headers,
        json={"version": 1},
    )
    preview = admin_api_client.post(
        "/admin/prompts/wf-1/preview",
        headers=headers,
        json={"content": "Hello {name}", "variables": {"name": "AgentClaw"}},
    )
    assert listed.status_code == 200
    assert listed.json()["prompts"][0]["prompt_key"] == "system"
    assert detail.status_code == 200
    assert detail.json()["variables"] == ["name"]
    assert updated.status_code == 200
    assert updated.json()["content"] == "Hi {name}"
    assert updated.json()["is_custom"] is True
    assert reset.status_code == 200
    assert reset.json()["version"] == 1
    assert history.status_code == 200
    assert [item["version"] for item in history.json()["history"]] == [2, 1]
    assert rollback.status_code == 200
    assert rollback.json()["updated_by"] == "admin"
    assert preview.status_code == 200
    assert preview.json()["rendered"] == "Hello AgentClaw"
    assert ("update", "wf-1", "system", "Hi {name}", "admin") in calls
    assert ("rollback", "wf-1", "system", 1, "admin") in calls


def test_admin_conversation_routes_forward_identity_and_feedback_fields(
    admin_api_client,
    auth_tokens,
):
    from agentclaw.api.routers.admin import conversations as conversations_router

    calls: list[tuple] = []
    messages = [{"role": "user", "content": "hello", "timestamp": 1}]

    class FakeConversationService:
        async def list_conversations(self, **kwargs):
            calls.append(("list", kwargs))
            return {"conversations": [], "total": 0, "page": kwargs["page"], "page_size": kwargs["page_size"]}

        async def create_conversation(self, **kwargs):
            calls.append(("create", kwargs))
            return {"id": "conv-1", "messages": [], **kwargs}

        async def get_conversation(self, workflow_id, conversation_id, **kwargs):
            calls.append(("get", workflow_id, conversation_id, kwargs))
            return {
                "id": conversation_id,
                "workflow_id": workflow_id,
                "title": "old",
                "messages": messages,
                "source": "admin",
            }

        async def update_conversation(self, **kwargs):
            calls.append(("update", kwargs))
            return {
                "id": kwargs["conversation_id"],
                "workflow_id": kwargs["workflow_id"],
                "title": kwargs["title"],
                "messages": kwargs["messages"],
                "source": "admin",
            }

        async def delete_conversation(self, workflow_id, conversation_id, **kwargs):
            calls.append(("delete", workflow_id, conversation_id, kwargs))
            return True

        async def submit_feedback(self, **kwargs):
            calls.append(("submit_feedback", kwargs))
            return True

        async def get_feedback(self, conversation_id):
            calls.append(("get_feedback", conversation_id))
            return {0: "like"}

    admin_api_client.app.dependency_overrides[
        conversations_router.get_conversation_service
    ] = lambda: FakeConversationService()
    headers = auth_header(auth_tokens.admin)

    created = admin_api_client.post(
        "/admin/conversations",
        headers=headers,
        json={
            "workflow_id": "wf-1",
            "title": "Admin conversation",
            "source": "admin",
            "owner_id": "owner-1",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
        },
    )
    listed = admin_api_client.get("/admin/conversations/wf-1?source=admin", headers=headers)
    detail = admin_api_client.get("/admin/conversations/wf-1/conv-1", headers=headers)
    updated = admin_api_client.put(
        "/admin/conversations/wf-1/conv-1",
        headers=headers,
        json={"title": "Updated", "messages": messages},
    )
    feedback = admin_api_client.post(
        "/admin/conversations/wf-1/conv-1/feedback",
        headers=headers,
        json={"message_index": 0, "feedback": "like"},
    )
    feedback_list = admin_api_client.get(
        "/admin/conversations/wf-1/conv-1/feedback",
        headers=headers,
    )
    deleted = admin_api_client.delete("/admin/conversations/wf-1/conv-1", headers=headers)

    assert created.status_code == 200
    assert created.json()["owner_id"] == "owner-1"
    assert created.json()["tenant_id"] == "tenant-1"
    assert listed.status_code == 200
    assert detail.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated"
    assert feedback.status_code == 200
    assert feedback.json() == {"success": True}
    assert feedback_list.status_code == 200
    assert feedback_list.json()["feedbacks"] == {"0": "like"}
    assert deleted.status_code == 200
    assert deleted.json() == {"success": True}
    assert calls[0] == (
        "create",
        {
            "workflow_id": "wf-1",
            "title": "Admin conversation",
            "source": "admin",
            "owner_id": "owner-1",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
        },
    )
    assert ("submit_feedback", {"conversation_id": "conv-1", "message_index": 0, "feedback": "like"}) in calls


def test_admin_delete_conversation_returns_404_when_nothing_was_deleted(
    admin_api_client,
    auth_tokens,
):
    from agentclaw.api.routers.admin import conversations as conversations_router

    class FakeConversationService:
        async def delete_conversation(self, workflow_id, conversation_id, **kwargs):
            return False

    admin_api_client.app.dependency_overrides[
        conversations_router.get_conversation_service
    ] = lambda: FakeConversationService()

    response = admin_api_client.delete(
        "/admin/conversations/wf-1/conv-missing",
        headers=auth_header(auth_tokens.admin),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found"


def test_public_conversation_routes_force_public_source_for_full_lifecycle(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.routers.public import conversations as conversations_router
    from agentclaw.api.registry import WorkflowRegistry

    class PublicWorkflow:
        id = "wf-1"
        public_share_enabled = True
        public_share_token = "share-test"
        rate_limit = ""

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: PublicWorkflow() if workflow_id == "wf-1" else None),
    )

    calls: list[tuple] = []
    messages = [
        {"role": "user", "content": "hello", "timestamp": 1},
        {"role": "assistant", "content": "world", "timestamp": 2},
    ]

    class FakeConversationService:
        async def list_conversations(self, **kwargs):
            calls.append(("list", kwargs))
            return {
                "conversations": [
                    {
                        "id": "conv-1",
                        "workflow_id": kwargs["workflow_id"],
                        "title": "public",
                        "messages": messages,
                        "source": "public",
                        "owner_id": kwargs["owner_id"],
                    }
                ],
                "total": 1,
                "page": kwargs["page"],
                "page_size": kwargs["page_size"],
            }

        async def create_conversation(self, **kwargs):
            calls.append(("create", kwargs))
            return {"id": "conv-1", "messages": [], **kwargs}

        async def get_conversation(self, workflow_id, conversation_id, **kwargs):
            calls.append(("get", workflow_id, conversation_id, kwargs))
            return {
                "id": conversation_id,
                "workflow_id": workflow_id,
                "title": "public",
                "messages": messages,
                "source": "public",
                "owner_id": kwargs["owner_id"],
            }

        async def update_conversation(self, **kwargs):
            calls.append(("update", kwargs))
            return {
                "id": kwargs["conversation_id"],
                "workflow_id": kwargs["workflow_id"],
                "title": kwargs["title"],
                "messages": kwargs["messages"],
                "source": kwargs["source"],
            }

        async def delete_conversation(self, workflow_id, conversation_id, **kwargs):
            calls.append(("delete", workflow_id, conversation_id, kwargs))
            return True

        async def submit_feedback(self, **kwargs):
            calls.append(("submit_feedback", kwargs))
            return True

        async def get_feedback(self, conversation_id):
            calls.append(("get_feedback", conversation_id))
            return {1: "dislike"}

    public_api_client.app.dependency_overrides[
        conversations_router.get_conversation_service
    ] = lambda: FakeConversationService()
    session = _open_public_session(public_api_client, "wf-1")
    assert session.status_code == 200

    created = public_api_client.post(
        "/api/conversations?share_token=share-test",
        headers=_public_page_headers(),
        json={
            "workflow_id": "wf-1",
            "title": "Public conversation",
            "source": "admin",
            "owner_id": "owner-1",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
        },
    )
    listed = public_api_client.get("/api/conversations/wf-1?source=admin&share_token=share-test", headers=_public_page_headers())
    detail = public_api_client.get("/api/conversations/wf-1/conv-1?share_token=share-test", headers=_public_page_headers())
    updated = public_api_client.put(
        "/api/conversations/wf-1/conv-1?share_token=share-test",
        headers=_public_page_headers(),
        json={"title": "Updated public", "messages": messages},
    )
    submitted = public_api_client.post(
        "/api/conversations/wf-1/conv-1/feedback?share_token=share-test",
        headers=_public_page_headers(),
        json={"message_index": 1, "feedback": "dislike"},
    )
    feedback = public_api_client.get("/api/conversations/wf-1/conv-1/feedback?share_token=share-test", headers=_public_page_headers())
    deleted = public_api_client.delete("/api/conversations/wf-1/conv-1?share_token=share-test", headers=_public_page_headers())

    assert created.status_code == 200
    assert created.json()["source"] == "public"
    assert created.json()["owner_id"]
    assert created.json()["user_id"] is None
    assert created.json()["tenant_id"] is None
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["conversations"][0]["owner_id"] == created.json()["owner_id"]
    assert detail.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["source"] == "public"
    assert submitted.status_code == 200
    assert feedback.status_code == 200
    assert feedback.json()["feedbacks"] == {"1": "dislike"}
    assert deleted.status_code == 200

    create_call = next(call for call in calls if call[0] == "create")
    list_call = next(call for call in calls if call[0] == "list")
    update_call = next(call for call in calls if call[0] == "update")
    delete_call = next(call for call in calls if call[0] == "delete")
    get_calls = [call for call in calls if call[0] == "get"]

    assert create_call[1]["source"] == "public"
    assert create_call[1]["owner_id"]
    assert create_call[1]["user_id"] is None
    assert create_call[1]["tenant_id"] is None
    assert list_call[1]["source"] == "public"
    assert list_call[1]["owner_id"] == create_call[1]["owner_id"]
    assert update_call[1]["source"] == "public"
    assert update_call[1]["owner_id"] == create_call[1]["owner_id"]
    assert delete_call[3]["source"] == "public"
    assert delete_call[3]["owner_id"] == create_call[1]["owner_id"]
    assert get_calls
    assert all(call[3]["source"] == "public" for call in get_calls)
    assert all(call[3]["owner_id"] == create_call[1]["owner_id"] for call in get_calls)


def test_public_conversation_routes_require_published_workflow_and_share_token(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.routers.public import conversations as conversations_router
    from agentclaw.api.registry import WorkflowRegistry

    class PrivateWorkflow:
        id = "wf-private"
        public_share_enabled = False
        public_share_token = "share-test"

    class PublicWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"

    workflows = {
        "wf-private": PrivateWorkflow(),
        "wf-public": PublicWorkflow(),
    }
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: workflows.get(workflow_id)),
    )

    class FakeConversationService:
        async def create_conversation(self, **kwargs):
            raise AssertionError("unauthorized public conversation must not be created")

        async def update_conversation(self, **kwargs):
            raise AssertionError("unauthorized public conversation must not be updated")

    public_api_client.app.dependency_overrides[
        conversations_router.get_conversation_service
    ] = lambda: FakeConversationService()

    unpublished = public_api_client.post(
        "/api/conversations?share_token=share-test",
        json={"workflow_id": "wf-private", "title": "private"},
    )
    missing_token = public_api_client.post(
        "/api/conversations",
        json={"workflow_id": "wf-public", "title": "missing token"},
    )
    wrong_token_update = public_api_client.put(
        "/api/conversations/wf-public/conv-1?share_token=wrong",
        headers=_public_page_headers(),
        json={"title": "wrong token"},
    )

    assert unpublished.status_code == 404
    assert unpublished.json()["code"] == "WORKFLOW_NOT_FOUND"
    assert missing_token.status_code == 403
    assert missing_token.json()["code"] == "FORBIDDEN"
    assert wrong_token_update.status_code == 403
    assert wrong_token_update.json()["code"] == "FORBIDDEN"


def test_public_conversation_routes_apply_rate_limit(public_api_client, monkeypatch):
    from agentclaw.api.routers.public import access as public_access
    from agentclaw.api.routers.public import conversations as conversations_router
    from agentclaw.api.registry import WorkflowRegistry

    class PublicWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        rate_limit = "1/min"

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: PublicWorkflow() if workflow_id == "wf-public" else None),
    )
    public_access.reset_public_rate_limiter()

    class FakeConversationService:
        async def list_conversations(self, **kwargs):
            return {"conversations": [], "total": 0, "page": kwargs["page"], "page_size": kwargs["page_size"]}

        async def create_conversation(self, **kwargs):
            return {"id": "conv-1", "messages": [], **kwargs}

    public_api_client.app.dependency_overrides[
        conversations_router.get_conversation_service
    ] = lambda: FakeConversationService()
    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    body = {"workflow_id": "wf-public", "title": "Public conversation"}
    first = public_api_client.post("/api/conversations?share_token=share-test", headers=_public_page_headers(), json=body)
    second = public_api_client.post("/api/conversations?share_token=share-test", headers=_public_page_headers(), json=body)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


def test_public_conversation_routes_require_same_origin_public_session(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.routers.public import conversations as conversations_router
    from agentclaw.api.registry import WorkflowRegistry

    class PublicWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        rate_limit = ""

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: PublicWorkflow() if workflow_id == "wf-public" else None),
    )

    class FakeConversationService:
        async def create_conversation(self, **kwargs):
            raise AssertionError("public conversation must require a same-origin public page session")

    public_api_client.app.dependency_overrides[
        conversations_router.get_conversation_service
    ] = lambda: FakeConversationService()

    response = public_api_client.post(
        "/api/conversations?share_token=share-test",
        json={"workflow_id": "wf-public", "title": "Public conversation"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_public_conversation_creation_consumes_configured_quota(public_api_client, monkeypatch):
    from agentclaw.api.routers.public import access as public_access
    from agentclaw.api.routers.public import conversations as conversations_router
    from agentclaw.api.registry import WorkflowRegistry

    class PublicWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"
        rate_limit = ""
        public_conversation_limit = 1

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: PublicWorkflow() if workflow_id == "wf-public" else None),
    )
    public_access.reset_public_rate_limiter()

    class FakeConversationService:
        async def create_conversation(self, **kwargs):
            return {"id": "conv-1", "messages": [], **kwargs}

    public_api_client.app.dependency_overrides[
        conversations_router.get_conversation_service
    ] = lambda: FakeConversationService()
    session = _open_public_session(public_api_client, "wf-public")
    assert session.status_code == 200

    body = {"workflow_id": "wf-public", "title": "Public conversation"}
    first = public_api_client.post("/api/conversations?share_token=share-test", headers=_public_page_headers(), json=body)
    second = public_api_client.post("/api/conversations?share_token=share-test", headers=_public_page_headers(), json=body)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


def test_scheduler_job_lifecycle_routes_use_admin_auth_and_scheduler(monkeypatch, auth_tokens):
    from agentclaw.scheduler import api as scheduler_api
    from agentclaw.scheduler.models import (
        ExecutionStatus,
        JobExecution,
        JobStatus,
        ScheduledJob,
        TriggerConfig,
    )

    app = FastAPI()
    app.include_router(scheduler_api.router, prefix="/api")
    client = TestClient(app)

    now = datetime.now(timezone.utc)
    job = ScheduledJob(
        id="job-1",
        name="Original job",
        workflow_id="wf-1",
        trigger=TriggerConfig(type="cron", expression="*/5 * * * *"),
        inputs={"user_input": "hello"},
        created_at=now,
        updated_at=now,
    )
    execution = JobExecution(
        id="execution-1",
        job_id="job-1",
        status=ExecutionStatus.SUCCESS,
        trigger_source="manual",
        inputs={"user_input": "hello"},
        outputs={"answer": "ok"},
        started_at=now,
        ended_at=now,
        duration_ms=10,
    )
    calls: list[tuple] = []

    class FakeScheduler:
        async def add_job(self, request):
            calls.append(("add", request.name, request.webhook.secret))
            return job.model_copy(update={"name": request.name, "webhook": request.webhook})

        async def list_jobs(self, status=None, workflow_id=None, page=1, limit=50):
            calls.append(("list", status, workflow_id, page, limit))
            return [job], 1

        async def get_job(self, job_id):
            calls.append(("get", job_id))
            return job if job_id == "job-1" else None

        async def update_job(self, job_id, request):
            calls.append(("update", job_id, request.name))
            return job.model_copy(update={"name": request.name or job.name})

        async def remove_job(self, job_id):
            calls.append(("remove", job_id))
            return job_id == "job-1"

        async def pause_job(self, job_id):
            calls.append(("pause", job_id))
            return job.model_copy(update={"status": JobStatus.PAUSED})

        async def resume_job(self, job_id):
            calls.append(("resume", job_id))
            return job.model_copy(update={"status": JobStatus.ENABLED})

        async def trigger_job(self, job_id, **kwargs):
            calls.append(("trigger", job_id, kwargs))
            return "execution-1"

        async def list_executions(self, job_id, page=1, limit=20):
            calls.append(("list_executions", job_id, page, limit))
            return [execution], 1

        async def get_execution(self, execution_id):
            calls.append(("get_execution", execution_id))
            return execution if execution_id == "execution-1" else None

    monkeypatch.setattr(scheduler_api, "_get_scheduler", lambda: FakeScheduler())
    headers = auth_header(auth_tokens.admin)

    created = client.post(
        "/api/scheduler/jobs",
        headers=headers,
        json={
            "name": "Created job",
            "workflow_id": "wf-1",
            "trigger": {"type": "cron", "expression": "*/5 * * * *"},
            "inputs": {"user_input": "hello"},
            "webhook": {"enabled": True, "secret": "local-secret"},
        },
    )
    listed = client.get("/api/scheduler/jobs?status=enabled&workflow_id=wf-1", headers=headers)
    detail = client.get("/api/scheduler/jobs/job-1", headers=headers)
    updated = client.put("/api/scheduler/jobs/job-1", headers=headers, json={"name": "Updated job"})
    paused = client.post("/api/scheduler/jobs/job-1/pause", headers=headers)
    resumed = client.post("/api/scheduler/jobs/job-1/resume", headers=headers)
    triggered = client.post("/api/scheduler/jobs/job-1/trigger", headers=headers)
    job_with_webhook = job.model_copy(
        update={
            "webhook": job.webhook.model_copy(
                update={"enabled": True, "secret": "local-secret", "allow_input_override": True}
            )
        }
    )

    class WebhookScheduler(FakeScheduler):
        async def get_job(self, job_id):
            return job_with_webhook

    monkeypatch.setattr(scheduler_api, "_get_scheduler", lambda: WebhookScheduler())
    webhook_forbidden = client.post(
        "/api/scheduler/jobs/job-1/webhook",
        headers={"X-Webhook-Secret": "wrong"},
        json={"user_input": "webhook"},
    )
    webhook = client.post(
        "/api/scheduler/jobs/job-1/webhook",
        headers={"X-Webhook-Secret": "local-secret"},
        json={"user_input": "webhook"},
    )
    executions = client.get("/api/scheduler/jobs/job-1/executions", headers=headers)
    execution_detail = client.get(
        "/api/scheduler/jobs/job-1/executions/execution-1",
        headers=headers,
    )
    deleted = client.delete("/api/scheduler/jobs/job-1", headers=headers)
    workflow_key_forbidden = client.get(
        "/api/scheduler/jobs",
        headers=auth_header(auth_tokens.workflow),
    )

    assert created.status_code == 201
    assert created.json()["name"] == "Created job"
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert detail.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated job"
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "enabled"
    assert triggered.status_code == 200
    assert triggered.json()["execution_id"] == "execution-1"
    assert webhook_forbidden.status_code == 403
    assert webhook.status_code == 200
    assert webhook.json()["execution_id"] == "execution-1"
    assert executions.status_code == 200
    assert executions.json()["executions"][0]["outputs"]["answer"] == "ok"
    assert execution_detail.status_code == 200
    assert execution_detail.json()["id"] == "execution-1"
    assert deleted.status_code == 200
    assert deleted.json() == {"success": True}
    assert workflow_key_forbidden.status_code == 403
    assert any(call[0] == "trigger" and call[2]["trigger_source"] == "manual" for call in calls)

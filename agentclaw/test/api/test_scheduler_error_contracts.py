from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentclaw.test.conftest import auth_header


pytestmark = pytest.mark.api


def _scheduler_client():
    from agentclaw.scheduler import api as scheduler_api

    app = FastAPI()
    app.include_router(scheduler_api.router, prefix="/api")
    return TestClient(app), scheduler_api


def _valid_job_payload(**overrides):
    payload = {
        "name": "Nightly job",
        "workflow_id": "wf-1",
        "trigger": {"type": "cron", "expression": "*/5 * * * *"},
        "inputs": {"user_input": "hello"},
    }
    payload.update(overrides)
    return payload


def test_scheduler_routes_report_503_when_scheduler_is_unavailable(monkeypatch, auth_tokens):
    client, scheduler_api = _scheduler_client()
    monkeypatch.setattr(scheduler_api, "_get_scheduler", lambda: None)
    headers = auth_header(auth_tokens.admin)

    responses = [
        client.post("/api/scheduler/jobs", headers=headers, json=_valid_job_payload()),
        client.get("/api/scheduler/jobs", headers=headers),
        client.get("/api/scheduler/jobs/job-1", headers=headers),
        client.put("/api/scheduler/jobs/job-1", headers=headers, json={"name": "Updated"}),
        client.delete("/api/scheduler/jobs/job-1", headers=headers),
        client.post("/api/scheduler/jobs/job-1/pause", headers=headers),
        client.post("/api/scheduler/jobs/job-1/resume", headers=headers),
        client.post("/api/scheduler/jobs/job-1/trigger", headers=headers),
        client.get("/api/scheduler/jobs/job-1/executions", headers=headers),
        client.get("/api/scheduler/jobs/job-1/executions/execution-1", headers=headers),
        client.post("/api/scheduler/jobs/job-1/webhook", headers={"X-Webhook-Secret": "secret"}),
    ]

    assert {response.status_code for response in responses} == {503}
    assert all(response.json()["code"] == "SCHEDULER_NOT_AVAILABLE" for response in responses)


def test_scheduler_list_rejects_invalid_status_before_querying_scheduler(monkeypatch, auth_tokens):
    client, scheduler_api = _scheduler_client()
    calls: list[str] = []

    class FakeScheduler:
        async def list_jobs(self, *args, **kwargs):
            calls.append("list_jobs")
            return [], 0

    monkeypatch.setattr(scheduler_api, "_get_scheduler", lambda: FakeScheduler())

    response = client.get(
        "/api/scheduler/jobs?status=unknown",
        headers=auth_header(auth_tokens.admin),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert calls == []


def test_scheduler_missing_resources_return_404(monkeypatch, auth_tokens):
    client, scheduler_api = _scheduler_client()
    headers = auth_header(auth_tokens.admin)

    class FakeScheduler:
        async def get_job(self, job_id):
            return None

        async def update_job(self, job_id, request):
            return None

        async def remove_job(self, job_id):
            return False

        async def pause_job(self, job_id):
            return None

        async def resume_job(self, job_id):
            return None

        async def trigger_job(self, job_id, **kwargs):
            raise ValueError(f"Job '{job_id}' not found")

    monkeypatch.setattr(scheduler_api, "_get_scheduler", lambda: FakeScheduler())

    responses = [
        client.get("/api/scheduler/jobs/missing", headers=headers),
        client.put("/api/scheduler/jobs/missing", headers=headers, json={"name": "Updated"}),
        client.delete("/api/scheduler/jobs/missing", headers=headers),
        client.post("/api/scheduler/jobs/missing/pause", headers=headers),
        client.post("/api/scheduler/jobs/missing/resume", headers=headers),
        client.post("/api/scheduler/jobs/missing/trigger", headers=headers),
        client.post("/api/scheduler/jobs/missing/webhook", headers={"X-Webhook-Secret": "secret"}),
    ]

    assert {response.status_code for response in responses} == {404}
    assert all(response.json()["code"] == "NOT_FOUND" for response in responses)


def test_scheduler_webhook_disabled_and_missing_secret_are_rejected(monkeypatch):
    from agentclaw.scheduler.models import ScheduledJob, TriggerConfig, WebhookConfig

    client, scheduler_api = _scheduler_client()
    base_job = ScheduledJob(
        id="job-1",
        name="Webhook job",
        workflow_id="wf-1",
        trigger=TriggerConfig(type="cron", expression="*/5 * * * *"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    class FakeScheduler:
        def __init__(self, job):
            self.job = job

        async def get_job(self, job_id):
            return self.job

    monkeypatch.setattr(scheduler_api, "_get_scheduler", lambda: FakeScheduler(base_job))
    disabled = client.post("/api/scheduler/jobs/job-1/webhook")

    enabled_without_secret = base_job.model_copy(
        update={"webhook": WebhookConfig(enabled=True, secret=None)}
    )
    monkeypatch.setattr(
        scheduler_api,
        "_get_scheduler",
        lambda: FakeScheduler(enabled_without_secret),
    )
    missing_secret = client.post("/api/scheduler/jobs/job-1/webhook")

    assert disabled.status_code == 400
    assert disabled.json()["code"] == "WEBHOOK_DISABLED"
    assert missing_secret.status_code == 403
    assert missing_secret.json()["code"] == "WEBHOOK_SECRET_REQUIRED"


def test_scheduler_webhook_non_json_body_uses_default_inputs(monkeypatch):
    from agentclaw.scheduler.models import ScheduledJob, TriggerConfig, WebhookConfig

    client, scheduler_api = _scheduler_client()
    captured: dict[str, object] = {}
    job = ScheduledJob(
        id="job-1",
        name="Webhook job",
        workflow_id="wf-1",
        trigger=TriggerConfig(type="cron", expression="*/5 * * * *"),
        webhook=WebhookConfig(
            enabled=True,
            secret="local-secret",
            allow_input_override=True,
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    class FakeScheduler:
        async def get_job(self, job_id):
            return job

        async def trigger_job(self, job_id, **kwargs):
            captured["job_id"] = job_id
            captured["kwargs"] = kwargs
            return "execution-1"

    monkeypatch.setattr(scheduler_api, "_get_scheduler", lambda: FakeScheduler())

    response = client.post(
        "/api/scheduler/jobs/job-1/webhook",
        headers={"X-Webhook-Secret": "local-secret", "content-type": "text/plain"},
        content=b"not-json",
    )

    assert response.status_code == 200
    assert response.json()["execution_id"] == "execution-1"
    assert captured == {
        "job_id": "job-1",
        "kwargs": {"trigger_source": "webhook", "override_inputs": None},
    }


def test_scheduler_execution_detail_must_belong_to_requested_job(monkeypatch, auth_tokens):
    from agentclaw.scheduler.models import ExecutionStatus, JobExecution

    client, scheduler_api = _scheduler_client()
    execution = JobExecution(
        id="execution-1",
        job_id="other-job",
        status=ExecutionStatus.SUCCESS,
        started_at=datetime.now(timezone.utc),
    )

    class FakeScheduler:
        async def get_execution(self, execution_id):
            return execution

    monkeypatch.setattr(scheduler_api, "_get_scheduler", lambda: FakeScheduler())

    response = client.get(
        "/api/scheduler/jobs/job-1/executions/execution-1",
        headers=auth_header(auth_tokens.admin),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"

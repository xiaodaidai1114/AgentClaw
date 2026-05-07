from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hmac
import json
import os
import textwrap
import time
import uuid
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest


pytestmark = [pytest.mark.real, pytest.mark.integration]


REAL_LOG_RUN_ID = uuid.uuid4().hex
SECRET_FIELD_NAMES = {
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "refresh_key",
    "private_key",
    "secret",
    "token",
    "password",
}
SECRET_FIELD_FRAGMENTS = (
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "refresh_key",
    "private_key",
    "secret",
    "token",
    "password",
)
NON_SECRET_TOKEN_FIELDS = {
    "max_tokens",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "tokens",
    "token_count",
    "llm_calls",
}
MAX_LOG_STRING_LENGTH = 8000


def _base_url() -> str:
    value = os.getenv("AGENTCLAW_REAL_BASE_URL", "").strip().rstrip("/")
    if not value:
        pytest.skip("set AGENTCLAW_REAL_BASE_URL to run real environment API tests")
    return value


def _admin_token() -> str:
    value = os.getenv("AGENTCLAW_REAL_ADMIN_TOKEN", "").strip()
    if not value:
        pytest.skip("set AGENTCLAW_REAL_ADMIN_TOKEN to run real admin API tests")
    return value


def _workflow_key() -> str:
    value = os.getenv("AGENTCLAW_REAL_WORKFLOW_API_KEY", "").strip()
    if not value:
        pytest.skip("set AGENTCLAW_REAL_WORKFLOW_API_KEY to run real workflow API tests")
    return value


@contextmanager
def _client() -> Iterator[httpx.Client]:
    base_url = _base_url()
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        try:
            client.get("/admin/health")
        except httpx.TransportError as exc:
            pytest.skip(
                f"real AgentClaw server at {base_url} is not reachable: "
                f"{exc.__class__.__name__}"
            )
        yield client


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_real_file_access_token(
    file_id: str,
    admin_token: str,
    *,
    ttl_seconds: int = 3600,
) -> str:
    expires_at = int(time.time() + max(1, ttl_seconds))
    payload = f"agentclaw-file-v1:{file_id}:{expires_at}".encode("utf-8")
    signature = hmac.new(admin_token.encode("utf-8"), payload, sha256).hexdigest()
    return f"{expires_at}.{signature}"


def _db_config() -> dict[str, Any]:
    host = os.getenv("PG_HOST", "").strip()
    user = os.getenv("PG_USER", "").strip()
    if not host or not user:
        pytest.skip("set PG_HOST and PG_USER to verify real database logs")
    return {
        "host": host,
        "port": int(os.getenv("PG_PORT", "5432")),
        "user": user,
        "password": os.getenv("PG_PASSWORD", ""),
        "database": os.getenv("PG_DATABASE", "agentclaw"),
    }


def _workflow_workspace() -> Path:
    override = os.getenv("AGENTCLAW_REAL_WORKFLOW_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    demo_dir = Path("demo2")
    if demo_dir.exists():
        return (demo_dir / "agentclaw_real_workflows").resolve()

    return Path("agentclaw_real_workflows").resolve()


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _result_log_path() -> Path:
    override = os.getenv("AGENTCLAW_REAL_RESULT_LOG", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    demo_dir = Path("demo2")
    if demo_dir.exists():
        return (demo_dir / "agentclaw_real_logs" / "real_environment_api_results.jsonl").resolve()

    return (Path(".agentclaw") / "test-logs" / "real_environment_api_results.jsonl").resolve()


def _is_secret_field(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in NON_SECRET_TOKEN_FIELDS or normalized.endswith("_tokens"):
        return False
    return normalized in SECRET_FIELD_NAMES or any(
        fragment in normalized
        for fragment in SECRET_FIELD_FRAGMENTS
    )


def _sanitize_for_log(value: Any, *, key: str = "") -> Any:
    if key and _is_secret_field(key):
        return "***" if value not in (None, "", [], {}) else value

    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_for_log(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            _sanitize_for_log(item)
            for item in value
        ]

    if isinstance(value, str) and len(value) > MAX_LOG_STRING_LENGTH:
        return value[:MAX_LOG_STRING_LENGTH] + "...<truncated>"

    return value


def _log_real_result(event: str, **fields: Any) -> Path:
    path = _result_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run_id": REAL_LOG_RUN_ID,
        "event": event,
        "base_url": os.getenv("AGENTCLAW_REAL_BASE_URL", "").strip().rstrip("/"),
        **fields,
    }
    safe_record = _sanitize_for_log(record)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe_record, ensure_ascii=False, default=str) + "\n")
    return path


def _response_payload_for_log(response: httpx.Response) -> dict[str, Any]:
    try:
        body: Any = response.json()
    except Exception:
        body = response.text[:MAX_LOG_STRING_LENGTH]
    return {
        "status_code": response.status_code,
        "body": body,
    }


def _log_response(event: str, response: httpx.Response, **fields: Any) -> None:
    _log_real_result(
        event,
        response=_response_payload_for_log(response),
        **fields,
    )


def _write_hot_workflow_file(workflow_id: str) -> Path:
    workspace = _workflow_workspace()
    workspace.mkdir(parents=True, exist_ok=True)
    workflow_file = workspace / f"{workflow_id}.py"
    workflow_file.write_text(
        textwrap.dedent(
            f"""
            from agentclaw import CustomNode, Input, Workflow


            workflow = Workflow(
                id={workflow_id!r},
                name="Real Hot Register Echo",
                description="Deterministic workflow used by real environment tests.",
                inputs=[
                    Input("user_input", str, required=True, description="Message"),
                    Input("suffix", str, default="ok", description="Suffix"),
                ],
                user_input="user_input",
            )


            class BuildAnswerNode(CustomNode):
                def process(self, user_input="", suffix="ok", **_):
                    normalized = str(user_input).strip()
                    answer = f"real-hot-register-ok::{{normalized}}::{{suffix}}"
                    return {{
                        "normalized_input": normalized,
                        "answer": answer,
                        "__messages__": [
                            {{"role": "assistant", "content": answer}},
                        ],
                    }}


            workflow.add_node(
                BuildAnswerNode(
                    id="build_answer",
                    description="Build deterministic test answer",
                )
            )
            workflow.add_edge("__start__", "build_answer")
            workflow.publish(stream=False)
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return workflow_file


def _write_model_workflow_file(workflow_id: str, model_id: str) -> Path:
    workspace = _workflow_workspace()
    workspace.mkdir(parents=True, exist_ok=True)
    workflow_file = workspace / f"{workflow_id}.py"
    workflow_file.write_text(
        textwrap.dedent(
            f"""
            from agentclaw import Input, LLMNode, Workflow


            workflow = Workflow(
                id={workflow_id!r},
                name="Real Model Call",
                description="Real environment test workflow that calls the configured model.",
                inputs=[
                    Input("user_input", str, required=True, description="Message"),
                ],
                user_input="user_input",
            )

            workflow.add_node(
                LLMNode(
                    id="model_echo",
                    model_id={model_id!r},
                    system_prompt=(
                        "You are an API integration test. "
                        "Return the exact marker from the user message and no extra commentary."
                    ),
                    user_prompt="{{user_input}}",
                    output_key="answer",
                    output_to_user=True,
                    stream=False,
                    model_params={{"temperature": 0, "max_tokens": 64}},
                )
            )
            workflow.add_edge("__start__", "model_echo")
            workflow.publish(stream=False)
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return workflow_file


def _select_real_model_id(client: httpx.Client, workflow_key: str) -> tuple[str, set[str]]:
    response = client.get("/api/models", headers=_bearer(workflow_key))
    _log_response("api.models.catalog", response)
    assert response.status_code == 200, response.text[:1000]

    payload = response.json()
    model_ids = {
        str(model.get("id"))
        for model in payload.get("models", [])
        if model.get("id")
    }
    if not model_ids:
        pytest.skip("real server has no configured chat models")

    requested = os.getenv("AGENTCLAW_REAL_MODEL_ID", "").strip()
    if requested:
        assert requested in model_ids, (
            "AGENTCLAW_REAL_MODEL_ID must be one of the server's configured models"
        )
        _log_real_result(
            "api.models.selected",
            selected_model_id=requested,
            selection_source="AGENTCLAW_REAL_MODEL_ID",
            available_model_ids=sorted(model_ids),
        )
        return requested, model_ids

    default_model_id = payload.get("default_model_id")
    if default_model_id and default_model_id in model_ids:
        _log_real_result(
            "api.models.selected",
            selected_model_id=str(default_model_id),
            selection_source="default_model_id",
            available_model_ids=sorted(model_ids),
        )
        return str(default_model_id), model_ids

    selected = sorted(model_ids)[0]
    _log_real_result(
        "api.models.selected",
        selected_model_id=selected,
        selection_source="first_sorted_model",
        available_model_ids=sorted(model_ids),
    )
    return selected, model_ids


def _register_model_workflow(
    client: httpx.Client,
    admin_token: str,
    workflow_id: str,
    model_id: str,
) -> dict[str, Any]:
    workflow_file = _write_model_workflow_file(workflow_id, model_id)
    response = client.post(
        "/admin/workflows/register-file",
        headers=_bearer(admin_token),
        json={
            "file_path": str(workflow_file),
            "workflow_id": workflow_id,
            "force_replace": True,
            "ensure_prompt_loaded": False,
        },
    )

    _log_response(
        "admin.workflows.register_file",
        response,
        workflow_id=workflow_id,
        workflow_file=str(workflow_file),
        workflow_kind="llm",
        model_id=model_id,
    )
    assert response.status_code == 200, response.text[:1000]
    payload = response.json()
    touched_ids = set(payload.get("registered_workflow_ids") or [])
    added_ids = set(payload.get("added_workflow_ids") or [])
    assert workflow_id in touched_ids | added_ids
    return payload


def _register_hot_workflow(
    client: httpx.Client,
    admin_token: str,
    workflow_id: str,
) -> dict[str, Any]:
    workflow_file = _write_hot_workflow_file(workflow_id)
    response = client.post(
        "/admin/workflows/register-file",
        headers=_bearer(admin_token),
        json={
            "file_path": str(workflow_file),
            "workflow_id": workflow_id,
            "force_replace": True,
            "ensure_prompt_loaded": False,
        },
    )

    _log_response(
        "admin.workflows.register_file",
        response,
        workflow_id=workflow_id,
        workflow_file=str(workflow_file),
        workflow_kind="custom",
    )
    assert response.status_code == 200, response.text[:1000]
    payload = response.json()
    touched_ids = set(payload.get("registered_workflow_ids") or [])
    added_ids = set(payload.get("added_workflow_ids") or [])
    assert workflow_id in touched_ids | added_ids
    return payload


def _run_hot_workflow(
    client: httpx.Client,
    workflow_key: str,
    workflow_id: str,
) -> dict[str, Any]:
    message = f"ping-{uuid.uuid4().hex[:8]}"
    suffix = "db-log"
    conversation_id = f"real-hot-{uuid.uuid4().hex[:12]}"
    expected_answer = f"real-hot-register-ok::{message}::{suffix}"

    response = client.post(
        "/api/workflow/run",
        headers=_bearer(workflow_key),
        json={
            "workflow_id": workflow_id,
            "response_mode": "blocking",
            "conversation_id": conversation_id,
            "inputs": {
                "user_input": f"  {message}  ",
                "suffix": suffix,
            },
        },
    )

    _log_response(
        "api.workflow.run.custom",
        response,
        workflow_id=workflow_id,
        conversation_id=conversation_id,
        expected_answer=expected_answer,
    )
    assert response.status_code == 200, response.text[:1000]
    payload = response.json()
    assert payload["answer"] == expected_answer
    assert payload["conversation_id"] == conversation_id
    assert payload["metadata"]["status"] == "completed"
    return {
        "payload": payload,
        "workflow_id": workflow_id,
        "message": message,
        "suffix": suffix,
        "conversation_id": conversation_id,
        "expected_answer": expected_answer,
        "trace_id": payload.get("metadata", {}).get("trace_id"),
    }


def _run_model_workflow(
    client: httpx.Client,
    workflow_key: str,
    workflow_id: str,
) -> dict[str, Any]:
    marker = f"AGENTCLAW_REAL_MODEL_OK_{uuid.uuid4().hex[:8].upper()}"
    conversation_id = f"real-model-{uuid.uuid4().hex[:12]}"

    response = client.post(
        "/api/workflow/run",
        headers=_bearer(workflow_key),
        json={
            "workflow_id": workflow_id,
            "response_mode": "blocking",
            "conversation_id": conversation_id,
            "inputs": {
                "user_input": f"Return exactly this marker: {marker}",
            },
        },
    )

    _log_response(
        "api.workflow.run.llm",
        response,
        workflow_id=workflow_id,
        conversation_id=conversation_id,
        marker=marker,
    )
    assert response.status_code == 200, response.text[:1000]
    payload = response.json()
    answer = str(payload.get("answer") or "")
    assert marker in answer
    assert payload["conversation_id"] == conversation_id
    assert payload["metadata"]["status"] == "completed"
    return {
        "payload": payload,
        "workflow_id": workflow_id,
        "conversation_id": conversation_id,
        "marker": marker,
        "answer": answer,
        "trace_id": payload.get("metadata", {}).get("trace_id"),
    }


def _poll_trace_detail(
    client: httpx.Client,
    admin_token: str,
    trace_id: str,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_response = None

    while time.monotonic() < deadline:
        response = client.get(f"/admin/traces/{trace_id}", headers=_bearer(admin_token))
        last_response = response
        if response.status_code == 200:
            payload = response.json()
            if payload.get("node_logs"):
                _log_real_result(
                    "admin.traces.detail",
                    trace_id=trace_id,
                    trace=payload,
                )
                return payload
        time.sleep(0.1)

    assert last_response is not None
    _log_response(
        "admin.traces.detail.timeout",
        last_response,
        trace_id=trace_id,
        timeout_seconds=timeout_seconds,
    )
    assert last_response.status_code == 200, last_response.text[:1000]
    return last_response.json()


def _poll_scheduler_execution(
    client: httpx.Client,
    admin_token: str,
    job_id: str,
    execution_id: str,
    *,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    terminal_statuses = {"success", "failed", "timeout", "cancelled"}
    deadline = time.monotonic() + timeout_seconds
    last_response = None

    while time.monotonic() < deadline:
        response = client.get(
            f"/api/scheduler/jobs/{job_id}/executions/{execution_id}",
            headers=_bearer(admin_token),
        )
        last_response = response
        if response.status_code == 200:
            payload = response.json()
            if payload.get("status") in terminal_statuses:
                _log_real_result(
                    "api.scheduler.execution_detail",
                    job_id=job_id,
                    execution_id=execution_id,
                    execution=payload,
                )
                return payload
        time.sleep(0.2)

    assert last_response is not None
    _log_response(
        "api.scheduler.execution_detail.timeout",
        last_response,
        job_id=job_id,
        execution_id=execution_id,
        timeout_seconds=timeout_seconds,
    )
    assert last_response.status_code == 200, last_response.text[:1000]
    return last_response.json()


async def _poll_database_trace(
    trace_id: str,
    *,
    timeout_seconds: float = 5.0,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    import asyncpg

    config = _db_config()
    conn = await asyncpg.connect(**config)
    deadline = time.monotonic() + timeout_seconds
    workflow_row = None
    node_rows = []
    llm_count = 0

    try:
        while time.monotonic() < deadline:
            workflow_row = await conn.fetchrow(
                """
                SELECT
                    workflow_id,
                    thread_id,
                    status,
                    input_data::text AS input_data,
                    output_data::text AS output_data,
                    node_log_ids::text AS node_log_ids
                FROM workflow_logs
                WHERE id = $1::uuid
                """,
                trace_id,
            )
            node_rows = await conn.fetch(
                """
                SELECT
                    name,
                    node_type,
                    status,
                    input_data::text AS input_data,
                    output_data::text AS output_data
                FROM node_logs
                WHERE workflow_log_id = $1::uuid
                ORDER BY start_time ASC
                """,
                trace_id,
            )
            llm_count = await conn.fetchval(
                "SELECT COUNT(*) FROM llm_logs WHERE workflow_log_id = $1::uuid",
                trace_id,
            )

            if workflow_row and workflow_row["status"] == "success" and node_rows:
                workflow_dict = dict(workflow_row)
                node_dicts = [dict(row) for row in node_rows]
                _log_real_result(
                    "postgres.workflow_trace",
                    trace_id=trace_id,
                    workflow_log=workflow_dict,
                    node_logs=node_dicts,
                    llm_count=int(llm_count),
                )
                return workflow_dict, node_dicts, int(llm_count)
            await asyncio.sleep(0.1)

        assert workflow_row is not None
        workflow_dict = dict(workflow_row)
        node_dicts = [dict(row) for row in node_rows]
        _log_real_result(
            "postgres.workflow_trace.timeout",
            trace_id=trace_id,
            workflow_log=workflow_dict,
            node_logs=node_dicts,
            llm_count=int(llm_count),
            timeout_seconds=timeout_seconds,
        )
        return workflow_dict, node_dicts, int(llm_count)
    finally:
        await conn.close()


async def _poll_database_llm_logs(
    trace_id: str,
    *,
    timeout_seconds: float = 5.0,
) -> list[dict[str, Any]]:
    import asyncpg

    config = _db_config()
    conn = await asyncpg.connect(**config)
    deadline = time.monotonic() + timeout_seconds
    rows = []

    try:
        while time.monotonic() < deadline:
            rows = await conn.fetch(
                """
                SELECT
                    model_id,
                    model_name,
                    status,
                    prompt,
                    completion,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    metadata::text AS metadata
                FROM llm_logs
                WHERE workflow_log_id = $1::uuid
                ORDER BY created_at ASC
                """,
                trace_id,
            )
            if rows:
                row_dicts = [dict(row) for row in rows]
                _log_real_result(
                    "postgres.llm_logs",
                    trace_id=trace_id,
                    llm_logs=row_dicts,
                )
                return row_dicts
            await asyncio.sleep(0.1)

        row_dicts = [dict(row) for row in rows]
        _log_real_result(
            "postgres.llm_logs.timeout",
            trace_id=trace_id,
            llm_logs=row_dicts,
            timeout_seconds=timeout_seconds,
        )
        return row_dicts
    finally:
        await conn.close()


def test_real_admin_health_endpoint_is_reachable():
    with _client() as client:
        response = client.get("/admin/health")

    _log_response("admin.health", response, endpoint="/admin/health")
    assert response.status_code == 200
    assert response.json().get("status") == "ok"


def test_real_admin_routes_reject_missing_token():
    with _client() as client:
        response = client.get("/admin/workflows")

    _log_response(
        "admin.auth.reject_missing",
        response,
        endpoint="/admin/workflows",
    )
    assert response.status_code in {401, 403}


def test_real_admin_core_read_apis():
    token = _admin_token()
    endpoints = (
        "/admin/workflows",
        "/admin/dashboard/stats",
        "/admin/settings/env",
        "/admin/tasks",
        "/api/upload/list",
        "/api/scheduler/jobs",
        "/api/channels",
        "/api/conversations/__real_probe__",
    )

    with _client() as client:
        responses = [
            client.get(endpoint, headers=_bearer(token))
            for endpoint in endpoints
        ]

    for response in responses:
        _log_response(
            "admin.core_read",
            response,
            endpoint=str(response.request.url.path),
        )
        assert response.status_code == 200, response.text[:500]
        assert isinstance(response.json(), dict)


def test_real_admin_extended_read_apis_log_response_shapes():
    token = _admin_token()
    endpoints = (
        "/admin/models",
        "/admin/models/available",
        "/admin/traces/summary",
        "/admin/dashboard/trends?time_range=24h",
        "/admin/settings/global",
        "/admin/settings/infra/auth",
    )

    with _client() as client:
        responses = [
            client.get(endpoint, headers=_bearer(token))
            for endpoint in endpoints
        ]

    for response in responses:
        _log_response(
            "admin.extended_read",
            response,
            endpoint=str(response.request.url.path),
        )
        assert response.status_code == 200, response.text[:500]
        assert isinstance(response.json(), dict)

    models_payload = responses[0].json()
    available_payload = responses[1].json()
    trace_summary_payload = responses[2].json()
    trends_payload = responses[3].json()

    assert "models" in models_payload
    assert "fallback_state" in models_payload
    assert "models" in available_payload
    assert set(trace_summary_payload) >= {"total", "success", "error", "running"}
    assert trends_payload["time_range"] == "24h"
    assert "data_points" in trends_payload


def test_real_admin_token_can_probe_protected_file_route():
    token = _admin_token()

    with _client() as client:
        response = client.get(
            "/api/files/__missing_real_test_file__",
            headers=_bearer(token),
        )

    _log_response(
        "api.files.protected_probe",
        response,
        endpoint="/api/files/__missing_real_test_file__",
    )
    assert response.status_code in {404, 503}


def test_real_admin_token_verify():
    token = _admin_token()

    with _client() as client:
        response = client.post("/admin/auth/verify", json={"token": token})

    _log_response("admin.auth.verify", response, endpoint="/admin/auth/verify")
    assert response.status_code == 200
    assert response.json() == {"valid": True}


def test_real_public_workflow_read_apis_with_workflow_key():
    key = _workflow_key()
    endpoints = (
        "/api/workflows",
        "/api/models",
        "/api/upload/status",
    )

    with _client() as client:
        responses = [
            client.get(endpoint, headers=_bearer(key))
            for endpoint in endpoints
        ]

    for response in responses:
        _log_response(
            "api.public_read",
            response,
            endpoint=str(response.request.url.path),
        )
        assert response.status_code == 200, response.text[:500]
        assert isinstance(response.json(), dict)

    workflows_payload = responses[0].json()
    models_payload = responses[1].json()
    upload_payload = responses[2].json()
    assert "workflows" in workflows_payload
    assert isinstance(workflows_payload["workflows"], list)
    assert "models" in models_payload
    assert isinstance(models_payload["models"], list)
    assert set(upload_payload) >= {"available", "max_size"}


def test_real_public_and_admin_routes_reject_missing_token():
    endpoints = (
        "/api/workflows",
        "/api/models",
        "/api/upload/status",
        "/api/upload/list",
        "/api/scheduler/jobs",
        "/api/channels",
        "/api/conversations/__real_probe__",
        "/api/files/__missing_real_test_file__",
        "/admin/settings/env",
    )

    with _client() as client:
        responses = [client.get(endpoint) for endpoint in endpoints]

    for response in responses:
        _log_response(
            "auth.reject_missing",
            response,
            endpoint=str(response.request.url.path),
        )
        assert response.status_code in {401, 403}


def test_real_workflow_key_cannot_access_management_apis():
    key = _workflow_key()
    endpoints = (
        "/admin/workflows",
        "/admin/dashboard/stats",
        "/admin/settings/env",
        "/admin/tasks",
        "/api/upload/list",
        "/api/scheduler/jobs",
        "/api/channels",
        "/api/conversations/__real_probe__",
        "/api/files/__missing_real_test_file__",
    )

    with _client() as client:
        responses = [
            client.get(endpoint, headers=_bearer(key))
            for endpoint in endpoints
        ]

    for response in responses:
        _log_response(
            "auth.reject_workflow_key_for_management",
            response,
            endpoint=str(response.request.url.path),
        )
        assert response.status_code in {401, 403}


def test_real_public_conversation_lifecycle_logs_database_backed_responses():
    token = _admin_token()
    workflow_id = "agentclaw_real_conversation_lifecycle"
    title = f"Real conversation {uuid.uuid4().hex[:8]}"
    updated_title = f"{title} updated"
    messages = [
        {
            "role": "user",
            "content": "hello conversation lifecycle",
            "timestamp": int(time.time() * 1000),
        },
        {
            "role": "assistant",
            "content": "conversation lifecycle response",
            "timestamp": int(time.time() * 1000),
        },
    ]
    conversation_id = None

    with _client() as client:
        create_response = client.post(
            "/api/conversations",
            headers=_bearer(token),
            json={
                "workflow_id": workflow_id,
                "title": title,
                "source": "admin",
                "owner_id": "owner-real-test",
                "user_id": "user-real-test",
                "tenant_id": "tenant-real-test",
            },
        )
        _log_response(
            "api.conversations.create",
            create_response,
            workflow_id=workflow_id,
        )
        assert create_response.status_code == 200, create_response.text[:1000]
        created = create_response.json()
        conversation_id = created["id"]
        assert created["source"] == "public"
        assert created["owner_id"] == "owner-real-test"
        assert created["user_id"] == "user-real-test"
        assert created["tenant_id"] == "tenant-real-test"

        list_response = client.get(
            f"/api/conversations/{workflow_id}?source=admin",
            headers=_bearer(token),
        )
        _log_response(
            "api.conversations.list",
            list_response,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
        )
        assert list_response.status_code == 200, list_response.text[:1000]
        assert any(
            item.get("id") == conversation_id
            for item in list_response.json().get("conversations", [])
        )

        update_response = client.put(
            f"/api/conversations/{workflow_id}/{conversation_id}",
            headers=_bearer(token),
            json={"title": updated_title, "messages": messages},
        )
        _log_response(
            "api.conversations.update",
            update_response,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
        )
        assert update_response.status_code == 200, update_response.text[:1000]
        updated = update_response.json()
        assert updated["title"] == updated_title
        assert updated["source"] == "public"
        assert updated["messages"] == messages

        detail_response = client.get(
            f"/api/conversations/{workflow_id}/{conversation_id}",
            headers=_bearer(token),
        )
        _log_response(
            "api.conversations.detail",
            detail_response,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
        )
        assert detail_response.status_code == 200, detail_response.text[:1000]
        assert detail_response.json()["messages"] == messages

        feedback_response = client.post(
            f"/api/conversations/{workflow_id}/{conversation_id}/feedback",
            headers=_bearer(token),
            json={"message_index": 1, "feedback": "like"},
        )
        _log_response(
            "api.conversations.feedback.submit",
            feedback_response,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
        )
        assert feedback_response.status_code == 200, feedback_response.text[:1000]
        assert feedback_response.json()["success"] is True

        feedback_list_response = client.get(
            f"/api/conversations/{workflow_id}/{conversation_id}/feedback",
            headers=_bearer(token),
        )
        _log_response(
            "api.conversations.feedback.list",
            feedback_list_response,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
        )
        assert feedback_list_response.status_code == 200, feedback_list_response.text[:1000]
        assert feedback_list_response.json()["feedbacks"] == {"1": "like"}

        delete_response = client.delete(
            f"/api/conversations/{workflow_id}/{conversation_id}",
            headers=_bearer(token),
        )
        _log_response(
            "api.conversations.delete",
            delete_response,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
        )
        assert delete_response.status_code == 200, delete_response.text[:1000]
        assert delete_response.json()["success"] is True

        after_delete_response = client.get(
            f"/api/conversations/{workflow_id}/{conversation_id}",
            headers=_bearer(token),
        )
        _log_response(
            "api.conversations.detail_after_delete",
            after_delete_response,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
        )
        assert after_delete_response.status_code == 404


def test_real_upload_signed_file_roundtrip_logs_browser_download():
    admin_token = _admin_token()
    workflow_key = _workflow_key()
    content = f"agentclaw real upload {uuid.uuid4().hex}".encode("utf-8")
    filename = f"real-upload-{uuid.uuid4().hex[:8]}.txt"

    with _client() as client:
        status_response = client.get(
            "/api/upload/status",
            headers=_bearer(workflow_key),
        )
        _log_response("api.upload.status_before_roundtrip", status_response)
        assert status_response.status_code == 200, status_response.text[:1000]
        if not status_response.json().get("available"):
            pytest.skip("real server file upload is not available")

        upload_response = client.post(
            "/api/upload",
            headers=_bearer(workflow_key),
            files={"file": (filename, content, "text/plain")},
        )
        _log_response(
            "api.upload.create",
            upload_response,
            filename=filename,
        )
        assert upload_response.status_code == 200, upload_response.text[:1000]
        uploaded = upload_response.json()
        file_id = uploaded["id"]
        assert uploaded["original_name"] == filename
        assert uploaded["size"] == len(content)

        list_response = client.get(
            "/api/upload/list",
            headers=_bearer(admin_token),
        )
        _log_response(
            "api.upload.list_after_create",
            list_response,
            file_id=file_id,
        )
        assert list_response.status_code == 200, list_response.text[:1000]
        assert any(
            item.get("id") == file_id
            for item in list_response.json().get("files", [])
        )

        signed_token = _create_real_file_access_token(file_id, admin_token)
        download_response = client.get(
            f"/api/files/{file_id}",
            params={"token": signed_token},
        )
        _log_response(
            "api.files.signed_download",
            download_response,
            file_id=file_id,
            signed_token=signed_token,
        )
        assert download_response.status_code == 200, download_response.text[:1000]
        assert download_response.content == content
        assert "filename=" in download_response.headers["content-disposition"]
        assert download_response.headers["x-content-type-options"] == "nosniff"

        forced_download_response = client.get(
            f"/api/files/{file_id}",
            params={"token": signed_token, "download": "true"},
        )
        _log_response(
            "api.files.signed_forced_download",
            forced_download_response,
            file_id=file_id,
            signed_token=signed_token,
        )
        assert forced_download_response.status_code == 200, forced_download_response.text[:1000]
        assert forced_download_response.content == content
        assert forced_download_response.headers["content-disposition"].startswith("attachment;")


def test_real_hot_register_workflow_executes_and_records_trace():
    admin_token = _admin_token()
    workflow_key = _workflow_key()
    workflow_id = "agentclaw_real_hot_register_echo"

    with _client() as client:
        _register_hot_workflow(client, admin_token, workflow_id)

        catalog_response = client.get(
            "/api/workflows",
            headers=_bearer(workflow_key),
        )
        _log_response(
            "api.workflows.catalog_after_register",
            catalog_response,
            workflow_id=workflow_id,
        )
        assert catalog_response.status_code == 200, catalog_response.text[:1000]
        assert any(
            item.get("id") == workflow_id
            for item in catalog_response.json().get("workflows", [])
        )

        detail_response = client.get(
            f"/admin/workflows/{workflow_id}",
            headers=_bearer(admin_token),
        )
        _log_response(
            "admin.workflows.detail_after_register",
            detail_response,
            workflow_id=workflow_id,
        )
        assert detail_response.status_code == 200, detail_response.text[:1000]
        detail_payload = detail_response.json()
        assert detail_payload["workflow"]["id"] == workflow_id
        assert any(
            node.get("id") == "build_answer"
            for node in detail_payload["workflow"].get("nodes", [])
        )

        run = _run_hot_workflow(client, workflow_key, workflow_id)
        trace_id = run["trace_id"]
        if not trace_id:
            pytest.skip("real server did not return trace_id; database tracing is not enabled")

        trace = _poll_trace_detail(client, admin_token, trace_id)
        assert trace["id"] == trace_id
        assert trace["workflow_id"] == workflow_id
        assert trace["thread_id"] == run["conversation_id"]
        assert trace["status"] == "success"
        assert trace["input_data"]["user_input"].strip() == run["message"]
        assert trace["output_data"]["answer"] == run["expected_answer"]
        assert trace["llm_logs"] == []
        assert any(
            node.get("name") == "build_answer" and node.get("status") == "success"
            for node in trace["node_logs"]
        )

        traces_response = client.get(
            f"/admin/traces?workflow_id={workflow_id}&limit=5",
            headers=_bearer(admin_token),
        )
        _log_response(
            "admin.traces.list_after_run",
            traces_response,
            workflow_id=workflow_id,
            trace_id=trace_id,
        )
        assert traces_response.status_code == 200, traces_response.text[:1000]
        assert any(
            item.get("id") == trace_id
            for item in traces_response.json().get("traces", [])
        )

        stats_response = client.get(
            f"/admin/workflows/{workflow_id}/stats",
            headers=_bearer(admin_token),
        )
        _log_response(
            "admin.workflows.stats_after_run",
            stats_response,
            workflow_id=workflow_id,
            trace_id=trace_id,
        )
        assert stats_response.status_code == 200, stats_response.text[:1000]
        stats = stats_response.json()
        assert stats["total_count"] >= 1
        assert stats["success_count"] >= 1


def test_real_scheduler_job_lifecycle_executes_hot_registered_workflow():
    admin_token = _admin_token()
    workflow_key = _workflow_key()
    workflow_id = "agentclaw_real_scheduler_echo"
    webhook_secret = f"real-scheduler-{uuid.uuid4().hex}"
    job_id = None

    with _client() as client:
        _register_hot_workflow(client, admin_token, workflow_id)

        create_response = client.post(
            "/api/scheduler/jobs",
            headers=_bearer(admin_token),
            json={
                "name": f"Real scheduler job {uuid.uuid4().hex[:8]}",
                "description": "Real environment scheduler lifecycle test",
                "workflow_id": workflow_id,
                "trigger": {
                    "type": "date",
                    "run_date": (
                        datetime.now(timezone.utc) + timedelta(days=365)
                    ).isoformat(),
                },
                "inputs": {
                    "user_input": "scheduler-manual",
                    "suffix": "manual",
                },
                "config": {
                    "timeout": 30,
                    "retry_count": 0,
                    "retry_interval": 1,
                    "concurrency": "skip",
                    "max_instances": 1,
                },
                "webhook": {
                    "enabled": True,
                    "secret": webhook_secret,
                    "allow_input_override": True,
                },
            },
        )
        _log_response(
            "api.scheduler.jobs.create",
            create_response,
            workflow_id=workflow_id,
            webhook_secret=webhook_secret,
        )
        if create_response.status_code == 503:
            pytest.skip("real server scheduler is not available")
        assert create_response.status_code == 201, create_response.text[:1000]
        job = create_response.json()
        job_id = job["id"]
        assert job["workflow_id"] == workflow_id
        assert job["webhook"]["enabled"] is True

        try:
            detail_response = client.get(
                f"/api/scheduler/jobs/{job_id}",
                headers=_bearer(admin_token),
            )
            _log_response(
                "api.scheduler.jobs.detail",
                detail_response,
                workflow_id=workflow_id,
                job_id=job_id,
            )
            assert detail_response.status_code == 200, detail_response.text[:1000]

            list_response = client.get(
                f"/api/scheduler/jobs?workflow_id={workflow_id}",
                headers=_bearer(admin_token),
            )
            _log_response(
                "api.scheduler.jobs.list_by_workflow",
                list_response,
                workflow_id=workflow_id,
                job_id=job_id,
            )
            assert list_response.status_code == 200, list_response.text[:1000]
            assert any(item.get("id") == job_id for item in list_response.json().get("jobs", []))

            update_response = client.put(
                f"/api/scheduler/jobs/{job_id}",
                headers=_bearer(admin_token),
                json={
                    "inputs": {
                        "user_input": "scheduler-updated",
                        "suffix": "updated",
                    }
                },
            )
            _log_response(
                "api.scheduler.jobs.update",
                update_response,
                workflow_id=workflow_id,
                job_id=job_id,
            )
            assert update_response.status_code == 200, update_response.text[:1000]
            assert update_response.json()["inputs"]["suffix"] == "updated"

            pause_response = client.post(
                f"/api/scheduler/jobs/{job_id}/pause",
                headers=_bearer(admin_token),
            )
            _log_response(
                "api.scheduler.jobs.pause",
                pause_response,
                workflow_id=workflow_id,
                job_id=job_id,
            )
            assert pause_response.status_code == 200, pause_response.text[:1000]
            assert pause_response.json()["status"] == "paused"

            resume_response = client.post(
                f"/api/scheduler/jobs/{job_id}/resume",
                headers=_bearer(admin_token),
            )
            _log_response(
                "api.scheduler.jobs.resume",
                resume_response,
                workflow_id=workflow_id,
                job_id=job_id,
            )
            assert resume_response.status_code == 200, resume_response.text[:1000]
            assert resume_response.json()["status"] == "enabled"

            trigger_response = client.post(
                f"/api/scheduler/jobs/{job_id}/trigger",
                headers=_bearer(admin_token),
            )
            _log_response(
                "api.scheduler.jobs.trigger_manual",
                trigger_response,
                workflow_id=workflow_id,
                job_id=job_id,
            )
            assert trigger_response.status_code == 200, trigger_response.text[:1000]
            manual_execution_id = trigger_response.json()["execution_id"]
            manual_execution = _poll_scheduler_execution(
                client,
                admin_token,
                job_id,
                manual_execution_id,
                timeout_seconds=15.0,
            )
            assert manual_execution["status"] == "success"
            assert "scheduler-updated" in manual_execution["outputs"]["answer"]

            forbidden_response = client.post(
                f"/api/scheduler/jobs/{job_id}/webhook",
                headers={"X-Webhook-Secret": "wrong"},
                json={
                    "user_input": "scheduler-webhook",
                    "suffix": "webhook",
                },
            )
            _log_response(
                "api.scheduler.jobs.webhook_forbidden",
                forbidden_response,
                workflow_id=workflow_id,
                job_id=job_id,
            )
            assert forbidden_response.status_code == 403

            webhook_response = client.post(
                f"/api/scheduler/jobs/{job_id}/webhook",
                headers={"X-Webhook-Secret": webhook_secret},
                json={
                    "user_input": "scheduler-webhook",
                    "suffix": "webhook",
                },
            )
            _log_response(
                "api.scheduler.jobs.webhook_trigger",
                webhook_response,
                workflow_id=workflow_id,
                job_id=job_id,
                webhook_secret=webhook_secret,
            )
            assert webhook_response.status_code == 200, webhook_response.text[:1000]
            webhook_execution_id = webhook_response.json()["execution_id"]
            webhook_execution = _poll_scheduler_execution(
                client,
                admin_token,
                job_id,
                webhook_execution_id,
                timeout_seconds=15.0,
            )
            assert webhook_execution["status"] == "success"
            assert "scheduler-webhook" in webhook_execution["outputs"]["answer"]

            executions_response = client.get(
                f"/api/scheduler/jobs/{job_id}/executions",
                headers=_bearer(admin_token),
            )
            _log_response(
                "api.scheduler.jobs.executions",
                executions_response,
                workflow_id=workflow_id,
                job_id=job_id,
            )
            assert executions_response.status_code == 200, executions_response.text[:1000]
            execution_ids = {
                item.get("id")
                for item in executions_response.json().get("executions", [])
            }
            assert {manual_execution_id, webhook_execution_id}.issubset(execution_ids)
        finally:
            if job_id:
                delete_response = client.delete(
                    f"/api/scheduler/jobs/{job_id}",
                    headers=_bearer(admin_token),
                )
                _log_response(
                    "api.scheduler.jobs.delete",
                    delete_response,
                    workflow_id=workflow_id,
                    job_id=job_id,
                )
                assert delete_response.status_code == 200, delete_response.text[:1000]


@pytest.mark.asyncio
async def test_real_hot_registered_workflow_writes_database_logs():
    admin_token = _admin_token()
    workflow_key = _workflow_key()
    workflow_id = "agentclaw_real_hot_register_echo_db"

    with _client() as client:
        _register_hot_workflow(client, admin_token, workflow_id)
        run = _run_hot_workflow(client, workflow_key, workflow_id)

    trace_id = run["trace_id"]
    if not trace_id:
        pytest.skip("real server did not return trace_id; database tracing is not enabled")

    workflow_row, node_rows, llm_count = await _poll_database_trace(trace_id)
    input_data = _decode_json(workflow_row["input_data"])
    output_data = _decode_json(workflow_row["output_data"])
    node_log_ids = _decode_json(workflow_row["node_log_ids"])
    build_answer_node = next(
        row for row in node_rows
        if row["name"] == "build_answer"
    )
    node_input = _decode_json(build_answer_node["input_data"])
    node_output = _decode_json(build_answer_node["output_data"])

    assert workflow_row["workflow_id"] == workflow_id
    assert workflow_row["thread_id"] == run["conversation_id"]
    assert workflow_row["status"] == "success"
    assert input_data["user_input"].strip() == run["message"]
    assert output_data["answer"] == run["expected_answer"]
    assert node_log_ids
    assert build_answer_node["status"] == "success"
    assert build_answer_node["node_type"] == "BuildAnswerNode"
    assert node_input["user_input"].strip() == run["message"]
    assert node_output["answer"] == run["expected_answer"]
    assert llm_count == 0


@pytest.mark.asyncio
async def test_real_hot_registered_workflow_calls_configured_model_and_writes_llm_logs():
    admin_token = _admin_token()
    workflow_key = _workflow_key()
    workflow_id = "agentclaw_real_hot_register_model"

    with _client() as client:
        model_id, model_ids = _select_real_model_id(client, workflow_key)
        _register_model_workflow(client, admin_token, workflow_id, model_id)

        detail_response = client.get(
            f"/admin/workflows/{workflow_id}",
            headers=_bearer(admin_token),
        )
        _log_response(
            "admin.workflows.detail_after_model_register",
            detail_response,
            workflow_id=workflow_id,
            model_id=model_id,
        )
        assert detail_response.status_code == 200, detail_response.text[:1000]
        detail_payload = detail_response.json()
        assert detail_payload["workflow"]["id"] == workflow_id
        assert any(
            node.get("id") == "model_echo" and node.get("model_id") == model_id
            for node in detail_payload["workflow"].get("nodes", [])
        )

        run = _run_model_workflow(client, workflow_key, workflow_id)
        trace_id = run["trace_id"]
        if not trace_id:
            pytest.skip("real server did not return trace_id; database tracing is not enabled")

        trace = _poll_trace_detail(client, admin_token, trace_id, timeout_seconds=15.0)
        assert trace["workflow_id"] == workflow_id
        assert trace["thread_id"] == run["conversation_id"]
        assert trace["status"] == "success"
        assert run["marker"] in trace["output_data"]["answer"]
        assert any(
            node.get("name") == "model_echo" and node.get("status") == "success"
            for node in trace["node_logs"]
        )
        assert trace["llm_logs"]
        assert any(
            log.get("status") == "success" and log.get("model_id") in model_ids
            for log in trace["llm_logs"]
        )

    llm_logs = await _poll_database_llm_logs(trace_id, timeout_seconds=15.0)
    assert llm_logs
    successful_log = next(log for log in llm_logs if log["status"] == "success")
    assert successful_log["model_id"] in model_ids
    assert successful_log["model_name"]
    assert run["marker"] in (successful_log["prompt"] or "")
    assert run["marker"] in (successful_log["completion"] or run["answer"])
    assert successful_log["total_tokens"] >= 0


def test_real_workflow_run_smoke_when_explicitly_enabled():
    if os.getenv("AGENTCLAW_REAL_RUN_WORKFLOW", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("set AGENTCLAW_REAL_RUN_WORKFLOW=1 to run a real workflow execution")

    key = _workflow_key()
    workflow_id = os.getenv("AGENTCLAW_REAL_WORKFLOW_ID", "").strip()
    if not workflow_id:
        pytest.skip("set AGENTCLAW_REAL_WORKFLOW_ID for real workflow execution")

    with _client() as client:
        response = client.post(
            "/api/workflow/run",
            headers=_bearer(key),
            json={
                "workflow_id": workflow_id,
                "response_mode": "blocking",
                "inputs": {},
                "user": "real-test",
            },
        )

    _log_response(
        "api.workflow.run.explicit_smoke",
        response,
        workflow_id=workflow_id,
    )
    assert response.status_code < 500, response.text[:1000]

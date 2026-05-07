from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
import uuid

import anyio
import pytest

from agentclaw.api.services.trace_service import TraceService


pytestmark = pytest.mark.unit


def _run(async_fn, *args, **kwargs):
    async def call():
        return await async_fn(*args, **kwargs)

    return anyio.run(call)


class FakeTraceRegistry:
    @staticmethod
    def list_all():
        return [
            SimpleNamespace(id="wf-1"),
            SimpleNamespace(id="wf-2"),
        ]


class FakeTraceBackend:
    def __init__(self):
        self.list_calls: list[dict] = []
        self.count_calls: list[dict] = []
        self.workflow_log_calls: list[str] = []
        self.trace_id = str(uuid.uuid4())
        self.sub_trace_id = str(uuid.uuid4())

    async def list_workflow_logs(self, **kwargs):
        self.list_calls.append(kwargs)
        return [
            {
                "id": uuid.UUID(self.trace_id),
                "workflow_id": "wf-1",
                "thread_id": 123,
                "user_id": None,
                "status": "success",
            }
        ]

    async def count_workflow_logs(self, **kwargs):
        self.count_calls.append(kwargs)
        return 1

    async def get_trace_token_stats_batch(self, trace_ids):
        return {
            self.trace_id: {
                "total_tokens": 10,
                "prompt_tokens": 4,
                "completion_tokens": 6,
                "llm_calls": 2,
            }
        }

    async def get_workflow_log(self, trace_id):
        trace_id = str(trace_id)
        self.workflow_log_calls.append(trace_id)
        if trace_id == self.trace_id:
            return {
                "id": uuid.UUID(self.trace_id),
                "workflow_id": "wf-1",
                "thread_id": uuid.UUID(int=1),
                "user_id": uuid.UUID(int=2),
                "input_data": '{"user_input": "hello"}',
                "output_data": '{"answer": "world"}',
                "metadata": '{"trace": true}',
                "node_log_ids": '["node-1"]',
                "status": "success",
                "duration_ms": 10,
            }
        if trace_id == self.sub_trace_id:
            return {
                "id": self.sub_trace_id,
                "workflow_id": "internal-agent",
                "thread_id": "thread-internal",
                "status": "success",
                "duration_ms": 3,
                "start_time": datetime(2026, 4, 29, 10, 0),
                "end_time": datetime(2026, 4, 29, 10, 1),
                "error": None,
            }
        return None

    async def get_node_logs(self, trace_id):
        return [
            {
                "id": uuid.UUID(int=3),
                "workflow_log_id": uuid.UUID(self.trace_id),
                "parent_node_log_id": None,
                "name": "node-1",
                "node_type": "llm",
                "input_data": '{"prompt": "hello"}',
                "output_data": (
                    '{"answer": "world", '
                    f'"__sub_metadata__": {{"sub_trace_id": "{self.sub_trace_id}"}}}}'
                ),
                "metadata": '{"node": true}',
                "start_time": datetime(2026, 4, 29, 10, 0, 1),
                "end_time": datetime(2026, 4, 29, 10, 0, 2),
                "status": "success",
                "duration_ms": 100,
            }
        ]

    async def get_llm_logs(self, trace_id):
        return [
            {
                "id": uuid.UUID(int=4),
                "workflow_log_id": uuid.UUID(self.trace_id),
                "node_log_id": uuid.UUID(int=3),
                "model_id": "model-1",
                "model_name": "gpt-test",
                "metadata": '{"usage": true}',
                "created_at": datetime(2026, 4, 29, 10, 0, 1, 500000),
                "status": "success",
                "latency_ms": 50,
                "total_tokens": 10,
            }
        ]


def test_trace_service_list_filters_registered_workflows_and_adds_token_stats():
    backend = FakeTraceBackend()
    service = TraceService(tracer=backend, registry=FakeTraceRegistry)

    result = _run(
        service.list_traces,
        status="success",
        page=2,
        limit=5,
        include_internal=False,
    )
    unregistered = _run(
        service.list_traces,
        workflow_id="internal-agent",
        include_internal=False,
    )

    assert result["total"] == 1
    assert result["page"] == 2
    assert result["limit"] == 5
    assert result["traces"][0]["id"] == backend.trace_id
    assert result["traces"][0]["thread_id"] == "123"
    assert result["traces"][0]["total_tokens"] == 10
    assert result["traces"][0]["prompt_tokens"] == 4
    assert result["traces"][0]["completion_tokens"] == 6
    assert result["traces"][0]["llm_calls"] == 2
    assert backend.list_calls[0]["workflow_ids"] == ["wf-1", "wf-2"]
    assert backend.list_calls[0]["offset"] == 5
    assert backend.count_calls[0]["workflow_ids"] == ["wf-1", "wf-2"]
    assert unregistered == {"traces": [], "total": 0, "page": 1, "limit": 20}


def test_trace_service_detail_parses_json_and_collects_internal_traces():
    backend = FakeTraceBackend()
    service = TraceService(tracer=backend)

    invalid = _run(service.get_trace, "not-a-uuid")
    detail = _run(service.get_trace, backend.trace_id)

    assert invalid is None
    assert detail["id"] == backend.trace_id
    assert detail["thread_id"] == str(uuid.UUID(int=1))
    assert detail["user_id"] == str(uuid.UUID(int=2))
    assert detail["input_data"] == {"user_input": "hello"}
    assert detail["output_data"] == {"answer": "world"}
    assert detail["metadata"] == {"trace": True}
    assert detail["node_log_ids"] == ["node-1"]
    assert detail["node_logs"][0]["input_data"] == {"prompt": "hello"}
    assert detail["node_logs"][0]["output_data"]["answer"] == "world"
    assert detail["llm_logs"][0]["metadata"] == {"usage": True}
    assert detail["internal_traces"] == [
        {
            "trace_id": backend.sub_trace_id,
            "workflow_id": "internal-agent",
            "thread_id": "thread-internal",
            "status": "success",
            "duration_ms": 3,
            "start_time": datetime(2026, 4, 29, 10, 0),
            "end_time": datetime(2026, 4, 29, 10, 1),
            "error": None,
        }
    ]
    assert backend.workflow_log_calls == [backend.trace_id, backend.sub_trace_id]


def test_trace_service_timeline_combines_node_and_llm_events_in_time_order():
    backend = FakeTraceBackend()
    service = TraceService(tracer=backend)

    events = _run(service.get_trace_timeline, backend.trace_id)

    assert [event["event_type"] for event in events] == [
        "node_start",
        "llm_call",
        "node_end",
    ]
    assert events[0]["timestamp"] <= events[1]["timestamp"] <= events[2]["timestamp"]
    assert events[0]["metadata"] == {"node_type": "llm"}
    assert events[1]["metadata"] == {"model_id": "model-1", "total_tokens": 10}
    assert events[2]["status"] == "success"

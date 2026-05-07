from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agentclaw.runtime.tracing.db_tracer import DatabaseTracer
from agentclaw.state.serializer import safe_json_dumps


pytestmark = pytest.mark.unit


def test_workflow_log_filters_use_start_time_for_audit_time_ranges():
    tracer = DatabaseTracer()

    conditions, params, next_param = tracer._build_workflow_log_filters(
        workflow_id="system_log_audit",
        status="error",
        start_time=datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc),
    )

    query_fragment = " AND ".join(conditions)
    assert "workflow_id = $1" in conditions
    assert "status IN ($2, $3)" in conditions
    assert "start_time >= $4" in conditions
    assert "start_time <= $5" in conditions
    assert "log_time" not in query_fragment
    assert params[0] == "system_log_audit"
    assert params[1:3] == ["error", "timeout"]
    assert all(param.tzinfo is None for param in params[3:])
    assert next_param == 6


def test_safe_json_dumps_serializes_nested_datetime_for_trace_outputs():
    payload = {
        "workflow_id": "system_log_audit",
        "window": {
            "start": datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 4, 27, 10, 0),
        },
        "events": [
            {"at": datetime(2026, 4, 26, 10, 30), "status": "error"},
        ],
    }

    dumped = safe_json_dumps(payload)
    loaded = json.loads(dumped)

    assert loaded["window"]["start"] == "2026-04-26T10:00:00+00:00"
    assert loaded["window"]["end"] == "2026-04-27T10:00:00"
    assert loaded["events"][0]["at"] == "2026-04-26T10:30:00"

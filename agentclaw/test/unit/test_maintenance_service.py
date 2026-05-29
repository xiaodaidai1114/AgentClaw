from __future__ import annotations

from datetime import datetime, timezone

import anyio
import pytest


pytestmark = pytest.mark.unit


def _run(async_fn, *args, **kwargs):
    async def call():
        return await async_fn(*args, **kwargs)

    return anyio.run(call)


class FakeMaintenanceDB:
    def __init__(self):
        self.execute_calls: list[tuple[str, tuple]] = []
        self.fetch_calls: list[tuple[str, tuple]] = []

    async def pg_execute(self, sql: str, *args):
        self.execute_calls.append((sql, args))

    async def pg_fetch(self, sql: str, *args):
        self.fetch_calls.append((sql, args))
        if "expired_base_threads" in sql:
            return [{"base_thread_id": "conv_expired"}]
        return []


def test_cleanup_execution_logs_uses_log_retention_without_touching_checkpoints():
    from agentclaw.runtime.maintenance import MaintenanceRetentionService

    db = FakeMaintenanceDB()
    service = MaintenanceRetentionService(db=db)
    cutoff = datetime(2026, 5, 1, tzinfo=timezone.utc)

    summary = _run(service.cleanup_execution_logs, cutoff)

    assert summary["log_retention_days"] is None
    assert len(db.execute_calls) == 3
    combined_sql = "\n".join(sql for sql, _ in db.execute_calls)
    assert "DELETE FROM llm_logs" in combined_sql
    assert "DELETE FROM node_logs" in combined_sql
    assert "DELETE FROM workflow_logs" in combined_sql
    assert "checkpoint" not in combined_sql.lower()
    assert all(args == (cutoff,) for _, args in db.execute_calls)


def test_cleanup_checkpointer_removes_expired_threads_and_compacts_active_history():
    from agentclaw.runtime.maintenance import MaintenanceRetentionService

    db = FakeMaintenanceDB()
    service = MaintenanceRetentionService(db=db)
    cutoff = datetime(2026, 5, 1, tzinfo=timezone.utc)

    summary = _run(service.cleanup_checkpointer, cutoff)

    assert summary["expired_base_threads"] == 1
    combined_sql = "\n".join(sql for sql, _ in db.execute_calls)
    assert "expired_base_threads" in db.fetch_calls[0][0]
    assert "UPDATE agent_conversations" in combined_sql
    assert "checkpoint_expired_at" in combined_sql
    assert "DELETE FROM checkpoint_writes" in combined_sql
    assert "DELETE FROM checkpoint_blobs" in combined_sql
    assert "DELETE FROM checkpoints" in combined_sql
    assert "row_number()" in combined_sql
    assert "ORDER BY (checkpoint->>'ts')::timestamptz DESC, checkpoint_id DESC" in combined_sql
    assert "jsonb_each_text" in combined_sql
    assert "conv_expired" in repr(db.execute_calls)

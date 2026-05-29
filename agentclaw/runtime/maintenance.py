from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


def normalize_retention_days(value: Any, default: int = 0) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return default
    return days if days >= 0 else default


class MaintenanceRetentionService:
    """Database retention cleanup for execution logs and LangGraph checkpoints."""

    def __init__(self, db=None):
        self.db = db

    async def cleanup_execution_logs(self, cutoff: datetime, *, log_retention_days: int | None = None) -> dict[str, Any]:
        if not self.db:
            return {"log_retention_days": log_retention_days, "executed": False}

        await self.db.pg_execute(
            """
            DELETE FROM llm_logs
            WHERE workflow_log_id IN (
                SELECT id FROM workflow_logs WHERE start_time < $1
            )
            """,
            cutoff,
        )
        await self.db.pg_execute(
            """
            DELETE FROM node_logs
            WHERE workflow_log_id IN (
                SELECT id FROM workflow_logs WHERE start_time < $1
            )
            """,
            cutoff,
        )
        await self.db.pg_execute(
            """
            DELETE FROM workflow_logs
            WHERE start_time < $1
            """,
            cutoff,
        )
        return {"log_retention_days": log_retention_days, "executed": True}

    async def cleanup_checkpointer(self, cutoff: datetime, *, checkpointer_retention_days: int | None = None) -> dict[str, Any]:
        if not self.db:
            return {
                "checkpointer_retention_days": checkpointer_retention_days,
                "expired_base_threads": 0,
                "executed": False,
            }

        expired_rows = await self.db.pg_fetch(
            """
            WITH thread_activity AS (
                SELECT split_part(thread_id, ':', 1) AS base_thread_id,
                       max((checkpoint->>'ts')::timestamptz) AS last_checkpoint_at
                FROM checkpoints
                GROUP BY 1
            ),
            expired_base_threads AS (
                SELECT base_thread_id
                FROM thread_activity
                WHERE last_checkpoint_at < $1
            )
            SELECT base_thread_id FROM expired_base_threads
            """,
            cutoff,
        )
        expired_base_threads = [row["base_thread_id"] for row in expired_rows]

        for base_thread_id in expired_base_threads:
            await self.db.pg_execute(
                """
                UPDATE agent_conversations
                SET checkpoint_expired_at = EXTRACT(EPOCH FROM now())::bigint * 1000
                WHERE id = $1
                  AND checkpoint_expired_at IS NULL
                """,
                base_thread_id,
            )
            await self.db.pg_execute(
                """
                DELETE FROM checkpoint_writes
                WHERE split_part(thread_id, ':', 1) = $1
                """,
                base_thread_id,
            )
            await self.db.pg_execute(
                """
                DELETE FROM checkpoint_blobs
                WHERE split_part(thread_id, ':', 1) = $1
                """,
                base_thread_id,
            )
            await self.db.pg_execute(
                """
                DELETE FROM checkpoints
                WHERE split_part(thread_id, ':', 1) = $1
                """,
                base_thread_id,
            )

        await self.db.pg_execute(
            """
            WITH ranked_checkpoints AS (
                SELECT thread_id,
                       checkpoint_ns,
                       checkpoint_id,
                       checkpoint,
                       (checkpoint->>'ts')::timestamptz AS checkpoint_at,
                       row_number() OVER (
                           PARTITION BY thread_id, checkpoint_ns
                           ORDER BY (checkpoint->>'ts')::timestamptz DESC, checkpoint_id DESC
                       ) AS rn
                FROM checkpoints
            ),
            removable_checkpoints AS (
                SELECT thread_id, checkpoint_ns, checkpoint_id
                FROM ranked_checkpoints
                WHERE checkpoint_at < $1 AND rn > 1
            )
            DELETE FROM checkpoint_writes w
            USING removable_checkpoints r
            WHERE w.thread_id = r.thread_id
              AND w.checkpoint_ns = r.checkpoint_ns
              AND w.checkpoint_id = r.checkpoint_id
            """,
            cutoff,
        )
        await self.db.pg_execute(
            """
            WITH ranked_checkpoints AS (
                SELECT thread_id,
                       checkpoint_ns,
                       checkpoint_id,
                       checkpoint,
                       (checkpoint->>'ts')::timestamptz AS checkpoint_at,
                       row_number() OVER (
                           PARTITION BY thread_id, checkpoint_ns
                           ORDER BY (checkpoint->>'ts')::timestamptz DESC, checkpoint_id DESC
                       ) AS rn
                FROM checkpoints
            ),
            removable_checkpoints AS (
                SELECT thread_id, checkpoint_ns, checkpoint_id
                FROM ranked_checkpoints
                WHERE checkpoint_at < $1 AND rn > 1
            )
            DELETE FROM checkpoints c
            USING removable_checkpoints r
            WHERE c.thread_id = r.thread_id
              AND c.checkpoint_ns = r.checkpoint_ns
              AND c.checkpoint_id = r.checkpoint_id
            """,
            cutoff,
        )
        await self.db.pg_execute(
            """
            WITH required_blobs AS (
                SELECT DISTINCT c.thread_id,
                       c.checkpoint_ns,
                       kv.key AS channel,
                       kv.value AS version
                FROM checkpoints c
                CROSS JOIN LATERAL jsonb_each_text(c.checkpoint -> 'channel_versions') kv
            )
            DELETE FROM checkpoint_blobs b
            WHERE NOT EXISTS (
                SELECT 1
                FROM required_blobs rb
                WHERE rb.thread_id = b.thread_id
                  AND rb.checkpoint_ns = b.checkpoint_ns
                  AND rb.channel = b.channel
                  AND rb.version = b.version
            )
            """,
        )
        return {
            "checkpointer_retention_days": checkpointer_retention_days,
            "expired_base_threads": len(expired_base_threads),
            "executed": True,
        }


async def run_retention_once(config=None, db=None, *, now: datetime | None = None) -> dict[str, Any]:
    if config is None:
        from agentclaw.config import get_config
        config = get_config()
    if db is None:
        from agentclaw.database import get_database
        db = get_database()

    maintenance = getattr(config, "maintenance", None)
    log_days = normalize_retention_days(getattr(maintenance, "log_retention_days", 0), 0)
    checkpoint_days = normalize_retention_days(getattr(maintenance, "checkpointer_retention_days", 0), 0)
    current_time = now or datetime.now(timezone.utc)
    service = MaintenanceRetentionService(db=db)
    summary: dict[str, Any] = {
        "log_retention_days": log_days,
        "checkpointer_retention_days": checkpoint_days,
        "log_cleanup": None,
        "checkpointer_cleanup": None,
    }

    if db is None or not getattr(db, "pg_pool", True):
        summary["skipped"] = "database_unavailable"
        return summary

    if log_days > 0:
        summary["log_cleanup"] = await service.cleanup_execution_logs(
            current_time - timedelta(days=log_days),
            log_retention_days=log_days,
        )
    if checkpoint_days > 0:
        summary["checkpointer_cleanup"] = await service.cleanup_checkpointer(
            current_time - timedelta(days=checkpoint_days),
            checkpointer_retention_days=checkpoint_days,
        )
    return summary


async def retention_loop(config=None, db=None, *, initial_delay_seconds: float = 60.0, interval_seconds: float = 86400.0) -> None:
    try:
        if initial_delay_seconds > 0:
            await asyncio.sleep(initial_delay_seconds)
        while True:
            try:
                summary = await run_retention_once(config=config, db=db)
                if summary.get("log_cleanup") or summary.get("checkpointer_cleanup"):
                    logger.info(f"维护清理完成: {summary}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"维护清理失败: {exc}")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.debug("维护清理任务已停止")
        raise

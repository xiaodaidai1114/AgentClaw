"""
渠道模块 - 持久化存储

PostgreSQL 存储渠道配置和消息日志。
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agentclaw.channels.models import ChannelMessageLog, ChannelRecord
from agentclaw.logger.config import get_logger
from agentclaw.utils.datetime import to_local_aware_datetime

logger = get_logger(__name__)


class ChannelStore:
    """渠道 PostgreSQL 存储"""

    def __init__(self, pg_pool):
        self._pool = pg_pool

    async def init(self) -> None:
        """创建表和索引"""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    id VARCHAR(64) PRIMARY KEY,
                    name VARCHAR(128) UNIQUE NOT NULL,
                    type VARCHAR(32) NOT NULL,
                    workflow_id VARCHAR(128) NOT NULL DEFAULT '__builtin__',
                    user_input_field VARCHAR(64) NOT NULL DEFAULT 'user_input',
                    thread_mode VARCHAR(32) NOT NULL DEFAULT 'per_user',
                    enabled BOOLEAN NOT NULL DEFAULT true,
                    config JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_channels_type
                ON channels(type)
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS channel_message_logs (
                    id VARCHAR(64) PRIMARY KEY,
                    channel_id VARCHAR(64) NOT NULL,
                    channel_name VARCHAR(128) NOT NULL DEFAULT '',
                    user_id VARCHAR(256) NOT NULL DEFAULT '',
                    chat_id VARCHAR(256) NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    reply TEXT NOT NULL DEFAULT '',
                    workflow_id VARCHAR(128) NOT NULL DEFAULT '',
                    trace_id VARCHAR(64) NOT NULL DEFAULT '',
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("""
                ALTER TABLE channel_message_logs
                ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64) NOT NULL DEFAULT ''
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cml_channel_id
                ON channel_message_logs(channel_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cml_created_at
                ON channel_message_logs(created_at DESC)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cml_status
                ON channel_message_logs(status)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cml_trace_id
                ON channel_message_logs(trace_id)
            """)
        logger.info("Channel tables initialized")

    # ── Channel CRUD ──────────────────────────────────

    async def create_channel(self, record: ChannelRecord) -> ChannelRecord:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO channels
                    (id, name, type, workflow_id, user_input_field,
                     thread_mode, enabled, config, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                record.id,
                record.name,
                record.type,
                record.workflow_id,
                record.user_input_field,
                record.thread_mode,
                record.enabled,
                json.dumps(record.config, ensure_ascii=False),
                record.created_at,
                record.updated_at,
            )
        return record

    async def get_channel(self, channel_id: str) -> Optional[ChannelRecord]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM channels WHERE id = $1", channel_id
            )
        if not row:
            return None
        return self._row_to_channel(row)

    async def get_channel_by_name(self, name: str) -> Optional[ChannelRecord]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM channels WHERE name = $1", name
            )
        if not row:
            return None
        return self._row_to_channel(row)

    async def list_channels(
        self,
        type: Optional[str] = None,
        enabled: Optional[bool] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Tuple[List[ChannelRecord], int]:
        conditions = []
        params: list = []
        idx = 1

        if type:
            conditions.append(f"type = ${idx}")
            params.append(type)
            idx += 1
        if enabled is not None:
            conditions.append(f"enabled = ${idx}")
            params.append(enabled)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with self._pool.acquire() as conn:
            total_row = await conn.fetchrow(
                f"SELECT COUNT(*) as cnt FROM channels {where}", *params
            )
            total = total_row["cnt"] if total_row else 0

            offset = (page - 1) * limit
            rows = await conn.fetch(
                f"SELECT * FROM channels {where} "
                f"ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
                *params,
                limit,
                offset,
            )

        return [self._row_to_channel(r) for r in rows], total

    async def update_channel(
        self, channel_id: str, updates: dict
    ) -> Optional[ChannelRecord]:
        if not updates:
            return await self.get_channel(channel_id)

        set_clauses = []
        params: list = []
        idx = 1

        simple_fields = [
            "workflow_id", "user_input_field", "thread_mode", "enabled",
        ]
        for f in simple_fields:
            if f in updates:
                set_clauses.append(f"{f} = ${idx}")
                params.append(updates[f])
                idx += 1

        if "config" in updates:
            set_clauses.append(f"config = ${idx}")
            cfg = updates["config"]
            if isinstance(cfg, dict):
                cfg = json.dumps(cfg, ensure_ascii=False)
            params.append(cfg)
            idx += 1

        # always bump updated_at
        set_clauses.append(f"updated_at = ${idx}")
        params.append(datetime.utcnow())
        idx += 1

        params.append(channel_id)
        sql = (
            f"UPDATE channels SET {', '.join(set_clauses)} "
            f"WHERE id = ${idx}"
        )

        async with self._pool.acquire() as conn:
            await conn.execute(sql, *params)

        return await self.get_channel(channel_id)

    async def delete_channel(self, channel_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM channels WHERE id = $1", channel_id
            )
        return result == "DELETE 1"

    # ── Message Logs ──────────────────────────────────

    async def save_message_log(self, log: ChannelMessageLog) -> None:
        """保存消息日志（设计为 fire-and-forget 调用）"""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO channel_message_logs
                        (id, channel_id, channel_name, user_id, chat_id,
                         message, reply, workflow_id, trace_id, status,
                         duration_ms, error, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    """,
                    log.id,
                    log.channel_id,
                    log.channel_name,
                    log.user_id,
                    log.chat_id,
                    log.message,
                    log.reply,
                    log.workflow_id,
                    log.trace_id,
                    log.status,
                    log.duration_ms,
                    log.error,
                    log.created_at,
                )
        except Exception as e:
            logger.error(f"Failed to save message log: {e}")

    async def list_message_logs(
        self,
        channel_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Tuple[List[ChannelMessageLog], int]:
        conditions = []
        params: list = []
        idx = 1
        normalized_start = to_local_aware_datetime(start_time)
        normalized_end = to_local_aware_datetime(end_time)

        if channel_id:
            conditions.append(f"channel_id = ${idx}")
            params.append(channel_id)
            idx += 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if normalized_start:
            conditions.append(f"created_at >= ${idx}")
            params.append(normalized_start)
            idx += 1
        if normalized_end:
            conditions.append(f"created_at <= ${idx}")
            params.append(normalized_end)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with self._pool.acquire() as conn:
            total_row = await conn.fetchrow(
                f"SELECT COUNT(*) as cnt FROM channel_message_logs {where}",
                *params,
            )
            total = total_row["cnt"] if total_row else 0

            offset = (page - 1) * limit
            rows = await conn.fetch(
                f"SELECT * FROM channel_message_logs {where} "
                f"ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
                *params,
                limit,
                offset,
            )

        return [self._row_to_log(r) for r in rows], total

    async def get_log_stats(
        self,
        channel_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """获取消息日志统计"""
        conditions = []
        params: list = []
        idx = 1
        normalized_start = to_local_aware_datetime(start_time)
        normalized_end = to_local_aware_datetime(end_time)

        if channel_id:
            conditions.append(f"channel_id = ${idx}")
            params.append(channel_id)
            idx += 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if normalized_start:
            conditions.append(f"created_at >= ${idx}")
            params.append(normalized_start)
            idx += 1
        if normalized_end:
            conditions.append(f"created_at <= ${idx}")
            params.append(normalized_end)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                WITH filtered_logs AS (
                    SELECT status, duration_ms, trace_id
                    FROM channel_message_logs {where}
                ),
                base_stats AS (
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE status = 'success') as success,
                        COUNT(*) FILTER (WHERE status = 'error') as error,
                        COUNT(*) FILTER (WHERE status = 'timeout') as timeout,
                        COALESCE(AVG(duration_ms) FILTER (WHERE status = 'success'), 0) as avg_duration_ms
                    FROM filtered_logs
                ),
                token_stats AS (
                    SELECT
                        COALESCE(SUM(llm.total_tokens), 0) as total_tokens,
                        COALESCE(SUM(llm.prompt_tokens), 0) as prompt_tokens,
                        COALESCE(SUM(llm.completion_tokens), 0) as completion_tokens
                    FROM llm_logs llm
                    WHERE llm.workflow_log_id::text IN (
                        SELECT trace_id FROM filtered_logs
                        WHERE trace_id IS NOT NULL AND trace_id != ''
                    )
                )
                SELECT
                    base_stats.total,
                    base_stats.success,
                    base_stats.error,
                    base_stats.timeout,
                    base_stats.avg_duration_ms,
                    token_stats.total_tokens,
                    token_stats.prompt_tokens,
                    token_stats.completion_tokens
                FROM base_stats
                CROSS JOIN token_stats
                """,
                *params,
            )

        return {
            "total": row["total"] if row else 0,
            "success": row["success"] if row else 0,
            "error": row["error"] if row else 0,
            "timeout": row["timeout"] if row else 0,
            "avg_duration_ms": float(row["avg_duration_ms"]) if row else 0,
            "total_tokens": row["total_tokens"] if row else 0,
            "prompt_tokens": row["prompt_tokens"] if row else 0,
            "completion_tokens": row["completion_tokens"] if row else 0,
        }

    # ── Migration ─────────────────────────────────────

    async def import_from_json(self, json_path: str) -> int:
        """
        从 channels.json 一次性导入到数据库。

        仅在数据库中无渠道配置时调用，避免重复导入。
        返回导入数量。
        """
        path = Path(json_path)
        if not path.exists():
            return 0

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        imported = 0
        for ch in data.get("channels", []):
            name = ch.get("name", "")
            if not name:
                continue

            # 跳过已存在的
            existing = await self.get_channel_by_name(name)
            if existing:
                continue

            record = ChannelRecord(
                id=str(uuid.uuid4()),
                name=name,
                type=ch.get("type", ""),
                workflow_id=ch.get("workflow_id", "__builtin__"),
                user_input_field=ch.get("user_input_field", "user_input"),
                thread_mode=ch.get("thread_mode", "per_user"),
                enabled=ch.get("enabled", True),
                config=ch.get("config", {}),
            )
            await self.create_channel(record)
            imported += 1
            logger.info(f"Imported channel from JSON: {name} → id={record.id}")

        if imported:
            logger.info(f"Imported {imported} channels from {json_path}")
        return imported

    # ── Row Deserializers ─────────────────────────────

    @staticmethod
    def _row_to_channel(row) -> ChannelRecord:
        config_data = row["config"]
        if isinstance(config_data, str):
            config_data = json.loads(config_data)

        return ChannelRecord(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            workflow_id=row["workflow_id"],
            user_input_field=row["user_input_field"],
            thread_mode=row["thread_mode"],
            enabled=row["enabled"],
            config=config_data or {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_log(row) -> ChannelMessageLog:
        return ChannelMessageLog(
            id=row["id"],
            channel_id=row["channel_id"],
            channel_name=row["channel_name"],
            user_id=row["user_id"],
            chat_id=row["chat_id"],
            message=row["message"],
            reply=row["reply"],
            workflow_id=row["workflow_id"],
            trace_id=row.get("trace_id", "") or "",
            status=row["status"],
            duration_ms=row["duration_ms"] or 0,
            error=row["error"] or "",
            created_at=row["created_at"],
        )

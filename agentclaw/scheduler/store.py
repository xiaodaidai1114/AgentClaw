"""
定时任务模块 - 持久化存储

支持 PostgreSQL 和内存两种后端。
"""

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agentclaw.logger.config import get_logger
from agentclaw.scheduler.models import (
    ExecutionStatus,
    JobConfig,
    JobExecution,
    JobStatus,
    ScheduledJob,
    TriggerConfig,
    WebhookConfig,
)

logger = get_logger(__name__)


class JobStore(ABC):
    """任务存储抽象接口"""

    @abstractmethod
    async def init(self) -> None:
        """初始化存储（创建表等）"""

    @abstractmethod
    async def save_job(self, job: ScheduledJob) -> None:
        """保存任务"""

    @abstractmethod
    async def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        """获取任务"""

    @abstractmethod
    async def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        workflow_id: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Tuple[List[ScheduledJob], int]:
        """列取任务"""

    @abstractmethod
    async def update_job(self, job_id: str, updates: dict) -> Optional[ScheduledJob]:
        """更新任务"""

    @abstractmethod
    async def delete_job(self, job_id: str) -> bool:
        """删除任务"""

    @abstractmethod
    async def save_execution(self, execution: JobExecution) -> None:
        """保存执行记录"""

    @abstractmethod
    async def update_execution(self, execution_id: str, updates: dict) -> None:
        """更新执行记录"""

    @abstractmethod
    async def get_execution(self, execution_id: str) -> Optional[JobExecution]:
        """获取执行记录"""

    @abstractmethod
    async def list_executions(
        self, job_id: str, page: int = 1, limit: int = 20
    ) -> Tuple[List[JobExecution], int]:
        """列取执行记录"""


class PostgresJobStore(JobStore):
    """PostgreSQL 存储实现"""

    def __init__(self, pg_pool):
        self._pool = pg_pool

    async def init(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id VARCHAR(64) PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    description TEXT,
                    workflow_id VARCHAR(100) NOT NULL,
                    trigger_config JSONB NOT NULL,
                    inputs JSONB DEFAULT '{}'::jsonb,
                    status VARCHAR(20) DEFAULT 'enabled',
                    job_config JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    last_run_at TIMESTAMPTZ,
                    next_run_at TIMESTAMPTZ,
                    run_count INT DEFAULT 0,
                    fail_count INT DEFAULT 0
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_status
                ON scheduled_jobs(status)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_workflow
                ON scheduled_jobs(workflow_id)
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS job_executions (
                    id VARCHAR(64) PRIMARY KEY,
                    job_id VARCHAR(64) NOT NULL REFERENCES scheduled_jobs(id) ON DELETE CASCADE,
                    status VARCHAR(20) DEFAULT 'pending',
                    started_at TIMESTAMPTZ DEFAULT NOW(),
                    ended_at TIMESTAMPTZ,
                    duration_ms INT,
                    inputs JSONB,
                    outputs JSONB,
                    error TEXT,
                    retry_count INT DEFAULT 0
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_job_executions_job
                ON job_executions(job_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_job_executions_started
                ON job_executions(started_at DESC)
            """)
            # Webhook support columns
            await conn.execute("""
                ALTER TABLE scheduled_jobs
                ADD COLUMN IF NOT EXISTS webhook_config JSONB DEFAULT '{}'::jsonb
            """)
            await conn.execute("""
                ALTER TABLE job_executions
                ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(20) DEFAULT 'schedule'
            """)
            # Migrate TIMESTAMP → TIMESTAMPTZ for timezone-aware datetime support
            await self._migrate_timestamp_columns(conn)
        logger.info("Scheduler tables initialized")

    async def _migrate_timestamp_columns(self, conn) -> None:
        """Migrate TIMESTAMP columns to TIMESTAMPTZ (idempotent)."""
        migrations = [
            ("scheduled_jobs", ["created_at", "updated_at", "last_run_at", "next_run_at"]),
            ("job_executions", ["started_at", "ended_at"]),
        ]
        for table, columns in migrations:
            for col in columns:
                await conn.execute(f"""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = '{table}' AND column_name = '{col}'
                              AND data_type = 'timestamp without time zone'
                        ) THEN
                            ALTER TABLE {table} ALTER COLUMN {col} TYPE TIMESTAMPTZ
                                USING {col} AT TIME ZONE 'UTC';
                        END IF;
                    END $$;
                """)

    async def save_job(self, job: ScheduledJob) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO scheduled_jobs
                    (id, name, description, workflow_id, trigger_config, inputs,
                     status, job_config, webhook_config, created_at, updated_at, next_run_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                job.id,
                job.name,
                job.description,
                job.workflow_id,
                json.dumps(job.trigger.model_dump(mode="json")),
                json.dumps(job.inputs),
                job.status.value,
                json.dumps(job.config.model_dump()),
                json.dumps(job.webhook.model_dump()),
                job.created_at,
                job.updated_at,
                job.next_run_at,
            )

    async def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM scheduled_jobs WHERE id = $1", job_id
            )
        if not row:
            return None
        return self._row_to_job(row)

    async def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        workflow_id: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Tuple[List[ScheduledJob], int]:
        conditions = []
        params: list = []
        idx = 1

        if status:
            conditions.append(f"status = ${idx}")
            params.append(status.value)
            idx += 1
        if workflow_id:
            conditions.append(f"workflow_id = ${idx}")
            params.append(workflow_id)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with self._pool.acquire() as conn:
            total_row = await conn.fetchrow(
                f"SELECT COUNT(*) as cnt FROM scheduled_jobs {where}", *params
            )
            total = total_row["cnt"] if total_row else 0

            offset = (page - 1) * limit
            rows = await conn.fetch(
                f"SELECT * FROM scheduled_jobs {where} "
                f"ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
                *params,
                limit,
                offset,
            )

        return [self._row_to_job(r) for r in rows], total

    async def update_job(self, job_id: str, updates: dict) -> Optional[ScheduledJob]:
        if not updates:
            return await self.get_job(job_id)

        set_clauses = []
        params: list = []
        idx = 1

        field_mapping = {
            "name": "name",
            "description": "description",
            "workflow_id": "workflow_id",
            "status": "status",
            "last_run_at": "last_run_at",
            "next_run_at": "next_run_at",
            "run_count": "run_count",
            "fail_count": "fail_count",
        }

        for key, col in field_mapping.items():
            if key in updates:
                set_clauses.append(f"{col} = ${idx}")
                val = updates[key]
                if isinstance(val, JobStatus):
                    val = val.value
                params.append(val)
                idx += 1

        # JSONB fields
        if "trigger" in updates:
            set_clauses.append(f"trigger_config = ${idx}")
            trigger = updates["trigger"]
            if isinstance(trigger, TriggerConfig):
                trigger = trigger.model_dump(mode="json")
            params.append(json.dumps(trigger))
            idx += 1

        if "inputs" in updates:
            set_clauses.append(f"inputs = ${idx}")
            params.append(json.dumps(updates["inputs"]))
            idx += 1

        if "config" in updates:
            set_clauses.append(f"job_config = ${idx}")
            cfg = updates["config"]
            if isinstance(cfg, JobConfig):
                cfg = cfg.model_dump()
            params.append(json.dumps(cfg))
            idx += 1

        if "webhook" in updates:
            set_clauses.append(f"webhook_config = ${idx}")
            wh = updates["webhook"]
            if isinstance(wh, WebhookConfig):
                wh = wh.model_dump()
            params.append(json.dumps(wh))
            idx += 1

        set_clauses.append(f"updated_at = ${idx}")
        params.append(datetime.now(timezone.utc))
        idx += 1

        params.append(job_id)
        sql = (
            f"UPDATE scheduled_jobs SET {', '.join(set_clauses)} "
            f"WHERE id = ${idx}"
        )

        async with self._pool.acquire() as conn:
            await conn.execute(sql, *params)

        return await self.get_job(job_id)

    async def delete_job(self, job_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM scheduled_jobs WHERE id = $1", job_id
            )
        return result == "DELETE 1"

    async def save_execution(self, execution: JobExecution) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO job_executions
                    (id, job_id, status, trigger_source, started_at, inputs, retry_count)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                execution.id,
                execution.job_id,
                execution.status.value,
                execution.trigger_source,
                execution.started_at,
                json.dumps(execution.inputs),
                execution.retry_count,
            )

    async def update_execution(self, execution_id: str, updates: dict) -> None:
        set_clauses = []
        params: list = []
        idx = 1

        simple_fields = ["ended_at", "duration_ms", "error", "retry_count"]
        for f in simple_fields:
            if f in updates:
                set_clauses.append(f"{f} = ${idx}")
                params.append(updates[f])
                idx += 1

        if "status" in updates:
            set_clauses.append(f"status = ${idx}")
            val = updates["status"]
            if isinstance(val, ExecutionStatus):
                val = val.value
            params.append(val)
            idx += 1

        if "outputs" in updates:
            set_clauses.append(f"outputs = ${idx}")
            params.append(json.dumps(updates["outputs"]))
            idx += 1

        if not set_clauses:
            return

        params.append(execution_id)
        sql = (
            f"UPDATE job_executions SET {', '.join(set_clauses)} "
            f"WHERE id = ${idx}"
        )

        async with self._pool.acquire() as conn:
            await conn.execute(sql, *params)

    async def get_execution(self, execution_id: str) -> Optional[JobExecution]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM job_executions WHERE id = $1", execution_id
            )
        if not row:
            return None
        return self._row_to_execution(row)

    async def list_executions(
        self, job_id: str, page: int = 1, limit: int = 20
    ) -> Tuple[List[JobExecution], int]:
        offset = (page - 1) * limit
        async with self._pool.acquire() as conn:
            total_row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM job_executions WHERE job_id = $1",
                job_id,
            )
            total = total_row["cnt"] if total_row else 0

            rows = await conn.fetch(
                "SELECT * FROM job_executions WHERE job_id = $1 "
                "ORDER BY started_at DESC LIMIT $2 OFFSET $3",
                job_id,
                limit,
                offset,
            )

        return [self._row_to_execution(r) for r in rows], total

    @staticmethod
    def _row_to_job(row) -> ScheduledJob:
        trigger_data = row["trigger_config"]
        if isinstance(trigger_data, str):
            trigger_data = json.loads(trigger_data)

        config_data = row["job_config"]
        if isinstance(config_data, str):
            config_data = json.loads(config_data)

        inputs_data = row["inputs"]
        if isinstance(inputs_data, str):
            inputs_data = json.loads(inputs_data)

        webhook_data = row.get("webhook_config", {})
        if isinstance(webhook_data, str):
            webhook_data = json.loads(webhook_data)

        return ScheduledJob(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            workflow_id=row["workflow_id"],
            trigger=TriggerConfig.model_validate(trigger_data),
            inputs=inputs_data or {},
            status=JobStatus(row["status"]),
            config=JobConfig.model_validate(config_data),
            webhook=WebhookConfig.model_validate(webhook_data or {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_run_at=row["last_run_at"],
            next_run_at=row["next_run_at"],
            run_count=row["run_count"] or 0,
            fail_count=row["fail_count"] or 0,
        )

    @staticmethod
    def _row_to_execution(row) -> JobExecution:
        inputs_data = row["inputs"]
        if isinstance(inputs_data, str):
            inputs_data = json.loads(inputs_data)

        outputs_data = row["outputs"]
        if isinstance(outputs_data, str) and outputs_data:
            outputs_data = json.loads(outputs_data)

        return JobExecution(
            id=row["id"],
            job_id=row["job_id"],
            status=ExecutionStatus(row["status"]),
            trigger_source=row.get("trigger_source", "schedule"),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            duration_ms=row["duration_ms"],
            inputs=inputs_data or {},
            outputs=outputs_data,
            error=row["error"],
            retry_count=row["retry_count"] or 0,
        )


class MemoryJobStore(JobStore):
    """内存存储实现（用于测试）"""

    def __init__(self):
        self._jobs: Dict[str, ScheduledJob] = {}
        self._executions: Dict[str, JobExecution] = {}

    async def init(self) -> None:
        pass

    async def save_job(self, job: ScheduledJob) -> None:
        self._jobs[job.id] = job.model_copy()

    async def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        job = self._jobs.get(job_id)
        return job.model_copy() if job else None

    async def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        workflow_id: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Tuple[List[ScheduledJob], int]:
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        if workflow_id:
            jobs = [j for j in jobs if j.workflow_id == workflow_id]

        total = len(jobs)
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        offset = (page - 1) * limit
        return [j.model_copy() for j in jobs[offset : offset + limit]], total

    async def update_job(self, job_id: str, updates: dict) -> Optional[ScheduledJob]:
        job = self._jobs.get(job_id)
        if not job:
            return None

        for key, val in updates.items():
            if hasattr(job, key):
                setattr(job, key, val)
        job.updated_at = datetime.now(timezone.utc)
        return job.model_copy()

    async def delete_job(self, job_id: str) -> bool:
        if job_id in self._jobs:
            del self._jobs[job_id]
            # cascade delete executions
            self._executions = {
                k: v for k, v in self._executions.items() if v.job_id != job_id
            }
            return True
        return False

    async def save_execution(self, execution: JobExecution) -> None:
        self._executions[execution.id] = execution.model_copy()

    async def update_execution(self, execution_id: str, updates: dict) -> None:
        ex = self._executions.get(execution_id)
        if not ex:
            return
        for key, val in updates.items():
            if hasattr(ex, key):
                setattr(ex, key, val)

    async def get_execution(self, execution_id: str) -> Optional[JobExecution]:
        ex = self._executions.get(execution_id)
        return ex.model_copy() if ex else None

    async def list_executions(
        self, job_id: str, page: int = 1, limit: int = 20
    ) -> Tuple[List[JobExecution], int]:
        execs = [e for e in self._executions.values() if e.job_id == job_id]
        total = len(execs)
        execs.sort(key=lambda e: e.started_at, reverse=True)
        offset = (page - 1) * limit
        return [e.model_copy() for e in execs[offset : offset + limit]], total

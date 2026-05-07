"""
定时任务模块 - 调度器核心

管理 APScheduler 实例，协调任务存储和执行。
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from agentclaw.logger.config import get_logger
from agentclaw.scheduler.lock import AdvisoryLock
from agentclaw.scheduler.models import (
    CreateJobRequest,
    JobConfig,
    JobStatus,
    ScheduledJob,
    TriggerConfig,
    TriggerType,
    UpdateJobRequest,
    WebhookConfig,
)
from agentclaw.scheduler.runner import JobRunner
from agentclaw.scheduler.store import JobStore

logger = get_logger(__name__)


@dataclass
class SchedulerConfig:
    """调度器配置"""
    enabled: bool = True
    timezone: str = "Asia/Shanghai"
    max_workers: int = 10
    coalesce: bool = True
    max_instances: int = 1


class WorkflowScheduler:
    """工作流调度器"""

    _instance: Optional["WorkflowScheduler"] = None

    def __init__(self, store: JobStore, runner: JobRunner, config: SchedulerConfig):
        self._store = store
        self._runner = runner
        self._config = config
        self._apscheduler = None
        self._running = False

    @classmethod
    async def initialize(
        cls,
        config: SchedulerConfig,
        pg_pool=None,
    ) -> "WorkflowScheduler":
        """初始化调度器（单例）"""
        if cls._instance and cls._instance._running:
            return cls._instance

        if pg_pool is None:
            from agentclaw.database import get_database
            db = get_database()
            if db and db.pg_pool:
                pg_pool = db.pg_pool

        # 创建 store
        if pg_pool:
            from agentclaw.scheduler.store import PostgresJobStore
            store = PostgresJobStore(pg_pool)
        else:
            from agentclaw.scheduler.store import MemoryJobStore
            store = MemoryJobStore()
            logger.warning("Scheduler using MemoryJobStore (no PostgreSQL)")

        # 创建 lock
        lock = AdvisoryLock(pg_pool) if pg_pool else _NoopLock()

        # 创建 runner
        runner = JobRunner(store, lock)

        instance = cls(store, runner, config)
        await instance.start()

        cls._instance = instance
        return instance

    @classmethod
    def get_instance(cls) -> Optional["WorkflowScheduler"]:
        """获取调度器实例"""
        return cls._instance

    async def start(self) -> None:
        """启动调度器"""
        if self._running:
            return

        # 初始化存储
        await self._store.init()

        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.date import DateTrigger
            from apscheduler.triggers.interval import IntervalTrigger
        except ImportError:
            logger.error(
                "APScheduler not installed. "
                "Install with: pip install 'agentclaw[scheduler]'"
            )
            raise

        self._apscheduler = AsyncIOScheduler(
            timezone=self._config.timezone,
            job_defaults={
                "coalesce": self._config.coalesce,
                "max_instances": self._config.max_instances,
            },
        )

        # 加载已有任务
        jobs, _ = await self._store.list_jobs(
            status=JobStatus.ENABLED, limit=10000
        )
        loaded_jobs = 0
        for job in jobs:
            stale_updates = self._stale_date_job_updates(job)
            if stale_updates:
                await self._store.update_job(job.id, stale_updates)
                logger.info(f"Job {job.id} ({job.name}) 已过期，启动时自动禁用")
                continue
            try:
                self._register_apscheduler_job(job)
                loaded_jobs += 1
            except Exception as e:
                logger.warning(f"Failed to register job {job.id}: {e}")

        self._apscheduler.start()
        self._running = True
        logger.info(
            f"Scheduler started: {loaded_jobs}/{len(jobs)} jobs loaded, "
            f"timezone={self._config.timezone}"
        )

    async def stop(self) -> None:
        """停止调度器"""
        if self._apscheduler and self._running:
            self._apscheduler.shutdown(wait=False)
            self._running = False
            logger.info("Scheduler stopped")

    # ── CRUD ──────────────────────────────────────────

    async def add_job(self, request: CreateJobRequest) -> ScheduledJob:
        """创建任务"""
        job = ScheduledJob(
            name=request.name,
            description=request.description,
            workflow_id=request.workflow_id,
            trigger=request.trigger,
            inputs=request.inputs,
            config=request.config or JobConfig(),
            webhook=request.webhook or WebhookConfig(),
        )

        # 计算下次执行时间
        job.next_run_at = self._compute_next_run(job.trigger)

        await self._store.save_job(job)

        if self._apscheduler and self._running:
            self._register_apscheduler_job(job)

        logger.info(
            f"Job added: {job.id} ({job.name}), "
            f"next_run={job.next_run_at}"
        )
        return job

    async def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        """获取任务"""
        return await self._store.get_job(job_id)

    async def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        workflow_id: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Tuple[List[ScheduledJob], int]:
        """列取任务"""
        return await self._store.list_jobs(status, workflow_id, page, limit)

    async def update_job(
        self, job_id: str, request: UpdateJobRequest
    ) -> Optional[ScheduledJob]:
        """更新任务"""
        updates = request.model_dump(exclude_none=True)
        if not updates:
            return await self._store.get_job(job_id)

        # 如果更新了 trigger，重新计算 next_run_at
        if "trigger" in updates:
            trigger = TriggerConfig.model_validate(updates["trigger"])
            updates["next_run_at"] = self._compute_next_run(trigger)

        job = await self._store.update_job(job_id, updates)

        # 重新注册 APScheduler job
        if job and self._apscheduler and self._running:
            try:
                self._apscheduler.remove_job(job_id)
            except Exception:
                pass
            if job.status == JobStatus.ENABLED:
                self._register_apscheduler_job(job)

        return job

    async def remove_job(self, job_id: str) -> bool:
        """删除任务"""
        if self._apscheduler:
            try:
                self._apscheduler.remove_job(job_id)
            except Exception:
                pass

        deleted = await self._store.delete_job(job_id)
        if deleted:
            logger.info(f"Job removed: {job_id}")
        return deleted

    async def pause_job(self, job_id: str) -> Optional[ScheduledJob]:
        """暂停任务"""
        if self._apscheduler:
            try:
                self._apscheduler.pause_job(job_id)
            except Exception:
                pass

        return await self._store.update_job(
            job_id, {"status": JobStatus.PAUSED}
        )

    async def resume_job(self, job_id: str) -> Optional[ScheduledJob]:
        """恢复任务"""
        job = await self._store.get_job(job_id)
        if not job:
            return None

        if self._apscheduler:
            try:
                self._apscheduler.resume_job(job_id)
            except Exception:
                # job 可能不在 APScheduler 中，重新注册
                self._register_apscheduler_job(job)

        return await self._store.update_job(
            job_id, {"status": JobStatus.ENABLED}
        )

    async def trigger_job(
        self,
        job_id: str,
        trigger_source: str = "manual",
        override_inputs: dict | None = None,
    ) -> str:
        """立即触发任务"""
        job = await self._store.get_job(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found")

        from agentclaw.scheduler.models import ExecutionStatus, JobExecution

        effective_inputs = override_inputs if override_inputs is not None else job.inputs
        execution = JobExecution(
            job_id=job.id,
            status=ExecutionStatus.PENDING,
            trigger_source=trigger_source,
            inputs=effective_inputs,
            retry_count=0,
        )
        await self._store.save_execution(execution)

        # 异步执行，不阻塞
        asyncio.create_task(
            self._runner.run_job(
                job,
                trigger_source,
                override_inputs,
                execution_id=execution.id,
            )
        )
        return execution.id

    # ── 执行记录 ──────────────────────────────────────

    async def list_executions(
        self, job_id: str, page: int = 1, limit: int = 20
    ):
        return await self._store.list_executions(job_id, page, limit)

    async def get_execution(self, execution_id: str):
        return await self._store.get_execution(execution_id)

    # ── 内部方法 ──────────────────────────────────────

    def _register_apscheduler_job(self, job: ScheduledJob) -> None:
        """将 ScheduledJob 注册到 APScheduler"""
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        trigger = job.trigger

        if trigger.type == TriggerType.CRON:
            parts = trigger.expression.split()
            ap_trigger = CronTrigger(
                minute=parts[0] if len(parts) > 0 else "*",
                hour=parts[1] if len(parts) > 1 else "*",
                day=parts[2] if len(parts) > 2 else "*",
                month=parts[3] if len(parts) > 3 else "*",
                day_of_week=parts[4] if len(parts) > 4 else "*",
                timezone=trigger.timezone or self._config.timezone,
            )
        elif trigger.type == TriggerType.INTERVAL:
            kwargs = {}
            if trigger.weeks:
                kwargs["weeks"] = trigger.weeks
            if trigger.days:
                kwargs["days"] = trigger.days
            if trigger.hours:
                kwargs["hours"] = trigger.hours
            if trigger.minutes:
                kwargs["minutes"] = trigger.minutes
            if trigger.seconds:
                kwargs["seconds"] = trigger.seconds
            if trigger.start_date:
                kwargs["start_date"] = trigger.start_date
            if trigger.end_date:
                kwargs["end_date"] = trigger.end_date
            ap_trigger = IntervalTrigger(**kwargs)
        elif trigger.type == TriggerType.DATE:
            ap_trigger = DateTrigger(
                run_date=trigger.run_date,
                timezone=trigger.timezone or self._config.timezone,
            )
        else:
            raise ValueError(f"Unknown trigger type: {trigger.type}")

        self._apscheduler.add_job(
            self._job_callback,
            trigger=ap_trigger,
            id=job.id,
            name=job.name,
            replace_existing=True,
            args=[job.id],
        )

    async def _job_callback(self, job_id: str) -> None:
        """APScheduler 回调"""
        job = await self._store.get_job(job_id)
        if not job:
            logger.warning(f"Job {job_id} not found in store, skipping")
            return

        if job.status != JobStatus.ENABLED:
            logger.debug(f"Job {job_id} is {job.status.value}, skipping")
            return

        logger.info(f"Job triggered: {job.id} ({job.name})")

        try:
            await self._runner.run_job(job, trigger_source="schedule")
        except Exception as e:
            logger.error(f"Job {job_id} callback error: {e}")

        # 更新 next_run_at
        next_run = self._compute_next_run(job.trigger)
        if next_run:
            await self._store.update_job(job_id, {"next_run_at": next_run})

    def _stale_date_job_updates(self, job: ScheduledJob) -> Optional[dict]:
        """识别启动时已过期的一次性任务，避免 APScheduler 记录 misfire 警告。"""
        if job.trigger.type != TriggerType.DATE:
            return None
        next_run = self._compute_next_run(job.trigger)
        if next_run is None or next_run >= datetime.now(timezone.utc):
            return None
        return {"status": JobStatus.DISABLED, "next_run_at": None}

    def _compute_next_run(self, trigger: TriggerConfig) -> Optional[datetime]:
        """计算下次执行时间"""
        try:
            if trigger.type == TriggerType.CRON:
                from croniter import croniter
                now = datetime.now(timezone.utc)
                cron = croniter(trigger.expression, now)
                next_dt = cron.get_next(datetime)
                # croniter returns naive datetime; attach UTC timezone
                if next_dt.tzinfo is None:
                    next_dt = next_dt.replace(tzinfo=timezone.utc)
                return next_dt
            elif trigger.type == TriggerType.DATE:
                run_date = trigger.run_date
                if run_date and run_date.tzinfo is None:
                    run_date = run_date.replace(tzinfo=timezone.utc)
                return run_date
            elif trigger.type == TriggerType.INTERVAL:
                # interval 没有固定的"下次时间"，返回 None
                return None
        except Exception as e:
            logger.warning(f"Failed to compute next_run: {e}")
        return None


class _NoopLock:
    """无操作锁（无数据库时使用）"""

    async def try_acquire(self, key: str) -> bool:
        return True

    async def release(self, key: str) -> None:
        pass

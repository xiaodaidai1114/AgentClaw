"""
定时任务模块 - 任务执行器

负责实际执行工作流任务，处理超时、重试和结果记录。
"""

import asyncio
import time
from datetime import datetime, timezone

from agentclaw.logger.config import get_logger
from agentclaw.scheduler.lock import AdvisoryLock
from agentclaw.scheduler.models import (
    ConcurrencyPolicy,
    ExecutionStatus,
    JobExecution,
    ScheduledJob,
)
from agentclaw.scheduler.store import JobStore

logger = get_logger(__name__)


class JobRunner:
    """任务执行器"""

    def __init__(self, store: JobStore, lock: AdvisoryLock):
        self._store = store
        self._lock = lock

    async def run_job(
        self,
        job: ScheduledJob,
        trigger_source: str = "schedule",
        override_inputs: dict | None = None,
        execution_id: str | None = None,
    ) -> None:
        """执行一个定时任务"""
        # 1. 并发控制
        lock_acquired = False
        if job.config.concurrency != ConcurrencyPolicy.PARALLEL:
            lock_acquired = await self._lock.try_acquire(job.id)
            if not lock_acquired:
                logger.info(
                    f"Job {job.id} ({job.name}) skipped: "
                    f"another instance is running"
                )
                if execution_id:
                    now = datetime.now(timezone.utc)
                    await self._store.update_execution(
                        execution_id,
                        {
                            "status": ExecutionStatus.CANCELLED,
                            "ended_at": now,
                            "error": "Skipped: another instance is running",
                        },
                    )
                return

        try:
            await self._execute_with_retry(job, trigger_source, override_inputs, execution_id)
        finally:
            if lock_acquired:
                await self._lock.release(job.id)

    async def _execute_with_retry(
        self,
        job: ScheduledJob,
        trigger_source: str = "schedule",
        override_inputs: dict | None = None,
        initial_execution_id: str | None = None,
    ) -> None:
        """带重试的执行逻辑"""
        effective_inputs = override_inputs if override_inputs is not None else job.inputs
        max_retries = job.config.retry_count
        retry = 0

        while True:
            execution_id = initial_execution_id if retry == 0 else None
            execution_payload = dict(
                job_id=job.id,
                status=ExecutionStatus.RUNNING,
                trigger_source=trigger_source,
                inputs=effective_inputs,
                retry_count=retry,
            )
            if execution_id:
                execution_payload["id"] = execution_id
            execution = JobExecution(**execution_payload)
            if execution_id:
                await self._store.update_execution(
                    execution.id,
                    {"status": ExecutionStatus.RUNNING},
                )
            else:
                await self._store.save_execution(execution)

            success = await self._execute_once(job, execution)

            # 更新 job 计数
            update_fields = {
                "last_run_at": datetime.now(timezone.utc),
                "run_count": job.run_count + 1,
            }
            if not success:
                update_fields["fail_count"] = job.fail_count + 1

            await self._store.update_job(job.id, update_fields)

            if success or retry >= max_retries:
                break

            # 重试：指数退避
            retry += 1
            delay = job.config.retry_interval * (2 ** (retry - 1))
            logger.info(
                f"Job {job.id} ({job.name}) retry {retry}/{max_retries} "
                f"in {delay}s"
            )
            await asyncio.sleep(delay)

    async def _execute_once(
        self, job: ScheduledJob, execution: JobExecution
    ) -> bool:
        """执行一次工作流，返回是否成功"""
        start = time.perf_counter()

        try:
            # 获取工作流
            from agentclaw.api.registry import WorkflowRegistry

            workflow = WorkflowRegistry.get(job.workflow_id)
            if not workflow:
                error_msg = f"Workflow '{job.workflow_id}' not found"
                logger.error(f"Job {job.id}: {error_msg}")
                await self._store.update_execution(
                    execution.id,
                    {
                        "status": ExecutionStatus.FAILED,
                        "error": error_msg,
                        "ended_at": datetime.now(timezone.utc),
                        "duration_ms": int(
                            (time.perf_counter() - start) * 1000
                        ),
                    },
                )
                return False

            # 创建 OutputChannel 以捕获 output_to_user 内容
            from agentclaw.runtime.streaming.context import (
                OutputChannel,
                _output_channel_var,
            )

            channel = OutputChannel(
                workflow_id=job.workflow_id,
                thread_id=execution.id,
                stream_mode=False,
            )
            channel_token = _output_channel_var.set(channel)

            try:
                # 执行工作流
                result = await asyncio.wait_for(
                    workflow.run(
                        inputs=execution.inputs,
                        thread_id=execution.id,
                        timeout=job.config.timeout,
                    ),
                    timeout=job.config.timeout,
                )
            finally:
                _output_channel_var.reset(channel_token)

            # 提取结果
            state = result.get("state", {})
            metadata = result.get("metadata", {})
            duration_ms = int((time.perf_counter() - start) * 1000)

            # 提取 answer：优先 OutputChannel，其次 __messages__，最后 state["answer"]
            answer = None

            # 1. 从 OutputChannel 获取（最可靠，捕获所有 output_to_user 内容）
            if channel.outputs:
                answer = "".join(channel.outputs)

            # 2. 从 __messages__ 取最后一条 assistant 消息
            if not answer:
                messages = state.get("__messages__") or []
                for msg in reversed(messages):
                    if isinstance(msg, dict) and msg.get("role") == "assistant":
                        content = msg.get("content", "")
                        if content:
                            answer = content
                            break

            # 3. fallback 到 state["answer"]
            if not answer:
                answer = state.get("answer")

            outputs = {
                "answer": answer or "",
                "status": state.get("__status__", "completed"),
                "metadata": {
                    k: v
                    for k, v in metadata.items()
                    if k in ("trace_id", "workflow_id", "duration_ms")
                },
            }

            await self._store.update_execution(
                execution.id,
                {
                    "status": ExecutionStatus.SUCCESS,
                    "outputs": outputs,
                    "ended_at": datetime.now(timezone.utc),
                    "duration_ms": duration_ms,
                },
            )

            logger.info(
                f"Job {job.id} ({job.name}) completed in {duration_ms}ms"
            )
            return True

        except asyncio.TimeoutError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.warning(
                f"Job {job.id} ({job.name}) timed out after "
                f"{job.config.timeout}s"
            )
            await self._store.update_execution(
                execution.id,
                {
                    "status": ExecutionStatus.TIMEOUT,
                    "error": f"Execution timed out after {job.config.timeout}s",
                    "ended_at": datetime.now(timezone.utc),
                    "duration_ms": duration_ms,
                },
            )
            return False

        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            error_msg = f"{type(e).__name__}: {e}"
            logger.error(f"Job {job.id} ({job.name}) failed: {error_msg}")
            await self._store.update_execution(
                execution.id,
                {
                    "status": ExecutionStatus.FAILED,
                    "error": error_msg,
                    "ended_at": datetime.now(timezone.utc),
                    "duration_ms": duration_ms,
                },
            )
            return False

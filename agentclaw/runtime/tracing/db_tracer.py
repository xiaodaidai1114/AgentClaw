"""
数据库追踪器

将 Trace、Span、Generation 记录写入数据库，用于：
- 调用链追踪
- 性能分析
- Token 用量统计
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from contextvars import ContextVar
from contextlib import asynccontextmanager
import asyncio
import json
import os
import uuid

from agentclaw.runtime.tracing.base import BaseTracer, GenerationData
from agentclaw.state.serializer import safe_json_dumps
from agentclaw.logger.config import get_logger
from agentclaw.utils.datetime import to_local_naive_datetime

if TYPE_CHECKING:
    from agentclaw.database.manager import DatabaseManager

logger = get_logger(__name__)


# ============ 数据模型 ============

@dataclass
class TraceRecord:
    """Trace 记录"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str = ""
    thread_id: str = ""
    user_id: Optional[str] = None
    name: str = ""
    run_type: str = "blocking"  # blocking / stream
    input_data: Optional[dict] = None
    output_data: Optional[dict] = None
    node_log_ids: List[str] = field(default_factory=list)  # 节点日志ID列表（按执行顺序）
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: str = "running"  # running, success, error
    error: Optional[str] = None
    
    def append_node_log(self, node_log_id: str) -> None:
        """追加节点日志ID"""
        self.node_log_ids.append(node_log_id)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "name": self.name,
            "run_type": self.run_type,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "node_log_ids": self.node_log_ids,
            "metadata": self.metadata,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class SpanRecord:
    """Span 记录（节点执行）"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = ""
    parent_span_id: Optional[str] = None
    name: str = ""
    node_type: str = ""
    input_data: Optional[dict] = None
    output_data: Optional[dict] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    duration_ms: float = 0
    status: str = "running"
    error: Optional[str] = None
    _save_task: Optional[asyncio.Task] = field(default=None, repr=False)  # 保存任务引用
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "node_type": self.node_type,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "metadata": self.metadata,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class GenerationRecord:
    """Generation 记录（LLM 调用）"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = ""
    span_id: str = ""
    model_id: str = ""
    model_name: str = ""
    prompt: str = ""
    completion: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "success"
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "model_id": self.model_id,
            "model_name": self.model_name,
            "prompt": self.prompt,
            "completion": self.completion,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "status": self.status,
            "error": self.error,
        }


# ============ ContextVar ============

_current_trace: ContextVar[Optional[TraceRecord]] = ContextVar('_current_trace', default=None)
_current_span: ContextVar[Optional[SpanRecord]] = ContextVar('_current_span', default=None)


# ============ DatabaseTracer ============

class DatabaseTracer(BaseTracer):
    """
    数据库追踪器
    
    记录工作流执行的 Trace、Span、Generation 到数据库
    数据库写入在后台异步执行，不阻塞工作流
    
    Example:
        tracer = DatabaseTracer(db_manager)
        
        async with tracer.trace("my_workflow", thread_id="xxx") as trace:
            async with tracer.span("node_1", node_type="llm") as span:
                # 执行节点
                tracer.log_generation(model="gpt-4", ...)
    """
    
    def __init__(self, db: Optional["DatabaseManager"] = None):
        self.db = db
        self._enabled = db is not None
        self._pending_tasks: Set[asyncio.Task] = set()
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def enable(self, db: "DatabaseManager") -> None:
        """启用追踪"""
        self.db = db
        self._enabled = True
    
    def disable(self) -> None:
        """禁用追踪"""
        self._enabled = False
    
    def _fire_and_forget(self, coro) -> Optional[asyncio.Task]:
        """
        Fire-and-forget: 在后台执行协程，不阻塞当前流程
        
        Returns:
            创建的任务对象，可用于等待完成
        """
        try:
            loop = asyncio.get_running_loop()
            if loop.is_closed():
                return None
            task = loop.create_task(coro)
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
            return task
        except RuntimeError:
            # 没有运行中的事件循环
            return None

    def _build_workflow_log_filters(
        self,
        workflow_id: Optional[str] = None,
        workflow_ids: Optional[List[str]] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> tuple[list[str], list[Any], int]:
        """构建 workflow_logs 查询条件，并统一处理带时区时间参数。"""
        conditions: list[str] = []
        params: list[Any] = []
        param_idx = 1

        if workflow_id:
            conditions.append(f"workflow_id = ${param_idx}")
            params.append(workflow_id)
            param_idx += 1
        elif workflow_ids is not None:
            if not workflow_ids:
                conditions.append("1 = 0")
            else:
                placeholders = ", ".join(
                    [f"${i}" for i in range(param_idx, param_idx + len(workflow_ids))]
                )
                conditions.append(f"workflow_id IN ({placeholders})")
                params.extend(workflow_ids)
                param_idx += len(workflow_ids)

        if status:
            if status == "error":
                conditions.append(f"status IN (${param_idx}, ${param_idx + 1})")
                params.extend(["error", "timeout"])
                param_idx += 2
            else:
                conditions.append(f"status = ${param_idx}")
                params.append(status)
                param_idx += 1

        normalized_start = to_local_naive_datetime(start_time)
        if normalized_start:
            conditions.append(f"start_time >= ${param_idx}")
            params.append(normalized_start)
            param_idx += 1

        normalized_end = to_local_naive_datetime(end_time)
        if normalized_end:
            conditions.append(f"start_time <= ${param_idx}")
            params.append(normalized_end)
            param_idx += 1

        return conditions, params, param_idx

    async def _get_trace_summary_aggregate(
        self,
        workflow_id: Optional[str] = None,
        workflow_ids: Optional[List[str]] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> dict:
        """统一的追踪汇总查询，供仪表盘/执行追踪等场景复用。"""
        zero_summary = {
            "total": 0,
            "success": 0,
            "error": 0,
            "running": 0,
            "avg_duration_ms": None,
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
        if not self.db or not self.db.pg_pool:
            return zero_summary

        await self._expire_stale_running_logs(
            workflow_id=workflow_id,
            workflow_ids=workflow_ids,
        )
        conditions, params, _ = self._build_workflow_log_filters(
            workflow_id=workflow_id,
            workflow_ids=workflow_ids,
            status=status,
            start_time=start_time,
            end_time=end_time,
        )
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        row = await self.db.pg_fetchrow(f"""
            WITH filtered_traces AS (
                SELECT id, status, duration_ms
                FROM workflow_logs
                {where_clause}
            ),
            trace_stats AS (
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status = 'success') as success,
                    COUNT(*) FILTER (WHERE status IN ('error', 'timeout')) as error,
                    COUNT(*) FILTER (WHERE status = 'running') as running,
                    AVG(duration_ms) FILTER (WHERE status = 'success') as avg_duration_ms
                FROM filtered_traces
            ),
            token_stats AS (
                SELECT
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as completion_tokens
                FROM llm_logs
                WHERE workflow_log_id IN (SELECT id FROM filtered_traces)
            )
            SELECT
                trace_stats.total,
                trace_stats.success,
                trace_stats.error,
                trace_stats.running,
                trace_stats.avg_duration_ms,
                token_stats.total_tokens,
                token_stats.prompt_tokens,
                token_stats.completion_tokens
            FROM trace_stats
            CROSS JOIN token_stats
        """, *params)
        return dict(row) if row else zero_summary
    
    async def flush(self) -> None:
        """等待所有待处理的写入任务完成"""
        if self._pending_tasks:
            # 过滤掉已完成的任务
            pending = [t for t in self._pending_tasks if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._pending_tasks.clear()

    @staticmethod
    def _get_stale_running_timeout_seconds() -> int:
        """获取 stale running 自动超时阈值（秒）。"""
        raw = os.getenv("TRACE_STALE_TIMEOUT_SECONDS", "300")
        try:
            value = int(raw)
            return value if value > 0 else 300
        except Exception:
            return 300

    async def _expire_stale_running_logs(
        self,
        workflow_id: Optional[str] = None,
        workflow_ids: Optional[List[str]] = None,
    ) -> int:
        """
        将长时间处于 running 的执行归档为 timeout，避免 UI 永久显示“运行中”。

        Returns:
            归档条数
        """
        if not self.db or not self.db.pg_pool:
            return 0

        timeout_seconds = self._get_stale_running_timeout_seconds()
        timeout_reason = f"Execution timed out after {timeout_seconds}s (stale running cleanup)"

        conditions = [
            "status = 'running'",
            "start_time < (NOW() - make_interval(secs => $1))",
        ]
        params: List[Any] = [timeout_seconds, timeout_reason]
        param_idx = 3

        if workflow_id:
            conditions.append(f"workflow_id = ${param_idx}")
            params.append(workflow_id)
            param_idx += 1
        elif workflow_ids is not None:
            if not workflow_ids:
                return 0
            placeholders = ", ".join(
                [f"${i}" for i in range(param_idx, param_idx + len(workflow_ids))]
            )
            conditions.append(f"workflow_id IN ({placeholders})")
            params.extend(workflow_ids)

        where_clause = " AND ".join(conditions)

        try:
            rows = await self.db.pg_fetch(
                f"""
                UPDATE workflow_logs
                SET
                    status = 'timeout',
                    error = COALESCE(NULLIF(error, ''), $2),
                    end_time = COALESCE(end_time, NOW()),
                    duration_ms = CASE
                        WHEN duration_ms IS NULL OR duration_ms <= 0
                            THEN EXTRACT(EPOCH FROM (COALESCE(end_time, NOW()) - start_time)) * 1000
                        ELSE duration_ms
                    END
                WHERE {where_clause}
                RETURNING id
                """,
                *params,
            )
            expired = len(rows) if rows else 0
            if expired > 0:
                logger.info(f"自动归档 stale running traces: {expired} 条 -> timeout")
            return expired
        except Exception as e:
            logger.warning(f"归档 stale running traces 失败: {e}")
            return 0
    
    # === Trace 上下文 ===
    
    @asynccontextmanager
    async def trace(
        self,
        name: str,
        workflow_id: str = "",
        thread_id: str = "",
        user_id: Optional[str] = None,
        input_data: Optional[dict] = None,
        metadata: Optional[dict] = None,
        run_type: str = "blocking",
    ):
        """创建 Trace 上下文"""
        record = TraceRecord(
            workflow_id=workflow_id,
            thread_id=thread_id,
            user_id=user_id,
            name=name,
            run_type=run_type,
            input_data=input_data,
            metadata=metadata or {},
        )
        
        token = _current_trace.set(record)
        
        if self._enabled:
            # 后台保存，不阻塞
            self._fire_and_forget(self._save_trace(record))
        
        try:
            yield record
        except Exception as e:
            record.status = "error"
            record.error = str(e)
            raise
        finally:
            record.end_time = datetime.now()
            if record.status == "running":
                record.status = "success"
            
            if self._enabled:
                # trace 结束时同步更新，确保详情查询能立即读到最终 output_data/status
                await self._update_trace(record)

            _current_trace.set(None)
    
    # === Span 上下文 ===
    
    @asynccontextmanager
    async def span(
        self,
        name: str,
        node_type: str = "function",
        input_data: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ):
        """创建 Span 上下文"""
        trace = _current_trace.get()
        parent_span = _current_span.get()
        
        record = SpanRecord(
            trace_id=trace.id if trace else "",
            parent_span_id=parent_span.id if parent_span else None,
            name=name,
            node_type=node_type,
            input_data=input_data,
            metadata=metadata or {},
        )
        
        token = _current_span.set(record)
        save_task = None
        
        if self._enabled:
            # 后台保存，保留任务引用以便后续等待
            save_task = self._fire_and_forget(self._save_span(record))
            record._save_task = save_task
        
        try:
            yield record
        except Exception as e:
            # GraphInterrupt 是正常的中断信号，不标记为 error
            from langgraph.errors import GraphInterrupt
            if not isinstance(e, GraphInterrupt):
                record.status = "error"
                record.error = str(e)
            raise
        finally:
            record.end_time = datetime.now()
            record.duration_ms = (record.end_time - record.start_time).total_seconds() * 1000
            if record.status == "running":
                record.status = "success"
            
            if self._enabled:
                # 确保 INSERT 完成后再执行 UPDATE，避免竞态条件
                if save_task is not None:
                    try:
                        await save_task
                    except Exception:
                        pass  # INSERT 失败不影响后续流程
                # 后台更新，不阻塞
                self._fire_and_forget(self._update_span(record))
            
            _current_span.set(parent_span)
    
    # === Generation 记录 ===
    
    async def log_generation(
        self,
        model_id: str,
        model_name: str,
        prompt: str,
        completion: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0,
        metadata: Optional[dict] = None,
        status: str = "success",
        error: Optional[str] = None,
    ) -> Optional[GenerationRecord]:
        """记录 LLM 调用"""
        if not self._enabled:
            return None
        
        trace = _current_trace.get()
        span = _current_span.get()
        
        record = GenerationRecord(
            trace_id=trace.id if trace else "",
            span_id=span.id if span else "",
            model_id=model_id,
            model_name=model_name,
            prompt=prompt,
            completion=completion,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
            metadata=metadata or {},
            status=status,
            error=error,
        )
        
        # 后台保存，不阻塞
        self._fire_and_forget(self._save_generation(record))
        return record
    
    # === 数据库操作 ===
    
    async def _save_trace(self, trace: TraceRecord) -> None:
        """保存 Trace 到数据库"""
        if not self.db or not self.db.pg_pool:
            return
        
        try:
            await self.db.pg_execute("""
                INSERT INTO workflow_logs (id, workflow_id, thread_id, user_id, name, run_type, input_data, metadata, start_time, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (id) DO UPDATE SET
                    node_log_ids = EXCLUDED.node_log_ids,
                    end_time = EXCLUDED.end_time,
                    status = EXCLUDED.status,
                    error = EXCLUDED.error
            """, trace.id, trace.workflow_id, trace.thread_id, trace.user_id, trace.name, trace.run_type,
                safe_json_dumps(trace.input_data) if trace.input_data else None,
                safe_json_dumps(trace.metadata) if trace.metadata else None,
                trace.start_time, trace.status)
        except Exception as e:
            logger.warning(f"保存 workflow_log 失败: {e}")
    
    async def _update_trace(self, trace: TraceRecord) -> None:
        """更新 Trace"""
        if not self.db or not self.db.pg_pool:
            return

        # 计算 duration_ms
        duration_ms = None
        if trace.end_time and trace.start_time:
            duration_ms = (trace.end_time - trace.start_time).total_seconds() * 1000

        try:
            output_json = safe_json_dumps(trace.output_data) if trace.output_data else None
            await self.db.pg_execute("""
                UPDATE workflow_logs SET
                    node_log_ids = $2,
                    output_data = $3,
                    end_time = $4,
                    status = $5,
                    error = $6,
                    duration_ms = $7
                WHERE id = $1
            """, trace.id,
                safe_json_dumps(trace.node_log_ids) if trace.node_log_ids else "[]",
                output_json,
                trace.end_time, trace.status, trace.error, duration_ms)
        except Exception as e:
            logger.warning(f"更新 workflow_log 失败: {e}")
    
    async def _save_span(self, span: SpanRecord) -> None:
        """保存 Span 到数据库"""
        if not self.db or not self.db.pg_pool:
            return
        
        try:
            # 处理空字符串为 None
            workflow_log_id = span.trace_id if span.trace_id else None
            parent_node_log_id = span.parent_span_id if span.parent_span_id else None
            
            await self.db.pg_execute("""
                INSERT INTO node_logs (id, workflow_log_id, parent_node_log_id, name, node_type, input_data, metadata, start_time, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """, span.id, workflow_log_id, parent_node_log_id, span.name, span.node_type,
                safe_json_dumps(span.input_data) if span.input_data else None,
                safe_json_dumps(span.metadata) if span.metadata else None,
                span.start_time, span.status)
        except Exception as e:
            logger.warning(f"保存 node_log 失败: {e}")
    
    async def _update_span(self, span: SpanRecord) -> None:
        """更新 Span"""
        if not self.db or not self.db.pg_pool:
            return
        
        input_json = safe_json_dumps(span.input_data) if span.input_data else None
        output_json = safe_json_dumps(span.output_data) if span.output_data else None
        
        try:
            await self.db.pg_execute("""
                UPDATE node_logs SET
                    input_data = $2,
                    output_data = $3,
                    end_time = $4,
                    duration_ms = $5,
                    status = $6,
                    error = $7
                WHERE id = $1
            """, span.id, input_json, output_json,
                span.end_time, span.duration_ms, span.status, span.error)
        except Exception as e:
            logger.warning(f"更新 node_log 失败: {e}")
    
    async def _save_generation(self, gen: GenerationRecord) -> None:
        """保存 Generation 到数据库"""
        if not self.db or not self.db.pg_pool:
            return
        
        try:
            # 处理空字符串为 None（数据库期望 UUID 或 NULL）
            workflow_log_id = gen.trace_id if gen.trace_id else None
            node_log_id = gen.span_id if gen.span_id else None
            
            await self.db.pg_execute("""
                INSERT INTO llm_logs (id, workflow_log_id, node_log_id, model_id, model_name, prompt, completion,
                    prompt_tokens, completion_tokens, total_tokens, latency_ms, metadata, created_at, status, error)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            """, gen.id, workflow_log_id, node_log_id, gen.model_id, gen.model_name,
                gen.prompt, gen.completion, gen.prompt_tokens, gen.completion_tokens,
                gen.total_tokens, gen.latency_ms,
                safe_json_dumps(gen.metadata) if gen.metadata else None,
                gen.created_at, gen.status, gen.error)
        except Exception as e:
            logger.warning(f"保存 llm_log 失败: {e}")
    
    async def update_generation_metadata(self, generation_id: str, metadata_update: dict) -> None:
        """合并更新 generation 的 metadata"""
        if not self.db or not self.db.pg_pool or not generation_id:
            return
        try:
            row = await self.db.pg_fetchrow(
                "SELECT metadata FROM llm_logs WHERE id = $1", generation_id
            )
            if row:
                existing = json.loads(row["metadata"]) if row["metadata"] else {}
                existing.update(metadata_update)
                await self.db.pg_execute(
                    "UPDATE llm_logs SET metadata = $2 WHERE id = $1",
                    generation_id, safe_json_dumps(existing),
                )
        except Exception as e:
            logger.warning(f"更新 llm_log metadata 失败: {e}")

    # === 查询接口 ===
    
    async def get_workflow_log(self, log_id: str) -> Optional[dict]:
        """获取 workflow_log 详情"""
        if not self.db or not self.db.pg_pool:
            return None
        
        row = await self.db.pg_fetchrow("SELECT * FROM workflow_logs WHERE id = $1", log_id)
        return dict(row) if row else None
    
    async def list_workflow_logs(
        self,
        workflow_id: Optional[str] = None,
        workflow_ids: Optional[List[str]] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[dict]:
        """
        列出 workflow_logs
        
        Args:
            workflow_id: 工作流 ID（可选）
            workflow_ids: 工作流 ID 列表，用于过滤只显示这些工作流的日志（可选）
            status: 状态过滤 running/success/error（可选）
            start_time: 开始时间过滤（可选）
            end_time: 结束时间过滤（可选）
            limit: 每页数量
            offset: 偏移量
            
        Returns:
            工作流日志列表
        """
        if not self.db or not self.db.pg_pool:
            return []
        
        try:
            await self._expire_stale_running_logs(workflow_id=workflow_id, workflow_ids=workflow_ids)
            conditions, params, param_idx = self._build_workflow_log_filters(
                workflow_id=workflow_id,
                workflow_ids=workflow_ids,
                status=status,
                start_time=start_time,
                end_time=end_time,
            )
            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
            rows = await self.db.pg_fetch(
                f"SELECT * FROM workflow_logs{where_clause} ORDER BY start_time DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}",
                *params, limit, offset
            )
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"列出工作流日志失败: {e}")
            return []
    
    async def get_usage_stats(
        self,
        workflow_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict:
        """获取使用统计"""
        if not self.db or not self.db.pg_pool:
            return {"total_tokens": 0, "total_calls": 0}
        
        try:
            conditions, params, _ = self._build_workflow_log_filters(
                workflow_id=workflow_id,
                start_time=start_date,
                end_time=end_date,
            )
            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
            row = await self.db.pg_fetchrow(f"""
                WITH filtered_traces AS (
                    SELECT id
                    FROM workflow_logs
                    {where_clause}
                )
                SELECT
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COUNT(*) as total_calls
                FROM llm_logs
                WHERE workflow_log_id IN (SELECT id FROM filtered_traces)
            """, *params)
            return dict(row) if row else {"total_tokens": 0, "total_calls": 0}
        except Exception as e:
            logger.warning(f"获取统计失败: {e}")
            return {"total_tokens": 0, "total_calls": 0}
    
    async def get_workflow_stats(
        self,
        workflow_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict:
        """
        获取工作流统计数据
        
        Args:
            workflow_id: 工作流 ID
            start_date: 开始时间（可选）
            end_date: 结束时间（可选）
            
        Returns:
            统计数据字典，包含：
            - total_count: 总执行次数
            - success_count: 成功次数
            - error_count: 失败次数
            - running_count: 运行中次数（未正常结束）
            - completed_count: 已完成次数（success + error）
            - success_rate: 成功率（基于已完成的执行）
            - avg_duration_ms: 平均耗时
            - p95_duration_ms: P95 耗时
            - p99_duration_ms: P99 耗时
        """
        if not self.db or not self.db.pg_pool:
            return {}
        
        try:
            summary = await self._get_trace_summary_aggregate(
                workflow_id=workflow_id,
                start_time=start_date,
                end_time=end_date,
            )
            normalized_start = to_local_naive_datetime(start_date)
            normalized_end = to_local_naive_datetime(end_date)

            conditions = ["workflow_id = $1"]
            params = [workflow_id]
            param_idx = 2
            
            if normalized_start:
                conditions.append(f"start_time >= ${param_idx}")
                params.append(normalized_start)
                param_idx += 1
            
            if normalized_end:
                conditions.append(f"start_time <= ${param_idx}")
                params.append(normalized_end)
                param_idx += 1
            
            where_clause = " AND ".join(conditions)
            
            row = await self.db.pg_fetchrow(f"""
                SELECT 
                    COUNT(*) FILTER (WHERE status = 'timeout') as timeout_count,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) FILTER (WHERE status = 'success') as p95_duration_ms,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) FILTER (WHERE status = 'success') as p99_duration_ms
                FROM workflow_logs
                WHERE {where_clause}
            """, *params)
            
            extra = dict(row) if row else {}
            success = summary.get("success", 0)
            error = summary.get("error", 0)
            completed = success + error
            return {
                "total_count": summary.get("total", 0),
                "success_count": success,
                "error_count": error,
                "running_count": summary.get("running", 0),
                "timeout_count": extra.get("timeout_count", 0),
                "avg_duration_ms": summary.get("avg_duration_ms"),
                "p95_duration_ms": extra.get("p95_duration_ms"),
                "p99_duration_ms": extra.get("p99_duration_ms"),
                "total_tokens": summary.get("total_tokens", 0),
                "prompt_tokens": summary.get("prompt_tokens", 0),
                "completion_tokens": summary.get("completion_tokens", 0),
                "completed_count": completed,
                "success_rate": (success / completed * 100) if completed > 0 else 0,
            }
        except Exception as e:
            logger.warning(f"获取工作流统计失败: {e}")
            return {}
    
    async def get_node_logs(self, trace_id: str) -> List[dict]:
        """
        获取某次执行的所有节点日志
        
        Args:
            trace_id: 工作流执行日志 ID
            
        Returns:
            节点日志列表，按开始时间排序
        """
        if not self.db or not self.db.pg_pool:
            return []
        
        try:
            # 转换为 UUID 类型
            import uuid as uuid_module
            trace_uuid = uuid_module.UUID(trace_id) if isinstance(trace_id, str) else trace_id
            
            rows = await self.db.pg_fetch("""
                SELECT * FROM node_logs 
                WHERE workflow_log_id = $1 
                ORDER BY start_time ASC
            """, trace_uuid)
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"获取节点日志失败: {e}")
            return []
    
    async def get_llm_logs(self, trace_id: str) -> List[dict]:
        """
        获取某次执行的所有 LLM 调用日志
        
        Args:
            trace_id: 工作流执行日志 ID
            
        Returns:
            LLM 调用日志列表，按创建时间排序
        """
        if not self.db or not self.db.pg_pool:
            return []
        
        try:
            # 转换为 UUID 类型
            import uuid as uuid_module
            trace_uuid = uuid_module.UUID(trace_id) if isinstance(trace_id, str) else trace_id
            
            rows = await self.db.pg_fetch("""
                SELECT * FROM llm_logs 
                WHERE workflow_log_id = $1 
                ORDER BY created_at ASC
            """, trace_uuid)
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"获取 LLM 日志失败: {e}")
            return []

    async def get_trace_token_stats_batch(self, trace_ids: List[str]) -> dict:
        """批量获取 trace 的 token 聚合统计。"""
        if not self.db or not self.db.pg_pool or not trace_ids:
            return {}

        try:
            import uuid as uuid_module

            trace_uuids = [
                uuid_module.UUID(trace_id) if isinstance(trace_id, str) else trace_id
                for trace_id in trace_ids
            ]
            rows = await self.db.pg_fetch("""
                SELECT
                    workflow_log_id,
                    COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COUNT(*) as llm_calls
                FROM llm_logs
                WHERE workflow_log_id = ANY($1)
                GROUP BY workflow_log_id
            """, trace_uuids)
            return {
                str(row["workflow_log_id"]): {
                    "prompt_tokens": row["prompt_tokens"],
                    "completion_tokens": row["completion_tokens"],
                    "total_tokens": row["total_tokens"],
                    "llm_calls": row["llm_calls"],
                }
                for row in rows
            }
        except Exception as e:
            logger.warning(f"批量获取 trace token 统计失败: {e}")
            return {}

    async def get_last_workflow_execution_time(self, workflow_id: str) -> Optional[datetime]:
        """获取工作流最后一次执行时间。"""
        if not self.db or not self.db.pg_pool:
            return None

        try:
            await self._expire_stale_running_logs(workflow_id=workflow_id)
            row = await self.db.pg_fetchrow("""
                SELECT start_time
                FROM workflow_logs
                WHERE workflow_id = $1
                ORDER BY start_time DESC
                LIMIT 1
            """, workflow_id)
            return row["start_time"] if row else None
        except Exception as e:
            logger.warning(f"获取工作流最后执行时间失败: {e}")
            return None
    
    async def count_workflow_logs(
        self,
        workflow_id: Optional[str] = None,
        workflow_ids: Optional[List[str]] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> int:
        """
        统计工作流日志数量
        
        Args:
            workflow_id: 工作流 ID（可选）
            workflow_ids: 工作流 ID 列表，用于过滤（可选）
            status: 状态过滤（可选）
            start_time: 开始时间过滤（可选）
            end_time: 结束时间过滤（可选）
            
        Returns:
            日志数量
        """
        if not self.db or not self.db.pg_pool:
            return 0
        
        try:
            await self._expire_stale_running_logs(workflow_id=workflow_id, workflow_ids=workflow_ids)
            conditions, params, _ = self._build_workflow_log_filters(
                workflow_id=workflow_id,
                workflow_ids=workflow_ids,
                status=status,
                start_time=start_time,
                end_time=end_time,
            )
            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
            row = await self.db.pg_fetchrow(
                f"SELECT COUNT(*) as count FROM workflow_logs{where_clause}",
                *params
            )
            return row["count"] if row else 0
        except Exception as e:
            logger.warning(f"统计工作流日志失败: {e}")
            return 0
    
    async def get_global_stats(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        workflow_ids: Optional[List[str]] = None,
    ) -> dict:
        """
        获取全局统计数据（用于 Dashboard）
        
        Args:
            start_date: 开始时间（可选）
            end_date: 结束时间（可选）
            workflow_ids: 工作流 ID 列表，用于过滤（可选）
            
        Returns:
            统计数据字典，包含：
            - total_count: 总执行次数
            - success_count: 成功次数
            - error_count: 失败次数
            - running_count: 运行中次数
            - success_rate: 成功率
            - avg_duration_ms: 平均耗时
        """
        if not self.db or not self.db.pg_pool:
            return {}
        
        try:
            summary = await self._get_trace_summary_aggregate(
                workflow_ids=workflow_ids,
                start_time=start_date,
                end_time=end_date,
            )
            success = summary.get("success", 0)
            error = summary.get("error", 0)
            completed = success + error
            return {
                "total_count": summary.get("total", 0),
                "success_count": success,
                "error_count": error,
                "running_count": summary.get("running", 0),
                "avg_duration_ms": summary.get("avg_duration_ms"),
                "success_rate": (success / completed * 100) if completed > 0 else 0,
            }
        except Exception as e:
            logger.warning(f"获取全局统计失败: {e}")
            return {}
    
    async def get_traces_summary(
        self,
        workflow_id: Optional[str] = None,
        workflow_ids: Optional[List[str]] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> dict:
        """
        获取追踪统计摘要
        
        Args:
            workflow_ids: 工作流 ID 列表，用于过滤（可选）
        
        Returns:
            统计摘要字典，包含：
            - total: 总数
            - success: 成功数
            - error: 失败数
            - running: 运行中数
            - avg_duration_ms: 平均耗时
        """
        if not self.db or not self.db.pg_pool:
            return {
                "total": 0,
                "success": 0,
                "error": 0,
                "running": 0,
                "avg_duration_ms": None,
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }
        
        try:
            return await self._get_trace_summary_aggregate(
                workflow_id=workflow_id,
                workflow_ids=workflow_ids,
                status=status,
                start_time=start_time,
                end_time=end_time,
            )
        except Exception as e:
            logger.warning(f"获取追踪摘要失败: {e}")
            return {
                "total": 0,
                "success": 0,
                "error": 0,
                "running": 0,
                "avg_duration_ms": None,
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }
    
    async def get_execution_trends(
        self,
        start_date: datetime,
        end_date: datetime,
        interval: str = "hour",
    ) -> dict:
        """
        获取执行趋势数据（用于 Dashboard 趋势图）
        
        Args:
            start_date: 开始时间
            end_date: 结束时间
            interval: 聚合间隔 (hour/day)
            
        Returns:
            趋势数据字典，包含：
            - data_points: 成功/失败次数数据点列表
            - duration_points: 耗时数据点列表
        """
        if not self.db or not self.db.pg_pool:
            return {"data_points": [], "duration_points": []}
        
        try:
            await self._expire_stale_running_logs()

            # 根据间隔选择时间截断函数
            if interval == "day":
                trunc_func = "date_trunc('day', start_time)"
                time_format = "YYYY-MM-DD"
            else:  # hour
                trunc_func = "date_trunc('hour', start_time)"
                time_format = "YYYY-MM-DD HH24:00"
            
            rows = await self.db.pg_fetch(f"""
                SELECT 
                    to_char({trunc_func}, '{time_format}') as time,
                    COUNT(*) FILTER (WHERE status = 'success') as success,
                    COUNT(*) FILTER (WHERE status IN ('error', 'timeout')) as error,
                    AVG(duration_ms) FILTER (WHERE status = 'success') as avg_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) 
                        FILTER (WHERE status = 'success') as p95_ms
                FROM workflow_logs
                WHERE start_time >= $1 AND start_time <= $2
                GROUP BY {trunc_func}
                ORDER BY {trunc_func}
            """, start_date, end_date)
            
            data_points = []
            duration_points = []
            
            for row in rows:
                data_points.append({
                    "time": row["time"],
                    "success": row["success"] or 0,
                    "error": row["error"] or 0,
                })
                duration_points.append({
                    "time": row["time"],
                    "avg_ms": row["avg_ms"],
                    "p95_ms": row["p95_ms"],
                })
            
            return {
                "data_points": data_points,
                "duration_points": duration_points,
            }
        except Exception as e:
            logger.warning(f"获取执行趋势失败: {e}")
            return {"data_points": [], "duration_points": []}
    
    async def get_workflow_trends(
        self,
        workflow_id: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "hour",
    ) -> dict:
        """
        获取工作流执行趋势数据
        
        Args:
            workflow_id: 工作流 ID
            start_date: 开始时间
            end_date: 结束时间
            interval: 聚合间隔 (hour/day)
            
        Returns:
            趋势数据字典，包含：
            - data_points: 成功/失败次数数据点列表
            - duration_points: 耗时数据点列表
        """
        if not self.db or not self.db.pg_pool:
            return {"data_points": [], "duration_points": []}
        
        try:
            await self._expire_stale_running_logs(workflow_id=workflow_id)

            # 根据间隔选择时间截断函数
            if interval == "day":
                trunc_func = "date_trunc('day', start_time)"
                time_format = "YYYY-MM-DD"
            else:  # hour
                trunc_func = "date_trunc('hour', start_time)"
                time_format = "YYYY-MM-DD HH24:00"
            
            rows = await self.db.pg_fetch(f"""
                SELECT 
                    to_char({trunc_func}, '{time_format}') as time,
                    COUNT(*) FILTER (WHERE status = 'success') as success,
                    COUNT(*) FILTER (WHERE status IN ('error', 'timeout')) as error,
                    AVG(duration_ms) FILTER (WHERE status = 'success') as avg_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) 
                        FILTER (WHERE status = 'success') as p95_ms
                FROM workflow_logs
                WHERE workflow_id = $1 AND start_time >= $2 AND start_time <= $3
                GROUP BY {trunc_func}
                ORDER BY {trunc_func}
            """, workflow_id, start_date, end_date)
            
            data_points = []
            duration_points = []
            
            for row in rows:
                data_points.append({
                    "time": row["time"],
                    "success": row["success"] or 0,
                    "error": row["error"] or 0,
                })
                duration_points.append({
                    "time": row["time"],
                    "avg_ms": row["avg_ms"],
                    "p95_ms": row["p95_ms"],
                })
            
            return {
                "data_points": data_points,
                "duration_points": duration_points,
            }
        except Exception as e:
            logger.warning(f"获取工作流趋势失败: {e}")
            return {"data_points": [], "duration_points": []}


# ============ 全局实例 ============

_global_tracer: Optional[DatabaseTracer] = None
_tracer_initialized: bool = False


def get_db_tracer() -> Optional[DatabaseTracer]:
    """获取全局追踪器"""
    return _global_tracer


def setup_db_tracing(db: "DatabaseManager") -> DatabaseTracer:
    """
    设置数据库追踪
    
    Example:
        db = await init_database(postgres=PostgresConfig.from_env())
        tracer = setup_db_tracing(db)
    """
    global _global_tracer, _tracer_initialized
    _global_tracer = DatabaseTracer(db)
    _tracer_initialized = True
    logger.info("数据库追踪已启用")
    return _global_tracer


async def auto_setup_tracing() -> Optional[DatabaseTracer]:
    """
    自动设置追踪器
    
    检测 PostgreSQL 数据库是否可用：
    - 如果可用，启用数据库追踪
    - 如果不可用，给出警告并禁用追踪
    
    此函数会在 Workflow.run() 时自动调用（当 tracing=True）
    
    Returns:
        DatabaseTracer 实例，如果数据库不可用则返回 None
    """
    global _global_tracer, _tracer_initialized
    
    # 已经初始化过，直接返回
    if _tracer_initialized:
        return _global_tracer
    
    _tracer_initialized = True
    
    import os
    
    # 检查是否配置了 PostgreSQL
    pg_host = os.getenv("PG_HOST")
    if not pg_host:
        logger.debug("未配置 PG_HOST，追踪已禁用")
        return None
    
    try:
        from agentclaw.database import get_database, init_database, PostgresConfig

        db = get_database()
        if db is None:
            pg_config = PostgresConfig.from_env()
            db = await init_database(postgres=pg_config)

        if db and db.pg_pool:
            _global_tracer = DatabaseTracer(db)
            logger.info("✅ 数据库追踪已自动启用")
            return _global_tracer
        else:
            logger.warning("⚠️ PostgreSQL 连接失败，追踪已禁用")
            return None
            
    except Exception as e:
        logger.warning(f"⚠️ 追踪初始化失败: {e}，追踪已禁用")
        return None


def disable_tracing() -> None:
    """禁用追踪"""
    global _global_tracer, _tracer_initialized
    if _global_tracer:
        _global_tracer.disable()
    _global_tracer = None
    _tracer_initialized = True  # 标记为已初始化（禁用状态）
    logger.info("追踪已禁用")


def reset_tracing() -> None:
    """重置追踪状态（用于测试）"""
    global _global_tracer, _tracer_initialized
    _global_tracer = None
    _tracer_initialized = False


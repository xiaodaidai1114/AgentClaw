"""
定时任务模块 - 数据模型

包含域模型和 API 请求/响应 schemas。
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# ── 枚举 ──────────────────────────────────────────────

class TriggerType(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"
    DATE = "date"


class JobStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    PAUSED = "paused"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ConcurrencyPolicy(str, Enum):
    SKIP = "skip"
    QUEUE = "queue"
    PARALLEL = "parallel"


# ── 域模型 ────────────────────────────────────────────

class TriggerConfig(BaseModel):
    """触发器配置"""
    type: TriggerType

    # Cron 类型
    expression: Optional[str] = None
    timezone: Optional[str] = "Asia/Shanghai"

    # Interval 类型
    weeks: Optional[int] = None
    days: Optional[int] = None
    hours: Optional[int] = None
    minutes: Optional[int] = None
    seconds: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

    # Date 类型
    run_date: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_trigger_fields(self):
        if self.type == TriggerType.CRON:
            if not self.expression:
                raise ValueError("cron trigger requires 'expression'")
        elif self.type == TriggerType.INTERVAL:
            has_interval = any([
                self.weeks, self.days, self.hours, self.minutes, self.seconds
            ])
            if not has_interval:
                raise ValueError(
                    "interval trigger requires at least one of: "
                    "weeks, days, hours, minutes, seconds"
                )
        elif self.type == TriggerType.DATE:
            if not self.run_date:
                raise ValueError("date trigger requires 'run_date'")
        return self


class WebhookConfig(BaseModel):
    """Webhook 触发配置"""
    enabled: bool = False
    secret: Optional[str] = None
    allow_input_override: bool = True


class JobConfig(BaseModel):
    """任务执行配置"""
    timeout: int = 300
    retry_count: int = 0
    retry_interval: int = 60
    concurrency: ConcurrencyPolicy = ConcurrencyPolicy.SKIP
    max_instances: int = 1


class ScheduledJob(BaseModel):
    """定时任务"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    workflow_id: str
    trigger: TriggerConfig
    inputs: Dict[str, Any] = Field(default_factory=dict)
    status: JobStatus = JobStatus.ENABLED
    config: JobConfig = Field(default_factory=JobConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    run_count: int = 0
    fail_count: int = 0


class JobExecution(BaseModel):
    """任务执行记录"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    trigger_source: str = "schedule"
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0


# ── API Schemas ───────────────────────────────────────

class CreateJobRequest(BaseModel):
    """创建任务请求"""
    name: str = Field(..., description="任务名称")
    workflow_id: str = Field(..., description="工作流ID")
    trigger: TriggerConfig = Field(..., description="触发器配置")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="工作流输入参数")
    config: Optional[JobConfig] = Field(None, description="执行配置")
    description: Optional[str] = Field(None, description="任务描述")
    webhook: Optional[WebhookConfig] = Field(None, description="Webhook 配置")

    @model_validator(mode="after")
    def validate_webhook_secret(self):
        if self.webhook and self.webhook.enabled and not (self.webhook.secret or "").strip():
            raise ValueError("webhook.secret is required when webhook is enabled")
        return self


class UpdateJobRequest(BaseModel):
    """更新任务请求（所有字段可选）"""
    name: Optional[str] = None
    workflow_id: Optional[str] = None
    trigger: Optional[TriggerConfig] = None
    inputs: Optional[Dict[str, Any]] = None
    config: Optional[JobConfig] = None
    description: Optional[str] = None
    status: Optional[JobStatus] = None
    webhook: Optional[WebhookConfig] = None

    @model_validator(mode="after")
    def validate_webhook_secret(self):
        if self.webhook and self.webhook.enabled and not (self.webhook.secret or "").strip():
            raise ValueError("webhook.secret is required when webhook is enabled")
        return self


class JobResponse(BaseModel):
    """任务响应"""
    id: str
    name: str
    description: Optional[str] = None
    workflow_id: str
    trigger: TriggerConfig
    inputs: Dict[str, Any] = Field(default_factory=dict)
    status: JobStatus
    config: JobConfig
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    created_at: datetime
    updated_at: datetime
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    run_count: int = 0
    fail_count: int = 0


class JobListResponse(BaseModel):
    """任务列表响应"""
    jobs: List[JobResponse]
    total: int


class JobExecutionResponse(BaseModel):
    """执行记录响应"""
    id: str
    job_id: str
    status: ExecutionStatus
    trigger_source: str = "schedule"
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0


class JobExecutionListResponse(BaseModel):
    """执行记录列表响应"""
    executions: List[JobExecutionResponse]
    total: int
    page: int
    limit: int


class TriggerJobResponse(BaseModel):
    """手动触发响应"""
    execution_id: str
    message: str = "Job triggered successfully"

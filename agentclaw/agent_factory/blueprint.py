"""
Agent Blueprint 系统 - 企业 Agent 的统一数据结构

AgentBlueprint 是「一句话生成企业 Agent」流程中的结构化中间态：

    用户需求 → AgentBlueprint → 可运行 Agent 文件结构（agents/<name>/）

它独立于运行时 Workflow，用于描述 Agent 的角色、目标、技能、工具、
知识源、记忆、工作流、约束与护栏，支持 JSON / YAML 序列化，
便于版本管理与差异对比。

本模块为 Phase 1 交付物，纯数据结构，无运行时副作用，不影响现有流程。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel, Field, field_validator


# ------------------------------------------------------------------
# 状态 / 类型常量
#
# 使用字符串常量而非 Enum，是为了允许企业自定义扩展值，
# 同时在代码中提供受参考的取值集合。
# ------------------------------------------------------------------

class AgentStatus:
    """Agent 生命周期状态（详见 Phase 6 Agent Registry）"""
    DRAFT = "draft"
    PROTOTYPE = "prototype"
    TRIAL = "trial"
    PRODUCTION = "production"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class SkillSourceType:
    """Skill 来源类型"""
    BUILTIN = "builtin"
    ENTERPRISE = "enterprise"
    EVOLVED = "evolved"        # 由 Skill Evolution Engine 沉淀
    TEMPLATE = "template"
    CUSTOM = "custom"


class ToolPermissionLevel:
    """工具权限级别（Phase 9 RBAC 启用后强制校验）"""
    READ_ONLY = "read_only"
    WRITE_WITH_APPROVAL = "write_with_approval"
    WRITE_AUTO = "write_auto"
    ADMIN_ONLY = "admin_only"


class AgentDomain:
    """企业领域分类（Phase 2 Domain Matcher 使用）"""
    CUSTOMER_SUPPORT = "customer_support"
    SALES = "sales"
    FINANCE = "finance"
    HR = "hr"
    PROCUREMENT = "procurement"
    LEGAL = "legal"
    KNOWLEDGE_BASE = "knowledge_base"
    OPERATIONS = "operations"
    GENERAL = "general"


# Agent v0.1 雏形的默认版本号
DEFAULT_VERSION = "v0.1"


# ------------------------------------------------------------------
# 子模型
# ------------------------------------------------------------------

class SkillSpec(BaseModel):
    """技能规格"""
    name: str
    description: str = ""
    type: str = SkillSourceType.CUSTOM
    required: bool = False
    source: str = SkillSourceType.CUSTOM
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("SkillSpec.name 不能为空")
        return v.strip()


class ToolSpec(BaseModel):
    """工具规格"""
    name: str
    description: str = ""
    type: str = "function"
    required: bool = False
    auth_required: bool = False
    permission_level: str = ToolPermissionLevel.READ_ONLY

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("ToolSpec.name 不能为空")
        return v.strip()


class KnowledgeSourceSpec(BaseModel):
    """知识源规格"""
    name: str
    type: str = "knowledge_base"  # knowledge_base / file / url / api
    description: str = ""


class MemorySpec(BaseModel):
    """记忆规格"""
    type: str = "workflow"  # workflow / global / user
    persist: bool = True
    description: str = ""


class WorkflowStep(BaseModel):
    """工作流步骤"""
    step_id: str
    name: str
    description: str = ""
    input: str = ""
    output: str = ""
    tools: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)

    @field_validator("step_id", "name")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("WorkflowStep.step_id 与 name 不能为空")
        return v.strip()


# ------------------------------------------------------------------
# 主模型
# ------------------------------------------------------------------

class AgentBlueprint(BaseModel):
    """
    Agent Blueprint - 企业 Agent 的统一数据结构

    一句话需求经 Agent Factory 生成此 Blueprint，再由 Scaffold Generator
    落地为可运行 Agent 目录（agents/<name>/）。

    必填字段：name、domain、role（Agent 的核心身份）。
    其余字段均有合理默认值，确保 v0.1 雏形可被最小化创建。
    """

    # 标识
    name: str
    display_name: str = ""
    description: str = ""
    domain: str
    role: str

    # 角色定义
    goals: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)

    # 输入输出
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)

    # 能力装配
    skills: List[SkillSpec] = Field(default_factory=list)
    tools: List[ToolSpec] = Field(default_factory=list)
    knowledge_sources: List[KnowledgeSourceSpec] = Field(default_factory=list)
    memory: MemorySpec = Field(default_factory=MemorySpec)

    # 工作流
    workflow: List[WorkflowStep] = Field(default_factory=list)

    # 约束与护栏
    constraints: List[str] = Field(default_factory=list)
    guardrails: List[str] = Field(default_factory=list)

    # 版本与状态
    version: str = DEFAULT_VERSION
    status: str = AgentStatus.DRAFT

    # 时间戳（UTC，序列化为 ISO 字符串）
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("AgentBlueprint.name 不能为空")
        return v.strip()

    @field_validator("domain")
    @classmethod
    def _validate_domain(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("AgentBlueprint.domain 不能为空")
        return v.strip()

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("AgentBlueprint.role 不能为空")
        return v.strip()

    def touch(self) -> None:
        """刷新 updated_at 时间戳（变更后调用）"""
        self.updated_at = datetime.now(timezone.utc)

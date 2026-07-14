"""
Registry - 企业 Agent / Skill 统一注册中心 + 版本管理

- AgentRegistry：Agent 注册、查询、状态（draft→production→deprecated→archived）
- SkillRegistry：Skill 注册、按 domain/agent 查询、启禁用、关联 agent
- VersionManager：版本创建、列表、diff、回滚、标记生产/废弃

存储：JSONL（agents.jsonl / skills.jsonl），相对项目根或 AGENTCLAW_DATA_DIR。
本 Phase 为纯新增模块，不依赖运行时。
"""

from .agent_registry import (
    ALL_CHANGE_TYPES,
    AgentRecord,
    AgentRegistry,
    AgentVersion,
    CHANGE_INITIAL,
    CHANGE_PROMPT_UPDATED,
    CHANGE_ROLLBACK,
    CHANGE_SKILL_ADDED,
    CHANGE_SKILL_REMOVED,
    CHANGE_WORKFLOW_UPDATED,
)
from .skill_registry import SkillRecord, SkillRegistry
from .version_manager import VersionManager

__all__ = [
    # Agent
    "AgentRecord",
    "AgentRegistry",
    "AgentVersion",
    "CHANGE_INITIAL",
    "CHANGE_SKILL_ADDED",
    "CHANGE_SKILL_REMOVED",
    "CHANGE_PROMPT_UPDATED",
    "CHANGE_WORKFLOW_UPDATED",
    "CHANGE_ROLLBACK",
    "ALL_CHANGE_TYPES",
    # Skill
    "SkillRecord",
    "SkillRegistry",
    # 版本
    "VersionManager",
]

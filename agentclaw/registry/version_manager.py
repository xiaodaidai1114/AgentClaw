"""
Version Manager - Agent 版本管理

每次 Skill/Prompt/Workflow 变化生成新版本：
- create_version：递增版本（v0.1 → v0.2），追加到版本历史
- list_versions / get_version：查看版本
- diff：比较两版本的 skill 增删
- rollback：回滚到旧版本（创建一个 rollback 类型的新版本）
- mark_production / mark_deprecated：标记生产 / 废弃
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from agentclaw.agent_factory.blueprint import AgentStatus

from .agent_registry import (
    AgentRecord,
    AgentRegistry,
    AgentVersion,
    CHANGE_ROLLBACK,
)


_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)$")


def _bump_version(current: str) -> str:
    """v0.1 → v0.2；无法解析则回退 v0.1"""
    m = _VERSION_RE.match(current or "")
    if m:
        major, minor = int(m.group(1)), int(m.group(2))
        return f"v{major}.{minor + 1}"
    return "v0.1"


class VersionManager:
    """Agent 版本管理器"""

    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry

    # ------------------------------------------------------------------
    def create_version(
        self,
        agent_id: str,
        *,
        change_type: str,
        change_reason: str = "",
        changed_by: str = "",
        added_skills: Optional[List[str]] = None,
        removed_skills: Optional[List[str]] = None,
        changelog: str = "",
    ) -> AgentVersion:
        """创建新版本（递增 minor），追加到 agent 版本历史"""
        r = self._require(agent_id)
        new_version = _bump_version(r.current_version)
        v = AgentVersion(
            version=new_version,
            change_type=change_type,
            change_reason=change_reason,
            changed_by=changed_by,
            added_skills=list(added_skills or []),
            removed_skills=list(removed_skills or []),
            changelog=changelog,
        )
        r.versions.append(v)
        r.current_version = new_version
        self.registry.upsert(r)
        return v

    def list_versions(self, agent_id: str) -> List[AgentVersion]:
        r = self.registry.get(agent_id)
        return list(r.versions) if r else []

    def get_version(self, agent_id: str, version: str) -> Optional[AgentVersion]:
        for v in self.list_versions(agent_id):
            if v.version == version:
                return v
        return None

    def diff(self, agent_id: str, v1: str, v2: str) -> Dict[str, object]:
        """比较两版本的 skill 集合差异（累积 added - removed）"""
        ver1 = self.get_version(agent_id, v1)
        ver2 = self.get_version(agent_id, v2)
        if ver1 is None:
            raise ValueError(f"版本不存在: {v1}")
        if ver2 is None:
            raise ValueError(f"版本不存在: {v2}")
        s1 = set(ver1.added_skills) - set(ver1.removed_skills)
        s2 = set(ver2.added_skills) - set(ver2.removed_skills)
        return {
            "agent_id": agent_id,
            "from": v1,
            "to": v2,
            "added": sorted(s2 - s1),
            "removed": sorted(s1 - s2),
        }

    def rollback(self, agent_id: str, to_version: str, *, changed_by: str = "") -> AgentVersion:
        """
        回滚到旧版本：创建一个 change_type=rollback 的新版本，
        current_version 指向新版本号，changelog 记录回滚来源。
        （不删除中间版本，保留完整历史）
        """
        r = self._require(agent_id)
        if self.get_version(agent_id, to_version) is None:
            raise ValueError(f"回滚目标版本不存在: {to_version}")
        new_version = _bump_version(r.current_version)
        v = AgentVersion(
            version=new_version,
            change_type=CHANGE_ROLLBACK,
            change_reason=f"rollback to {to_version}",
            changed_by=changed_by,
            changelog=f"从 {to_version} 回滚（回滚自 {r.current_version}）",
        )
        r.versions.append(v)
        r.current_version = new_version
        self.registry.upsert(r)
        return v

    # ------------------------------------------------------------------
    def mark_production(self, agent_id: str) -> AgentRecord:
        return self.registry.update_status(agent_id, AgentStatus.PRODUCTION)

    def mark_deprecated(self, agent_id: str) -> AgentRecord:
        return self.registry.update_status(agent_id, AgentStatus.DEPRECATED)

    def mark_trial(self, agent_id: str) -> AgentRecord:
        return self.registry.update_status(agent_id, AgentStatus.TRIAL)

    # ------------------------------------------------------------------
    def _require(self, agent_id: str) -> AgentRecord:
        r = self.registry.get(agent_id)
        if r is None:
            raise ValueError(f"agent 不存在: {agent_id}")
        return r

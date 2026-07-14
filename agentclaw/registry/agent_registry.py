"""
Agent Registry - 企业 Agent 统一注册中心

注册、查询、状态、版本记录。Agent 运行物落地为 agents/<name>.py，
Registry 只记录元数据 + 版本历史（不存储运行物本身）。

状态（复用 blueprint.AgentStatus）：
    draft / prototype / trial / production / deprecated / archived

存储：JSONL（agents.jsonl），按 agent_id upsert。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from agentclaw.agent_factory.blueprint import AgentStatus


# 版本变更类型
CHANGE_INITIAL = "initial_creation"
CHANGE_SKILL_ADDED = "skill_added"
CHANGE_SKILL_REMOVED = "skill_removed"
CHANGE_PROMPT_UPDATED = "prompt_updated"
CHANGE_WORKFLOW_UPDATED = "workflow_updated"
CHANGE_ROLLBACK = "rollback"

ALL_CHANGE_TYPES = frozenset({
    CHANGE_INITIAL,
    CHANGE_SKILL_ADDED,
    CHANGE_SKILL_REMOVED,
    CHANGE_PROMPT_UPDATED,
    CHANGE_WORKFLOW_UPDATED,
    CHANGE_ROLLBACK,
})


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _default_registry_dir() -> Path:
    data_dir = os.getenv("AGENTCLAW_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir).expanduser() / "registry"
    project_dir = os.getenv("AGENTCLAW_PROJECT_DIR", "").strip()
    base = Path(project_dir).expanduser() if project_dir else Path.cwd()
    return base / "data" / "registry"


# ------------------------------------------------------------------
# 数据模型
# ------------------------------------------------------------------

class AgentVersion(BaseModel):
    """Agent 版本记录"""
    version: str
    created_at: datetime = Field(default_factory=_now_utc)
    change_type: str
    change_reason: str = ""
    changed_by: str = ""
    added_skills: List[str] = Field(default_factory=list)
    removed_skills: List[str] = Field(default_factory=list)
    changelog: str = ""


class AgentRecord(BaseModel):
    """Agent 注册记录"""
    agent_id: str
    name: str
    display_name: str = ""
    domain: str
    current_version: str = "v0.1"
    status: str = AgentStatus.DRAFT
    file_path: str = ""            # agents/<name>.py
    blueprint_path: str = ""       # agents/<name>/agent.yaml
    versions: List[AgentVersion] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)


# ------------------------------------------------------------------
# AgentRegistry
# ------------------------------------------------------------------

class AgentRegistry:
    """Agent 注册中心（JSONL 存储）"""

    def __init__(self, store_path: Optional[Path] = None) -> None:
        self.store_path = Path(store_path) if store_path else _default_registry_dir() / "agents.jsonl"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_all(self) -> Dict[str, dict]:
        if not self.store_path.exists():
            return {}
        result: Dict[str, dict] = {}
        with self.store_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    result[d["agent_id"]] = d
                except (json.JSONDecodeError, KeyError):
                    continue
        return result

    def _write_all(self, records: Dict[str, dict]) -> None:
        with self.store_path.open("w", encoding="utf-8") as f:
            for d in records.values():
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def register(self, record: AgentRecord) -> AgentRecord:
        """注册新 agent；若新记录无版本历史，自动补 initial 版本"""
        existing = self.get(record.agent_id)
        if existing is None and not record.versions:
            record.versions = [AgentVersion(
                version=record.current_version,
                change_type=CHANGE_INITIAL,
                change_reason="initial registration",
                changed_by="agent_registry",
            )]
        return self.upsert(record)

    def upsert(self, record: AgentRecord) -> AgentRecord:
        record.updated_at = _now_utc()
        all_data = self._read_all()
        all_data[record.agent_id] = record.model_dump(mode="json")
        self._write_all(all_data)
        return record

    def get(self, agent_id: str) -> Optional[AgentRecord]:
        d = self._read_all().get(agent_id)
        return AgentRecord.model_validate(d) if d else None

    def exists(self, agent_id: str) -> bool:
        return agent_id in self._read_all()

    def list_all(
        self,
        domain: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[AgentRecord]:
        records = [AgentRecord.model_validate(d) for d in self._read_all().values()]
        if domain is not None:
            records = [r for r in records if r.domain == domain]
        if status is not None:
            records = [r for r in records if r.status == status]
        return records

    def update_status(self, agent_id: str, status: str) -> AgentRecord:
        if status not in {
            AgentStatus.DRAFT, AgentStatus.PROTOTYPE, AgentStatus.TRIAL,
            AgentStatus.PRODUCTION, AgentStatus.DEPRECATED, AgentStatus.ARCHIVED,
        }:
            raise ValueError(f"非法 agent 状态: {status}")
        r = self.get(agent_id)
        if r is None:
            raise ValueError(f"agent 不存在: {agent_id}")
        r.status = status
        return self.upsert(r)

    def remove(self, agent_id: str) -> bool:
        all_data = self._read_all()
        if agent_id not in all_data:
            return False
        del all_data[agent_id]
        self._write_all(all_data)
        return True

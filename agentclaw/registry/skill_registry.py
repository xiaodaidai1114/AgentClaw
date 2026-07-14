"""
Skill Registry - 企业 Skill 统一注册中心

注册、查询、按 domain/agent 查询、启禁用、版本。
Skill 物理产物在 skills/enterprise/<domain>/<name>/，Registry 记录元数据 + 关联 agent。

状态：默认 published（注册即启用）；enable/disable 切 published/deprecated。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from agentclaw.evolution.skill_candidate import STATUS_DEPRECATED, STATUS_PUBLISHED

from .agent_registry import _default_registry_dir, _now_utc


class SkillRecord(BaseModel):
    """Skill 注册记录"""
    skill_id: str
    name: str
    domain: str
    version: str = "v0.1"
    status: str = STATUS_PUBLISHED
    path: str = ""                 # skills/enterprise/<domain>/<name>/
    source_candidate_id: str = ""  # 来自哪个 SkillCandidate（Phase 5）
    agent_ids: List[str] = Field(default_factory=list)  # 使用该 skill 的 agent
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)


class SkillRegistry:
    """Skill 注册中心（JSONL 存储）"""

    def __init__(self, store_path: Optional[Path] = None) -> None:
        self.store_path = Path(store_path) if store_path else _default_registry_dir() / "skills.jsonl"
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
                    result[d["skill_id"]] = d
                except (json.JSONDecodeError, KeyError):
                    continue
        return result

    def _write_all(self, records: Dict[str, dict]) -> None:
        with self.store_path.open("w", encoding="utf-8") as f:
            for d in records.values():
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def register(self, record: SkillRecord) -> SkillRecord:
        return self.upsert(record)

    def upsert(self, record: SkillRecord) -> SkillRecord:
        record.updated_at = _now_utc()
        all_data = self._read_all()
        all_data[record.skill_id] = record.model_dump(mode="json")
        self._write_all(all_data)
        return record

    def get(self, skill_id: str) -> Optional[SkillRecord]:
        d = self._read_all().get(skill_id)
        return SkillRecord.model_validate(d) if d else None

    def exists(self, skill_id: str) -> bool:
        return skill_id in self._read_all()

    def list_all(
        self,
        domain: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[SkillRecord]:
        records = [SkillRecord.model_validate(d) for d in self._read_all().values()]
        if domain is not None:
            records = [r for r in records if r.domain == domain]
        if status is not None:
            records = [r for r in records if r.status == status]
        return records

    def list_by_domain(self, domain: str) -> List[SkillRecord]:
        return self.list_all(domain=domain)

    def list_by_agent(self, agent_id: str) -> List[SkillRecord]:
        return [
            r for r in self.list_all()
            if agent_id in r.agent_ids
        ]

    def enable(self, skill_id: str) -> SkillRecord:
        return self._set_status(skill_id, STATUS_PUBLISHED)

    def disable(self, skill_id: str) -> SkillRecord:
        return self._set_status(skill_id, STATUS_DEPRECATED)

    def link_agent(self, skill_id: str, agent_id: str) -> SkillRecord:
        r = self._require(skill_id)
        if agent_id not in r.agent_ids:
            r.agent_ids.append(agent_id)
        return self.upsert(r)

    def unlink_agent(self, skill_id: str, agent_id: str) -> SkillRecord:
        r = self._require(skill_id)
        if agent_id in r.agent_ids:
            r.agent_ids.remove(agent_id)
        return self.upsert(r)

    def remove(self, skill_id: str) -> bool:
        all_data = self._read_all()
        if skill_id not in all_data:
            return False
        del all_data[skill_id]
        self._write_all(all_data)
        return True

    # ------------------------------------------------------------------
    def _set_status(self, skill_id: str, status: str) -> SkillRecord:
        r = self._require(skill_id)
        r.status = status
        return self.upsert(r)

    def _require(self, skill_id: str) -> SkillRecord:
        r = self.get(skill_id)
        if r is None:
            raise ValueError(f"skill 不存在: {skill_id}")
        return r

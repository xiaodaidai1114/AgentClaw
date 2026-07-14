"""
SkillCandidate Schema + 状态常量 + CandidateStore

Skill Evolution Engine 的核心数据结构：从 Pattern 生成的候选 Skill，
经评估 → 人工审批 → 发布到 Skill Registry。

状态流转（企业环境，Skill 不自动发布到生产）：
    candidate → pending_approval → approved → published
                                  ↘ rejected
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# 状态常量
# ------------------------------------------------------------------

STATUS_CANDIDATE = "candidate"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_PUBLISHED = "published"
STATUS_DEPRECATED = "deprecated"
STATUS_REJECTED = "rejected"

ALL_STATUSES = frozenset({
    STATUS_CANDIDATE,
    STATUS_PENDING_APPROVAL,
    STATUS_APPROVED,
    STATUS_PUBLISHED,
    STATUS_DEPRECATED,
    STATUS_REJECTED,
})


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def stable_id(prefix: str, *parts: str) -> str:
    """基于内容生成稳定 id（幂等：相同输入相同 id）"""
    content = "|".join(str(p) for p in parts)
    h = hashlib.md5(content.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{h}"


# ------------------------------------------------------------------
# SkillCandidate
# ------------------------------------------------------------------

class SkillCandidate(BaseModel):
    """候选 Skill：从重复 Pattern 提取，待评估与人工审批"""
    candidate_id: str
    name: str                       # skill slug（小写连字符）
    description: str
    domain: str
    trigger_conditions: List[str] = Field(default_factory=list)
    steps: List[str] = Field(default_factory=list)
    required_tools: List[str] = Field(default_factory=list)
    rules: List[str] = Field(default_factory=list)        # 业务规则（来自人工修正）
    examples: List[Dict[str, Any]] = Field(default_factory=list)
    source_patterns: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: str = STATUS_CANDIDATE
    rejection_reason: str = ""
    approved_by: str = ""
    approved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now_utc)


# ------------------------------------------------------------------
# CandidateStore（JSONL，可替换为 Registry 后续）
# ------------------------------------------------------------------

def _default_candidates_dir() -> Path:
    data_dir = os.getenv("AGENTCLAW_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir).expanduser() / "experience"
    project_dir = os.getenv("AGENTCLAW_PROJECT_DIR", "").strip()
    base = Path(project_dir).expanduser() if project_dir else Path.cwd()
    return base / "data" / "experience"


class CandidateStore:
    """SkillCandidate 的 JSONL 存储（按 candidate_id upsert）"""

    def __init__(self, file_path: Optional[Path] = None) -> None:
        self.file_path = Path(file_path) if file_path else _default_candidates_dir() / "candidates.jsonl"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_all(self) -> Dict[str, Dict[str, Any]]:
        if not self.file_path.exists():
            return {}
        result: Dict[str, Dict[str, Any]] = {}
        with self.file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    result[data.get("candidate_id")] = data
                except json.JSONDecodeError:
                    continue
        return result

    def save(self, candidate: SkillCandidate) -> SkillCandidate:
        """upsert（按 candidate_id 覆盖）"""
        all_data = self._read_all()
        all_data[candidate.candidate_id] = candidate.model_dump(mode="json")
        with self.file_path.open("w", encoding="utf-8") as f:
            for data in all_data.values():
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        return candidate

    def get(self, candidate_id: str) -> Optional[SkillCandidate]:
        data = self._read_all().get(candidate_id)
        return SkillCandidate.model_validate(data) if data else None

    def list_all(self, status: Optional[str] = None) -> List[SkillCandidate]:
        all_data = self._read_all()
        candidates = [SkillCandidate.model_validate(d) for d in all_data.values()]
        if status is not None:
            candidates = [c for c in candidates if c.status == status]
        return candidates

    def list_pending(self) -> List[SkillCandidate]:
        return self.list_all(status=STATUS_PENDING_APPROVAL)

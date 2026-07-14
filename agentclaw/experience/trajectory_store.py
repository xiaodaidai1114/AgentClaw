"""
Trajectory 存储 - JSONL 优先，StorageBackend 抽象（预留 PostgreSQL）

存储布局（JSONL 模式，相对项目根或 AGENTCLAW_DATA_DIR）：
    <base_dir>/events.jsonl        每行一个事件 JSON
    <base_dir>/trajectories.jsonl  每行一个 Trajectory JSON

接口设计为可替换：实现 StorageBackend 即可切换到 PostgreSQL 或其他后端。
事件写入前由 EventLogger 应用 privacy_filter 脱敏。
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from .event_schema import (
    EVENT_TYPE_AGENT_RESPONDED,
    EVENT_TYPE_HUMAN_FEEDBACK,
    EVENT_TYPE_TASK_FAILED,
    EVENT_TYPE_TASK_STARTED,
    EVENT_TYPE_TOOL_CALLED,
    BaseEvent,
    ToolCalledEvent,
    Trajectory,
    event_from_dict,
)


DEFAULT_EXPERIENCE_DIR = "data/experience"


def _default_base_dir() -> Path:
    """默认存储目录：AGENTCLAW_DATA_DIR/experience > 项目根/data/experience"""
    data_dir = os.getenv("AGENTCLAW_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir).expanduser() / "experience"
    project_dir = os.getenv("AGENTCLAW_PROJECT_DIR", "").strip()
    base = Path(project_dir).expanduser() if project_dir else Path.cwd()
    return base / DEFAULT_EXPERIENCE_DIR


# ------------------------------------------------------------------
# 存储后端抽象
# ------------------------------------------------------------------

class StorageBackend(ABC):
    """存储后端抽象（JSONL / 未来 PostgreSQL 等）"""

    @abstractmethod
    def append_event(self, event_dict: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def append_trajectory(self, trajectory_dict: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def list_events(self, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def list_trajectories(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        ...


class JSONLStorage(StorageBackend):
    """JSONL 文件存储（默认后端）"""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else _default_base_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.base_dir / "events.jsonl"
        self.trajectories_file = self.base_dir / "trajectories.jsonl"

    def _append_line(self, file: Path, data: Dict[str, Any]) -> None:
        with file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def _read_lines(self, file: Path) -> List[Dict[str, Any]]:
        if not file.exists():
            return []
        result: List[Dict[str, Any]] = []
        with file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return result

    def append_event(self, event_dict: Dict[str, Any]) -> None:
        self._append_line(self.events_file, event_dict)

    def append_trajectory(self, trajectory_dict: Dict[str, Any]) -> None:
        self._append_line(self.trajectories_file, trajectory_dict)

    def list_events(self, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        events = self._read_lines(self.events_file)
        if task_id is not None:
            events = [e for e in events if e.get("task_id") == task_id]
        return events

    def list_trajectories(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        trajs = self._read_lines(self.trajectories_file)
        if agent_id is not None:
            trajs = [t for t in trajs if t.get("agent_id") == agent_id]
        return trajs


# ------------------------------------------------------------------
# TrajectoryStore：事件记录 + 聚合
# ------------------------------------------------------------------

class TrajectoryStore:
    """事件记录 + Trajectory 聚合"""

    def __init__(self, storage: Optional[StorageBackend] = None) -> None:
        self.storage = storage or JSONLStorage()

    def record_event(self, event: BaseEvent) -> None:
        """记录单个事件（调用方负责脱敏）"""
        self.storage.append_event(event.model_dump(mode="json"))

    def finalize_trajectory(
        self,
        task_id: str,
        agent_id: str,
        *,
        agent_version: str = "",
        task: str = "",
        final_answer: str = "",
        success: bool = True,
    ) -> Trajectory:
        """聚合同 task_id 的事件为一条 Trajectory，写入存储"""
        events = self.storage.list_events(task_id=task_id)

        tool_calls: List[ToolCalledEvent] = []
        human_feedback = ""
        human_correction = ""
        rating = 0
        steps: List[Dict[str, Any]] = []
        determined_success = success

        for ev in events:
            etype = ev.get("event_type")
            if etype == EVENT_TYPE_TASK_STARTED:
                if not task:
                    task = ev.get("user_request", "")
                if not agent_version:
                    agent_version = ev.get("agent_version", "")
                steps.append({"type": "task_started", "timestamp": ev.get("timestamp")})
            elif etype == EVENT_TYPE_TOOL_CALLED:
                obj = event_from_dict(ev)
                if isinstance(obj, ToolCalledEvent):
                    tool_calls.append(obj)
                    steps.append({
                        "type": "tool",
                        "tool": obj.tool_name,
                        "success": obj.success,
                    })
            elif etype == EVENT_TYPE_AGENT_RESPONDED:
                if not final_answer:
                    final_answer = ev.get("response", "")
            elif etype == EVENT_TYPE_HUMAN_FEEDBACK:
                human_feedback = ev.get("feedback", "") or human_feedback
                human_correction = ev.get("human_correction", "") or human_correction
                if ev.get("rating"):
                    rating = ev["rating"]
            elif etype == EVENT_TYPE_TASK_FAILED:
                determined_success = False
                steps.append({
                    "type": "failed",
                    "error_type": ev.get("error_type"),
                    "failed_step": ev.get("failed_step"),
                })

        traj = Trajectory(
            trajectory_id=task_id,  # task_id 与 trajectory 1:1
            agent_id=agent_id,
            agent_version=agent_version,
            task=task,
            steps=steps,
            tool_calls=tool_calls,
            final_answer=final_answer,
            human_feedback=human_feedback,
            human_correction=human_correction,
            rating=rating,
            success=determined_success,
        )
        self.storage.append_trajectory(traj.model_dump(mode="json"))
        return traj

    def list_trajectories(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.storage.list_trajectories(agent_id)

    def list_events(self, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.storage.list_events(task_id)

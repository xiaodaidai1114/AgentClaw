from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from agentclaw.memory.workflow_memory import get_workflow_memory_path


@dataclass(frozen=True)
class RuntimePathContext:
    cwd: str
    project_dir: str
    skill_tools_working_dir: str
    coding_tools_project_dir: str
    skills_dir: Optional[str] = None
    models_config: Optional[str] = None
    mcp_config: Optional[str] = None
    env_file: Optional[str] = None
    workflow_memory_path: Optional[str] = None


def _to_resolved_str(path_like: Any) -> Optional[str]:
    if not path_like:
        return None
    return str(Path(path_like).expanduser().resolve())


def resolve_runtime_path_context(
    *,
    workflow_id: Optional[str] = None,
    skill_manager: Optional[Any] = None,
) -> RuntimePathContext:
    from agentclaw.config import get_config

    cwd_path = Path.cwd().resolve()
    config = get_config()

    project_dir = _to_resolved_str(config.project.project_dir) or str(cwd_path)

    skills_dir = None
    if skill_manager and getattr(skill_manager, "skills_dir", None):
        skills_dir = _to_resolved_str(skill_manager.skills_dir)
    if skills_dir is None:
        skills_dir = _to_resolved_str(config.project.skills_dir)

    models_config = _to_resolved_str(config.project.models_config)
    mcp_config = _to_resolved_str(config.project.mcp_config)
    env_file = _to_resolved_str(config.project.env_file)

    workflow_memory_path = None
    if workflow_id:
        workflow_memory_path = str(
            get_workflow_memory_path(Path(project_dir), workflow_id).resolve()
        )

    # skill-tools 的 working_dir 和 coding-tools 的 project_dir 都应该指向当前项目根，
    # 不能从 skills_dir.parent 反推，否则多项目/嵌套项目场景会跑偏到上层仓库。
    return RuntimePathContext(
        cwd=str(cwd_path),
        project_dir=project_dir,
        skill_tools_working_dir=project_dir,
        coding_tools_project_dir=project_dir,
        skills_dir=skills_dir,
        models_config=models_config,
        mcp_config=mcp_config,
        env_file=env_file,
        workflow_memory_path=workflow_memory_path,
    )

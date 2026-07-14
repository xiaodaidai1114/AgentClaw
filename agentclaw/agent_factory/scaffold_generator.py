"""
Scaffold Generator - Blueprint → 可运行 Agent 文件结构

生成物（位于 <project_dir>/agents/）：

    agents/{name}.py              # 可运行 Workflow（import 即 publish 注册）
    agents/{name}/
        agent.yaml                # Blueprint 序列化
        prompt.md                 # 系统提示词
        workflow.json             # 工作流步骤
        README.md                 # 说明
        skills/  tools/  knowledge/   # 能力占位目录
        versions/v0.1/
            agent.yaml            # 版本快照
            changelog.md          # 初始变更记录

生成的 .py 遵循 AgentClaw 合法 API（Workflow/LLMNode/Input/publish），
可被 importlib 加载触发注册，从而被 POST /api/workflow/run 调用执行。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from .blueprint import AgentBlueprint
from .serializer import save as save_blueprint


@dataclass
class ScaffoldResult:
    """脚手架生成结果"""
    blueprint: AgentBlueprint
    project_dir: Path
    scaffold_dir: Path        # agents/{name}/
    workflow_file: Path       # agents/{name}.py
    agent_yaml: Path
    prompt_md: Path
    workflow_json: Path
    readme: Path
    versions_dir: Path        # agents/{name}/versions/v0.1/


class ScaffoldGenerator:
    """从 AgentBlueprint 生成可运行 Agent 文件结构"""

    def generate(
        self,
        blueprint: AgentBlueprint,
        project_dir: Union[str, Path, None] = None,
    ) -> ScaffoldResult:
        project_dir = self._resolve_project_dir(project_dir)
        agents_dir = project_dir / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        name = blueprint.name
        scaffold_dir = agents_dir / name
        scaffold_dir.mkdir(parents=True, exist_ok=True)

        # 占位能力目录
        for sub in ("skills", "tools", "knowledge"):
            (scaffold_dir / sub).mkdir(exist_ok=True)
            (scaffold_dir / sub / ".gitkeep").touch()

        # agent.yaml
        agent_yaml = scaffold_dir / "agent.yaml"
        save_blueprint(blueprint, agent_yaml)

        # prompt.md
        prompt_md = scaffold_dir / "prompt.md"
        prompt_md.write_text(self._render_prompt_md(blueprint), encoding="utf-8")

        # workflow.json
        workflow_json = scaffold_dir / "workflow.json"
        workflow_json.write_text(
            json.dumps(
                [step.model_dump(mode="json") for step in blueprint.workflow],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # README.md
        readme = scaffold_dir / "README.md"
        readme.write_text(self._render_readme(blueprint), encoding="utf-8")

        # versions/v0.1/
        versions_dir = scaffold_dir / "versions" / "v0.1"
        versions_dir.mkdir(parents=True, exist_ok=True)
        save_blueprint(blueprint, versions_dir / "agent.yaml")
        (versions_dir / "changelog.md").write_text(
            self._render_initial_changelog(blueprint), encoding="utf-8"
        )

        # agents/{name}.py（可运行 Workflow）
        workflow_file = agents_dir / f"{name}.py"
        workflow_file.write_text(
            self._render_workflow_py(blueprint), encoding="utf-8"
        )

        return ScaffoldResult(
            blueprint=blueprint,
            project_dir=project_dir,
            scaffold_dir=scaffold_dir,
            workflow_file=workflow_file,
            agent_yaml=agent_yaml,
            prompt_md=prompt_md,
            workflow_json=workflow_json,
            readme=readme,
            versions_dir=versions_dir,
        )

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def _resolve_project_dir(self, project_dir: Union[str, Path, None]) -> Path:
        if project_dir is not None:
            return Path(project_dir)
        try:
            from agentclaw.config import get_config

            return Path(get_config().project.project_dir)
        except Exception:
            return Path.cwd()

    def build_system_prompt(self, blueprint: AgentBlueprint) -> str:
        """由 Blueprint 生成 LLM 系统提示词"""
        lines = [f"你是{blueprint.role}。"]
        if blueprint.description:
            lines.append("")
            lines.append(f"职责概述：{blueprint.description}")

        if blueprint.goals:
            lines.append("")
            lines.append("【目标】")
            lines.extend(f"- {g}" for g in blueprint.goals)

        if blueprint.responsibilities:
            lines.append("")
            lines.append("【职责】")
            lines.extend(f"- {r}" for r in blueprint.responsibilities)

        if blueprint.guardrails:
            lines.append("")
            lines.append("【约束与护栏】")
            lines.extend(f"- {g}" for g in blueprint.guardrails)

        if blueprint.constraints:
            lines.append("")
            lines.append("【约束】")
            lines.extend(f"- {c}" for c in blueprint.constraints)

        lines.append("")
        lines.append("请基于上述定位，理解用户需求并给出专业、有帮助的回答。")
        return "\n".join(lines)

    def _render_prompt_md(self, blueprint: AgentBlueprint) -> str:
        return f"""# {blueprint.display_name or blueprint.name}

> 由 AgentClaw Agent Factory 自动生成 · {blueprint.version}

{blueprint.description}

## 系统提示词

```text
{self.build_system_prompt(blueprint)}
```

## 技能
{self._format_list([s.name for s in blueprint.skills]) or '（暂无）'}

## 工具
{self._format_list([t.name for t in blueprint.tools]) or '（暂无）'}
"""

    def _render_readme(self, blueprint: AgentBlueprint) -> str:
        return f"""# {blueprint.display_name or blueprint.name}

{blueprint.description}

- **领域**：{blueprint.domain}
- **角色**：{blueprint.role}
- **版本**：{blueprint.version}
- **状态**：{blueprint.status}

## 运行

该 Agent 由 `agents/{blueprint.name}.py` 定义，启动服务后自动注册，
可通过 `POST /api/workflow/run` 调用：

```bash
curl -X POST http://localhost:8000/api/workflow/run \\
  -H "Authorization: Bearer $WORKFLOW_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{"workflow_id": "{blueprint.name}", "inputs": {{"user_input": "你好"}}}}'
```

## 后续增强

这是 v0.1 雏形。通过 Experience Collector 采集使用轨迹，
Skill Evolution Engine 会从重复反馈中沉淀新 Skill，持续生成新版本。
"""

    def _render_initial_changelog(self, blueprint: AgentBlueprint) -> str:
        return f"""# Changelog

## {blueprint.version}

- **change_type**: initial_creation
- **change_reason**: 由 AgentClaw Agent Factory 根据一句话需求生成
- **changed_by**: agent_factory

### 初始技能
{self._format_list([s.name for s in blueprint.skills]) or '（暂无）'}

### 初始工具
{self._format_list([t.name for t in blueprint.tools]) or '（暂无）'}
"""

    def _render_workflow_py(self, blueprint: AgentBlueprint) -> str:
        system_prompt = self.build_system_prompt(blueprint)
        name = blueprint.name
        display_name = blueprint.display_name or name
        description = blueprint.description or display_name
        return f'''"""
Auto-generated by AgentClaw Agent Factory.

Agent:   {display_name}
Domain:  {blueprint.domain}
Role:    {blueprint.role}
Version: {blueprint.version}

由一句话需求生成，可运行但不要求完美。
后续通过 Experience Collector + Skill Evolution Engine 持续增强。
"""
from agentclaw import Workflow, LLMNode, Input

workflow = Workflow(
    id={name!r},
    name={display_name!r},
    description={description!r},
    inputs=[
        Input("user_input", str, required=True, description="用户输入"),
    ],
    user_input="user_input",
)

workflow.add_node(LLMNode(
    id="chat",
    system_prompt={system_prompt!r},
    enable_memory=True,
    output_to_user=True,
))

workflow.publish()
'''

    @staticmethod
    def _format_list(items) -> str:
        items = list(items or [])
        if not items:
            return ""
        return "\n".join(f"- {i}" for i in items)

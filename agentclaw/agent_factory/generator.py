"""
Agent Factory 编排入口

一句话需求 → 完整可运行 Agent：

    request → RequirementAnalyzer → DomainClassifier → TemplateMatcher
            → BlueprintGenerator → ScaffoldGenerator → (可选) 热注册

热注册通过 importlib 加载生成的 agents/{name}.py 触发 Workflow.publish()，
使其进入 WorkflowRegistry，从而可被 POST /api/workflow/run 调用执行。
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from .blueprint import AgentBlueprint
from .blueprint_generator import BlueprintGenerator
from .domain_classifier import DomainClassifier
from .requirement_analyzer import RequirementAnalyzer
from .scaffold_generator import ScaffoldGenerator, ScaffoldResult
from .template_matcher import TemplateMatcher
from .template_store import EnterpriseTemplate, TemplateStore


@dataclass
class GenerationResult:
    """Agent 生成结果"""
    blueprint: AgentBlueprint
    requirement: "RequirementAnalysis"  # noqa: F821
    domain: str
    template: EnterpriseTemplate
    scaffold: ScaffoldResult
    registered: bool


def _resolve_project_root(project_dir: Union[str, Path, None]) -> Path:
    """解析项目根目录：显式参数 > 配置 AGENTCLAW_PROJECT_DIR > cwd"""
    if project_dir is not None:
        return Path(project_dir)
    try:
        from agentclaw.config import get_config

        return Path(get_config().project.project_dir)
    except Exception:
        return Path.cwd()


def generate_agent(
    request: str,
    project_dir: Union[str, Path, None] = None,
    *,
    register: bool = False,
    templates_dir: Union[str, Path, None] = None,
) -> GenerationResult:
    """
    一句话生成企业 Agent。

    Args:
        request: 自然语言需求，如「创建一个销售线索分析助手」
        project_dir: 项目目录（生成 agents/<name>/ 与 agents/<name>.py）；默认用配置项目目录
        register: 是否立即热注册到 WorkflowRegistry（默认 False，避免污染运行时）
        templates_dir: 额外模板目录（Phase 3 的 templates/enterprise_agents/）

    Returns:
        GenerationResult
    """
    requirement = RequirementAnalyzer().analyze(request)
    domain = DomainClassifier().classify(request)

    # 默认自动发现项目根下的 templates/enterprise_agents/（Phase 3 企业模板，覆盖内置）
    if templates_dir is None:
        candidate = _resolve_project_root(project_dir) / "templates" / "enterprise_agents"
        if candidate.exists():
            templates_dir = candidate

    store = TemplateStore(
        templates_dir=Path(templates_dir) if templates_dir else None
    )
    template = TemplateMatcher(store).match(domain)

    blueprint = BlueprintGenerator().generate(requirement, domain, template)
    scaffold = ScaffoldGenerator().generate(blueprint, project_dir)

    registered = False
    if register:
        registered = register_workflow_file(blueprint.name, scaffold.workflow_file)

    return GenerationResult(
        blueprint=blueprint,
        requirement=requirement,
        domain=domain,
        template=template,
        scaffold=scaffold,
        registered=registered,
    )


def register_workflow_file(name: str, workflow_file: Union[str, Path]) -> bool:
    """
    热注册：importlib 加载生成的 workflow 文件触发 publish()。

    Args:
        name: workflow_id（即 AgentBlueprint.name）
        workflow_file: 生成的 agents/<name>.py 路径

    Returns:
        True 若 WorkflowRegistry 中存在该 workflow
    """
    from agentclaw.api.registry import WorkflowRegistry

    workflow_file = Path(workflow_file)
    if not workflow_file.exists():
        return False

    # 若已存在同名 workflow，先 unregister 以支持重新生成同名 agent
    if WorkflowRegistry.get(name) is not None:
        WorkflowRegistry.unregister(name)

    module_name = f"agent_factory_generated_{name}"
    # 支持重复注册：移除旧模块以便重新加载
    sys.modules.pop(module_name, None)

    spec = importlib.util.spec_from_file_location(module_name, workflow_file)
    if spec is None or spec.loader is None:
        return False

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    return WorkflowRegistry.get(name) is not None

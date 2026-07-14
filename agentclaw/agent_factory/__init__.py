"""
Agent Factory - 一句话生成企业 Agent

目标：企业用户输入一句自然语言需求 → 生成可运行（但不要求完美）的 Agent v0.1
雏形，后续通过 Skill Evolution 持续成长为企业专属 AI 员工。

Phase 1：AgentBlueprint 统一数据结构 + JSON/YAML 序列化
Phase 2：Requirement Analyzer / Domain Classifier / Template Matcher /
         Blueprint Generator / Scaffold Generator / 编排入口（含热注册）

典型用法：
    from agentclaw.agent_factory import generate_agent
    result = generate_agent("创建一个销售线索分析助手", register=True)

本包为纯新增模块。运行时能力（API 路由）通过 AGENTCLAW_ENABLE_AGENT_FACTORY
开关控制（默认 off），CLI create-agent 为显式命令不影响现有流程。
"""

from .blueprint import (
    AgentBlueprint,
    SkillSpec,
    ToolSpec,
    KnowledgeSourceSpec,
    MemorySpec,
    WorkflowStep,
    AgentStatus,
    SkillSourceType,
    ToolPermissionLevel,
    AgentDomain,
    DEFAULT_VERSION,
)
from .serializer import (
    to_dict,
    from_dict,
    to_json,
    from_json,
    to_yaml,
    from_yaml,
    save,
    load,
    yaml_available,
)
from .requirement_analyzer import (
    RequirementAnalysis,
    RequirementAnalyzer,
    INTENT_CREATE,
    INTENT_RUN,
    INTENT_QUERY,
    INTENT_UNKNOWN,
)
from .domain_classifier import DomainClassifier, DOMAIN_KEYWORDS, TERM_MAP
from .template_store import (
    EnterpriseTemplate,
    TemplateStore,
    BUILTIN_TEMPLATES,
)
from .template_matcher import TemplateMatcher
from .blueprint_generator import BlueprintGenerator
from .scaffold_generator import ScaffoldGenerator, ScaffoldResult
from .generator import (
    generate_agent,
    register_workflow_file,
    GenerationResult,
)

__all__ = [
    # Schema
    "AgentBlueprint",
    "SkillSpec",
    "ToolSpec",
    "KnowledgeSourceSpec",
    "MemorySpec",
    "WorkflowStep",
    # 常量
    "AgentStatus",
    "SkillSourceType",
    "ToolPermissionLevel",
    "AgentDomain",
    "DEFAULT_VERSION",
    # 序列化
    "to_dict",
    "from_dict",
    "to_json",
    "from_json",
    "to_yaml",
    "from_yaml",
    "save",
    "load",
    "yaml_available",
    # 需求分析与领域
    "RequirementAnalysis",
    "RequirementAnalyzer",
    "INTENT_CREATE",
    "INTENT_RUN",
    "INTENT_QUERY",
    "INTENT_UNKNOWN",
    "DomainClassifier",
    "DOMAIN_KEYWORDS",
    "TERM_MAP",
    # 模板
    "EnterpriseTemplate",
    "TemplateStore",
    "BUILTIN_TEMPLATES",
    "TemplateMatcher",
    # 生成
    "BlueprintGenerator",
    "ScaffoldGenerator",
    "ScaffoldResult",
    "generate_agent",
    "register_workflow_file",
    "GenerationResult",
]

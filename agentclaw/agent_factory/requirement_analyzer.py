"""
Requirement Analyzer - 一句话需求 → 结构化需求

输入：「创建一个负责销售线索分析的 AI 员工」
输出：RequirementAnalysis（domain 意图 / agent_type / 业务目标 / 预期用户 / 所需能力）

规则模式（关键词 + 术语映射），无外部依赖，确定性可测试。
后续可接入 LLM 做更精细的解析（保持 analyze 接口不变）。
"""

from __future__ import annotations

import re
from typing import List

from pydantic import BaseModel, Field

from .blueprint import AgentDomain
from .domain_classifier import DomainClassifier


# 意图关键词
INTENT_CREATE = "create_agent"
INTENT_RUN = "run_agent"
INTENT_QUERY = "query"
INTENT_UNKNOWN = "unknown"

_CREATE_KEYWORDS = ["创建", "生成", "做一个", "搭建", "建一个", "create", "build", "make"]
_RUN_KEYWORDS = ["运行", "执行", "跑一下", "分析这", "处理这", "run", "execute"]
_QUERY_KEYWORDS = ["查询", "什么是", "如何", "问", "query", "how", "what"]


class RequirementAnalysis(BaseModel):
    """结构化需求分析结果"""
    raw_request: str
    domain: str = AgentDomain.GENERAL
    intent: str = INTENT_UNKNOWN
    agent_type: str = "general"
    agent_name: str = "general_agent"
    business_goal: str = ""
    expected_users: List[str] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)


class RequirementAnalyzer:
    """将一句自然语言需求解析为结构化 RequirementAnalysis"""

    def __init__(self) -> None:
        self._classifier = DomainClassifier()

    def analyze(self, request: str) -> RequirementAnalysis:
        request = (request or "").strip()
        domain = self._classifier.classify(request)
        slug = self._classifier.derive_agent_slug(request, domain)
        agent_name = self._derive_agent_name(slug)
        # agent_type 去掉可能的 _agent 后缀，保留语义
        agent_type = slug

        intent = self._detect_intent(request)
        business_goal = self._extract_business_goal(request)
        expected_users = self._extract_expected_users(request, domain)
        required_capabilities = self._extract_capabilities(request, domain)

        return RequirementAnalysis(
            raw_request=request,
            domain=domain,
            intent=intent,
            agent_type=agent_type,
            agent_name=agent_name,
            business_goal=business_goal,
            expected_users=expected_users,
            required_capabilities=required_capabilities,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _derive_agent_name(slug: str) -> str:
        """若 slug 已以 agent 类后缀结尾则直接用，否则补 _agent"""
        suffix_words = ("agent", "assistant", "worker", "bot")
        if any(slug.endswith(s) for s in suffix_words):
            return slug
        return f"{slug}_agent"

    def _detect_intent(self, request: str) -> str:
        lower = request.lower()
        for kw in _CREATE_KEYWORDS:
            if kw in lower:
                return INTENT_CREATE
        for kw in _RUN_KEYWORDS:
            if kw in lower:
                return INTENT_RUN
        for kw in _QUERY_KEYWORDS:
            if kw in lower:
                return INTENT_QUERY
        return INTENT_UNKNOWN

    def _extract_business_goal(self, request: str) -> str:
        """业务目标：去掉「创建一个...」「我想要...」等引导词后的核心诉求"""
        goal = request
        for prefix in ["创建一个", "创建一个负责", "做一个", "帮我创建一个", "我想要一个",
                        "我需要一个", "生成一个", "搭建一个", "建一个"]:
            if goal.startswith(prefix):
                goal = goal[len(prefix):]
                break
        goal = re.sub(r"的\s*ai\s*员工.*$", "", goal, flags=re.IGNORECASE)
        goal = re.sub(r"的\s*助手.*$", "", goal)
        goal = re.sub(r"(smart\s*)?agent.*$", "", goal, flags=re.IGNORECASE)
        return goal.strip() or request

    def _extract_expected_users(self, request: str, domain: str) -> List[str]:
        """预期用户：基于领域默认角色 + 请求中出现的角色词"""
        defaults = {
            AgentDomain.SALES: ["销售团队", "销售主管"],
            AgentDomain.CUSTOMER_SUPPORT: ["客服团队", "客服主管"],
            AgentDomain.FINANCE: ["财务团队", "财务主管"],
            AgentDomain.HR: ["HR 团队", "招聘负责人"],
            AgentDomain.PROCUREMENT: ["采购团队", "采购主管"],
            AgentDomain.LEGAL: ["法务团队", "合规专员"],
            AgentDomain.KNOWLEDGE_BASE: ["全体员工"],
            AgentDomain.OPERATIONS: ["运营团队", "数据分析师"],
            AgentDomain.GENERAL: ["终端用户"],
        }
        return list(defaults.get(domain, ["终端用户"]))

    def _extract_capabilities(self, request: str, domain: str) -> List[str]:
        """所需能力：领域默认能力 + 请求中出现的动词性能力词"""
        defaults = {
            AgentDomain.SALES: ["线索评分", "客户分析", "报告生成"],
            AgentDomain.CUSTOMER_SUPPORT: ["意图识别", "工单分类", "回复建议"],
            AgentDomain.FINANCE: ["单据审核", "对账", "异常检测"],
            AgentDomain.HR: ["简历筛选", "岗位匹配", "候选人评估"],
            AgentDomain.PROCUREMENT: ["供应商比对", "风险评估", "审批流转"],
            AgentDomain.LEGAL: ["条款审查", "风险提示", "合规检查"],
            AgentDomain.KNOWLEDGE_BASE: ["语义检索", "答案生成", "引用溯源"],
            AgentDomain.OPERATIONS: ["数据采集", "指标计算", "趋势分析"],
            AgentDomain.GENERAL: ["理解需求", "调用工具", "生成回答"],
        }
        caps = list(defaults.get(domain, ["理解需求", "生成回答"]))
        # 请求中显式提到的能力词补充
        extra_map = {
            "评分": "评分", "分析": "分析", "报告": "报告生成", "审核": "审核",
            "审批": "审批", "检索": "检索", "监控": "监控", "推荐": "推荐",
        }
        for word, cap in extra_map.items():
            if word in request and cap not in caps:
                caps.append(cap)
        return caps

"""
Domain Classifier - 企业领域分类

从一句自然语言需求识别企业领域，用于模板匹配。

支持 9 个领域：customer_support / sales / finance / hr / procurement /
legal / knowledge_base / operations / general（兜底）。

规则模式（关键词命中计数），无外部依赖，确定性可测试。
Phase 2 后续可接入 LLM 做更智能的分类（保持 classify 接口不变）。
"""

from __future__ import annotations

import re
from typing import Dict, List

from .blueprint import AgentDomain


# 领域 → 关键词（中英文，小写匹配）
DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    AgentDomain.SALES: [
        "销售", "线索", "商机", "成单", "转化", "crm", "订单", "客户跟进",
        "sales", "lead", "customer", "deal", "pipeline",
    ],
    AgentDomain.CUSTOMER_SUPPORT: [
        "客服", "售后", "工单", "投诉", "支持", "退换", "咨询解答",
        "support", "ticket", "after-sale", "complaint",
    ],
    AgentDomain.FINANCE: [
        "财务", "报销", "发票", "对账", "预算", "审计", "账单", "费用",
        "finance", "invoice", "expense", "reimburse",
    ],
    AgentDomain.HR: [
        "招聘", "简历", "员工", "绩效", "薪酬", "入职", "离职", "考勤",
        "hr", "recruit", "resume", "employee",
    ],
    AgentDomain.PROCUREMENT: [
        "采购", "供应商", "招标", "比价", "供货",
        "procurement", "vendor", "supplier", "bid",
    ],
    AgentDomain.LEGAL: [
        "法务", "合同", "合规", "审查", "条款", "风险",
        "legal", "contract", "compliance",
    ],
    AgentDomain.KNOWLEDGE_BASE: [
        "知识库", "问答", "检索", "faq", "文档问答",
        "knowledge", "kb", "faq",
    ],
    AgentDomain.OPERATIONS: [
        "运营", "数据分析", "报表", "监控", "指标", "bi", "周报", "月报",
        "operations", "analytics", "report", "dashboard",
    ],
}

# 中文术语 → 英文 slug 片段，用于派生 agent_type / agent name
TERM_MAP: Dict[str, str] = {
    "销售": "sales", "线索": "lead", "商机": "opportunity", "客户": "customer",
    "分析": "analysis", "员工": "agent",
    "客服": "support", "售后": "after_sale", "工单": "ticket", "投诉": "complaint",
    "财务": "finance", "报销": "expense", "发票": "invoice", "审核": "review",
    "招聘": "recruiting", "简历": "resume", "绩效": "performance", "薪酬": "payroll",
    "采购": "procurement", "供应商": "vendor", "审批": "approval", "招标": "bidding",
    "法务": "legal", "合同": "contract", "合规": "compliance", "审查": "review",
    "知识库": "knowledge", "问答": "qa", "文档": "document", "检索": "search",
    "运营": "operations", "报表": "report", "监控": "monitor", "数据": "data",
    "周报": "weekly_report", "月报": "monthly_report",
    "报告": "report",
}


def _normalize(text: str) -> str:
    return (text or "").lower().strip()


class DomainClassifier:
    """根据关键词命中数识别企业领域"""

    def classify(self, text: str) -> str:
        """返回 9 个领域之一；无命中时返回 general"""
        normalized = _normalize(text)
        if not normalized:
            return AgentDomain.GENERAL

        scores: Dict[str, int] = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            score = 0
            for kw in keywords:
                if not kw:
                    continue
                if kw in normalized:
                    score += 1
            if score > 0:
                scores[domain] = score

        if not scores:
            return AgentDomain.GENERAL

        # 取命中数最高的领域；并列时取字典序靠前（稳定）
        best = max(scores.items(), key=lambda kv: (kv[1], -ord(kv[0][0])))
        return best[0]

    def derive_agent_slug(self, text: str, domain: str) -> str:
        """
        从请求派生 agent 的英文 slug，如「销售线索分析助手」→ sales_lead_analysis_assistant。

        规则：按请求中术语出现顺序匹配 TERM_MAP，去重组合；
        若无任何术语命中，回退为 domain。
        """
        if not text:
            return domain

        # 按在原文中的出现位置排序，保证 slug 顺序符合自然语言
        found: List[tuple[int, str]] = []
        for cn, en in TERM_MAP.items():
            idx = text.find(cn)
            if idx >= 0:
                found.append((idx, en))

        if not found:
            return domain

        found.sort(key=lambda x: x[0])
        parts: List[str] = []
        seen = set()
        for _, en in found:
            if en not in seen:
                seen.add(en)
                parts.append(en)

        slug = "_".join(parts)
        # 清理非法字符（slug 仅允许 [a-z0-9_]）
        slug = re.sub(r"[^a-z0-9_]", "", slug)
        slug = re.sub(r"_+", "_", slug).strip("_")
        return slug or domain

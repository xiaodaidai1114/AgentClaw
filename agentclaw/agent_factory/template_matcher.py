"""
Template Matcher - 按领域匹配企业模板

给定 domain，返回对应 EnterpriseTemplate；无匹配时回退 general 模板。
"""

from __future__ import annotations

from .blueprint import AgentDomain
from .template_store import EnterpriseTemplate, TemplateStore


class TemplateMatcher:
    """按 domain 匹配模板，未命中回退 general"""

    def __init__(self, store: TemplateStore | None = None) -> None:
        self._store = store or TemplateStore()

    @property
    def store(self) -> TemplateStore:
        return self._store

    def match(self, domain: str) -> EnterpriseTemplate:
        """返回 domain 对应模板；无匹配时回退 general；general 也缺失时取 store 中第一个"""
        tpl = self._store.get(domain)
        if tpl is not None:
            return tpl

        tpl = self._store.get(AgentDomain.GENERAL)
        if tpl is not None:
            return tpl

        all_templates = self._store.list_all()
        if not all_templates:
            # 理论上不会发生（内置至少有 general），但保持防御
            return EnterpriseTemplate(domain=AgentDomain.GENERAL, display_name="通用助手")
        return all_templates[0]

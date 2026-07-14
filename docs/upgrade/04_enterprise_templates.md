# Phase 3 — 企业 Agent 模板系统

> 状态：✅ 已完成
> 交付物：`templates/enterprise_agents/` 下 9 个企业场景 YAML + `generate_agent` 自动发现 + 9 个单元测试
> 验收：9 passed，Phase 2（agent_factory）回归 19 passed 无回归

---

## 1. 目标

让 Agent Factory **优先匹配企业模板**而非每次从零生成。一句话需求 → DomainClassifier 识别领域 → TemplateMatcher 匹配模板 → BlueprintGenerator 基于模板生成 Agent v0.1。

本 Phase 为**纯数据 + 一处小改**：
- 新增 `templates/enterprise_agents/*.yaml`（9 个企业场景模板）
- 改 `generate_agent` 默认自动发现该目录（覆盖内置最小模板集）

不动 Phase 2 的运行时代码（requirement_analyzer / domain_classifier / blueprint_generator / scaffold_generator 全部复用）。

## 2. 9 个企业模板

| domain（AgentDomain） | 文件 | 场景 | 代表技能 / 工具 |
|---|---|---|---|
| `customer_support` | [customer_support.yaml](templates/enterprise_agents/customer_support.yaml) | 客服：意图分类、工单、回复建议 | intent_classification / sentiment_analysis · ticket_search · order_lookup |
| `sales` | [sales.yaml](templates/enterprise_agents/sales.yaml) | 销售线索评分、跟进优先级 | lead_scoring / customer_profiling · crm_query · enrich_company |
| `finance` | [finance_review.yaml](templates/enterprise_agents/finance_review.yaml) | 报销/发票审核、合规检查 | receipt_validation / policy_compliance · erp_query · invoice_verify |
| `hr` | [hr_recruiting.yaml](templates/enterprise_agents/hr_recruiting.yaml) | 简历筛选、人岗匹配、面试安排 | resume_parsing / job_matching · ats_query · calendar_schedule |
| `procurement` | [procurement.yaml](templates/enterprise_agents/procurement.yaml) | 采购需求、供应商比价、审批 | requirement_analysis / vendor_evaluation · supplier_search · price_compare |
| `legal` | [legal_review.yaml](templates/enterprise_agents/legal_review.yaml) | 合同条款审查、风险识别 | clause_extraction / risk_identification · contract_search · regulation_lookup |
| `knowledge_base` | [knowledge_assistant.yaml](templates/enterprise_agents/knowledge_assistant.yaml) | 知识库问答、引用溯源 | knowledge_retrieval / answer_grounding · kb_search |
| `operations` | [operations_analysis.yaml](templates/enterprise_agents/operations_analysis.yaml) | 运营指标分析、报表洞察 | metric_analysis / trend_insight · bi_query · sql_execute |
| `general` | [general.yaml](templates/enterprise_agents/general.yaml) | 通用兜底 | （无领域工具，纯对话） |

每个模板均配：领域专属技能（含 confidence）、只读/审批工具、3 步 workflow（理解→检索/分析→生成）、企业护栏（不越权/不泄露/转人工）、推荐知识源、评估指标。

## 3. 模板 Schema

与 Phase 2 的 `EnterpriseTemplate`（[agent_factory/template_store.py](agentclaw/agent_factory/template_store.py)）一致：

```yaml
domain: <AgentDomain 值，必填>
display_name: <展示名>
description: <一句话描述>
default_role: <角色>
default_goals: [...]            # 目标
default_responsibilities: [...] # 职责
default_skills:                 # SkillSpec
  - name: ...
    type: builtin
    confidence: 0.x
default_tools:                  # ToolSpec
  - name: ...
    type: function
    permission_level: read_only | write_with_approval | write_auto | admin_only
default_workflow:               # WorkflowStep
  - step_id: ...
    name: ...
    input: ...
    output: ...
    tools: [...]
    skills: [...]
default_guardrails: [...]
recommended_knowledge_sources: # KnowledgeSourceSpec
  - name: ...
    type: knowledge_base
evaluation_metrics: [...]
```

## 4. 自动发现 + 覆盖内置

**自动发现**（[generator.py:75-79](agentclaw/agent_factory/generator.py#L75)）：`generate_agent` 默认从项目根 `templates/enterprise_agents/` 扫描 `*.y*ml`，无需显式传 `templates_dir`：

```python
if templates_dir is None:
    candidate = _resolve_project_root(project_dir) / "templates" / "enterprise_agents"
    if candidate.exists():
        templates_dir = candidate
```

**覆盖内置**（[template_store.py:134-148](agentclaw/agent_factory/template_store.py#L134)）：`TemplateStore._load_from_dir` 按 `domain` 覆盖内置 `BUILTIN_TEMPLATES`（Phase 2 的 general/sales/customer_support 最小集）。同名 domain 以外部 YAML 为准。

因此本 Phase 的 9 个 YAML 一放入即生效，CLI（`agentclaw create-agent`）和 API（`POST /api/agents/generate`）都自动用企业模板。

## 5. 测试（[test_enterprise_templates.py](agentclaw/test/unit/test_enterprise_templates.py)）

9 个测试，覆盖：

- 目录下恰好 9 个 YAML
- 9 个 domain 全部加载
- 各 domain 匹配到对应模板（match 正确）
- 未知 domain 兜底 general
- 外部 YAML 覆盖内置（sales 新增 enrich_company、customer_support 新增 sentiment_analysis）
- 每个模板必填字段齐全（domain/display_name/role/workflow/guardrails/metrics）
- workflow step 有唯一 step_id + name
- 企业模板（除 general）配置了领域专属工具
- `_resolve_project_root` 能定位模板目录

**运行结果**：`9 passed`；Phase 2 `test_agent_factory.py` `19 passed` 无回归。

## 6. 用法示例

```python
from agentclaw.agent_factory import generate_agent

# 自动发现 templates/enterprise_agents/，匹配 legal 模板
result = generate_agent("创建一个合同审查助手", project_dir=".", register=False)
print(result.domain)    # legal
print(result.template.display_name)  # 法务初审助手
# blueprint.skills 含 clause_extraction/risk_identification（来自 legal 模板）
```

CLI：`agentclaw create-agent "创建一个合同审查助手"`（Phase 2 命令，现在自动用企业模板）。

## 7. 后续衔接

| Phase | 如何使用本 Phase 成果 |
|---|---|
| Phase 4 Experience Collector | 采集各企业 agent 运行轨迹（trace 三层表） |
| Phase 5 Skill Evolution | 从轨迹沉淀的新 skill 反哺回模板（如 sales 新增高价值判定 skill） |
| Phase 6 Registry | 模板 + 生成的 agent 统一注册管理 |
| Phase 8 Evaluation | 模板的 `evaluation_metrics` 作为评估指标来源 |

## 8. 扩展

新增企业领域模板：在 `templates/enterprise_agents/` 放一个 `domain: xxx` 的 YAML 即可（TemplateStore 自动扫描）。若领域是新的，还需在 [domain_classifier.py](agentclaw/agent_factory/domain_classifier.py) 的 `DOMAIN_KEYWORDS` 加关键词，否则分类不到。

## 9. 回滚

删除 `templates/enterprise_agents/` 目录即回退到 Phase 2 内置最小模板集（general/sales/customer_support），不影响其他功能。

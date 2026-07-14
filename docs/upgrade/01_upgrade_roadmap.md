# Phase 0.2 — Enterprise Agent Factory + Skill Evolution Platform 升级路线图

> 基于 [00_repository_audit.md](./00_repository_audit.md) 的审计事实制定。
> 核心原则：**增量重构、不重写、可回滚、配置开关化、不破坏已跑通流程**。

---

## 1. 总体目标

把现有 AgentClaw（声明式 Agent 工作流框架 + 可持续生长的 Claw 底座）升级为 **Enterprise Agent Factory + Skill Evolution Platform**：

> 企业用户输入一句自然语言需求 → 系统生成可运行（但不要求完美）的 Agent v0.1 → 通过企业真实使用数据、用户反馈、任务轨迹、人工修改、失败案例，不断沉淀新 Skills → Agent 从「实习生」逐渐成长为企业专属 AI 员工。

### 1.1 五大闭环

| 闭环 | 能力 |
|---|---|
| **工厂化生成** | 一句话 → 领域分类 → 模板匹配 → Blueprint → 可运行 Agent v0.1 |
| **版本化管理** | Agent/Skill/Prompt/Workflow 变更都生成新版本，可 diff/回滚 |
| **经验→技能进化** | 使用轨迹 → 模式挖掘 → Skill Candidate → 评估 → 人工审批 → 发布 |
| **企业安全** | RBAC + 工具权限 + 审计日志 + Secrets 管理 |
| **可观测性** | Run Trace + Agent 维度 Metrics + Health |

### 1.2 升级哲学（关键认知）

AgentClaw **已有**「一句话生成智能体 → 沉淀为复用能力」的生长链路（README 已写明）。本次升级**不是新建一个并行系统**，而是：

- 把 `agent_creator` skill 的「LLM 手册式生成」升级为「结构化 Blueprint + 工厂流水线」
- 把 Tracing 的「执行追踪」升级为「经验采集 + 模式挖掘 + 技能进化」闭环
- 把 `WorkflowRegistry`（内存）+ `SkillManager`（内存）升级为「带版本/状态/审批的持久化 Registry」
- 把三种平铺令牌升级为「RBAC + 审计」

所有升级都通过环境变量开关控制，关闭即回到 v1.1.7 行为。

---

## 2. 当前架构问题（来自审计）

| # | 问题 | 证据 | 影响 |
|---|---|---|---|
| P1 | 无统一 Agent Blueprint 数据结构 | agent 定义散落在 `agents/*.py` Python 代码 + `claw_app.json` manifest，无结构化中间态 | 无法程序化生成/版本/diff Agent |
| P2 | 一句话生成是「LLM 手册式」，非工厂流水线 | `agent_creator` 是给 LLM 读的 SKILL.md，生成 `workflows/*.py`，不生成 manifest/README/模板，引用的 scripts 缺失 | 生成质量依赖 LLM，不可控、不可复用 |
| P3 | 无企业模板系统 | 模板库主打娱乐/创作，刻意避开企业流程（[claw_apps_showcase_plan.md](agentclaw/docs/zh/claw_apps_showcase_plan.md) L143-148） | 缺销售/财务/HR/采购/法务垂直模板 |
| P4 | Experience 采集有基础但不闭环 | Tracing 三层表完整，但缺 tool_logs/成本/决策流/经验字段/反馈关联（12 个缺口） | 无法从使用中沉淀技能 |
| P5 | Skill Evolution 完全缺失 | 无 pattern_miner/skill_candidate/approval/publisher | Agent 无法自我进化 |
| P6 | Agent/Skill 无版本管理 | `WorkflowRegistry`/`SkillManager` 内存单例，agent 无版本目录 | 无法 diff/回滚/标记生产版本 |
| P7 | 无 Agent 评估 | 有 `get_workflow_stats` 统计，但无评估集/回归 | 升级无质量门禁 |
| P8 | 无 RBAC | 三种平铺令牌，`AuthPrincipal` scopes 仅两种粗粒度，`APIKeyManager` 半成品未启用 | 企业无法分角色管控 |
| P9 | 无审计日志 | `updated_by` 硬编码 `"admin"`，敏感操作无记录 | 合规/追溯缺失 |
| P10 | 无工具权限级别 | 有工具确认门 + 工具策略，但无 read_only/write_with_approval 分级 | 企业工具风险管控不足 |
| P11 | CLI 仅 3 命令 | 只有 serve/init/up，无 create-agent/evolve/evaluate | 命令行不可用 |
| P12 | Secrets 可能写入 agent 配置 | models.json 可直接写 api_key | 企业密钥管理风险 |

---

## 3. 推荐目标架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    企业用户一句话需求                            │
│              "创建一个负责销售线索分析的 AI 员工"                 │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Agent Factory Layer  (agentclaw/agent_factory/)                │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐    │
│  │Requirement   │→│Domain        │→│Template Matcher      │    │
│  │Analyzer      │ │Classifier    │ │(templates/enterprise)│    │
│  └──────────────┘ └──────────────┘ └──────────┬───────────┘    │
│                                                  ▼               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Blueprint Generator → AgentBlueprint (Pydantic)         │   │
│  │  + Skill Planner + Tool Planner + Workflow Planner      │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Scaffold Generator → agents/<name>/{agent.yaml,          │  │
│  │   prompt.md, workflow.json, README.md, skills/,          │  │
│  │   tools/, knowledge/, versions/v0.1/}                    │   │
│  └─────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼  (热注册 POST /_internal/admin/workflows/register-file)
┌─────────────────────────────────────────────────────────────────┐
│  AgentClaw Runtime (现有，复用不改动)                           │
│  Workflow + Node + LangGraph + Harness + Skills + Memory +      │
│  Knowledge + MCP + Tools                                       │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Enterprise Usage                                              │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Experience Collector  (agentclaw/experience/)                  │
│  实现 BaseTracer 子类，挂载于现有 trace/span/generation         │
│  + Task Event Logger + Tool Call Logger + Feedback Logger       │
│  + Human Edit Logger + Failure Case Logger + Privacy Filter     │
│  → experiences 表 + tool_logs 表 + trajectory 聚合              │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Trajectory Store  (data/experience/*.jsonl + PG)               │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Skill Evolution Engine  (agentclaw/evolution/)                 │
│  Pattern Miner → Skill Extractor → Skill Candidate →            │
│  Skill Evaluator → [Human Approval Gate] → Skill Publisher      │
│  复用 skill_creator 的 init/validate/package                    │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Skill Registry + Agent Registry  (agentclaw/registry/)         │
│  版本管理 / 状态机 / 回滚  (持久化到 PG)                         │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Improved Agent Version (v0.2, v0.3, ...)                       │
│  + Evaluation 回归门禁（退化则阻止自动发布）                     │
└─────────────────────────────────────────────────────────────────┘

  横切关注点：
  ┌────────────────┐ ┌──────────────┐ ┌────────────────────────┐
  │ RBAC + Audit   │ │ Observability│ │ API / CLI / Dashboard  │
  │ (Phase 9)      │ │ (Phase 10)   │ │ (Phase 11)             │
  └────────────────┘ └──────────────┘ └────────────────────────┘
```

---

## 4. 分阶段升级计划

> 共 11 个 Phase + Phase 0（已完成）。每个 Phase：纯新增模块优先，核心文件最小侵入修改，配置开关控制，可回滚。

### Phase 1：Agent Blueprint 系统

**目标**：为「一句话生成企业 Agent」建立统一数据结构。

**新增模块**：
- `agentclaw/agent_factory/__init__.py`
- `agentclaw/agent_factory/blueprint.py` — Pydantic Schema：`AgentBlueprint`、`SkillSpec`、`ToolSpec`、`KnowledgeSourceSpec`、`MemorySpec`、`WorkflowStep`
  - `AgentBlueprint` 字段：name, display_name, description, domain, role, goals[], responsibilities[], inputs[], outputs[], skills[], tools[], knowledge_sources[], memory, workflow[], constraints[], guardrails[], version(默认 "v0.1"), status, created_at, updated_at
  - `SkillSpec`：name, description, type, required, source, confidence
  - `ToolSpec`：name, description, type, required, auth_required, permission_level（预留 Phase 9）
  - `WorkflowStep`：step_id, name, description, input, output, tools[], skills[]
- `agentclaw/agent_factory/serializer.py` — Blueprint ↔ YAML/JSON（用 Pydantic 自带 + `pyyaml`，注意项目为避免 pyyaml 用了自研解析器，Blueprint 是结构化数据可用 Pydantic `model_dump_json` + 简单 YAML 序列化；若不想加 pyyaml 依赖，YAML 用自研或 JSON-only，YAML 作为可选）
- `agentclaw/test/unit/test_agent_blueprint.py` — 创建/序列化 YAML/加载/必填校验/version 默认 v0.1

**修改**：无（纯新增）。可选 `env_config.py` 加 `AGENTCLAW_AGENT_FACTORY_ENABLED`。

**风险**：极低（纯数据结构，无运行时副作用）。

**验收标准**：
- [ ] `AgentBlueprint` 可创建并序列化为 YAML/JSON
- [ ] 可从 YAML 加载还原
- [ ] 缺失必填字段（name/domain/role）报 `ValidationError`
- [ ] version 默认 `"v0.1"`
- [ ] `pytest agentclaw/test/unit/test_agent_blueprint.py` 通过
- [ ] `agentclaw serve` 现有流程不受影响

**回滚**：删除 `agent_factory/` 目录。

---

### Phase 2：一句话生成 Agent 能力

**目标**：用户输入一句企业需求，系统自动生成 Agent v0.1。

**新增模块**（`agentclaw/agent_factory/`）：
- `requirement_analyzer.py` — 输入一句话 → 结构化需求（domain, intent, agent_type, business_goal, expected_users[], required_capabilities[]）。规则 + LLM 双模式（LLM 走现有 `LLMManager`）
- `domain_classifier.py` — 识别 9 个企业领域：customer_support / sales / finance / hr / procurement / legal / knowledge_base / operations / general
- `template_matcher.py` — 按 domain 匹配企业模板（Phase 3 提供），无匹配用 general
- `blueprint_generator.py` — 综合需求 + 领域 + 模板 + 当前可用 Skills（查 `SkillManager`）+ Tools → 生成 `AgentBlueprint`
- `scaffold_generator.py` — Blueprint → 文件结构：
  ```
  agents/{agent_name}/
    agent.yaml          # Blueprint 序列化
    prompt.md           # 由 role/goals/guardrails 生成
    workflow.json       # 由 workflow[] 生成
    README.md
    skills/  tools/  knowledge/
    versions/v0.1/{agent.yaml, changelog.md}
  ```
  复用 `agent_square/__init__.py` 的 import/register 机制把生成的 workflow 热注册
- `generator.py` — 编排入口 `generate_agent(request: str) -> AgentBlueprint + scaffold_path`

**复用**：
- `agent_creator` SKILL.md 的证据管道设计哲学 + 4 级校验门禁
- `agentclaw/__init__.py` 导出的合法 API（Workflow/LLMNode/HumanNode/ToolKit/tool/...）生成 `agents/<name>.py`
- `POST /_internal/admin/workflows/register-file` 热注册
- `claw_app.json` 结构（生成 manifest 让 agent 进模板库）

**修改**：
- `cli.py` — 新增 `agentclaw create-agent "需求"` 子命令（开关控制）
- `api/server.py` + 新 `api/routers/public/agents.py` — `POST /api/agents/generate`（开关控制，默认挂载但鉴权）

**风险**：低。生成的 agent 走热注册，失败不影响现有注册表（`force_replace` 控制）。

**验收标准**：
- [ ] 输入「创建一个销售线索分析助手」生成 `agents/sales_lead_analysis_agent/` 含 agent.yaml/prompt.md/workflow.json/README.md/versions/v0.1/
- [ ] 生成的 agent 可被 `POST /api/workflow/run` 调用执行
- [ ] 不同领域匹配不同模板
- [ ] `agentclaw create-agent` CLI 可用

**回滚**：`AGENTCLAW_AGENT_FACTORY_ENABLED=false`，不注册路由/命令。

---

### Phase 3：企业 Agent 模板系统

**目标**：先匹配企业模板，再由 LLM/规则补全，不从 0 生成。

**新增模块**：
- `agentclaw/templates/enterprise_agents/` — 9 个 YAML 模板：
  - `customer_support.yaml`、`sales.yaml`、`finance_review.yaml`、`hr_recruiting.yaml`、`procurement.yaml`、`legal_review.yaml`、`knowledge_assistant.yaml`、`operations_analysis.yaml`、`general.yaml`
  - 每个含：domain, display_name, description, default_role, default_goals[], default_responsibilities[], default_skills[], default_tools[], default_workflow[], default_guardrails[], recommended_knowledge_sources[], evaluation_metrics[]
- `agentclaw/agent_factory/template_store.py` — 模板加载/按 domain 匹配/用户需求覆盖/新增模板
- `agentclaw/test/unit/test_enterprise_templates.py` — 模板加载/domain 匹配/覆盖

**复用**：以现有 `approval`（审批）、`kb_rag`（RAG）、`stock_daily_news`（定时报告）、`weekly_report`（办公报告）为「模板父本」。

**修改**：`template_matcher.py`（Phase 2）对接 `template_store`。

**风险**：极低（纯数据 + 加载器）。

**验收标准**：
- [ ] 9 个模板可加载
- [ ] 按 domain 匹配正确
- [ ] 用户需求可覆盖模板默认值
- [ ] 可添加新模板

**回滚**：删除 `templates/enterprise_agents/`。

---

### Phase 4：Experience Collector

**目标**：记录企业 Agent 使用过程，为 Skill Evolution 提供数据。

**新增模块**（`agentclaw/experience/`）：
- `event_schema.py` — Pydantic 事件：TaskStarted / ToolCalled / AgentResponded / HumanFeedbackReceived / TaskFailed / HumanEditApplied
- `event_logger.py` — 事件记录器（写 `experiences` 表 + JSONL fallback）
- `trajectory_store.py` — 一次任务聚合成 Trajectory（agent_id, agent_version, task, steps[], tool_calls[], final_answer, human_feedback, human_correction, success, created_at）
- `feedback_collector.py` — 对接现有 `message_feedback` 表，补 trace_id 关联
- `privacy_filter.py` — 脱敏 email/phone/address/api_key/token/password/身份证/银行卡
- `experience_tracer.py` — **实现 `BaseTracer` 子类**（参考 `DatabaseTracer`），覆写 `trace()/span()/log_generation()/update_generation_metadata()`，在现有三层结构上追加 experiences 数据；同时持久化 `HarnessRunState.events/decisions`（开关控制）

**新增表**（`database/manager.py` 幂等 DDL）：
- `experiences`（trace_id, agent_id, agent_version, event_type, event_data JSONB, created_at）
- `tool_logs`（trace_id, node_log_id, tool_name, tool_input JSONB, tool_output JSONB, success, latency_ms, risk_level, created_at）—— 从 `HarnessToolExecutor` 的 `ToolResultEnvelope` 持久化
- `trajectories`（trajectory_id, agent_id, agent_version, task, steps JSONB, tool_calls JSONB, final_answer, human_feedback, human_correction, success, created_at）
- ALTER `llm_logs` ADD `cost_estimate` FLOAT / `cached_tokens` INT IF NOT EXISTS（补缺口 3/4）

**复用**：现有 `workflow_logs/node_logs/llm_logs` 三层表 + `BaseTracer` 抽象 + `HarnessRunState`。

**存储**：优先 PG；`AGENTCLAW_EXPERIENCE_STORAGE=jsonl` 时 fallback 到 `data/experience/events.jsonl` + `trajectories.jsonl`。

**修改**（最小侵入）：
- `database/manager.py` — 新表 DDL + llm_logs 加列（IF NOT EXISTS）
- `runtime/tracing/db_tracer.py` — `log_generation` 传 cost_estimate/cached_tokens（开关）
- `runtime/harness/state.py` — `on_finish/on_error` 钩子持久化 events/decisions（开关，用包装器不改核心结构）

**风险**：中。涉及 Tracing 层。缓解：fire-and-forget 复用现有模式；开关默认 off 时完全不影响。

**验收标准**：
- [ ] 一次 agent 运行后，`experiences`/`tool_logs` 表有记录
- [ ] Trajectory 可聚合（含 steps/tool_calls/final_answer/feedback）
- [ ] 隐私字段被脱敏（email/phone/api_key 等）
- [ ] 成本/cached_tokens 落库
- [ ] `AGENTCLAW_EXPERIENCE_ENABLED=false` 时 Tracing 行为与升级前一致

**回滚**：`AGENTCLAW_EXPERIENCE_ENABLED=false`；drop 新表。

---

### Phase 5：Skill Evolution Engine

**目标**：从真实轨迹发现重复模式，生成 Skill Candidate。

**新增模块**（`agentclaw/evolution/`）：
- `pattern_miner.py` — 分析 Trajectories 寻找：高频任务/失败/人工修改/工具组合/流程步骤/规则补充。输出 Pattern（pattern_type, domain, description, evidence_count, confidence）
- `skill_extractor.py` — Pattern → Skill Candidate（生成 `skills/enterprise/<domain>/<name>/` 含 SKILL.md/rules.yaml/examples.json/metadata.yaml）
- `skill_candidate.py` — Pydantic Schema：name, description, domain, trigger_conditions[], steps[], required_tools[], examples[], source_patterns[], confidence, status(candidate/pending_approval/approved/published/deprecated/rejected), created_at
- `skill_evaluator.py` — 评估 candidate（基于证据强度、覆盖度、与现有 skill 重叠）
- `approval_gate.py` — 状态机：candidate → pending_approval → approved/rejected
- `skill_publisher.py` — approved → published，写入 Skill Registry，复用 `skill_creator` 的 `package_skill.py`/`quick_validate.py`

**复用**：`skill_creator` 的 `init_skill.py`（骨架）+ `quick_validate.py`（校验门禁）+ `package_skill.py`（打包）+ Skill 目录约定。

**新增表**：
- `skill_candidates`（id, name, domain, description, trigger_conditions JSONB, steps JSONB, required_tools JSONB, examples JSONB, source_patterns JSONB, confidence, status, created_at, approved_by, approved_at）

**修改**：无核心改动。

**风险**：低（纯新增分析模块，读 Trajectory 写 candidate）。

**验收标准**：
- [ ] 给定多条含相同人工反馈的 Trajectory，生成一个 `pending_approval` 状态的 Skill Candidate
- [ ] 未审批 skill 不能 publish
- [ ] 生成的 skill 目录符合 `quick_validate.py` 校验
- [ ] 「超过 10 万元需要主管审批」类业务规则可被识别

**回滚**：`AGENTCLAW_EVOLUTION_ENABLED=false`。

---

### Phase 6：Skill Registry + Agent Registry

**目标**：企业 Agent 和 Skill 的统一注册中心。

**新增模块**（`agentclaw/registry/`）：
- `agent_registry.py` — 注册/查询/版本查询/状态更新/回滚/按 domain 列表。Agent 状态：draft/prototype/trial/production/deprecated/archived
- `skill_registry.py` — 注册/查询/按 domain/按 agent/启禁/版本/回滚。Skill 状态：candidate/pending_approval/approved/published/deprecated/rejected
- `version_manager.py` — 版本创建/diff/回滚/标记生产/标记废弃

**新增表**：
- `agent_registry`（id, name, display_name, domain, current_version, status, owner_id, blueprint_path, created_at, updated_at）
- `agent_versions`（agent_id, version, change_type, change_reason, changed_by, added_skills JSONB, removed_skills JSONB, updated_prompt, updated_workflow, evaluation_result JSONB, rollback_from, created_at）
- `skill_registry`（id, name, domain, current_version, status, source, skill_path, created_at, updated_at）
- `skill_versions`（skill_id, version, change_log, created_at）

**复用**：现有 `WorkflowRegistry`（运行时内存注册）保持不变，Agent Registry 在其之上加持久化元数据层（不替换，包装）。

**修改**：
- `api/routers/admin/router.py` — 注册 `admin/agents.py`、`admin/skills.py` router
- `cli.py` — `list-agents`/`list-skill-candidates`/`approve-skill`/`publish-skill`/`rollback-agent`

**风险**：低（元数据层，不动运行时注册）。

**验收标准**：
- [ ] 可注册/查询 Agent 和 Skill
- [ ] 可查询版本、回滚
- [ ] Agent/Skill 状态机正确
- [ ] 按 domain/agent 查询正确

**回滚**：不挂载新 router；drop 新表。

---

### Phase 7：Agent Versioning

**目标**：Skill/Prompt/Workflow 变化都生成新 Agent 版本。

**新增/扩展**：
- `agents/<name>/versions/v0.1/`、`v0.2/`... 每版含 agent.yaml/prompt.md/workflow.json/changelog.md
- changelog.yaml：version, created_at, change_type, change_reason, changed_by, added_skills[], removed_skills[], updated_prompt, updated_workflow, evaluation_result, rollback_from

**复用**：`version_manager.py`（Phase 6）+ 现有 `prompt_history` 表（Prompt 已有版本机制，可对齐）。

**修改**：
- `blueprint_generator.py` / `skill_publisher.py` — 发布 skill 时触发 Agent 新版本
- `agent_registry.py` — 版本 diff/回滚/标记生产/废弃

**风险**：低。

**验收标准**：
- [ ] 发布 skill 后 Agent 生成 v0.2，changelog 记录 added_skills + reason
- [ ] 可查看版本差异
- [ ] 可回滚到旧版本
- [ ] 可标记生产/废弃版本

**回滚**：版本目录是数据，删除即回滚。

---

### Phase 8：Agent Evaluation

**目标**：Agent 必须能评估，升级有质量门禁。

**新增模块**（`agentclaw/evaluation/`）：
- `dataset.py` — 评估集管理（`agents/<name>/eval/cases.yaml` + `expected_outputs.yaml` + `results/`）
- `metrics.py` — 指标：task_success_rate, tool_call_success_rate, human_feedback_score, correction_rate, hallucination_risk, latency_ms, cost_estimate, fallback_rate, approval_required_rate
- `evaluator.py` — 运行评估集生成指标
- `regression_runner.py` — 升级前回归；新版本低于旧版本则**阻止自动发布**

**复用**：现有 `get_workflow_stats`（db_tracer.py:790）+ Tracing 数据。

**修改**：
- `skill_publisher.py` — 发布前调用 `regression_runner`，退化则阻止
- `cli.py` — `evaluate-agent <name>`

**风险**：低（只读评估 + 门禁）。

**验收标准**：
- [ ] 可运行评估集生成指标
- [ ] 指标下降时阻止自动发布到 production
- [ ] 评估结果记录到 `agent_versions.evaluation_result`

**回滚**：关闭门禁（`AGENTCLAW_EVALUATION_GATE_ENABLED=false`）。

---

### Phase 9：企业级安全和权限

**目标**：升级成企业可用平台。

**新增模块**：
- 扩展 `agentclaw/api/auth/`：`rbac.py`（角色 admin/agent_owner/skill_reviewer/operator/viewer + 权限 create_agent/edit_agent/run_agent/approve_skill/publish_skill/rollback_agent/view_logs/manage_tools）、`audit.py`（审计日志服务）、`tool_permission.py`（工具权限级别 read_only/write_with_approval/write_auto/admin_only）
- `agentclaw/api/routers/admin/rbac.py`、`audit.py` — 用户/角色/权限/审计日志 API
- 新增表：`users`、`roles`、`permissions`、`role_permissions`、`user_roles`、`audit_logs`（actor_type, actor_id, action, resource_type, resource_id, method, path, status_code, metadata JSONB, ip, user_agent, created_at）

**复用**：`AuthPrincipal`（已预留 scopes/user_id/tenant_id）+ `APIKeyManager`（半成品，激活 per-key workflows 白名单）+ `agent_conversations.tenant_id`（多租户隔离）。

**修改**（开关化，默认 off 时行为不变）：
- `api/auth/dependencies.py` — 扩展 `AuthPrincipal`（roles/permissions），新增 `require_permission(perm)` 依赖工厂；`AGENTCLAW_RBAC_ENABLED=false` 时回退到现有 `require_admin_auth`/`require_workflow_or_admin_auth`
- `api/auth/middleware.py` — `AGENTCLAW_AUDIT_LOG_ENABLED=true` 时对 `/admin/*` 写操作记录审计
- `admin/prompts.py` 等 — `updated_by` 从 `AuthPrincipal` 取真实 actor（替换硬编码 `"admin"`），开关控制
- `node/llm.py` / `toolkit.py` — 工具调用前校验 `permission_level`（开关）
- Secrets：agent 配置禁止写明文 api_key，强制走 `models.json` 或环境变量（校验 + 文档）

**风险**：高（涉及鉴权）。缓解：开关默认 off；启用时 Admin Token 自动具备全部权限（向后兼容）；充分测试。

**验收标准**：
- [ ] 5 个角色 + 8 个权限可用
- [ ] `require_permission()` 正确拦截
- [ ] 审计日志记录敏感操作（创建 Agent/改 Prompt/发布 Skill/调敏感工具/回滚）
- [ ] 工具按 permission_level 分级
- [ ] `AGENTCLAW_RBAC_ENABLED=false` 时鉴权与升级前一致
- [ ] Admin Token 在 RBAC 启用时仍可用（全权限）

**回滚**：`AGENTCLAW_RBAC_ENABLED=false` + `AGENTCLAW_AUDIT_LOG_ENABLED=false`。

---

### Phase 10：可观测性和运维

**目标**：让企业知道 Agent 用得怎么样。

**新增/扩展**：
- `api/routers/admin/metrics.py` — 按 Agent 统计：今日调用次数/成功率/平均延迟/人工接管率/用户评分/工具失败率/Token 成本估计
- `cli.py` — `agentclaw health`（或复用现有 `GET /health`）
- 扩展 `runtime/tracing/`：Run Trace 已有（input/计划/工具调用/中间结果/最终输出/错误/耗时/成本），补成本/决策流展示

**复用**：现有 Traces API + Dashboard stats + TraceService timeline。

**修改**：
- `api/server.py` — 挂载 `/admin/metrics` router
- `admin-dashboard/src/views/` — 新增 Metrics 页面

**风险**：低。

**验收标准**：
- [ ] Run Trace 完整可见
- [ ] 按 Agent 的 metrics 可查询
- [ ] `agentclaw health` / `GET /health` 可用

**回滚**：不挂载新 router。

---

### Phase 11：API / CLI / UI 升级 + 文档 + 示例

**目标**：完整企业交付。

**API**（`POST /api/agents/generate`、`GET /api/agents`、`GET /api/agents/{id}`、`POST /api/agents/{id}/run`、`GET /api/agents/{id}/versions`、`POST /api/agents/{id}/rollback`、`GET /api/skills`、`GET /api/skills/candidates`、`POST /api/skills/{id}/approve`、`POST /api/skills/{id}/publish`、`GET /api/experience/trajectories`、`GET /api/evaluation/{id}`）

**CLI**（`create-agent`/`list-agents`/`run-agent`/`list-trajectories`/`extract-skills`/`list-skill-candidates`/`approve-skill`/`publish-skill`/`evaluate-agent`/`rollback-agent`）

**UI**（admin-dashboard 新增：Agent Factory 生成页、Agent 版本管理页、Skill Candidate 审批页、Experience/Trajectory 浏览页、Evaluation 仪表盘、RBAC 管理页、Audit Log 页）

**文档**：
- `docs/upgrade/02_agent_blueprint.md` ~ `08_enterprise_security.md`
- `examples/enterprise_agents/`（sales_analysis_agent、customer_support_agent、finance_review_agent）
- README 增加：项目定位/快速开始/一句话生成/运行/收集 Experience/生成 Skill Candidate/批准发布/查看版本/回滚

**风险**：低（聚合层）。

**验收标准**：见 §6 端到端验收流程。

**回滚**：不挂载新 router/命令/页面。

---

## 5. 预计新增模块汇总

```
agentclaw/
├── agent_factory/              # Phase 1-3
│   ├── blueprint.py            # AgentBlueprint/SkillSpec/ToolSpec/WorkflowStep Schema
│   ├── serializer.py           # YAML/JSON 序列化
│   ├── requirement_analyzer.py # 一句话 → 结构化需求
│   ├── domain_classifier.py    # 9 领域分类
│   ├── template_matcher.py     # 模板匹配
│   ├── template_store.py       # 模板加载
│   ├── blueprint_generator.py  # 生成 Blueprint
│   ├── scaffold_generator.py   # Blueprint → 文件结构
│   └── generator.py            # 编排入口
├── templates/enterprise_agents/ # Phase 3（9 个 YAML）
├── experience/                 # Phase 4
│   ├── event_schema.py
│   ├── event_logger.py
│   ├── trajectory_store.py
│   ├── feedback_collector.py
│   ├── privacy_filter.py
│   └── experience_tracer.py    # BaseTracer 子类
├── evolution/                  # Phase 5
│   ├── pattern_miner.py
│   ├── skill_extractor.py
│   ├── skill_candidate.py
│   ├── skill_evaluator.py
│   ├── approval_gate.py
│   └── skill_publisher.py
├── registry/                   # Phase 6-7
│   ├── agent_registry.py
│   ├── skill_registry.py
│   └── version_manager.py
├── evaluation/                 # Phase 8
│   ├── dataset.py
│   ├── metrics.py
│   ├── evaluator.py
│   └── regression_runner.py
├── api/routers/
│   ├── public/agents.py        # Phase 2/11
│   └── admin/{agents,skills,rbac,audit,metrics}.py  # Phase 6/9/10/11
└── api/auth/
    ├── rbac.py                 # Phase 9
    ├── audit.py                # Phase 9
    └── tool_permission.py       # Phase 9
```

## 6. 预计修改模块汇总（最小侵入，全开关化）

| 文件 | 修改 | Phase |
|---|---|---|
| [cli.py](agentclaw/cli.py) | 新增 10+ 子命令 | 2/6/8/10/11 |
| [api/server.py](agentclaw/api/server.py) | 条件挂载新 router | 2/6/9/10/11 |
| [api/routers/admin/router.py](agentclaw/api/routers/admin/router.py) | 注册新 admin router | 6/9 |
| [api/auth/dependencies.py](agentclaw/api/auth/dependencies.py) | 扩展 AuthPrincipal + require_permission | 9 |
| [api/auth/middleware.py](agentclaw/api/auth/middleware.py) | 审计日志记录点 | 9 |
| [config.py](agentclaw/config.py) + [env_config.py](agentclaw/env_config.py) | 新增 5+ dataclass + ENV_SECTIONS | 1/4/9 |
| [database/manager.py](agentclaw/database/manager.py) | 新表 DDL + llm_logs 加列 | 4/6/9 |
| [runtime/tracing/db_tracer.py](agentclaw/runtime/tracing/db_tracer.py) | cost/cached_tokens 落库 | 4 |
| [runtime/harness/state.py](agentclaw/runtime/harness/state.py) | events/decisions 持久化钩子 | 4 |
| admin-dashboard `src/{router,api,views}` | 新增企业页面 | 11 |

## 7. 不改动模块（核心稳定区）

[graph/workflow.py](agentclaw/graph/workflow.py)、[node/llm.py](agentclaw/node/llm.py)、[graph/context.py](agentclaw/graph/context.py)、[state/checkpointer.py](agentclaw/state/checkpointer.py)、[runtime/streaming/context.py](agentclaw/runtime/streaming/context.py)、[api/registry.py](agentclaw/api/registry.py)、[skills/parser.py](agentclaw/skills/parser.py)、[skills/schema.py](agentclaw/skills/schema.py)、[knowledgebase/](agentclaw/knowledgebase/)、[scheduler/](agentclaw/scheduler/)、[channels/](agentclaw/channels/)、[agent_square/](agentclaw/agent_square/) 装载机制。

---

## 8. 端到端验收流程（升级后必须支持）

| 流程 | 输入 | 期望输出 |
|---|---|---|
| 1. 一句话生成 Agent | 「创建一个销售线索分析助手」 | `agents/sales_lead_analysis_agent/{agent.yaml,prompt.md,workflow.json,README.md,versions/v0.1/}` |
| 2. 运行 Agent | 「分析这批客户线索，给出优先级」 | 调用生成 Agent 返回结果 |
| 3. 记录 Experience | 一次运行后 | `data/experience/events.jsonl` + `trajectories.jsonl`（或 PG 表） |
| 4. 反馈生成 Skill Candidate | 多条「客户预算大于 50 万优先标记高价值」 | `skills/enterprise/sales/high_value_lead_detection/` 状态 `pending_approval` |
| 5. 批准并发布 Skill | 管理员批准 | Skill 状态 `published`，Agent 生成 v0.2，changelog 记录 added_skills + reason |
| 6. 评估和回滚 | 评估 v0.1 vs v0.2 | v0.2 更差可回滚到 v0.1 |

---

## 9. 回滚策略总览

**总原则**：所有新功能通过环境变量开关控制，默认 off（除 Phase 1 纯数据结构）。关闭即回到 v1.1.7 行为。

| 开关 | 控制 | 默认 |
|---|---|---|
| `AGENTCLAW_AGENT_FACTORY_ENABLED` | Agent Factory 路由/命令/模块 | off |
| `AGENTCLAW_EXPERIENCE_ENABLED` | Experience Collector（BaseTracer 子类 + 新表写入） | off |
| `AGENTCLAW_EVOLUTION_ENABLED` | Skill Evolution | off |
| `AGENTCLAW_RBAC_ENABLED` | RBAC（启用时 Admin Token 全权限兼容） | off |
| `AGENTCLAW_AUDIT_LOG_ENABLED` | 审计日志 | off |
| `AGENTCLAW_EVALUATION_GATE_ENABLED` | 发布前回归门禁 | off |

**代码回滚**：新模块在独立目录，删除目录 + 移除 `include_router` 即可。核心文件修改保持最小且开关化。

**数据回滚**：新增表独立，`DROP TABLE` 不影响现有表。`llm_logs` 加列用 `IF NOT EXISTS`，回滚时保留列即可（向后兼容）。

---

## 10. 执行顺序与依赖

```
Phase 0 (审计+路线图) ✅ ← 当前
   │
   ├─ Phase 1 (Blueprint Schema)        ← 无依赖，第一批 MVP
   │     │
   │     └─ Phase 2 (Agent Factory)     ← 依赖 Phase 1
   │           │
   │           └─ Phase 3 (企业模板)    ← 依赖 Phase 2 的 template_matcher
   │
   ├─ Phase 4 (Experience Collector)    ← 依赖现有 Tracing，可与 Phase 1-3 并行
   │     │
   │     └─ Phase 5 (Skill Evolution)   ← 依赖 Phase 4 的 Trajectory
   │
   ├─ Phase 6 (Registry)                ← 依赖 Phase 1 (Blueprint) + Phase 5 (Skill)
   │     │
   │     └─ Phase 7 (Versioning)        ← 依赖 Phase 6
   │
   ├─ Phase 8 (Evaluation)              ← 依赖 Phase 4 (Experience) + Phase 6 (Registry)
   │
   ├─ Phase 9 (Security/RBAC/Audit)     ← 独立，可并行
   │
   ├─ Phase 10 (Observability)          ← 依赖 Phase 4
   │
   └─ Phase 11 (API/CLI/UI/Docs)        ← 聚合层，最后
```

**可并行**：Phase 1-3（工厂链）、Phase 4-5（经验进化链）、Phase 9（安全）三条线可并行推进。

---

## 11. 第一批最小可落地改动（MVP，建议立即执行）

> 目标：验证升级链路通畅，零风险，纯新增。

1. ✅ 创建 `docs/upgrade/` + 本两份文档（已完成）
2. 新建 `agentclaw/agent_factory/blueprint.py`（Pydantic Schema，无运行时依赖）
3. 新建 `agentclaw/agent_factory/serializer.py`（Blueprint ↔ YAML/JSON）
4. 新建 `agentclaw/test/unit/test_agent_blueprint.py`（创建/序列化/加载/必填校验/version 默认 v0.1）
5. `env_config.py` + `config.py` 加 5 个开关（默认全 false）

**验收**：`pytest agentclaw/test/unit/test_agent_blueprint.py` 通过；`agentclaw serve` 现有流程完全不受影响。

---

## 12. 风险登记册

| 风险 | 等级 | Phase | 缓解 | 回滚 |
|---|---|---|---|---|
| 改动 workflow.py/llm.py 核心破坏现有 agent | 高 | 4/9 | 不改核心，走 Tracer 包装器/开关 | 关开关 |
| DB schema 变更影响已有数据 | 中 | 4/6/9 | IF NOT EXISTS 幂等；新表解耦 | DROP 新表 |
| RBAC 启用后 Admin Token 失败 | 高 | 9 | 默认 off；启用时 Admin 全权限兼容 | 关开关 |
| Experience 持久化写入压力 | 中 | 4 | fire-and-forget；JSONL fallback | 关开关 |
| Harness 决策持久化改动 state.py | 中 | 4 | 开关 + 包装器，不改核心结构 | 关开关 |
| 企业模板与 agent_square 冲突 | 低 | 3 | 独立目录 templates/enterprise_agents/ | 删目录 |
| Secrets 写入 agent 配置 | 中 | 9 | 校验 + 文档 + 强制 models.json/env | — |

---

*路线图完成。Phase 0（审计 + 路线图）已就绪，等待确认后进入 Phase 1。*

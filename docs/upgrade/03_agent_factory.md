# Phase 2 — 一句话生成 Agent 能力

> 状态：✅ 已完成
> 交付物：Agent Factory 生成链（7 模块）+ API 路由 + CLI 命令 + 33 单元测试
> 验收：全部通过，现有流程无回归（开关默认 off）

---

## 1. 目标

用户输入一句企业需求 → 系统自动生成可运行 Agent v0.1：

```
"创建一个销售线索分析助手"
   → RequirementAnalyzer → DomainClassifier → TemplateMatcher
   → BlueprintGenerator → ScaffoldGenerator → (可选) 热注册
   → agents/sales_lead_analysis_agent/{agent.yaml, prompt.md, workflow.json, README.md, versions/v0.1/}
   + agents/sales_lead_analysis_agent.py（可运行 Workflow）
```

## 2. 模块结构

```
agentclaw/agent_factory/
├── blueprint.py             # Phase 1：Schema
├── serializer.py            # Phase 1：序列化
├── requirement_analyzer.py  # Phase 2：一句话 → 结构化需求
├── domain_classifier.py     # Phase 2：9 领域分类 + agent slug 派生
├── template_store.py        # Phase 2：模板存储（内置 general/sales/customer_support + 目录扫描）
├── template_matcher.py      # Phase 2：按 domain 匹配，回退 general
├── blueprint_generator.py   # Phase 2：需求+模板 → AgentBlueprint
├── scaffold_generator.py    # Phase 2：Blueprint → 可运行 Agent 文件结构
└── generator.py             # Phase 2：编排入口 + importlib 热注册

agentclaw/api/routers/public/agents.py  # POST /api/agents/generate（开关）
```

## 3. 生成流程

| 阶段 | 模块 | 输入 → 输出 |
|---|---|---|
| 需求分析 | `RequirementAnalyzer` | 「创建一个销售线索分析助手」→ `RequirementAnalysis`(domain, intent, agent_name, business_goal, expected_users, required_capabilities) |
| 领域分类 | `DomainClassifier` | 文本 → 9 领域之一（关键词命中计数） |
| 模板匹配 | `TemplateMatcher` | domain → `EnterpriseTemplate`（无匹配回退 general） |
| Blueprint 生成 | `BlueprintGenerator` | 需求 + 模板 → `AgentBlueprint`（v0.1） |
| 脚手架生成 | `ScaffoldGenerator` | Blueprint → 完整文件结构 + 可运行 `.py` |
| 热注册 | `register_workflow_file` | importlib 加载 `.py` 触发 `publish()` → `WorkflowRegistry` |

### Agent name 派生

`DomainClassifier.derive_agent_slug` 用中英术语词典（`TERM_MAP`）按出现顺序组合：
- 动作词（创建/生成）与角色后缀（助手）不进 slug
- 「创建一个销售线索分析助手」→ `sales_lead_analysis` → agent_name `sales_lead_analysis_agent`

## 4. 生成物结构

```
agents/sales_lead_analysis_agent.py     # 可运行 Workflow（import 即 publish 注册）
agents/sales_lead_analysis_agent/
    agent.yaml                          # Blueprint 序列化
    prompt.md                           # 系统提示词（role/goals/guardrails）
    workflow.json                       # 工作流步骤
    README.md                           # 说明 + 调用示例
    skills/  tools/  knowledge/         # 能力占位目录
    versions/v0.1/
        agent.yaml                      # 版本快照
        changelog.md                    # 初始变更记录
```

生成的 `.py` 遵循 AgentClaw 合法 API（`Workflow`/`LLMNode`/`Input`/`publish`），可被 `importlib` 加载触发注册，从而被 `POST /api/workflow/run` 调用执行。

## 5. 内置模板

Phase 2 内置 3 个模板（让「不同领域匹配不同模板」可验收）：

| domain | 模板 | 含默认 skills/tools/workflow/guardrails |
|---|---|---|
| `general` | 通用助手 | 单步对话 |
| `sales` | 销售分析助手 | lead_scoring + crm_query + 3 步流程 |
| `customer_support` | 客服助手 | intent_classification + ticket_search + 2 步流程 |

其余 6 个领域（finance/hr/procurement/legal/knowledge_base/operations）当前回退 general。**Phase 3 会把完整 9 个模板放到 `templates/enterprise_agents/*.yaml`，`TemplateStore` 自动扫描加载覆盖内置模板**——无需改代码。

## 6. 用法

### CLI（始终可用，不受开关影响）

```bash
agentclaw create-agent "创建一个销售线索分析助手"
# 生成到项目 agents/ 目录

agentclaw create-agent "创建一个销售线索分析助手" --register
# 生成并热注册到 WorkflowRegistry
```

### API（需 `AGENTCLAW_ENABLE_AGENT_FACTORY=true`）

```http
POST /api/agents/generate
{
  "request": "创建一个销售线索分析助手",
  "register": true
}
```

### Python

```python
from agentclaw.agent_factory import generate_agent
result = generate_agent("创建一个销售线索分析助手", register=True)
print(result.blueprint.name)   # sales_lead_analysis_agent
print(result.registered)       # True
```

## 7. 配置开关

| 环境变量 | 默认 | 作用 |
|---|---|---|
| `AGENTCLAW_ENABLE_AGENT_FACTORY` | `false` | 是否挂载 `/api/agents/*` 路由（CLI 不受影响） |
| `AGENTCLAW_AGENT_FACTORY_AUTO_REGISTER` | `false` | 生成后是否自动热注册 |
| `AGENTCLAW_AGENT_FACTORY_TEMPLATES_DIR` | 空 | 企业模板目录（Phase 3 用） |

`AgentFactoryConfig`（[config.py](agentclaw/config.py)）+ `ENV_SECTIONS`（[env_config.py](agentclaw/env_config.py) "Agent Factory" section）。

## 8. 测试（[test_agent_factory.py](agentclaw/test/unit/test_agent_factory.py)）

33 个测试，覆盖：
- 需求分析（销售/客服/通用/空请求）
- 领域分类（9 领域参数化 + slug 派生）
- 模板匹配（sales 匹配、finance 回退 general、不同领域不同模板）
- Blueprint 生成（字段继承、合法标识符）
- 脚手架生成（完整目录结构、.py 语法合法、agent.yaml roundtrip、prompt.md 内容）
- 端到端（`generate_agent` 生成完整结构）
- 热注册（注册/重复注册/缺失文件/register 标志）
- CLI（`create-agent` 命令）
- 配置开关（默认 disabled、env_config 含新变量）

**运行结果**：`33 passed`；与 Phase 1 合跑 `65 passed`；与 `test_example_agent_square_templates` 组合 `73 passed`。

## 9. 与现有系统集成

- **零侵入核心**：未改 `graph/workflow.py`、`node/llm.py`、`api/registry.py` 核心
- **热注册复用**：`register_workflow_file` 用 `importlib` 触发 `Workflow.publish()`，重新生成同名 agent 时先 `WorkflowRegistry.unregister` 旧版本（支持迭代）
- **生成物符合现有装载机制**：`agents/{name}.py` 与现有 `agents/hello_world.py` 同构；`agents/{name}/` 与 `agent_square` 导入后的目录同构
- **开关默认 off**：`AGENTCLAW_ENABLE_AGENT_FACTORY=false` 时不挂载 API 路由，`agentclaw serve` 行为与升级前完全一致（已验证 `import agentclaw` + `AgentClawServer` 正常，开关默认 False）

## 10. 已知预存问题（非本 Phase 引入）

`test_cli_init.py::test_up_project_initialization_can_defer_env_creation_for_runtime_secret_prompt` 在与 `test_example_agent_square_templates.py` 组合跑时失败：后者导入 `agentclaw` 包触发 `load_dotenv`，把项目 `.env` 的真实 `ADMIN_TOKEN` 加载进 `os.environ`，污染了假设「环境无 token」的 `test_cli_init`。

- 单独跑 `test_cli_init.py`（含本 Phase 改动）：6 passed ✓
- 本 Phase 未修改 `_prompt_runtime_secrets` / `_get_existing_env_value` / `_init_project`
- 这是项目既有的测试隔离缺陷，不在 Phase 2 范围

## 11. 后续 Phase 衔接

| Phase | 衔接点 |
|---|---|
| Phase 3 企业模板 | 把 9 个 YAML 放 `templates/enterprise_agents/`，`TemplateStore` 自动扫描覆盖内置；`AGENTCLAW_AGENT_FACTORY_TEMPLATES_DIR` 指向该目录 |
| Phase 4 Experience Collector | 生成的 agent 运行时，Tracer 自动采集轨迹 |
| Phase 6 Agent Registry | 生成的 `agents/{name}/versions/v0.1/` 即版本管理起点 |
| Phase 9 Tool Permission | `ToolSpec.permission_level` 已在 Blueprint 中，RBAC 启用后校验 |

## 12. 回滚

- API 路由：`AGENTCLAW_ENABLE_AGENT_FACTORY=false`（默认）即不挂载
- CLI `create-agent`：删除 `cli.py` 中该命令（显式命令，不自动运行）
- 生成链：删除 `agentclaw/agent_factory/` 中 Phase 2 新增模块（保留 Phase 1 的 blueprint/serializer）
- 配置：删除 `AgentFactoryConfig` + env section

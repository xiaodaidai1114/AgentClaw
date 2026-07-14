# Phase 0.1 — AgentClaw 仓库审计报告

> 审计时间：2026-07-10
> 审计基线：`main` 分支，commit `8ffa4fa`，版本 `1.1.7`
> 审计目标：在不修改核心代码的前提下，完整摸清现有仓库结构，为「Enterprise Agent Factory + Skill Evolution Platform」增量升级提供事实依据。

---

## 0. 审计结论速览

AgentClaw **不是**一个需要从零改造的个人 Agent 玩具，而是一个已生产可用、架构成熟的**声明式 Agent 工作流框架 + 可持续生长的 Claw 智能体底座**。其 README 已明确写出「一句话需求 → 生成智能体 → 调整工作流 → 接入工具与知识库 → 调试测试 → 部署上线 → 发布为 API/MCP/基础能力」的能力生长链路。

因此本次「企业化升级」的本质是：**在已有生长链路上，补齐企业场景所需的「工厂化生成、版本化管理、经验→技能进化闭环、RBAC/审计、可观测性」五大闭环**，而非重写框架。这天然契合「增量、可回滚、不破坏现有流程」的升级原则。

| 维度 | 现状 | 对升级的意义 |
|---|---|---|
| 核心抽象 | Workflow + Node（非 "Agent"），Workflow ≈ 用户口中的 Agent | Agent Blueprint 的「运行物」应落地为 `agents/*.py` + `claw_app.json`，不另造运行时 |
| 执行引擎 | LangGraph + Harness 双模式，已具备 Agentic 工具循环 | Agent v0.1 可直接跑，无需新建执行器 |
| 追踪系统 | 三层表 `workflow_logs/node_logs/llm_logs` 已完整 | Experience Collector 复用此结构，零侵入挂载 |
| 创建能力 | `agent_creator`/`skill_creator` builtin skill 已存在 | Agent Factory / Skill Evolution 直接复用其手册与脚手架 |
| 鉴权 | 三种平铺令牌，无 RBAC/审计 | 企业安全需新增，但 `AuthPrincipal`/`APIKeyManager` 已预留扩展点 |
| 存储 | PG + Redis + Milvus，无 ORM/无迁移框架 | 新表用 `CREATE TABLE IF NOT EXISTS` 幂等创建，沿用现有约定 |

---

## 1. 项目总览

### 1.1 项目定位（源自 [README_CN.md](README_CN.md)）

> AgentClaw 是一个面向个人开发者与团队、基于 Harness 架构的声明式 Agent 框架，也是一个可持续生长的 Claw 智能体底座：你既可以一句话生成智能体，也能将构建结果持续沉淀为自己的 Claw 能力。

核心能力矩阵（README 归纳）：

| 能力模块 | 现在能做什么 |
|---|---|
| 智能体框架 | 声明式工作流、节点与路由编排、Agentic LLM 节点、自定义节点与工具 |
| Claw 执行能力 | 操作电脑、操作浏览器、读写代码、处理文件、调用工具 |
| 知识能力 | 知识库导入、文档解析、检索增强、知识注入 |
| 记忆能力 | 全局记忆、长期上下文沉淀、多轮对话连续性、上下文压缩 |
| 集成能力 | Skills、MCP、外部工具接入、渠道适配 |
| 运行能力 | 定时任务、前端与 Dashboard、状态持久化、提示词热更新 |
| 运营能力 | 会话管理、消息反馈、执行追踪、日志统计、Token 统计、渠道推送 |
| 交付能力 | 发布为 API、MCP Server 或 AgentClaw 内部基础能力 |

### 1.2 技术栈

- **语言**：Python 3.10+
- **Web**：FastAPI + Uvicorn
- **Agent 引擎**：LangGraph（`langgraph` + `langgraph-checkpoint-postgres`）
- **LLM**：`langchain-openai` / `openai` SDK，兼容 OpenAI 协议的多模型
- **数据校验**：Pydantic v2
- **数据库**：PostgreSQL（`asyncpg` 业务池 + `psycopg`/`psycopg-pool` 给 LangGraph Checkpointer）
- **缓存/锁/Pub-Sub**：Redis（`redis>=5.0`）
- **向量库**：Milvus（`pymilvus`，支持 `milvus-lite` 本地模式）
- **调度**：APScheduler 3.x + croniter
- **桌面/浏览器**：Playwright + pywinauto（Windows）
- **渠道**：飞书 `lark-oapi`、钉钉 `dingtalk-stream`、企微、QQ
- **CLI**：Click
- **前端**：Vue 3 + Vite 5 + naive-ui + Pinia + vue-router + vue-i18n
- **测试**：pytest + pytest-asyncio（后端）/ vitest + @vue/test-utils（前端）

### 1.3 包与版本

- PyPI 分发名：`agentclaw-ai`
- Python import 包名：`agentclaw`
- CLI 命令：`agentclaw`
- 当前版本：`1.1.7`（[agentclaw/version.py](agentclaw/version.py)，`_FALLBACK_VERSION = "1.1.7"`）
- 入口脚本：`[project.scripts] agentclaw = "agentclaw.cli:main"`（[pyproject.toml:99-100](pyproject.toml#L99)）

### 1.4 近期演进方向（CHANGELOG 1.1.4 → 1.1.7）

近四个版本集中在**公开智能体分享、公开房间、安全围栏、工作流级 API Key、敏感词库**：

- 1.1.5：`safe_guard` LLM 安全围栏、工作流级 API Key、公开敏感词库
- 1.1.6：公开多人会话有效期、Dashboard 公开会话管理页
- 1.1.7：公开分享页/房间模型切换、checkpoint 截断修复
- 最新 commit `8ffa4fa`：post-tool 控制器提示词调整（多步计划判断逻辑）——**这正是 Skill Evolution 关注的 Agentic 决策信号**

> **启示**：项目近期在强化「对外发布 + 安全」方向，尚未触及「企业内部多用户/RBAC/经验沉淀」。升级方向与之互补，不冲突。

---

## 2. 项目目录结构

```
AgentClaw/
├── server.py                  # 项目服务入口（import agents → 启动 AgentClawServer）
├── pyproject.toml             # 包元数据、依赖、pytest 配置
├── requirements.txt
├── models.json                # 模型配置（default/fallback/safe_guard/models[]）
├── mcp.json                   # MCP 服务器配置
├── docker-compose.yml         # 项目级基础设施（复制自内置模板）
├── .env                       # 运行配置清单（14 个 section）
├── VERSION                    # "1.1.7"
│
├── agents/                    # 【项目级 agent 定义】
│   ├── __init__.py            #   导入所有 workflow 触发注册
│   ├── hello_world.py         #   单文件 agent
│   ├── weather_bot.py
│   ├── daily_ai_news.py
│   ├── custom_demo/           #   已导入的模板（含 claw_app.json）
│   └── router/
│
├── workflows/                 # 【项目级 workflow 文件】（无 manifest，直接 import 注册）
│   ├── stock_daily_news.py    #   股市早报（@workflow.tool 取数 → agentic → 报告）
│   ├── xiaohongshu_writer.py
│   └── douyin_writer.py
│
├── skills/                    # 【项目级 skills 目录】（用户自定义 skill 落地处）
│   └── .gitkeep
│
├── .agentclaw/                # 【运行时实例配置】
│   ├── relay.json             #   服务 relay（url/pid/project_dir/internal_url）
│   ├── hello_world_settings.json     # per-workflow 设置（api_published/api_key/safe_guard）
│   ├── stock_daily_news_settings.json
│   └── ...（每个已发布 workflow 一个）
│
├── .knowledgebase/            # 知识库本地存储
├── logs/                      # 日志
├── assets/                    # README 用图片/logo
│
├── agentclaw/                 # ====== 框架核心包 ======
│   ├── __init__.py            # 顶层导出（Workflow/Node/ToolKit/MCP/Tracer/Server...）
│   ├── base.py                # BaseComponent 组件钩子基类（⚠️ 多数钩子为死代码）
│   ├── cli.py                 # CLI（serve/init/up）
│   ├── config.py              # AgentClawConfig 单例 + 子配置 dataclass
│   ├── env_config.py          # .env 渲染注册表（14 section，唯一真相源）
│   ├── exceptions.py
│   ├── platform_compat.py     # Windows 事件循环策略
│   ├── runtime_paths.py
│   ├── version.py
│   ├── warning_filters.py
│   │
│   ├── graph/                 # 工作流引擎
│   │   ├── workflow.py        #   ★ Workflow 核心（编译/执行/路由/并行，~2800 行）
│   │   ├── context.py         #   WorkflowContext（thread_id/cancel/timeout）
│   │   └── template.py        #   WorkflowTemplate
│   │
│   ├── node/                  # 节点体系
│   │   ├── base.py / types.py / custom.py
│   │   ├── llm.py             #   ★ LLMNode（含 Agentic Harness 集成）
│   │   ├── toolkit.py         #   ToolKit/Tool（本地工具）
│   │   ├── mcp.py             #   MCPNode/MCPPipelineNode
│   │   ├── human.py           #   HumanNode（中断续传）
│   │   ├── document.py / knowledgebase.py / sub_workflow.py / state_extract.py
│   │   └── llm_tools.py       #   工具批量执行
│   │
│   ├── runtime/               # 运行时
│   │   ├── harness/           #   ★ Agentic 控制面（agent_harness/tool_executor/state）
│   │   ├── streaming/         #   OutputChannel（Dify 格式 SSE 事件总线）
│   │   └── tracing/           #   ★ Tracing（base/db_tracer/wrappers）
│   │
│   ├── state/                 # 状态持久化
│   │   ├── checkpointer.py    #   PG/Memory checkpointer
│   │   └── memory.py          #   消息构造辅助
│   │
│   ├── model/                 # LLM 管理
│   │   ├── manager.py         #   LLMManager + UsageStats（含 cost_estimate）
│   │   └── vision.py
│   │
│   ├── prompt/                # 提示词管理
│   │   └── manager.py         #   PromptManager（热更新/版本）
│   │
│   ├── memory/                # 记忆
│   │   └── workflow_memory.py #   工作流级 memory.md 注入
│   │
│   ├── mcp/                   # MCP 子系统
│   │   ├── manager.py / client.py / toolkit.py / config.py / token_manager.py
│   │   └── builtin_servers/   #   coding/computer/download/planning/search/skill tools
│   │
│   ├── knowledgebase/         # 知识库（CRUD + 向量检索 + hybrid）
│   ├── scheduler/             # 定时任务（APScheduler + store/api）
│   ├── channels/              # 渠道适配（飞书/钉钉/企微/QQ + wecom_worker）
│   ├── audio/                 # ASR/TTS
│   │
│   ├── skills/                # ★ Skills 子系统
│   │   ├── schema.py          #   Skill dataclass
│   │   ├── parser.py          #   SkillParser（自研 YAML 解析）
│   │   ├── manager.py         #   SkillManager（match/refresh/reload）
│   │   ├── executor.py        #   SkillEnvironment（uv 隔离 venv）
│   │   └── builtin_skills/    #   agent_creator/skill_creator/agentclaw_api/coding_skill/clawhub/image-generation
│   │
│   ├── agent_square/          # ★ 模板库（14 个 claw_app）
│   │   ├── __init__.py        #   list/import/register claw_app
│   │   ├── approval/ hello_world/ kb_rag/ weekly_report/ ...
│   │   └── xiaohongshu_writer/ turtle_soup_agent/ werewolf_agent/ ...
│   │
│   ├── api/                   # ★ API 层
│   │   ├── server.py          #   AgentClawServer（路由挂载/中间件/dashboard 挂载）
│   │   ├── registry.py        #   WorkflowRegistry（内存单例）
│   │   ├── auth/              #   middleware/token/api_key/dependencies/utils
│   │   ├── routers/
│   │   │   ├── public/        #   execution/conversations/upload/files/square/rooms/audio/access/session
│   │   │   └── admin/         #   workflows/traces/knowledgebases/scheduler/conversations/...
│   │   ├── services/          #   trace/conversation/settings/dashboard/scheduler/...
│   │   ├── schemas/           #   common（APIError/ErrorCode）
│   │   └── files/
│   │
│   ├── database/              # 数据库
│   │   └── manager.py         #   ★ DatabaseManager（asyncpg/psycopg pool + schema 初始化）
│   │
│   ├── admin-dashboard/       # ★ 前端（Vue3 + naive-ui）
│   │   ├── src/               #   views/router/api/locales/components/composables
│   │   └── dist/              #   构建产物（挂载到 /dashboard /square /agent/{id}）
│   │
│   ├── docker/                # 内置 docker-compose.yml + start/stop/.env.example
│   ├── docs/                  # 框架文档（zh/en：quickstart/user_guide/api_reference/deployment/best_practices）
│   └── test/                  # ★ 测试（unit/boundary/integration/api/real）
│
└── docs/                      # ★ 本次升级文档落地处（upgrade/）
```

---

## 3. Agent 运行主流程

### 3.1 核心抽象：Workflow + Node

AgentClaw 的「Agent」在框架层叫 **Workflow**。一个 Workflow 由若干 **Node** 组成，通过 `add_edge` / `add_router` / `add_llm_router` 编排。定义在 [agentclaw/graph/workflow.py](agentclaw/graph/workflow.py)。

可用节点类型（[agentclaw/__init__.py:26-36](agentclaw/__init__.py#L26)）：

| 节点 | 职责 |
|---|---|
| `LLMNode` | LLM 对话/生成，支持 `agent_style="agentic"` 启用 Harness 工具循环 |
| `CustomNode` / `SyncNode` / `@node` | 自定义函数节点 |
| `HumanNode` | 人工中断续传（`interrupt()` + `Command(resume=...)`） |
| `MCPNode` / `MCPPipelineNode` | MCP 工具调用 |
| `DocumentNode` / `DocumentExtractNode` | 文档处理 |
| `KnowledgeBaseNode` | 知识库检索注入 |
| `SubWorkflowNode` | 子工作流 |
| `StateExtractNode` / `FunctionNode` | 状态提取/函数 |

### 3.2 从「发布」到「执行」的完整生命周期

**① 定义与发布**

```python
workflow = Workflow(id="hello", name="...", inputs=[...], user_input="user_input")
workflow.add_node(LLMNode(id="chat", system_prompt="...", output_to_user=True))
workflow.publish()   # ← 注册到 WorkflowRegistry
```

- `Workflow.publish()` — [workflow.py:2775](agentclaw/graph/workflow.py#L2775)：`_ensure_components()` → `_validate()` → `WorkflowRegistry.register(self, ...)`
- `WorkflowRegistry.register()` — [api/registry.py:60](agentclaw/api/registry.py#L60)：注册到内存 `_workflows` dict，应用本地 settings 覆盖，注册 prompt 端点。**统一通过 `POST /api/workflow/run` 调用，不再生成旧式路由**（[registry.py:111](agentclaw/api/registry.py#L111)）

**② API 调用执行**

入口 `POST /api/workflow/run` → `run_workflow()` — [routers/public/execution.py:493](agentclaw/api/routers/public/execution.py#L493)：

```
run_workflow → _run_workflow_request (execution.py:515)
  ├─ WorkflowRegistry.get(workflow_id)            # 查找
  ├─ authenticate_workflow_or_admin_bearer()       # 鉴权
  ├─ 构造 WorkflowContext(thread_id, user_id, stream, public_mode, tool_confirmation_level)
  ├─ _apply_request_model_selection()              # 模型选择 → context.runtime_model_id
  └─ 分叉：
     ├─ 流式: StreamingResponse(_stream_workflow)  # OutputChannel(stream_mode=True)
     │         └─ workflow.run(..., stream=False, thread_id=...)  # 内部仍走 run
     └─ 阻塞: OutputChannel(stream_mode=False) → workflow.run(inputs, context, thread_id=...)
```

**③ Workflow.run 内部调用链**

```
Workflow.run()                              workflow.py:1601
 └─ _run_blocking()                         workflow.py:1666
     ├─ _ensure_tracing()                   workflow.py:1707 → 1588
     ├─ TracedWorkflow(self, tracer)        workflow.py:1714   # 包装器
     └─ traced.run(...)
         └─ _run_blocking_traced()          wrappers.py:662
             ├─ _wrap_llm_manager()         wrappers.py:797   # 替换为 TracedLLMManager
             ├─ _wrap_nodes()               wrappers.py:815   # 猴补丁 _wrap_node_for_langgraph
             ├─ async with tracer.trace()   wrappers.py:696   # 开 Trace
             └─ workflow._run_blocking(already_traced=True)   wrappers.py:710
                 └─ _execute_workflow()     workflow.py:1791
                     ├─ _ensure_checkpointer()   workflow.py:1794 → 616
                     ├─ _ensure_mcp_connected()  workflow.py:1797
                     └─ _execute_with_langgraph() workflow.py:1814 → 1843
                         ├─ _compile_to_langgraph() workflow.py:1811 → 694
                         ├─ async with _trace_context()  workflow.py:2068
                         └─ compiled_graph.ainvoke(state, config)  workflow.py:2070
```

**④ 两种执行引擎**

- **LangGraph 模式**（默认，有 PG checkpointer + thread_id）：完整 trace 落库
- **内置引擎模式**（`_execute_builtin` — [workflow.py:2278](agentclaw/graph/workflow.py#L2278)）：不编译 LangGraph，**不写 node_logs**（trace 钩子不生效）——⚠️ Experience Collector 需注意此缺口

### 3.3 State 流转与持久化

- **thread_id 来源**：API body `conversation_id` → `thread_id = body.get("conversation_id") or str(uuid.uuid4())`（[execution.py:598](agentclaw/api/routers/public/execution.py#L598)）
- **注入 LangGraph**：`config = {"configurable": {"thread_id": thread_id}}`（[workflow.py:845-852](agentclaw/graph/workflow.py#L845)）
- **State 结构**：动态 TypedDict，由 `_state_schema` + 各 node `output_key` + `_input_schema.inputs` + 内部 `__*` 字段拼成（[workflow.py:756-789](agentclaw/graph/workflow.py#L756)）
- **系统保留字段**：`__messages__`、`__status__`、`__interrupted__`、`__interrupt_info__`、`__files__`、`__user__`、`__error__`、`__runtime_model_id__`、`__filtered_tools__` 等（[state/memory.py:35](agentclaw/state/memory.py#L35) 定义 `SYSTEM_STATE_FIELDS`）
- **Reducer**：`_last_value` / `_shallow_merge_value` / `_deep_merge_value`（[workflow.py:706-735](agentclaw/graph/workflow.py#L706)），节点可声明合并策略
- **Checkpointer**：`_ensure_checkpointer()` — [workflow.py:616](agentclaw/graph/workflow.py#L616)
  - `PG_HOST` 存在 → `AsyncPostgresSaver`（或 Windows 下 `ThreadedPostgresSaver`，[checkpointer.py:69](agentclaw/state/checkpointer.py#L69)）
  - 否则 → `MemorySaver`（内存，重启丢失）
  - LangGraph 自动管理三张表：`checkpoints` / `checkpoint_blobs` / `checkpoint_writes`
- **中断恢复**：`HumanNode` 触发 `interrupt()`（[human.py:168](agentclaw/node/human.py#L168)），`_execute_with_langgraph` 检测 `snapshot.next + user_input` → `Command(resume=...)` 恢复（[workflow.py:2030-2043](agentclaw/graph/workflow.py#L2030)）

---

## 4. Skill 的定义、加载、执行方式

### 4.1 Skill 定义格式

Skill 是一个**目录**，核心是 `SKILL.md`。数据模型在 [skills/schema.py](agentclaw/skills/schema.py)（`Skill` dataclass，L10-L90）。

目录约定（来自 [skill_creator/SKILL.md](agentclaw/skills/builtin_skills/skill_creator/SKILL.md) 与 [parser.py:196-230](agentclaw/skills/parser.py#L196)）：

```
skill-name/
├── SKILL.md              (必需) frontmatter + Markdown 正文
├── scripts/              (可选) *.py 可执行脚本，自动收集
├── references/           (可选) *.md 参考文档，按需加载
├── resources/            (可选) 资源文件
└── requirements.txt      (可选) 依赖
```

**SKILL.md 结构**：

- **YAML frontmatter**（必需，`---` 包裹）：仅允许 `name`、`description`、`license`、`allowed-tools`、`metadata` 五字段（[quick_validate.py:40](agentclaw/skills/builtin_skills/skill_creator/scripts/quick_validate.py#L40)）
  - `name`：`^[a-z0-9-]+$`，≤64 字符
  - `description`：≤1024 字符，不能含 `<>`
  - `metadata`：JSON 字符串或对象，如 `{"always_inject": true}` 表示始终注入上下文
- **Markdown 正文**（必需）：触发后才加载的指令
- **三级渐进式披露**：metadata 始终注入 → SKILL.md body 触发时加载 → references/scripts 按需加载（`Skill.to_prompt()` — [schema.py:49-63](agentclaw/skills/schema.py#L49)）

### 4.2 加载链

```
SkillParser.parse()           skills/parser.py:16    # 读 SKILL.md，自研简易 YAML 解析（避免 pyyaml 依赖）
  ↓
SkillManager                  skills/manager.py:16   # 扫描 skills_dir，加载到 _skills dict（key=name）
  ├─ match(query)             manager.py:221         # 关键词匹配打分，自动选择
  ├─ refresh()                manager.py:289         # 增量扫描新 skill
  └─ reload()
  ↓
SkillEnvironment              skills/executor.py:19  # 为有 requirements.txt 的 skill 在
  └─ execute()                executor.py:221        # ~/.agentclaw/skill-envs/<name>/ 创建隔离 venv（优先 uv），跑脚本
```

### 4.3 现有 builtin skills（[skills/builtin_skills/](agentclaw/skills/builtin_skills/)）

| Skill | 作用 |
|---|---|
| `agent_creator` | 给 LLM 的 workflow 构建手册（Minimal Build Loop 12 步），生成 `workflows/*.py` |
| `skill_creator` | skill 创建-校验-打包流水线（`init_skill.py`/`package_skill.py`/`quick_validate.py`） |
| `agentclaw_api` | AgentClaw 自身 API 能力参考（`always_inject: true`，7 份 references） |
| `coding_skill` | 代码编写能力 |
| `clawhub` | skill 社区分发（search/install/publish） |
| `image-generation` | 图片生成 |

### 4.4 关键复用点（对 Agent Factory / Skill Evolution）

**`agent_creator`**（[builtin_skills/agent_creator/SKILL.md](agentclaw/skills/builtin_skills/agent_creator/SKILL.md)）：
- ✅ 完整 workflow 构建手册（证据管道设计哲学：输入→发现→推理→验证→动作→响应）
- ✅ 4 级校验门禁（syntax → py_compile → import → runtime）
- ✅ 热注册路径 `POST /_internal/admin/workflows/register-file`
- ✅ NL2SQL 两种设计模式（tool-based / process-based）在 [references/nl2sql.md](agentclaw/skills/builtin_skills/agent_creator/references/nl2sql.md)
- ❌ **缺口**：引用的 `scripts/register_workflow.py`、`scripts/validate_workflow.py` 不存在（实际走 HTTP API）；不生成 `claw_app.json`/README/模板

**`skill_creator`**（[builtin_skills/skill_creator/SKILL.md](agentclaw/skills/builtin_skills/skill_creator/SKILL.md) + `scripts/`）：
- ✅ `init_skill.py`：一句话生成 skill 骨架
- ✅ `package_skill.py`：校验 + 打包成 `.skill`（zip）
- ✅ `quick_validate.py`：frontmatter/命名/描述校验门禁
- ✅ 6 步创建流程（理解→规划→初始化→编辑→打包→迭代）

**`agentclaw_api`**：覆盖 workflow/scheduler/channels/knowledgebase/prompts_models/traces，热注册 + 流式验证 + 渠道绑定 + 定时调度 + 知识库检索 + prompt 热加载 + 模型切换——覆盖 agent 生成后的「部署-接入-调度-调优」全链路。

---

## 5. claw_app.json 与 agent_square 模板库

### 5.1 claw_app.json 是什么

`claw_app.json` 是 **Agent Square 模板库**（对外名「模板库」/ Template Library）中每个模板的 **manifest 清单**，**不是** agent 的运行时定义。agent 真正定义在 `agents/<name>.py` 的 `Workflow(...).publish()`。

字段示例（[agent_square/approval/claw_app.json](agentclaw/agent_square/approval/claw_app.json)）：

```json
{
  "id": "approval",
  "name": "04 Human Review",
  "description": "...",
  "tags": ["示例","人工审核","HumanNode","客服"],
  "entry": "agents/approval.py",
  "workflow": "agents/approval.py",
  "workflow_id": "approval",
  "recommended_input": "...",
  "category": "example",
  "copyable": true,
  "inspectable": true
}
```

### 5.2 装载机制（[agent_square/__init__.py](agentclaw/agent_square/__init__.py)）

- `list_claw_apps()` (L57)：glob `*/claw_app.json` 读 manifest，**不导入 workflow 代码**（无副作用）
- `import_claw_app_to_project()` (L218)：`copytree` 到 `<project>/agents/<app_id>/`，追加 `agents/__init__.py` import
- `register_project_claw_app_workflow()` (L280)：`importlib.import_module` 触发 `publish()`，`is_builtin=False`
- `register_claw_app_workflows()` (L321)：启动时可选注册内置模板 `is_builtin=True`

Dashboard 侧：[services/dashboard_service.py](agentclaw/api/services/dashboard_service.py) `list_template_library_apps()` / `import_template_library_app()`。

### 5.3 现有模板清单（14 个）

| 模板 | 分类 | 场景 | 企业相关性 |
|---|---|---|---|
| hello_world | example | 单轮 LLM | 基础 |
| router | example | 意图路由 | 通用 |
| tool_agent | example | 自定义工具 | 通用 |
| approval | example | **客服邮件人工审核** | ★企业 |
| parallel | example | Fan-out/Fan-in | 通用 |
| mcp_agent | example | MCP 工具 | 通用 |
| gif_agent | example | Skills 注入 | 创作 |
| custom_demo | example | **数据报告生成器** | 办公 |
| doc_analyzer | example | **多文档分析** | 办公 |
| weekly_report | example | **周报生成器** | 办公 |
| kb_rag | example | **知识库 RAG 问答** | ★企业 |
| xiaohongshu_writer | content | 小红书文案 | 营销 |
| turtle_soup_agent | game | 海龟汤 | 娱乐 |
| werewolf_agent | game | 狼人杀 | 娱乐 |

**企业场景现状偏薄**：[docs/zh/claw_apps_showcase_plan.md](agentclaw/docs/zh/claw_apps_showcase_plan.md) 明确说明模板库第一批主打「可玩、可截图、可分享」，**刻意避开需要大量私有配置的企业流程**。缺少销售/CRM、财务、HR、合同审批、采购等垂直企业示例。

### 5.4 approval agent 范式（企业审批典范）

[agent_square/approval/agents/approval.py](agentclaw/agent_square/approval/agents/approval.py)：

1. `draft`（LLMNode）：起草回复
2. `review`（**HumanNode**）：中断等待人工输入
3. `add_llm_router`：LLM 意图路由——满意→`approved`→`finalize`；有意见→`revise`→回 `draft`
4. `finalize`（LLMNode）：生成确认话术

展示 **HumanNode 中断续传 + LLM 意图路由 + 循环修改** 模式。

### 5.5 workflows/ 与 agent_square/ 的关系

两者是**同一种定义方式（Python `Workflow.publish()`）的两种装载形态**，不是两套系统：

| 维度 | `workflows/*.py` | `agent_square/<app>/` |
|---|---|---|
| 本质 | 项目级 workflow 文件 | 随包发布的官方模板 |
| manifest | 无 `claw_app.json` | 有 |
| 注册 | bootstrap `import` 自动注册 | 启动时 `register_claw_app_workflows` 或用户导入后热注册 |
| Dashboard 可见 | 直接进「智能体」列表 | 进「模板库」，导入后才进列表 |

---

## 6. MCP / Tool 调用机制

### 6.1 本地 ToolKit

- `ToolKit.call(name, params)` — [toolkit.py:437](agentclaw/node/toolkit.py#L437)：解析参数 → `_call_handler`（asyncio.wait_for + timeout）或 `_call_http`
- `ToolKit.execute()` — [toolkit.py:423](agentclaw/node/toolkit.py#L423)：LLMNode 调用接口
- 声明：`@toolkit.tool async def my_tool(...) -> ...`

### 6.2 MCP 工具

- `MCPToolKit` 由 `Workflow._try_load_mcp()` 自动加载（[workflow.py:459](agentclaw/graph/workflow.py#L459)），全局缓存 `_mcp_toolkit_cache` 避免重复启动子进程
- `MCPNode._do_execute()` — [mcp.py:118](agentclaw/node/mcp.py#L118)：`toolkit.call_with_server(server, tool, arguments)`
- 内置 MCP servers（[mcp/builtin_servers/](agentclaw/mcp/builtin_servers/)）：coding_tools / computer_tools / download_tools / planning_tools / search_tools / skill_tools + registry
- LLMNode 内置工具复用连接：`_get_or_create_builtin_mcp_manager()` — [llm.py:406](agentclaw/node/llm.py#L406)

### 6.3 Agentic 工具循环（Harness）

`LLMNode` 设 `agent_style="agentic"` 时启用 Harness（[llm.py:1059](agentclaw/node/llm.py#L1059)）：

```
每轮:
  harness.begin_turn()
  → llm_manager.stream_with_tools/invoke
  → harness.process_model_response()
  → 若有 tool_calls:
      harness.run_tool_turn()           agent_harness.py:691
      → execute_tools()                 agent_harness.py:735
      → HarnessToolExecutor.execute_batch()  tool_executor.py:29
      → _execute_tool_batch_with_conflict_resolution()  tool_executor.py:85
```

- **工具确认门**：`_requires_user_confirmation()` + `_confirm_tool_call()` — [tool_executor.py:337,104](agentclaw/runtime/harness/tool_executor.py#L337)，通过 `confirm_service` + `OutputChannel.push_confirm_request`
- **决策信号**（Skill Evolution 关注）：`HarnessRunState.events/decisions/turns/warnings/errors` — [harness/state.py:43-90](agentclaw/runtime/harness/state.py#L43)，记录每轮 continue/finish/abort 决策原因。⚠️ **只在内存，工作流结束即丢**——这是 Agentic 经验最值钱的信号源，需持久化。

### 6.4 工具调用记录现状

**无独立 tool_logs 表**。工具调用分散在两处：

1. **SSE 瞬态事件**（不落库）：`OutputChannel.push_tool_start/push_tool` — [streaming/context.py:379,293](agentclaw/runtime/streaming/context.py#L379)，记录 tool_name/arguments/result/status/duration
2. **LLM generation metadata**（落库）：`llm_logs.metadata.tool_calls`（模型请求）+ `tool_results`（执行结果 `{id,name,result,status}`）—— `TracedLLMManager.update_tool_results()` — [wrappers.py:230](agentclaw/runtime/tracing/wrappers.py#L230) → `DatabaseTracer.update_generation_metadata()` — [db_tracer.py:681](agentclaw/runtime/tracing/db_tracer.py#L681)

---

## 7. Tracing 追踪系统（Experience Collector 的复用基础）

### 7.1 三层数据模型

DDL 在 [database/manager.py:511-564](agentclaw/database/manager.py#L511)：

**`workflow_logs`**（Trace 层）：
```
id UUID PK, workflow_id, thread_id, user_id, name,
run_type(blocking/stream), input_data JSONB, output_data JSONB,
node_log_ids JSONB, metadata JSONB,
status(running/success/error/timeout), error TEXT, duration_ms FLOAT,
start_time, end_time
```

**`node_logs`**（Span 层）：
```
id UUID PK, workflow_log_id UUID, parent_node_log_id UUID,
name, node_type, input_data JSONB, output_data JSONB, metadata JSONB,
status(running/success/error/interrupted), error TEXT, duration_ms FLOAT,
start_time, end_time
```

**`llm_logs`**（Generation 层）：
```
id UUID PK, workflow_log_id UUID, node_log_id UUID,
model_id, model_name, prompt TEXT, completion TEXT,
prompt_tokens INT, completion_tokens INT, total_tokens INT,
latency_ms FLOAT, status(success/error), error TEXT, metadata JSONB, created_at
```

三层外键关联：`workflow_logs.id` ← `node_logs.workflow_log_id` ← `llm_logs.node_log_id`；`workflow_logs.node_log_ids` JSONB 数组按序记录节点执行顺序。

### 7.2 关键方法（[runtime/tracing/db_tracer.py](agentclaw/runtime/tracing/db_tracer.py)）

- `DatabaseTracer.trace(name, workflow_id, thread_id, ...)` — L421：`@asynccontextmanager`，创建 `TraceRecord`，`_current_trace.set()`，fire-and-forget INSERT，退出时 UPDATE output/status/duration
- `DatabaseTracer.span(name, node_type, ...)` — L468：`@asynccontextmanager`，关联 `_current_trace` + `_current_span`，后台 INSERT + UPDATE
- `DatabaseTracer.log_generation(...)` — L525：从 ContextVar 取 trace_id/span_id，构造 `GenerationRecord`，后台 INSERT
- 写入策略：**fire-and-forget** 后台任务（`_fire_and_forget` — L192），`flush()` (L334) 等待完成
- `auto_setup_tracing()` — L1301：检测 `PG_HOST` 初始化 DB + tracer
- Stale running 自动归档为 timeout：`_expire_stale_running_logs()` — L353（阈值 `TRACE_STALE_TIMEOUT_SECONDS` 默认 300）

### 7.3 TracedWorkflow / TracedLLMManager 包装器（[runtime/tracing/wrappers.py](agentclaw/runtime/tracing/wrappers.py)）

- `TracedWorkflow` (L598)：`_wrap_llm_manager()` 替换为 `TracedLLMManager`；`_wrap_nodes()` **猴补丁** `workflow._wrap_node_for_langgraph` (L932) 强制重编译，每个节点执行包在 `tracer.span()` 中
- 用 `StateProxy` (L99) 记录节点实际访问的 key 作为 span.input_data；output_data 只保留本节点新增/修改字段；`__messages__` 压缩为 `{added, total, new_messages}`（`_summarize_messages` — L179，tail 6 条，单条截断 200 字符）
- `TracedLLMManager` (L201)：包装 invoke/stream/stream_with_tools，测时 + 取 usage + `log_generation`；usage 累加到 OutputChannel

### 7.4 BaseComponent 钩子（⚠️ 死代码，但天然挂载点）

[base.py:16](agentclaw/base.py#L16) 定义了 `BaseComponent` 标准钩子：`on_init`/`on_workflow_start`/`on_node_start`/`on_node_end`/`on_workflow_end`/`on_error`/`on_stream_chunk`。

**关键发现**：除 `on_init`（组件注册时调用 — workflow.py:419/478/1327, toolkit.py:227）外，其余钩子在执行路径中**从未被调用**。Tracing 完全不依赖钩子，而是通过猴补丁 + 包装器 + ContextVar 串联。

> **对 Experience Collector 的意义**：这是设计上预留但未接线的扩展点。推荐实现 `BaseTracer` 子类（像 `DatabaseTracer`）挂在 `tracer.trace()/span()/log_generation()` 上，**零侵入主流程**。

### 7.5 已记录数据汇总（可复用为 Experience Collector 基础）

| 数据维度 | 已有 | 来源 |
|---|---|---|
| 工作流执行 | trace_id, workflow_id, thread_id, user_id, input, output, status, error, duration | `workflow_logs` |
| 节点执行 | node_id, node_type, parent, input(访问字段), output(变更字段), status, error, duration | `node_logs` |
| LLM 调用 | model_id/name, prompt(完整 messages), completion, tokens(p/c/total), latency, status, metadata(tool_calls/tool_results) | `llm_logs` |
| 三层关联 | trace → node_logs.workflow_log_id → llm_logs.node_log_id | 外键链 |
| 节点顺序 | `workflow_logs.node_log_ids` JSONB | TraceRecord.append_node_log |
| 工具结果 | `{id,name,result,status}` 列表 | `llm_logs.metadata.tool_results` |
| 用户反馈 | conversation_id, message_index, feedback | `message_feedback`（⚠️ 未关联 trace_id） |
| 会话历史 | messages JSON | `agent_conversations` |
| Checkpoint | 完整 state 快照 | `checkpoints`/`checkpoint_blobs`/`checkpoint_writes` |
| 用户记忆 | user_id, key, value | `user_memories` |
| Token 聚合 | 按 trace 批量聚合 | `get_trace_token_stats_batch` — db_tracer.py:932 |
| 执行统计 | total/success/error/avg_duration/p95/p99 | `get_workflow_stats` — db_tracer.py:790 |

### 7.6 Experience Collector 的 12 个缺口

1. **BaseComponent 钩子未接线** → 可作为挂载点（推荐改挂 BaseTracer 子类）
2. **无独立 tool_logs 表** → 工具维度经验分析需新建表或扩展 node_logs
3. **成本未持久化** → `UsageStats.cost_estimate`（[manager.py:475](agentclaw/model/manager.py#L475)）存在但 `llm_logs` 无 cost 列
4. **cached_tokens 未持久化** → `UsageStats.cached_tokens`（L462）未进 llm_logs
5. **message_feedback 未关联 trace_id** → 仅 conversation_id+message_index，无法关联具体执行
6. **内置引擎路径无 trace** → `_execute_builtin` 不写 node_logs
7. **node_logs.metadata 始终为空** → schema 有列但 `tracer.span(metadata=None)` 未填
8. **Harness 决策/事件流未持久化** → `events/decisions/turns` 只在内存，**最值钱信号源丢失**
9. **无 prompt 模板版本快照** → `llm_logs.prompt` 是解析后 messages，未记 prompt_key/版本
10. **无"经验/结论"字段** → 现有表只记事实，无结构化 outcome/lesson/tags
11. **无子工作流 trace 关联** → `parent_node_log_id` 字段存在但填充情况未确认
12. **OutputChannel 事件无持久化** → tool_start/confirm_request/context_compression/model_retry 全瞬态

---

## 8. Memory / Knowledge 实现

### 8.1 Memory

- **工作流级记忆**：[memory/workflow_memory.py](agentclaw/memory/workflow_memory.py) —— 工作流级 `memory.md` 持续注入，沉淀长期上下文与偏好
- **对话历史**：`__messages__` state 字段，LLMNode `save_to_context=True` 时追加 user/assistant 消息（[llm.py:1666-1684](agentclaw/node/llm.py#L1666)）
- **上下文压缩**：长对话自动压缩，降低成本与退化（`POST /api/workflow/compress`、`POST /api/workflow/truncate`）
- **用户长期记忆**：`user_memories` 表（user_id, key, value JSONB，UNIQUE(user_id,key)）
- **消息辅助**：[state/memory.py](agentclaw/state/memory.py) `create_user_message`/`create_ai_message`/`format_messages_for_llm`/`get_last_user_message`

### 8.2 Knowledge Base

- 子系统：[knowledgebase/](agentclaw/knowledgebase/)（store + 向量检索 + hybrid + rerank）
- 节点：`KnowledgeBaseNode` 注入检索结果
- 配置：`KnowledgeBaseConfig`（[config.py:191-244](agentclaw/config.py#L191)）—— backend(milvus/milvus-lite)、retrieval_mode(hybrid/dense/keyword)、chunk_size/overlap、embedding/rerank/llm model
- 表：`knowledge_bases`、`knowledge_documents`、`knowledge_chunks`（GIN 全文索引）、`knowledge_search_logs`
- Admin API：[routers/admin/knowledgebases.py](agentclaw/api/routers/admin/knowledgebases.py) 完整 CRUD + 检索
- API 能力参考：[builtin_skills/agentclaw_api/references/knowledgebase.md](agentclaw/skills/builtin_skills/agentclaw_api/references/knowledgebase.md)

---

## 9. API 入口与路由清单

### 9.1 路由挂载总览（[api/server.py](agentclaw/api/server.py) `_create_app()` L734-1089）

| 路由组 | 前缀 | 挂载点 | 鉴权 |
|---|---|---|---|
| Public API | `/api/*` | server.py:1051 | 路由层 Depends |
| Scheduler API | `/api/scheduler/*` | server.py:1055 | 路由层 |
| Channel routes | `/api/channels/*` | server.py:1063 | 路由层 |
| MCP routes | `/mcp/*` | server.py:1078 | MCP Token |
| Admin API | `/admin/*` | server.py:1082 | AuthMiddleware 强制 Admin Token |
| Dashboard SPA | `/dashboard` `/square` `/agent/{id}` | server.py:1086 | — |
| Health | `GET /health` | server.py:1046 | 无 |

### 9.2 鉴权机制

- **Admin 路由**（`/admin/*`）：`AuthMiddleware`（[auth/middleware.py:63](agentclaw/api/auth/middleware.py#L63)）统一校验 Admin Token，白名单仅 `/admin/auth/verify`、`/admin/health`
- **Public 路由**（`/api/*`）：中间件放行，路由层 Depends（[auth/dependencies.py](agentclaw/api/auth/dependencies.py)）：
  - `require_admin_auth` (L110) — 仅 Admin Token
  - `require_workflow_or_admin_auth` (L105) — Admin 或 Workflow API Key
  - `authenticate_bearer` (L45) — 两者皆可
- **匿名公开端点**（`/api/public/*`）：无 Bearer，但需同源 page session + share_token + 限流（[routers/public/access.py](agentclaw/api/routers/public/access.py)、[session.py](agentclaw/api/routers/public/session.py)）
- **内部中转**（`/_internal/*`）：仅 127.0.0.1 可访问，自动注入 Admin Token（[middleware.py:135-171](agentclaw/api/auth/middleware.py#L135)）—— agent_creator / agentclaw_api skill 走此通道

### 9.3 关键端点

**工作流执行**（[routers/public/execution.py](agentclaw/api/routers/public/execution.py)）：
- `POST /api/workflow/run` — 统一执行（blocking/streaming），核心
- `POST /api/public/workflows/{id}/run` — 匿名运行
- `POST /api/confirm/{confirm_id}` — 危险操作确认
- `GET /api/download/{token}` — 临时文件下载
- `POST /api/workflow/compress` / `truncate` — 上下文压缩/截断

**Admin 工作流管理**（[routers/admin/workflows.py](agentclaw/api/routers/admin/workflows.py)）：
- `POST /admin/workflows/register-file` — **热注册 workflow 文件**（Agent Factory 关键）
- `GET /admin/workflows` / `{id}` / `{id}/stats` / `{id}/trends`
- `PUT /admin/workflows/{id}/nodes/{node_id}/model` — 切换节点模型
- `GET/PUT /admin/workflows/{id}/tool-config` — 工具配置（启禁 skills/tools）

**Traces**（[routers/admin/traces.py](agentclaw/api/routers/admin/traces.py)）：`GET /admin/traces/summary` / `/traces` / `/traces/{id}` / `/traces/{id}/timeline`

**Knowledge Base**（[routers/admin/knowledgebases.py](agentclaw/api/routers/admin/knowledgebases.py)）：完整 CRUD + 文档上传/导入/重建索引/搜索

**Scheduler**（[scheduler/api.py](agentclaw/scheduler/api.py) 前缀 `/api/scheduler`）：Jobs CRUD + pause/resume/trigger + webhook + executions

**Public Room**（[routers/public/rooms.py](agentclaw/api/routers/public/rooms.py)）：匿名多人房间，创建/session/bootstrap/join/state/events(SSE)/typing/chat/run；Admin 侧 [routers/admin/public_rooms.py](agentclaw/api/routers/admin/public_rooms.py)

**其他 Admin**：auth / dashboard / prompts / models / conversations / tasks / channels / settings / debug / audio

### 9.4 公共房间能力（与普通调用对比）

| 维度 | 普通 agent 调用 | Public Room |
|---|---|---|
| 鉴权 | Bearer API Key | 匿名 + room_token + 同源 session |
| 并发 | 每次独立 | 单房间同时刻**只允许一个运行**（`acquire_run_lock`，rooms.py:542） |
| 会话 | conversation_id 调用方给 | 绑定房间，共享同一 LangGraph thread |
| 实时 | SSE 给调用方 | SSE `/events` 推送**所有参与者**（Redis Pub-Sub） |
| 玩家聊天 | 无 | 有 `/chat`（带冷却） |
| 输入 | 直接传 | 改写为 `{nickname}：{user_text}` 注入 `__public_room__` |
| 生命周期 | 无 | `expires_at`（≤30 天）/ revoke / 踢人 |

---

## 10. 数据库 Schema 与存储方式

### 10.1 技术栈

- **PostgreSQL** 主存储，**Redis** 缓存/锁/Pub-Sub，**Milvus** 向量库
- **无 ORM**：直接 `asyncpg`（业务）+ `psycopg`/`psycopg-pool`（LangGraph Checkpointer）
- **无迁移框架**：无 Alembic、无 SQL 迁移文件。Schema 全部用 `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS` 在代码里幂等创建（核心 [database/manager.py:480-619](agentclaw/database/manager.py#L480)；各 service 各自 `_ensure_table()`）

### 10.2 表清单

**核心表**（[manager.py:_init_schema](agentclaw/database/manager.py#L485)）：

| 表 | 主键 | 关键字段 | 用途 |
|---|---|---|---|
| `prompts` | UUID | workflow_id, prompt_key, content, default_content, is_custom, version, updated_by | Prompt 热更新 |
| `prompt_history` | UUID | prompt_id, workflow_id, prompt_key, content, version | Prompt 版本历史 |
| `user_memories` | SERIAL | user_id, key, value(JSONB), UNIQUE(user_id,key) | 用户长期记忆 |
| `workflow_logs` | UUID | workflow_id, thread_id, user_id, run_type, input/output_data, node_log_ids, metadata, status, error, duration_ms | **traces 主表** |
| `node_logs` | UUID | workflow_log_id, parent_node_log_id, name, node_type, input/output_data, metadata, status, error, duration_ms | 节点日志 |
| `llm_logs` | UUID | workflow_log_id, node_log_id, model_id/name, prompt, completion, tokens, latency_ms, status, metadata | LLM 日志 |
| `files` | VARCHAR(64) | original_name, file_path, file_hash, mime_type, size | 文件存储 |

> traces 表即 `workflow_logs`（trace_id = workflow_logs.id），TraceService 通过 `get_db_tracer()`（[services/trace_service.py:264-269](agentclaw/api/services/trace_service.py#L264)）查询。

**对话表**（[conversation_service.py:42-123](agentclaw/api/services/conversation_service.py#L42)）：
- `agent_conversations`：id, workflow_id, title, messages(JSONB), source(`admin`/`public`), owner_id, user_id, **tenant_id**, checkpoint_expired_at... —— 已有 `tenant_id` 但**当前未做多租户隔离**（[dependencies.py:20-27](agentclaw/api/auth/dependencies.py#L20) 注释明确为未来预留）
- `message_feedback`：conversation_id, message_index, feedback, UNIQUE(conversation_id, message_index) —— **未关联 trace_id**

**知识库表**（[knowledgebase/store.py:22-130](agentclaw/knowledgebase/store.py#L22)）：`knowledge_bases`、`knowledge_documents`、`knowledge_chunks`（GIN 全文索引）、`knowledge_search_logs`

**调度器表**（[scheduler/store.py:85-145](agentclaw/scheduler/store.py#L85)）：`scheduled_jobs`（trigger_config JSONB、inputs、job_config、webhook_config、status、next_run_at）、`job_executions`（job_id FK CASCADE、status、trigger_source、inputs、outputs、error、retry_count）

**渠道表**（[channels/store.py:26-84](agentclaw/channels/store.py#L26)）：`channels`（name UNIQUE、type、workflow_id、thread_mode、enabled、config JSONB）、`channel_message_logs`

**公共房间表**（[public_room_service.py:303-353](agentclaw/api/services/public_room_service.py#L303)、[public_room_chat_service.py:100-133](agentclaw/api/services/public_room_chat_service.py#L100)）：`agent_public_rooms`、`agent_public_room_participants`（(room_id, owner_id) 复合主键）、`agent_public_room_chat_messages`（sequence_id BIGSERIAL, room_id FK CASCADE）

**LangGraph Checkpointer 表**：`checkpoints`/`checkpoint_blobs`/`checkpoint_writes`（框架管理）

### 10.3 配置存储（非数据库）

系统/工作流设置持久化在 **JSON 文件**（[settings_service.py:517-518](agentclaw/api/services/settings_service.py#L517)）：`{project_dir}/.agentclaw/{workflow_id}_settings.json`、`settings.infra.json` 等，不走数据库。

`.agentclaw/<workflow_id>_settings.json` 结构（per-workflow 实例配置，非 agent 定义）：
```json
{
  "workflow": {
    "api_published": true,
    "safe_guard_apply_api": false,
    "safe_guard_apply_public": false,
    "workflow_api_key": "wf-..."
  }
}
```

`.agentclaw/relay.json`（服务 relay 配置）：
```json
{"url": "http://127.0.0.1:8000", "pid": ..., "project_dir": "...", "internal_url": "http://127.0.0.1:<port>"}
```

---

## 11. 配置系统

### 11.1 运行时配置（[config.py](agentclaw/config.py)）

- `AgentClawConfig` 单例 dataclass（L385-458），通过 `get_config()` / `AgentClawConfig.load()` 访问
- 子配置 dataclass：`DatabaseConfig`、`RedisConfig`、`AuthConfig`、`WorkflowConfig`、`UploadConfig`、`KnowledgeBaseConfig`、`ProjectConfig`、`SchedulerConfig`、`MaintenanceConfig`
- 每个有 `from_env()` 类方法，从环境变量加载
- 加载流程：`load()` → `load_dotenv()`（自动发现 `.env`）→ 实例化各 dataclass → `apply_saved_system_settings()` 合并本地 JSON 覆盖
- **`AGENTCLAW_DATA_DIR` 解析**：`_data_dir_child()` (L23-28) 留空返回空串；`env_config.py` 的 `resolve_data_dir()` / `build_data_dir_env_vars()` 在 `agentclaw up` 时派生 LOG_FILE、UPLOAD_DIR、KNOWLEDGEBASE_STORAGE_DIR 等

### 11.2 .env 生成注册表（[env_config.py](agentclaw/env_config.py)）

**不是运行时读取，而是渲染 .env 文件的唯一真相源**。`ENV_SECTIONS`（L37-301）分 14 个 section：Server、Auth、Data Directory、Logging、PostgreSQL、Redis、Public Agent Security、Workflow Runtime、Prompt And Skills、Upload And Storage、Knowledge Base、Scheduler、MCP And Builtin Tools、Browser Tools。`render_env_file()` (L308) 渲染；每个 `EnvVarSpec` 有 name/default/description/commented/show_in_env。

> **对升级的意义**：新增环境变量（如 `AGENTCLAW_RBAC_ENABLED`、`AGENTCLAW_AUDIT_LOG_ENABLED`、`AGENTCLAW_EXPERIENCE_ENABLED`）的唯一入口是 `ENV_SECTIONS`，并在 `config.py` 加对应 dataclass + `from_env()`。

### 11.3 models.json（模型配置）

```json
{
  "default": "deepseek-v4-pro",
  "fallback": "deepseek-v4-pro",
  "safe_guard": "",
  "safe_guard_apply_api": false,
  "safe_guard_apply_public": true,
  "safe_guard_rules": "",
  "models": [{"id","channel","api_key","base_url","model","temperature","suppress_tool_choice"}]
}
```
支持 `${ENV_VAR}` 插值。`safe_guard` 是内容安全模型 ID（`safe_guard_apply_public` 默认 true）。

### 11.4 .env 关键配置项（[.env](.env)）

- **Auth**：`ADMIN_TOKEN=ac-admin-...`、`WORKFLOW_API_KEY=sk-...`、`MCP_TOKEN=mcp-...`
- **PG**：`PG_HOST=127.0.0.1`、`PG_PORT=5432`、`PG_DATABASE=agentclaw`、`PG_USER=postgres`、`PG_PASSWORD=agentclaw`
- **Redis**：`REDIS_HOST=127.0.0.1`、`REDIS_PORT=6380`（已改避开 VS Code 占用）
- **Server**：`PORT=8000`、`HOST=0.0.0.0`，以及 `AGENTCLAW_ENABLE_ADMIN_API/DASHBOARD/MCP_ROUTES/SCHEDULER_API/CHANNEL_ROUTES/API_DOCS` 开关
- **Workflow**：`WORKFLOW_TIMEOUT=300`、`WORKFLOW_RECURSION_LIMIT=0`、`MAX_TOOL_ROUNDS=0`
- **Public Security**：`AGENTCLAW_PUBLIC_MAX_INPUT_BYTES`、`AGENTCLAW_PUBLIC_DEFAULT_RATE_LIMIT`、`AGENTCLAW_PUBLIC_TOOL_POLICY`、`AGENTCLAW_PUBLIC_SENSITIVE_WORDS_PATH`
- **KnowledgeBase**：`KNOWLEDGEBASE_ENABLED=true`、`MILVUS_URI=http://127.0.0.1:19530`

---

## 12. 认证授权现状

### 12.1 当前鉴权模型（无 RBAC、无 audit log）

三种平铺令牌：

1. **Admin Token**（[auth/token.py:20-91](agentclaw/api/auth/token.py#L20)，`AdminTokenManager` 单例）：从 `ADMIN_TOKEN` env 读取或自动生成 `ac-admin-{32位hex}`，拥有全部 `/admin/*` 权限
2. **Workflow API Key**（[auth/token.py:94-169](agentclaw/api/auth/token.py#L94)，`WorkflowAPIKeyManager` 单例）：从 `WORKFLOW_API_KEY` env 读取或自动生成 `sk-{48位hex}`，可执行所有工作流，**不具备 Admin 权限**
3. **MCP Token**（[server.py:1093-1127](agentclaw/api/server.py#L1093)，`MCPTokenManager`）：保护 `/mcp/*`

另有 per-workflow 的 `public_share_token`（匿名公开页面）和 `room_token`（多人房间），通过 `safe_compare_digest` 常量时间比较。

### 12.2 权限粒度

- **路由层**：`/admin/*`（AdminToken 强制）vs `/api/*`（workflow/admin 皆可）vs `/api/public/*`（匿名+session+share_token+限流）
- **无角色/Scope**：`AuthPrincipal`（[dependencies.py:15-27](agentclaw/api/auth/dependencies.py#L15)）有 `scopes` 字段但仅 `("admin",)` / `("workflow",)` 两种粗粒度，`user_id`/`tenant_id` 明确注释"为未来多用户版预留"
- **`APIKey`/`APIKeyManager`/`AuthConfig`**（[auth/api_key.py](agentclaw/api/auth/api_key.py)）：定义了更细粒度能力（per-key workflows 白名单、rate_limit、expires_at），但**运行时未启用**——`server.py:_setup_auth` (L477-492) 默认 `AuthConfig(enabled=False)`，是"半成品"

### 12.3 安全机制（已有但非 RBAC）

- `AuthMiddleware`（[auth/middleware.py:63](agentclaw/api/auth/middleware.py#L63)）：白名单 + `/admin/*` Token 校验
- 内部中转 `/_internal/*`：仅 127.0.0.1，自动注入 Admin Token
- 公开端点：同源校验、HMAC 签名 cookie、限流（memory/redis）、敏感词打码、`SafetyGuard` 内容安全、工具策略（`block_builtin`/`block_all`）、`safe_guard` LLM 围栏

### 12.4 审计日志（完全缺失）

无独立审计日志表。`workflow_logs`/`node_logs`/`llm_logs`/`channel_message_logs` 记录的是执行追踪，不是用户操作审计。`updated_by` 字段（prompts 表）硬编码为 `"admin"`（如 [admin/prompts.py:64](agentclaw/api/routers/admin/prompts.py#L64)），无法区分真实操作者。Settings 修改、工作流热注册、渠道 CRUD 等敏感操作**完全没有审计记录**。

---

## 13. 测试体系

### 13.1 框架与配置

- **pytest** + **pytest-asyncio**（[pyproject.toml:54-57](pyproject.toml#L54)）
- 配置 [pyproject.toml:129-140](pyproject.toml#L129)：`testpaths = ["tests", "agentclaw/test"]`，但根目录 `tests/` **不存在**（实际只有 `agentclaw/test/`）
- 5 个自定义 marker：`api`、`unit`、`boundary`、`integration`、`real`

### 13.2 目录职责（[agentclaw/test/](agentclaw/test/)）

| 子目录 | 职责 | 典型文件 |
|---|---|---|
| `unit/` | 纯函数/模型隔离测试，无外部依赖 | test_env_config / test_safe_compare / test_trace_service / test_conversation_service 等 ~50 个 |
| `boundary/` | 边界/限制/阈值测试 | test_upload_limits / test_scheduler_models |
| `integration/` | 多层组合的进程内集成 | test_file_download_api / test_settings_env_reference |
| `api/` | API 契约测试，FastAPI TestClient | test_admin_api_contracts / test_public_api_contracts / test_public_room_api / test_security_headers 等 14 个 |
| `real/` | 对**已运行的真实服务器**端到端，httpx | test_real_environment_api（唯一，需 `AGENTCLAW_REAL_BASE_URL` 等环境变量，未配置时 skip） |

### 13.3 conftest（[test/conftest.py](agentclaw/test/conftest.py)）

- `auth_tokens` fixture：`monkeypatch` 替换 `AdminTokenManager`/`WorkflowAPIKeyManager` 为 Fake 版（固定 token），避免依赖 env
- `public_api_client` / `admin_api_client` fixtures：构建独立 FastAPI app + TestClient，admin 版挂 `AuthMiddleware`

### 13.4 覆盖率估算

约 75 个 Python 测试文件（unit ~50 + api 14 + boundary 2 + integration 2 + real 1）+ admin-dashboard 21 个 vitest `.spec.js`。整体偏重 unit + api 契约，**缺少 RBAC/审计相关测试**（因为功能不存在）。

---

## 14. 部署方式

### 14.1 CLI 三命令（[cli.py](agentclaw/cli.py)）

- `agentclaw init [path]` — 创建项目脚手架（agents/、server.py、models.json、.env、mcp.json、docker-compose.yml、skills/、README.md）
- `agentclaw up` — **推荐**：交互式启动向导，选 Docker / Remote 模式，自动初始化 + 写密钥 + 启动基础设施 + 启动 server
  - `--mode docker|remote` 跳过交互
  - `--vector-backend milvus|milvus-lite` 选向量存储
- `agentclaw serve` — 仅启动已有项目 server

### 14.2 Docker 基础设施

- 内置 [docker/docker-compose.yml](agentclaw/docker/docker-compose.yml)：postgres / redis / milvus（含 etcd+minio）/ adminer
- `agentclaw up` 自动 `docker compose up -d --wait`，并做宿主机端口可用性检查（TCP + Redis PING）
- 项目级 `docker-compose.yml` 由模板复制

### 14.3 运行模式

- **Docker 模式**：自动托管 PG/Redis/Milvus，适合本地开发/Demo
- **Remote 模式**：不启动 Docker，用已有 PG/Redis；连接信息可为空（空则内存模式）

### 14.4 数据目录分离

`AGENTCLAW_DATA_DIR` 可把日志、上传文件、知识库缓存、Docker 数据卷与项目代码分离（`env_config.py` 的 `build_data_dir_env_vars`）。

---

## 15. 文档状态

### 15.1 现有文档（[agentclaw/docs/](agentclaw/docs/)，中英双语）

- quickstart / user_guide / api_reference / deployment / best_practices
- zh 专属：claw_apps_showcase_plan / public_room_implementation / public_room_player_chat_design

### 15.2 README

- [README.md](README.md)（英文）/ [README_CN.md](README_CN.md)（中文）：产品预览、核心价值、快速开始、从想法到上线、使用场景、对比表、核心机制、代码示例
- 已有「Agent Creator 演示」GIF
- 商业与企业支持章节提及：企业定制开发、安全增强、平台集成

### 15.3 缺口

- 无 `docs/upgrade/`（本次新增）
- 无企业 RBAC / Skill Evolution / Agent Factory 相关文档
- 无 `examples/enterprise_agents/`（本次新增）

---

## 16. 模块分类：可复用 / 需新增 / 不建议改动

### 16.1 ✅ 可复用模块（直接集成，不改动）

| 模块 | 复用方式 |
|---|---|
| Workflow + Node 引擎 | Agent 的运行载体，Blueprint 落地为 `Workflow.publish()` |
| LangGraph + Harness | Agentic 工具循环，Agent v0.1 直接跑 |
| Tracing 三层表 | Experience Collector 数据基础，追加 `experiences` 表 |
| `BaseTracer` 抽象 | Experience Collector 实现 `BaseTracer` 子类零侵入挂载 |
| `agent_creator` 手册 | Agent Factory 的 LLM 构建指令基础 |
| `skill_creator` 脚手架 | Skill Evolution 的 init/validate/package |
| `agentclaw_api` skill | Agent 生成后的部署-接入-调度-调优能力参考 |
| `agent_square` 装载机制 | Blueprint 生成物的 import/register 路径 |
| `claw_app.json` 结构 | Agent 模板 manifest 格式 |
| 知识库 / 记忆 / MCP / 渠道 / 调度 | 企业 agent 直接装配 |
| `AuthPrincipal` / `APIKeyManager` | RBAC 扩展基础（已预留 scopes/user_id/tenant_id） |
| dataclass 配置 + `ENV_SECTIONS` | 新增配置项的标准入口 |
| `CREATE TABLE IF NOT EXISTS` 约定 | 新表幂等创建 |
| Dashboard (Vue3+naive-ui) | 新增页面复用 composables 与 CRUD 模式 |

### 16.2 ➕ 需新增模块

| 新增模块 | 位置建议 | 对应 Phase |
|---|---|---|
| **AgentBlueprint Schema** | `agentclaw/agent_factory/blueprint.py` | Phase 1 |
| **Agent Factory**（Requirement Analyzer / Domain Classifier / Template Matcher / Blueprint Generator / Scaffold Generator） | `agentclaw/agent_factory/` | Phase 2 |
| **企业模板库** | `agentclaw/templates/enterprise_agents/` | Phase 3 |
| **Experience Collector**（event_schema / event_logger / trajectory_store / feedback_collector / privacy_filter） | `agentclaw/experience/` | Phase 4 |
| **Skill Evolution Engine**（pattern_miner / skill_extractor / skill_candidate / skill_evaluator / approval_gate / skill_publisher） | `agentclaw/evolution/` | Phase 5 |
| **Agent Registry / Skill Registry / Version Manager** | `agentclaw/registry/` | Phase 6 |
| **Agent Versioning** | 复用 `registry/version_manager.py` + `agents/<name>/versions/` | Phase 7 |
| **Agent Evaluation**（dataset / metrics / evaluator / regression_runner） | `agentclaw/evaluation/` | Phase 8 |
| **RBAC / Audit / Tool Permission** | 扩展 `agentclaw/api/auth/` + 新增 `agentclaw/api/routers/admin/rbac.py`/`audit.py` | Phase 9 |
| **Observability 扩展** | 扩展 `runtime/tracing/` + `api/routers/admin/metrics.py` | Phase 10 |
| **企业 API / CLI / UI** | 扩展 `api/routers/` + `cli.py` + `admin-dashboard/src/views/` | Phase 11 |
| **企业示例** | `examples/enterprise_agents/` | 文档 |
| **升级文档** | `docs/upgrade/` | 全程 |

### 16.3 ⚠️ 需修改模块（最小侵入）

| 模块 | 修改内容 | 风险 |
|---|---|---|
| [cli.py](agentclaw/cli.py) | 新增 `create-agent`/`list-agents`/`run-agent`/`extract-skills`/`approve-skill`/`evaluate-agent`/`rollback-agent` 等子命令 | 低（纯新增命令） |
| [api/server.py](agentclaw/api/server.py) | 挂载新 router（`/api/agents/*`、`/api/skills/*`、`/admin/rbac/*`、`/admin/audit-logs`），用开关控制 | 低（include_router 条件化） |
| [api/routers/admin/router.py](agentclaw/api/routers/admin/router.py) | 注册新 admin 子 router | 低 |
| [api/auth/dependencies.py](agentclaw/api/auth/dependencies.py) | 扩展 `AuthPrincipal`（roles/permissions），新增 `require_permission()` 依赖工厂 | 中（需开关，默认行为不变） |
| [api/auth/middleware.py](agentclaw/api/auth/middleware.py) | 审计日志记录点（仅写操作） | 中（需开关） |
| [config.py](agentclaw/config.py) + [env_config.py](agentclaw/env_config.py) | 新增 `RBACConfig`/`AuditConfig`/`ExperienceConfig`/`EvolutionConfig` dataclass + ENV_SECTIONS | 低 |
| [runtime/tracing/db_tracer.py](agentclaw/runtime/tracing/db_tracer.py) | 成本/cached_tokens 落库（ALTER TABLE 加列） | 中（需迁移） |
| [database/manager.py](agentclaw/database/manager.py) | 新表 DDL（experiences/skill_candidates/agent_versions/audit_logs/users/roles...） | 低（IF NOT EXISTS 幂等） |
| [runtime/harness/state.py](agentclaw/runtime/harness/state.py) | `HarnessRunState.events/decisions` 持久化钩子 | 中（需开关，默认不持久化） |
| admin-dashboard `src/router` + `src/api` + `src/views` | 新增企业页面 | 低（纯新增） |

### 16.4 🚫 不建议改动模块（核心稳定区）

| 模块 | 原因 |
|---|---|
| [graph/workflow.py](agentclaw/graph/workflow.py) 核心 | ~2800 行，编译/执行/路由/并行核心，改动风险极高。Experience Collector 走 Tracer 包装器，不动这里 |
| [node/llm.py](agentclaw/node/llm.py) 核心 | LLMNode + Harness 集成，复杂。决策信号从 `HarnessRunState` 取，不改动节点本身 |
| [graph/context.py](agentclaw/graph/context.py) | WorkflowContext 是执行控制核心 |
| [state/checkpointer.py](agentclaw/state/checkpointer.py) | 持久化机制稳定 |
| [runtime/streaming/context.py](agentclaw/runtime/streaming/context.py) | OutputChannel SSE 事件总线，已有大量消费方 |
| [api/registry.py](agentclaw/api/registry.py) | WorkflowRegistry 内存单例，可扩展但不改核心 |
| [skills/parser.py](agentclaw/skills/parser.py) / [schema.py](agentclaw/skills/schema.py) | Skill 格式稳定，Evolution 生成的 skill 必须遵守此格式 |
| [knowledgebase/](agentclaw/knowledgebase/) / [scheduler/](agentclaw/scheduler/) / [channels/](agentclaw/channels/) | 成熟子系统，只调用不改动 |
| [agent_square/](agentclaw/agent_square/) 装载机制 | 稳定，Blueprint 生成物复用其 import/register |

---

## 17. 与升级目标的差距分析

升级目标 = Enterprise Agent Factory + Skill Evolution Platform。逐项对照：

| 目标能力 | 现状 | 差距 | 升级路径 |
|---|---|---|---|
| 一句话生成企业 Agent | `agent_creator` skill 可生成 `workflows/*.py`，但无结构化 Blueprint、无领域分类、无企业模板、不生成 manifest | 缺 Blueprint Schema / Domain Classifier / Template Matcher / Scaffold Generator | Phase 1-3 |
| Agent Blueprint 系统 | 无统一数据结构 | 全新增 | Phase 1 |
| 企业模板系统 | 模板库偏娱乐，无销售/财务/HR/采购/法务 | 新增 9 个企业模板 | Phase 3 |
| Experience Collector | Tracing 三层表已有，但缺 tool_logs/成本/决策流/经验字段/反馈关联 | 补表 + BaseTracer 子类 + 持久化 Harness 决策 | Phase 4 |
| Skill Evolution Engine | 完全缺失（有 skill_creator 脚手架可复用） | 全新增 pattern_miner → skill_candidate → approval → publish | Phase 5 |
| Agent 版本管理 | 无显式版本（prompt 有 version，但 agent 无） | 新增 `agents/<name>/versions/` + version_manager | Phase 6-7 |
| Skill Registry | `SkillManager` 内存加载，无注册中心/状态/版本 | 新增 skill_registry（candidate/pending/approved/published） | Phase 6 |
| Agent Registry | `WorkflowRegistry` 内存单例无持久化 | 新增 agent_registry 表 + 持久化 | Phase 6 |
| Agent Evaluation | 有 `get_workflow_stats` 统计，但无评估集/回归 | 全新增 dataset/metrics/evaluator/regression | Phase 8 |
| RBAC | 无（三种平铺令牌，AuthPrincipal/APIKeyManager 半成品） | 扩展 AuthPrincipal + 激活 APIKeyManager + users/roles 表 | Phase 9 |
| Audit Log | 完全缺失 | 新增 audit_logs 表 + 中间件记录 | Phase 9 |
| Tool Permission | 有工具确认门 + 工具策略，但无权限级别 | 扩展 ToolSpec permission_level | Phase 9 |
| 可观测性 | Traces + Dashboard stats 较全 | 补成本/决策流/Agent 维度 metrics | Phase 10 |
| 企业 API/CLI/UI | API 基础设施完善，CLI 仅 3 命令，UI 有 agent 管理页 | 扩展企业命令 + `/api/agents/*` + 企业页面 | Phase 11 |
| 测试 | unit+api 契约为主 | 每个新模块加测试 | 各 Phase |
| 文档 | 框架文档完善，无升级文档 | 新增 `docs/upgrade/` + `examples/` | 全程 |

---

## 18. 第一批最小可落地改动（MVP 切入点）

为降低风险，建议第一批改动**只做纯新增、零侵入**的内容，验证升级链路通畅：

1. **创建 `docs/upgrade/` 目录与本两份文档**（本次完成）
2. **新建 `agentclaw/agent_factory/blueprint.py`**：纯 Pydantic Schema（AgentBlueprint/SkillSpec/ToolSpec/WorkflowStep），无任何运行时依赖，无副作用
3. **新建 `agentclaw/agent_factory/serializer.py`**：Blueprint ↔ YAML/JSON 序列化
4. **新建 `agentclaw/test/unit/test_agent_blueprint.py`**：Schema 创建/序列化/加载/必填校验/version 默认 v0.1 测试
5. **新增配置开关**：`env_config.py` 加 `AGENTCLAW_AGENT_FACTORY_ENABLED`、`AGENTCLAW_EXPERIENCE_ENABLED`、`AGENTCLAW_EVOLUTION_ENABLED`、`AGENTCLAW_RBAC_ENABLED`、`AGENTCLAW_AUDIT_LOG_ENABLED`（默认全 false，确保不影响现有流程）

**验收**：`pytest agentclaw/test/unit/test_agent_blueprint.py` 通过；`agentclaw serve` 现有流程完全不受影响。

---

## 19. 风险点与回滚策略

### 19.1 风险点

| 风险 | 影响 | 缓解 |
|---|---|---|
| 改动 `workflow.py`/`llm.py` 核心破坏现有 agent | 高 | 不改动核心，所有扩展走 Tracer 包装器/新模块/开关 |
| 数据库 schema 变更影响已有数据 | 中 | 全用 `IF NOT EXISTS`/`ADD COLUMN IF NOT EXISTS` 幂等；新增表与现有表解耦 |
| RBAC 启用后现有 Admin Token 调用失败 | 高 | `AGENTCLAW_RBAC_ENABLED` 默认 false；启用时 Admin Token 自动具备全部权限（兼容） |
| Experience Collector 持久化增加写入压力 | 中 | fire-and-forget 复用现有模式；开关控制；可降级为 JSONL |
| Harness 决策持久化改动 `harness/state.py` | 中 | 用开关 + 包装器，不改 state.py 核心结构 |
| 企业模板与现有 agent_square 冲突 | 低 | 企业模板放独立目录 `templates/enterprise_agents/`，不混入 agent_square |
| 新增 CLI 命令与现有冲突 | 低 | 新命令名（create-agent 等）与现有 serve/init/up 不冲突 |
| 前端构建产物需重新打包 | 低 | 新页面纯新增，不影响现有路由 |

### 19.2 回滚策略

**原则**：每个 Phase 都通过环境变量开关控制，关闭即回滚到升级前行为。

| Phase | 开关 | 回滚方式 |
|---|---|---|
| Agent Factory | `AGENTCLAW_AGENT_FACTORY_ENABLED=false` | 不注册 `/api/agents/*` 路由，不加载 agent_factory 模块 |
| Experience Collector | `AGENTCLAW_EXPERIENCE_ENABLED=false` | 不挂 BaseTracer 子类，Tracing 回到原样 |
| Skill Evolution | `AGENTCLAW_EVOLUTION_ENABLED=false` | 不启用 pattern mining |
| RBAC | `AGENTCLAW_RBAC_ENABLED=false` | 鉴权回到三种平铺令牌 |
| Audit Log | `AGENTCLAW_AUDIT_LOG_ENABLED=false` | 中间件不记录审计 |

**代码回滚**：所有新模块在独立目录（`agent_factory/`、`experience/`、`evolution/`、`registry/`、`evaluation/`），删除目录 + 移除 include_router 即可完全回滚。对核心文件的修改保持最小且开关化。

**数据回滚**：新增表独立，不影响现有表；如需清理，`DROP TABLE` 新表即可。

---

*审计完成。下一步：基于本报告生成 `01_upgrade_roadmap.md` 升级路线图。*

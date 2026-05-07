# 部署指南

## 快速开始

```bash
uv pip install -e .[all]
agentclaw init myproject
cd myproject
# 编辑 init 自动生成的 .env 与 models.json
agentclaw up            # 启动向导：手动选择 Docker 或 Remote 模式
# 或
agentclaw up --mode remote  # 跳过向导，直接使用远程环境模式
```

## 三种部署模式

| 模式 | 外部依赖 | 适用场景 | 启动方式 |
|------|---------|---------|---------|
| **一键启动** | Docker | 个人开发、桌面助手、快速体验 | `agentclaw up` 或 `start.sh` |
| **远程数据库** | 已有 PG/Redis | 团队开发、云数据库 | `agentclaw up --mode remote` |
| **全量 Docker** | Docker | 远程服务器、API 服务、安全沙箱 | `docker compose up` |

---

## 模式一：一键启动

> **Docker 自动托管数据库，Agent 在本地运行，完整功能。**

`agentclaw up` 会进入启动向导，由用户手动选择 Docker 模式或 Remote 模式。选择 Docker 模式后，它会先检查目标目录是否已经是 AgentClaw 项目；如果不是，会询问启动/创建路径（支持相对或绝对路径，默认当前路径），自动执行项目初始化，提示填写必要运行密钥（留空自动生成），再拉起 Docker 中的 PostgreSQL + Redis + Adminer 并在本地启动 Agent 服务。Agent 在宿主机运行，可完整访问本地文件、MCP 工具、Skills。

如果当前项目已经存在，并且 Docker 基础设施已经运行，`agentclaw up` 会跳过 `docker compose up`，只启动 server；如果 Docker 基础设施未运行，则自动执行 `docker compose up -d`。

**方式 A：CLI 命令**

```bash
agentclaw up
# 🐳 启动基础设施 (PostgreSQL + Redis + Milvus + Adminer)...
#    ✅ PostgreSQL 已启动 (localhost:5432)
#    ✅ Redis 已启动 (localhost:6379)
#    ✅ Milvus 已启动 (localhost:19530)
#    ✅ Adminer 已启动 (localhost:8080)
# 🚀 启动 AgentClaw 服务器...
```

```bash
agentclaw up -p 9000          # 指定 AgentClaw API + Dashboard 端口
agentclaw up --reload         # 开发模式（热重载）
```

**方式 B：启动脚本**

```bash
# 启动（指定项目目录，默认当前目录）
./agentclaw/docker/start.sh ./myproject

# 停止
./agentclaw/docker/stop.sh
```

脚本支持通过环境变量自定义端口和地址：

```bash
FA_PORT=9000 FA_HOST=0.0.0.0 ./agentclaw/docker/start.sh
```

Docker 基础设施映射到宿主机的端口可在项目 `.env` 或当前环境变量中修改：

```bash
PORT=9000              # AgentClaw API + Dashboard；等同于 agentclaw up -p 9000
PG_PORT=6003           # PostgreSQL 宿主机端口
REDIS_PORT=6004        # Redis 宿主机端口
MINIO_API_PORT=19000
MINIO_CONSOLE_PORT=19001
MILVUS_PORT=19531
MILVUS_HTTP_PORT=9092
ADMINER_PORT=18080
agentclaw up --mode docker
```

**Docker 不可用时：**

```bash
agentclaw up
# ❌ Docker 不可用，无法使用 docker 启动模式
#    可安装 Docker 后重试，或使用: agentclaw up --mode remote
```

**服务端口：**

| 服务 | 端口 | 说明 |
|------|------|------|
| AgentClaw | `PORT` / `-p`，默认 8000 | API + Dashboard，运行在宿主机进程 |
| PostgreSQL | `PG_PORT`，默认 5432 | 数据库（Docker 容器映射到宿主机） |
| Redis | `REDIS_PORT`，默认 6379 | 缓存（Docker 容器映射到宿主机） |
| MinIO API | `MINIO_API_PORT`，默认 9000 | Milvus 对象存储 API（Docker 容器映射到宿主机） |
| MinIO Console | `MINIO_CONSOLE_PORT`，默认 9001 | MinIO 管理控制台 |
| Milvus | `MILVUS_PORT`，默认 19530 | 向量数据库 gRPC/API 端口 |
| Milvus HTTP | `MILVUS_HTTP_PORT`，默认 9091 | Milvus HTTP/metrics 端口 |
| Adminer | `ADMINER_PORT`，默认 8080 | 数据库管理 Web UI |

**适用场景：** 个人开发、桌面助手、Demo 演示、快速体验完整功能

---

## 模式二：远程数据库

> **服务本地运行，连接已有的 PostgreSQL / Redis。**

远程模式不会启动 Docker，而是使用当前 `.env` 或系统环境变量中的 PostgreSQL / Redis 配置。已有项目会直接启动；如果目标目录还不是 AgentClaw 项目，会自动初始化项目，并询问 PG / Redis 连接信息。PG_HOST 或 REDIS_HOST 留空表示不连接对应服务。

```bash
# .env
PG_HOST=your-pg-host
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=your-password
PG_DATABASE=agentclaw

# Redis（可选，启用 Prompt 热更新和多实例同步）
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password
```

```bash
agentclaw up --mode remote
# 🚀 启动 AgentClaw 服务器...
#    存储: PostgreSQL (your-pg-host:5432)
#    缓存: Redis (your-redis-host:6379)
```

**特点：**

- 服务在本地运行，完整访问宿主机文件系统、MCP 工具、Skills
- 数据存储在远程数据库，支持多实例共享
- 适合连接云数据库（RDS、Supabase、Neon 等）
- 无需 Docker

**功能对比：**

| 功能 | 仅 PG | PG + Redis |
|------|:-----:|:----------:|
| 全部核心功能 | ✅ | ✅ |
| 多实例部署 | ✅ | ✅ |
| 分布式调度锁 | ✅ | ✅ |
| 高并发写入 | ✅ | ✅ |
| Prompt 热更新 | ❌ | ✅ |
| 多实例 Prompt 同步 | ❌ | ✅ |

**适用场景：** 团队开发、预发布测试、已有数据库基础设施的环境

---

## 模式三：全量 Docker

> **等同于启动一台独立的 Linux 服务器，Agent 在容器内拥有完整的操作系统环境。**

整个 AgentClaw 连同 PostgreSQL、Redis 一起运行在 Docker 中。Agent 的所有操作（MCP 工具调用、Skills 脚本执行、文件读写）都发生在容器内的 Linux 环境中，不涉及宿主机。

```bash
cd myproject
docker compose up -d
```

**特点：**

- 容器即服务器：Agent 在容器内有完整的文件系统、网络、进程管理能力
- MCP 工具、Skills 脚本操作的是容器内的环境，而非宿主机
- 容器隔离确保 Agent 操作不会影响宿主机，安全可控
- 数据通过 Docker named volume 持久化，容器重建不丢数据

**适合：**

- 远程服务器部署，通过 API / Dashboard 远程管理
- 定时调度任务，挂后台长期运行
- 对外提供 API 服务、多租户平台
- 安全合规场景，需要沙箱隔离 Agent 行为

**不适合：**

- 桌面助手场景（Agent 无法操作你的本地文件、打开应用、执行本地命令）
- 需要 Agent 与宿主机交互的开发辅助场景
- 需要交互式调试（pdb 断点）的开发阶段

**服务端口：**

| 服务 | 端口 | 说明 |
|------|------|------|
| AgentClaw | 8000 | API + Dashboard（对外暴露） |
| PostgreSQL | - | 仅容器内部访问 |
| Redis | - | 仅容器内部访问 |

---

## 功能依赖矩阵

### 无依赖（始终可用）

无论是否配置 PG/Redis，以下功能均正常工作：

| 功能 | 说明 |
|------|------|
| 工作流执行 | 定义和运行工作流、节点编排、条件路由、并行执行 |
| LLM 调用 | 调用 OpenAI / Anthropic 等大模型 API |
| MCP 工具 | stdio / SSE 模式的 MCP 服务器集成 |
| Skills 技能 | 技能发现、脚本执行 |
| 模型配置 | models.json 模型管理 |
| Prompt（文件模式） | 从文件/内存加载 Prompt 模板 |
| HumanNode | 人工审批节点 |
| Admin Dashboard UI | 管理后台静态页面可访问（但数据页面为空） |
| API 执行端点 | `/api/workflow/run` 工作流执行接口（需要 Workflow API Key 或 Admin Token） |

### 需要 PostgreSQL

未配置 PostgreSQL 时（`PG_HOST` 未设置），以下功能不可用或降级：

| 功能 | 无 PG 时的表现 | 影响 |
|------|---------------|------|
| **执行追踪** | 回退到 NoopTracer，不记录任何日志 | Dashboard 追踪页面无数据，无法查看历史执行记录和性能分析 |
| **会话持久化** | 回退到内存 MemorySaver | 多轮对话状态仅存于内存，服务重启后丢失全部会话上下文 |
| **定时调度（持久化）** | 回退到 MemoryJobStore | 任务定义和执行记录重启后丢失 |
| **定时调度（分布式锁）** | 回退到 NoopLock | 多实例部署时同一任务可能被重复执行 |
| **对话历史** | 返回空数据 | Dashboard / 公开 Agent 的对话记录无法保存和恢复 |
| **消息反馈** | 不可用 | 用户无法对消息进行评价/反馈 |
| **Prompt 数据库模式** | 仅能使用文件/内存中的默认 Prompt | 无法通过 Admin API 动态创建、编辑、回滚 Prompt |
| **Prompt 版本历史** | 不记录 | prompt_history 表不可用，无法追溯 Prompt 变更 |
| **文件上传** | 文件保存到本地但无元数据追踪 | 无法去重、无法按 ID 检索已上传文件；上传状态接口返回 503 |
| **Dashboard 统计** | 统计数据为空 | 首页执行次数、成功率、趋势图均无数据 |
| **工作流统计** | 不可用 | 单个工作流的执行统计和趋势分析无数据 |
| **用户记忆** | 不可用 | user_memories 表不可用，无法跨会话持久化用户偏好 |
| **节点级日志** | 不记录 | 无法查看单个节点的输入输出、耗时、重试次数 |
| **LLM 调用日志** | 不记录 | 无法查看 Token 消耗、调用延迟、模型选择等详情 |

> **涉及的数据库表（共 11 张）：** `workflow_logs`、`node_logs`、`llm_logs`、`prompts`、`prompt_history`、`user_memories`、`files`、`scheduled_jobs`、`job_executions`、`agent_conversations`、`message_feedback`

### 需要 Redis

未配置 Redis 时（`REDIS_HOST` 未设置），以下功能不可用：

| 功能 | 无 Redis 时的表现 | 影响 |
|------|------------------|------|
| **Prompt 热更新** | 自动禁用热更新 | 修改 Prompt 后需重启服务才能生效 |
| **多实例 Prompt 同步** | 各实例独立加载 | 多实例部署时部分实例可能使用旧版 Prompt |

> Redis 影响范围较小，主要影响 Prompt 热更新。单实例部署且不需要动态修改 Prompt 时，可以不配置 Redis。

---

## 数据库表一览

以下 11 张表在 PostgreSQL 中自动创建（首次连接时通过 `CREATE TABLE IF NOT EXISTS`）：

| 表名 | 用途 |
|------|------|
| `workflow_logs` | 工作流执行记录（状态、耗时、错误） |
| `node_logs` | 节点级执行日志（输入输出、耗时） |
| `llm_logs` | LLM 调用详情（Token、延迟、模型） |
| `prompts` | Prompt 模板内容 |
| `prompt_history` | Prompt 版本变更历史 |
| `user_memories` | 用户长期记忆（KV 存储） |
| `files` | 上传文件元数据（哈希去重） |
| `scheduled_jobs` | 定时任务定义 |
| `job_executions` | 定时任务执行记录 |
| `agent_conversations` | Agent 对话历史 |
| `message_feedback` | 消息反馈评价 |

---

## 环境变量参考

`agentclaw init` / `agentclaw up` 生成的 `.env` 会包含面向用户的运行配置清单，并按模块说明每个配置项的作用。内部与兼容变量仍统一登记在 `agentclaw/env_config.py`，避免环境变量说明分散在不同文件里。

**核心变量：**

模型 API Key 请在项目 `models.json` 的对应模型配置中填写 `api_key`，不要放入默认 `.env`。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 8000 | HTTP Server 端口；CLI 显式 `--port` 会覆盖该值 |
| `HOST` | 0.0.0.0 | HTTP Server 监听地址；CLI 显式 `--host` 会覆盖该值 |
| `PG_HOST` | 未设置 | PostgreSQL 地址，未设置时数据库功能不可用 |
| `PG_PORT` | 5432 | PostgreSQL 端口 |
| `PG_USER` | postgres | PostgreSQL 用户名 |
| `PG_PASSWORD` | - | PostgreSQL 密码 |
| `PG_DATABASE` | agentclaw | 数据库名 |
| `REDIS_HOST` | 未设置 | Redis 地址，未设置时禁用 Prompt 热更新 |
| `REDIS_PORT` | 6379 | Redis 端口 |
| `ADMIN_TOKEN` | 自动生成 | 管理后台认证 Token |
| `WORKFLOW_API_KEY` | 自动生成 | `/api/workflow/run` 默认执行 Bearer Key，不具备 Admin 权限；工作流可单独配置 `workflow_api_key` |
| `MCP_TOKEN` | 自动生成 | MCP 鉴权令牌，请通过 `Authorization: Bearer <MCP_TOKEN>` 发送。缺失时 AgentClaw 会自动生成并写入项目 `.env`；默认不再接受 URL query token。 |
| `AGENTCLAW_TRUST_PROXY_HEADERS` | false | 是否信任反向代理传入的 `X-Forwarded-*`；只在可信代理会清理伪造头时开启 |
| `AGENTCLAW_CONTENT_SECURITY_POLICY` | 内置策略 | 覆盖默认 CSP 安全头；留空使用内置策略 |
| `AGENTCLAW_DUMP_LLM_FAILURE_PAYLOAD` | false | 失败 LLM 请求载荷 dump 开关，默认关闭 |
| `SCHEDULER_ENABLED` | true | 是否启用定时调度 |
| `SCHEDULER_TIMEZONE` | Asia/Shanghai | 调度器时区 |

---

## 公网部署与安全边界

Dashboard 可以部署到公网，但需要区分三类入口：

| 入口 | 鉴权/访问方式 | 说明 |
|------|---------------|------|
| `/admin/...` 和 Dashboard 管理页面 | `ADMIN_TOKEN` | 管理工作流、调度器、渠道、知识库、模型、提示词、追踪等 |
| `/api/workflow/run`、`/api/upload` | `WORKFLOW_API_KEY`、工作流级 `workflow_api_key` 或 `ADMIN_TOKEN` | 面向受信任调用方的工作流执行和会话附件上传 |
| `/dashboard/agent/{workflow_id}?share_token=...` | 工作流显式公开发布 + `share_token` + 同源 Public Session | 面向匿名用户的 Public Agent 分享页 |

注意事项：

- 默认不会公开发布任何工作流；需要在 Dashboard 的工作流配置中显式开启「公开发布」。
- 内置智能体不能公开分享。
- Workflow API Key 不能访问调度器、渠道推送、文件列表、Dashboard 管理、危险操作确认等 Admin 能力。
- Public Agent 匿名执行和公开会话会使用工作流的 `rate_limit`、`public_conversation_limit`、`public_message_limit`。
- `/api/files/{file_id}` 需要 Admin Token 或短期签名 URL。浏览器 Markdown 图片和普通下载链接应使用框架生成的签名 URL，不要使用裸文件 URL。
- 服务默认增加 `Content-Security-Policy`、`frame-ancestors 'none'`、`Referrer-Policy`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY` 等安全头；确有跨域静态资源需求时再通过 `AGENTCLAW_CONTENT_SECURITY_POLICY` 覆盖。
- `AGENTCLAW_DUMP_LLM_FAILURE_PAYLOAD` 默认关闭；只有本地排障时再开启，dump 内容会脱敏但仍可能包含业务上下文。
- Public Agent 的同源校验和限流默认不信任 `X-Forwarded-*`。只有当反向代理可信并会覆盖/清理外部伪造头时，才设置 `AGENTCLAW_TRUST_PROXY_HEADERS=1`。

反向代理建议：

- 统一把 Dashboard 和 API 放在同一 origin 下，例如 `https://agent.example.com/dashboard` 与 `https://agent.example.com/api/...`。
- 代理层清理外部传入的 `X-Forwarded-For`、`X-Forwarded-Proto`、`X-Forwarded-Host`，再由代理重新设置。
- 不要把独立本机 internal relay 暴露到公网；`/_internal/*` 不是外部 API。

---

## 未来规划

### SQLite 轻量存储后端

计划支持 SQLite 作为 PostgreSQL 的替代存储，实现零外部依赖的完整功能体验：

- 无需安装 PostgreSQL、Redis、Docker
- 所有 11 张表在 SQLite 中创建，功能完整
- 自动降级：无 PG 配置且无 Docker 时自动使用 SQLite
- 适合个人开发、Demo 演示、教学场景

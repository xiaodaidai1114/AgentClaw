# AgentClaw

<p align="center">
  <img src="./assets/agentclaw-logo.svg" alt="AgentClaw logo" width="420">
</p>

<p align="center">
  <strong>声明式 Agent 工作流框架</strong><br>
  <em>面向个人开发者与团队，快速构建、调试、部署并持续增强你的 Claw 智能体能力</em>
</p>

<p align="center">
  <a href="./README.md">English</a> •
  <a href="#-产品预览">产品预览</a> •
  <a href="#-从想法到上线">从想法到上线</a> •
  <a href="#-对比一眼看懂">对比一眼看懂</a> •
  <a href="#-快速开始">快速开始</a> •
  <a href="#-商业与企业支持">商业支持</a> •
  <a href="./agentclaw/docs/zh/user_guide.md">文档</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-Apache%202.0-green.svg" alt="License">
  <img src="https://img.shields.io/badge/version-1.0.5-orange.svg" alt="Version">
</p>

---

## 🎬 产品预览

### Agent Creator 演示：创建定时系统日志审计智能体

这个演示展示了 Agent Creator 如何根据自然语言需求创建一个可运行的系统日志审计智能体：连接 MySQL，读取 `system_audit_logs`，分析错误、告警、异常访问、权限拒绝、高风险操作和定时任务执行情况，配置每日定时任务，执行智能体，并生成 Markdown 报告。

<p align="center">
  <video src="./assets/agent_creator.mp4" controls width="100%">
    当前浏览器不支持内嵌视频。可以直接打开演示视频：<a href="./assets/agent_creator.mp4">assets/agent_creator.mp4</a>
  </video>
</p>

<p align="center">
  <a href="./assets/agent_creator.mp4">打开 Agent Creator 演示视频</a>
</p>

## 核心价值

AgentClaw 是一个面向个人开发者与团队、基于 Harness 架构的声明式 Agent 框架，也是一个可持续生长的 Claw 智能体底座：你既可以一句话生成智能体，也能将构建结果持续沉淀为自己的 Claw 能力。

它遵循“约定优于配置”的设计思路，把大量重复的智能体工程工作收进框架内部；相比从头开发智能体，在常见场景下通常可节省约 90% 的工作量。

这意味着，你既可以把 AgentClaw 当作日常可用的 Claw 来使用，也可以把它作为持续构建、调试、部署和沉淀能力的智能体底座。当前核心能力可以概括为：

| 能力模块 | 现在能做什么 |
|------|------|
| 智能体框架 | 声明式工作流、节点与路由编排、Agentic LLM 节点、自定义节点与工具 |
| Claw 执行能力 | 操作电脑、操作浏览器、读写代码、处理文件、调用工具 |
| 知识能力 | 知识库导入、文档解析、检索增强、知识注入 |
| 记忆能力 | 全局记忆、长期上下文沉淀、多轮对话连续性、上下文压缩 |
| 集成能力 | Skills、MCP、外部工具接入、渠道适配 |
| 运行能力 | 定时任务、前端与 Dashboard、状态持久化、提示词热更新 |
| 运营能力 | 会话管理、消息反馈、执行追踪、日志统计、Token 统计、渠道推送 |
| 交付能力 | 发布为 API、MCP Server 或 AgentClaw 内部基础能力 |

你在 AgentClaw 里构建的任何智能体、工具、Skill 与 MCP 接入，最终都不只是一次性工作流，而会转化为 Claw 智能体可复用、可继续增强的能力。

从一句话需求到能力发布，典型路径如下：

一句话需求 / `claw agent` -> 生成智能体 -> 调整工作流 -> 接入工具与知识库 -> 调试测试 -> 部署上线 -> 发布为 API / MCP / AgentClaw 基础能力

声明式工作流是这套能力生长链路的核心：你可以像搭积木一样描述 Agent 的行为，也可以在需要的时候继续下钻到更细的工程控制。

## 🚀 快速开始

### 1. 安装

```bash
pip install agentclaw-ai
```

如果你使用 `uv`，可以安装同一个 PyPI 包：

```bash
uv pip install agentclaw-ai
```

PyPI distribution 是 `agentclaw-ai`；Python import 包名和 CLI 命令仍保持 `agentclaw`。

### 2. 启动 AgentClaw

```bash
agentclaw up
```

`agentclaw up` 是推荐启动方式。它会进入交互式启动向导，由用户选择
Docker 模式或 Remote 模式。如果目标目录还不是 AgentClaw 项目，向导会询问
创建路径，自动完成初始化、写入必要运行密钥，并启动完整服务。

脚本或 CI 场景可以用 `--mode` 跳过交互选择：

```bash
agentclaw up --mode remote
```

如果你只想先创建项目骨架、不立即启动，可以使用：

```bash
agentclaw init myproject
cd myproject
```

生成的项目包含：

- `.env`：运行配置清单，覆盖服务、鉴权、存储、PG/Redis、工作流、调度、知识库、MCP 与内置工具
- `models.json`：模型配置文件
- `agents/hello_world.py`：默认示例工作流
- `server.py`：服务入口

### 3. 配置模型与环境

`agentclaw up` 启动后，打开 Dashboard，在 **系统配置 -> 模型配置** 中填写模型。这个表单会同步写入 `models.json`，并热更新运行中的模型信息。

你也可以手动编辑 `models.json`，然后重启服务。`.env` 用于启动与运行配置，例如端口、鉴权、存储、PostgreSQL、Redis、调度、知识库、MCP 和内置工具；标记为需重启的配置会在重启 Server 后生效。

### 4. 打开 Dashboard

访问 `http://localhost:8000`。你可以直接在前端创建、调试、测试和发布智能体，而不是只停留在代码样例层。

如果你只想直接启动一个已初始化项目的 server，可以使用：

```bash
agentclaw serve
```

默认生成的 `hello_world` 工作流就是第一步；之后你可以继续接入知识库、MCP、记忆、渠道和自定义工具。

### 5. 最小模型配置示例

```json
{
    "default": "gpt-4",
    "models": [
        {
            "id": "gpt-4",
            "model": "gpt-4",
            "api_key": "your-api-key-here",
            "base_url": "https://api.openai.com/v1"
        }
    ]
}
```

## 🧭 从想法到上线

AgentClaw 关注的不是只把一个 Agent 搭出来，而是让个人开发者和团队把自己的 Claw 从初始形态持续打磨成真正可用的智能体系统：

1. 从一句话需求、默认模板或前端界面生成第一个智能体
2. 调整节点配置、提示词、输入输出和运行时参数
3. 接入工具、MCP、知识库、记忆和渠道能力
4. 在前端、日志和追踪中调试行为，验证工具调用与知识链路
5. 通过声明式路由、自定义节点和并行执行，把普通 Agent 演进为更强的 Claw 能力
6. 发布为外部 API、MCP Server 或 AgentClaw 内部的可复用基础能力

## 🎯 使用场景

### 场景一：新手快速起步

```python
# agent.py
from agentclaw import Input, LLMNode, Workflow

workflow = Workflow(
    id="assistant",
    name="Assistant",
    description="一个可以直接运行的智能体",
    inputs=[
        Input("user_input", str, required=True, description="请输入用户问题"),
    ],
    user_input="user_input",
)

workflow.add_node(LLMNode(
    id="agent",
    system_prompt="你是一个强大的 AI 助手",
    enable_memory=True,
    output_to_user=True,
))

workflow.publish()
```

```python
# server.py
import agent

if __name__ == "__main__":
    from agentclaw import AgentClawServer
    server = AgentClawServer()
    server.run()
```

这一层强调的是低门槛：先跑起来，再通过前端继续调试与配置，而不是一开始就陷入大量底层样板代码。

### 场景二：专家编排复杂工作流

当需求逐渐变复杂时，声明式配置可以替代大量命令式编排代码：

```python
workflow.add_node(LLMNode(id="classify", output_format="json", output_to_user=True))
workflow.add_node(LLMNode(id="answer", output_to_user=True))
workflow.add_node(LLMNode(id="handle", output_to_user=True))

workflow.add_router(
    after="classify",
    routes={"question": "answer", "complaint": "handle"},
    condition="classify.intent"
)
```

自动状态管理、运行追踪、提示词热更新和 Dashboard 配置能力都在同一套框架内。

### 场景三：深度定制与扩展

AgentClaw 不只具备常规桌面智能体能力，还能把这些能力重新组合、持续沉淀成你自己的 Claw：

- 操作电脑
- 操作浏览器
- 写代码与修改文件
- 通过 Skills 注入专业知识
- 通过 MCP 接入更多外部能力

```python
# 自定义节点
@workflow.node
async def custom_logic(state: dict, context) -> dict:
    return {"result": "..."}

# 自定义工具
@toolkit.tool
async def custom_tool(param: str) -> str:
    return "..."

# 扩展 Skill - 在 skills/my-skill/SKILL.md 中补充专业知识与脚本
```

## 📊 对比一眼看懂

| 维度 | LangGraph | Claw类桌面智能体（如 OpenClaw） | 智能体平台 | AgentClaw |
|------|-----------|----------------------------------|------------|-----------|
| 核心定位 | 工作流编排框架 | 可直接使用的桌面 Claw 形态 | 平台化配置、分发与管理 | 声明式 Agent 工作流框架 + 可持续定制的 Claw |
| 适合对象 | 熟悉编排的工程团队 | 想直接使用桌面智能体的用户 | 需要统一管理多智能体的平台团队 | 个人开发者、独立开发者与团队 |
| 首次上手 | 需要从代码开始组织流程 | 可直接体验现成能力 | 从平台配置与接入开始 | 一句话需求 + 前端页面 + 默认模板即可起步 |
| 前端与调试 | 需要自行搭建 | 以使用界面为主 | 提供平台界面 | 内置前端、Dashboard、日志追踪与调试入口 |
| 桌面智能体能力 | 需要自己接入 | 核心能力之一 | 视平台能力而定 | 内置电脑操作、浏览器操作、代码与文件处理能力 |
| 定制与扩展 | 高自由度，但需要自己补齐体系 | 围绕现成 Claw 形态扩展 | 在平台能力边界内扩展 | 支持声明式工作流、自定义节点、工具、Skills、MCP |
| 能力沉淀 | 主要沉淀在单个项目代码中 | 以当前 Claw 体验为主 | 以平台资产沉淀为主 | 工作流、工具、Skills、MCP 都可沉淀为 Claw 能力 |
| 发布交付 | 需自己实现 API 与服务化 | 以本地或桌面交互为主 | 以平台内发布与运营为主 | 可发布为 API、MCP Server 或 AgentClaw 基础能力 |

### 核心优势

- 🚀 **上手快** - 默认模板、前端页面和 `agentclaw init` 让个人开发者与团队可以快速拥有第一个可运行智能体
- 🧠 **可持续做强** - 声明式工作流、自定义节点、路由、知识库、记忆、MCP 和渠道能力可以持续往深做
- 🦾 **可定制 Claw 智能体** - 你做出来的不只是一次性 Agent，而是在持续塑造自己的 Claw 智能体能力
- 📊 **闭环完整** - 从开发、调试、测试到部署、发布都在同一套体系里完成
- 🔧 **工程友好** - 配置、追踪、热更新、状态持久化和可观测性都是一等能力

## ⚙️ 核心机制

### 智能体框架
- **声明式工作流** - 用节点、路由、输入输出和配置描述 Agent 行为，而不是手写大量编排样板代码
- **Agentic LLM 节点** - 支持多轮工具调用、自主规划、复杂任务拆解和工具链路执行
- **自定义扩展** - 支持 `@workflow.node`、`@toolkit.tool`、Skills 与 MCP，把自定义能力接入同一套工作流体系

### Agent Runtime Harness 架构
- **可控的 agentic 循环** - Agentic 节点运行在 Harness 层上，将模型回合、工具执行、工具后处理决策、进度反馈和最终回复生成分开
- **更安全的工具执行** - 工具调用会经过结构化信封、参数校验、风险/确认门和明确的错误反馈
- **用户可见的进度** - 每轮工具结果可以压缩成一句友好的进度说明并写回上下文，让长工具链路更容易理解
- **上下文一致性** - Harness 在多轮运行中保持 reasoning、工具结果和后处理状态对齐，同时维护合法的 tool-call 消息顺序

启用 Harness 只需要在 `LLMNode` 上设置 `agent_style="agentic"`。Harness 不需要单独启动服务；当该节点运行时会自动启用。智能体需要调用工具时，可以同时设置 `enable_builtin_tools=True` 或显式配置 `tools=[...]`。

```python
workflow.add_node(LLMNode(
    id="agent",
    system_prompt="你是一个能自主使用工具的智能体。",
    agent_style="agentic",
    enable_builtin_tools=True,
    output_to_user=True,
    stream=True,
))
```

### Claw 能力底座
- **桌面智能体能力** - 支持操作电脑、操作浏览器、写代码与文件修改等常规 Claw 能力
- **能力沉淀** - 新增的工作流、工具、Skills 和 MCP 接入可以持续沉淀为 Claw 的复用能力
- **发布机制** - 可将工作流发布为 API、MCP Server 或 AgentClaw 内部基础能力

### 知识与记忆
- **知识库** - 支持文档导入、解析、检索和知识注入，让智能体能够基于业务资料工作
- **全局记忆** - 支持工作流级 `memory.md` 持续注入，沉淀长期上下文与偏好信息
- **上下文压缩** - 在长对话或长链路执行中自动压缩上下文，降低上下文膨胀带来的成本与退化

### 运行与集成
- **渠道适配** - 支持飞书、钉钉、企微、QQ 等渠道接入与主动推送
- **定时任务** - 支持 cron、间隔和一次性调度，让工作流按计划自动运行
- **前端与 Dashboard** - 提供对话界面、配置页面、日志追踪、调试入口和运行态管理
- **状态与热更新** - 支持提示词热更新、状态持久化和运行时配置管理

## 📚 代码示例

### 从零创建 Agent

```python
# agent.py
from agentclaw import Workflow, LLMNode

workflow = Workflow(
    id="hello",
    name="Hello World",
    user_input="user_input",
    inputs={"user_input": str},
)

workflow.add_node(LLMNode(
    id="chat",
    system_prompt="你是一个友好的助手",
    stream=True,
    output_to_user=True,
))

workflow.publish()
```

```python
# server.py
import agent

if __name__ == "__main__":
    from agentclaw import AgentClawServer
    server = AgentClawServer()
    server.run()
```

### 工具调用

```python
from agentclaw import ToolKit

toolkit = ToolKit()

@toolkit.tool
async def search_web(query: str) -> str:
    """搜索网页信息"""
    return f"搜索结果: {query}"

workflow.use(toolkit)

workflow.add_node(LLMNode(
    id="agent",
    system_prompt="你可以搜索网页",
    tools=["search_web"],
    stream=True,
    output_to_user=True,
))
```

### 多轮对话

```python
# 使用 thread_id 自动持久化对话
result = await workflow.run(
    {"user_input": "你好，我是小明"},
    thread_id="user_123"
)
result = await workflow.run(
    {"user_input": "我叫什么名字？"},  # 记得 "小明"
    thread_id="user_123"
)
```

### 发布为 MCP Server

```python
workflow = Workflow(
    id="my_tool",
    publish_as_mcp=True,  # 将工作流发布为 MCP 服务器
)
```

也可以不搭建完整工作流，直接通过 AgentClaw 内置 MCP 路由发布普通函数或 `ToolKit`。这种方式适合沉淀不需要完整工作流的复用能力，同时保留 SSE / 远程 MCP 访问能力，并且可以把多个工具合并到同一个 server 端点下。

```python
from agentclaw import ToolKit, publish_mcp_toolkit

toolkit = ToolKit()

@toolkit.tool
async def generate_image(prompt: str, size: str = "1024x1024") -> dict:
    """生成图片并返回保存后的文件路径。"""
    ...

publish_mcp_toolkit(toolkit, server="image-tools")
```

上面的示例会把 `generate_image` 暴露到聚合 MCP Server `/mcp/image-tools` 下，多个工具可以通过同一个 server 被远程复用。

## 📖 文档

- [快速开始](./agentclaw/docs/zh/quickstart.md) - 从初始化项目到跑通第一个工作流
- [用户指南](./agentclaw/docs/zh/user_guide.md) - 完整功能文档
- [API 参考](./agentclaw/docs/zh/api_reference.md) - 详细 API 文档
- [部署说明](./agentclaw/docs/zh/deployment.md) - 本地启动、基础设施与服务部署
- [最佳实践](./agentclaw/docs/zh/best_practices.md) - 推荐模式

## 🤝 商业与企业支持

如果你希望在 AgentClaw 基础上继续做更强的定制能力，也可以进一步扩展到更高要求的交付场景：

- 企业定制开发：面向业务流程、知识库、渠道和内部系统的专属智能体
- 安全增强方向：沙盒执行、环境隔离、权限控制、审计与安全策略
- 平台集成方向：接入现有模型平台、企业系统、消息渠道与身份体系
- 交付方式：私有部署、定制工作流、专属能力包与企业版演进支持

联系入口：

- 技术反馈与需求讨论：[GitHub Issues](https://github.com/negai-ai/agentclaw/issues)
- 项目主页与维护入口：[AgentClaw Repository](https://github.com/negai-ai/agentclaw)

## 🔧 环境要求

- Python >= 3.10
- Node.js（可选 - MCP 服务器和 Skills 脚本执行）
- PostgreSQL（可选 - 状态持久化和追踪）
- Redis（可选 - 多实例提示词同步与文件下载）

## 📄 许可证

[Apache License 2.0](./LICENSE)

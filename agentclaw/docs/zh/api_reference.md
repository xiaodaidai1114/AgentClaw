# AgentClaw API 参考

> 用户 API 文档 v1.0.0
>
> 说明：本文面向用户与集成方，只描述公开可调用的 `/api/...` 与 `/admin/...` 接口。`/_internal/...` 是系统内部转发路径，不属于外部调用入口。
>
> 内部 agent/shell 调用使用独立本机 internal relay：服务启动后读取项目目录下 `.agentclaw/relay.json` 的 `internal_url`，实际请求路径为 `{internal_url}/_internal` + 下方文档中的 `/api/...` 或 `/admin/...` 路径。relay 会在服务端注入认证，调用方只发送业务请求体；公网集成方仍使用本文列出的公开路径和对应 Bearer 鉴权。

---

## 目录

1. [核心类](#核心类)
2. [节点类型](#节点类型)
3. [组件](#组件)
4. [输入定义](#输入定义)
5. [服务器](#服务器)
6. [平台管理 API 概览](#平台管理-api-概览)
7. [定时任务 API](#定时任务-api)
8. [异常](#异常)

---

## 核心类

### Workflow

工作流定义和执行的核心类。

```python
from agentclaw import Workflow
```

#### 构造函数

```python
Workflow(
    id: str,                    # 唯一标识
    name: str,                  # 显示名称
    version: str = "1.0.0",     # 版本号
    description: str = "",      # 描述
    timeout: int = 300,         # 超时时间（秒）
    inputs: Any = None,         # 输入参数定义
    user_input: str = None,     # 用户消息字段名（必须在 inputs 中定义，且为字符串类型）
    auth_required: bool = False,      # 预留字段：当前个人版不改变鉴权行为
    allowed_roles: list[str] = None,  # 预留字段：当前个人版不做角色校验
    rate_limit: str = None,           # Public Agent 匿名访问限流，如 "10/min"
    public_share_enabled: bool = False,   # 是否开启匿名公开发布，默认关闭
    public_share_token: str = None,       # 公开分享 token，开启公开发布时自动生成
    workflow_api_key: str = None,         # 当前工作流独立执行密钥
    public_conversation_limit: int = 20,  # Public Agent 每客户端会话数配额
    public_message_limit: int = 200,      # Public Agent 单会话消息数配额
    inject_as_agentic_capability: bool = True,  # 是否注入内置智能体能力目录
    tracing: bool = True,       # 启用追踪
    publish_as_mcp: bool = False,   # 发布为 MCP Server
)
```

> `auth_required` 与 `allowed_roles` 是为后续多用户/团队版本保留的字段，当前个人版不会根据它们放行或拒绝请求。需要公网部署时，请使用 `ADMIN_TOKEN`、Workflow API Key 和 Public Agent 发布开关控制访问。

#### 主要方法

| 方法 | 说明 |
|------|------|
| `add_node(node)` | 添加节点 |
| `add_edge(from, to)` | 添加边 |
| `add_router(after, routes, condition)` | 添加条件路由 |
| `add_conditional_edge(source, condition, targets)` | 添加条件边 |
| `use(component)` | 注册组件 |
| `run(inputs, stream, thread_id)` | 执行工作流 |
| `publish()` | 发布为 API 端点 |
| `get_node(name)` | 获取指定节点 |

#### run() 方法

```python
result = await workflow.run(
    inputs={"user_input": "你好"},
    stream=False,              # True 开启流式
    thread_id="session_001",   # 会话持久化
)

# 返回值
{
    "outputs": [...],
    "state": {"node_id": "result"},
    "metadata": {"duration_ms": 1234}
}
```

---

## 节点类型

### LLMNode

LLM 调用节点。

```python
from agentclaw import LLMNode
```

#### 构造函数

```python
LLMNode(
    id: str,                              # 节点名称
    system_prompt: str = None,            # 系统提示词
    user_prompt: str = None,              # 用户消息模板
    output_key: str = None,               # 输出键名
    output_format: str = "text",          # "text" 或 "json"
    output_to_user: bool = False,         # 流式输出给用户
    model_id: str = None,                 # 指定模型 ID
    model_params: dict = None,            # 模型参数覆盖
    stream: bool = False,                 # 流式输出
    tools: List[str] = None,              # 启用的工具名
    tool_choice: str = "auto",            # auto / required / none
    max_tool_rounds: int = None,          # 最大工具调用轮数
    skills: Union[List[str], str] = None, # 技能列表或 "*"
    enable_builtin_skills: bool = False,  # 启用内置 skills（如 agent_creator）
    enable_builtin_tools: bool = False,   # 启用内置工具（包含任务规划工具）
    agent_style: str = "default",         # default / agentic
    use_context: bool = True,             # 使用对话历史
    save_to_context: bool = True,         # 保存到对话历史
    max_context_messages: int = None,     # 最大历史消息数
    enable_compression: bool = True,      # 启用上下文压缩
    compression_threshold: int = 100000,  # 压缩阈值（token 数）
    compression_model: str = None,        # 指定压缩模型
    images_key: str = "",                 # 图片 state key
    inject_files: bool = None,            # 注入 __files__ 到提示词
    enable_memory: bool = False,          # 注入当前工作流的 memory.md
    fallback_model_id: str = None,        # 节点级降级模型
    auto_fallback: bool = None,           # 节点级自动降级
    fallback_threshold: int = None,       # 节点级失败阈值
)
```

#### 示例

```python
# 基础节点
LLMNode(id="chat", system_prompt="你是一个友好的助手")

# JSON 输出
LLMNode(
    id="classify",
    system_prompt='分类意图，返回: {"intent": "..."}',
    output_format="json"
)

# 带工具
LLMNode(
    id="agent",
    system_prompt="你可以搜索和计算",
    tools=["search", "calculate"]
)

# 带技能
LLMNode(
    id="doc_agent",
    system_prompt="你是文档处理助手",
    skills=["pdf", "text-utils"]
)

# 自动匹配技能
LLMNode(
    id="smart_agent",
    system_prompt="你是智能助手",
    skills="*"
)
```

---

### HumanNode

人工介入节点。

```python
from agentclaw import HumanNode
```

#### 构造函数

```python
HumanNode(
    id: str,                      # 节点名称
    feedback_field: str = None,   # 接收人工输入的字段
    interrupt: bool = True,       # 是否中断等待
    save_to_context: bool = True, # 保存到对话历史
)
```

---

### CustomNode

自定义节点基类。

```python
from agentclaw import CustomNode
```

#### 构造函数

```python
CustomNode(
    id: str,                      # 节点名称
    output_key: str = None,       # 输出键名
    output_to_user: bool = True,  # 是否输出给用户
    on_error: ErrorStrategy = ErrorStrategy.ABORT,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    fallback_value: Any = None,
)
```

#### 使用

```python
class MyNode(CustomNode):
    def __init__(self, id, prefix="", **kwargs):
        super().__init__(id, **kwargs)
        self.prefix = prefix
    
    def process(self, text):  # 参数名自动从 state 取值
        return {"result": self.prefix + text}
```

---

### @node 装饰器

函数式节点装饰器。

```python
from agentclaw import node

@node("calc")
def calculate(a, b):  # 参数名自动从 state 取值
    return {"sum": a + b, "product": a * b}

@node("fetch")
async def fetch_data(url):
    data = await http_get(url)
    return {"data": data}
```

---

### MCPNode

MCP 工具直接调用节点。

```python
from agentclaw import MCPNode
```

#### 构造函数

```python
MCPNode(
    id: str,                  # 节点名称
    server: str,              # MCP Server 名称
    tool: str,                # 工具名称
    output: str,              # 输出参数名
    arguments: dict = None,   # 工具参数（支持 {key} 模板）
    input_mapping: dict = None,
    output_to_user: bool = True,
)
```

---

### MCPPipelineNode

MCP 管道节点，按顺序执行多个工具。

```python
from agentclaw import MCPPipelineNode

MCPPipelineNode(
    id: str,
    steps: List[dict],  # 步骤列表
)
```

---

### DocumentNode

文档解析节点。

```python
from agentclaw import DocumentNode

DocumentNode(
    id: str,
    input_key: str = "document",
    output_key: str = None,
    include_metadata: bool = False,
    max_length: int = 0,
)
```

---

### ParallelGroup

并行执行组。

```python
from agentclaw import ParallelGroup

ParallelGroup(
    id: str,
    nodes: List[BaseNode],
    merge_strategy: str = "dict",  # dict / list / first / custom
    merge_func: Callable = None,
    timeout: int = None,
    on_partial_failure: str = "continue",
)
```

---

### AgentNode

子工作流节点。

```python
from agentclaw import AgentNode

AgentNode(
    id: str,
    agent: Workflow,
    input_mapping: dict = None,
    output_key: str = None,
)
```

---

## 节点类型

### LLMNode

LLM 调用节点。

```python
from agentclaw import LLMNode
```

#### 构造函数

```python
LLMNode(
    id: str,                            # 节点名称
    system_prompt: str = None,          # 系统提示词
    user_prompt: str = None,            # 用户消息模板
    output_key: str = None,             # 输出键名
    output_format: str = "text",        # "text" 或 "json"
    output_to_user: bool = False,       # 流式输出给用户
    model_id: str = None,               # 指定模型 ID
    model_params: dict = None,          # 模型参数覆盖
    stream: bool = False,               # 流式输出
    tools: List[str] = None,            # 启用的工具名
    tool_choice: str = "auto",          # auto / required / none
    max_tool_rounds: int = None,        # 最大工具调用轮数
    skills: Union[List[str], str] = None,  # 技能列表或 "*"
    enable_builtin_skills: bool = False,   # 启用内置 skills（如 agent_creator）
    enable_builtin_tools: bool = False, # 启用内置工具（包含任务规划工具）
    agent_style: str = "default",       # default / agentic
    use_context: bool = True,           # 使用对话历史
    save_to_context: bool = True,       # 保存对话到历史
    max_context_messages: int = None,   # 最大历史消息数
    images_key: str = "",               # 图片在 state 中的 key
    fallback_model_id: str = None,      # 节点级降级模型
    auto_fallback: bool = None,         # 节点级自动降级开关
    fallback_threshold: int = None,     # 节点级失败阈值
)
```

#### 示例

```python
# 基础节点
LLMNode(
    id="chat",
    system_prompt="你是一个友好的助手",
    output_to_user=True
)

# JSON 输出
LLMNode(
    id="classify",
    system_prompt='分类意图，返回: {"intent": "..."}',
    output_format="json",
    output_key="classification"
)

# 带工具
LLMNode(
    id="agent",
    system_prompt="你可以搜索和计算",
    tools=["search", "calculate"],
    max_tool_rounds=5
)

# 自动匹配技能
LLMNode(
    id="smart_agent",
    system_prompt="你是智能助手",
    skills="*"
)
```

---

### HumanNode

人工介入节点，用于审批或输入。

```python
from agentclaw import HumanNode
```

#### 构造函数

```python
HumanNode(
    id: str,                      # 节点名称
    feedback_field: str = "feedback",  # 接收人工输入的字段
    interrupt: bool = True,       # 是否中断等待
    save_to_context: bool = True, # 保存用户输入到对话历史
)
```

#### 示例

```python
workflow.add_node(HumanNode(
    id="approval",
    feedback_field="approved"
))

# 第一次运行 - 在审批节点暂停
result = await workflow.run({"content": "..."}, thread_id="s1")

# 人工审批后恢复
result = await workflow.run({"approved": True}, thread_id="s1")
```

---

### CustomNode

自定义节点基类。

```python
from agentclaw import CustomNode
```

#### 构造函数

```python
CustomNode(
    id: str,                      # 节点 ID
    output_key: str = None,       # 输出键名
    output_to_user: bool = True,  # 是否对外输出
    on_error: ErrorStrategy = ErrorStrategy.ABORT,
    max_retries: int = 3,
    retry_delay: float = 1.0,
)
```

#### 示例

```python
class CalcNode(CustomNode):
    def process(self, a, b):  # 参数名自动从 state 取值
        return {"sum": a + b, "product": a * b}

class PrefixNode(CustomNode):
    def __init__(self, id, prefix=">>", **kwargs):
        super().__init__(id, **kwargs)
        self.prefix = prefix
    
    def process(self, text):
        return {"result": self.prefix + text}

workflow.add_node(PrefixNode("add_prefix", prefix="[INFO] "))
```

---

### @node 装饰器

函数式节点装饰器。

```python
from agentclaw import node

@node("upper")
def to_upper(text):  # 参数名自动从 state 取值
    return {"upper_text": text.upper()}

@node("fetch")
async def fetch_data(url):
    data = await http_get(url)
    return {"data": data}

workflow.add_node(to_upper)
```

---

### ParallelGroup

并行执行多个节点。

```python
from agentclaw import ParallelGroup
```

#### 构造函数

```python
ParallelGroup(
    id: str,                      # 组名称
    nodes: List[BaseNode],        # 并行执行的节点
    merge_strategy: str = "dict", # "dict", "list", "first", "custom"
    merge_func: Callable = None,  # 自定义合并函数
    timeout: int = None,          # 超时时间
)
```

#### 示例

```python
workflow.add_node(ParallelGroup(
    id="analysis",
    nodes=[
        LLMNode(id="sales", system_prompt="分析销售数据"),
        LLMNode(id="risk", system_prompt="分析风险"),
    ],
    merge_strategy="dict"
))
# 结果: state["sales"], state["risk"]
```

---

### MCPNode

MCP 工具直接调用节点。

```python
from agentclaw import MCPNode
```

#### 构造函数

```python
MCPNode(
    id: str,                      # 节点 ID
    server: str,                  # MCP Server 名称
    tool: str,                    # 工具名称
    output: str,                  # 输出参数名
    arguments: dict = None,       # 工具参数，支持 {key} 模板
    input_mapping: dict = None,   # 输入映射
    output_to_user: bool = True,  # 是否输出给用户
)
```

#### 示例

```python
workflow.add_node(MCPNode(
    id="fetch_page",
    server="fetch",
    tool="fetch",
    output="page_content",
    arguments={"url": "{target_url}"},
))
```

---

### MCPPipelineNode

MCP 管道节点，按顺序执行多个工具。

```python
from agentclaw import MCPPipelineNode

workflow.add_node(MCPPipelineNode(
    id="train_query",
    steps=[
        {"server": "12306", "tool": "get-current-date", "output": "query_date"},
        {"server": "12306", "tool": "get-tickets", 
         "arguments": {"date": "{query_date}"}, "output": "tickets"},
    ],
))
```

---

### DocumentNode

文档解析节点。

```python
from agentclaw import DocumentNode
```

#### 构造函数

```python
DocumentNode(
    id: str,
    input_key: str = "document",   # state 中文档路径的 key
    output_key: str = None,        # 解析结果存储的 key
    include_metadata: bool = False,
    max_length: int = 0,           # 最大输出长度
)
```

---

## 组件

### LLMManager

多模型 LLM 管理器。

```python
from agentclaw import LLMManager
```

#### 使用

```python
# 从 models.json 自动加载
workflow.use(LLMManager())

# 指定默认和降级模型
workflow.use(LLMManager(
    default="qwen3-next",
    fallback="qwen3-32b",
    auto_fallback=True,
    fallback_threshold=3,
))
```

---

### PromptManager

提示词模板管理器。

```python
from agentclaw import PromptManager
```

#### 使用

```python
pm = PromptManager()
pm.register("greeting", "你好，{name}！")

workflow.use(pm)

# 在节点中引用
LLMNode(id="greet", system_prompt="{@greeting}")
```

---

### ToolKit

工具注册和管理。

```python
from agentclaw import ToolKit
```

#### 装饰器注册

```python
toolkit = ToolKit()

@toolkit.tool
async def search(query: str, limit: int = 10) -> str:
    """
    搜索数据库
    
    Args:
        query: 搜索关键词
        limit: 最大结果数
    """
    return f"结果: {query}"

workflow.use(toolkit)

# 在节点中启用
LLMNode(id="agent", tools=["search"])
```

---

## 输入定义

### Input

输入参数定义。

```python
from agentclaw import Input
from agentclaw.inputs import Image, File, Audio
```

#### 构造函数

```python
Input(
    name: str,                    # 参数名称
    type: Type = str,             # 参数类型
    required: bool = False,       # 是否必填
    default: Any = None,          # 默认值
    description: str = "",        # 参数描述
    min: number = None,           # 最小值
    max: number = None,           # 最大值
    min_length: int = None,       # 最小长度
    max_length: int = None,       # 最大长度
    choices: List = None,         # 枚举选项
    accept: List[str] = None,     # 文件类型约束
    max_size: str = None,         # 最大文件大小
)
```

#### 示例

```python
workflow = Workflow(
    id="demo",
    inputs=[
        Input("query", str, required=True, description="查询内容"),
        Input("count", int, default=10, min=1, max=100),
        Input("mode", str, choices=["fast", "balanced", "quality"]),
        Input("image", Image, description="上传图片"),
        Input("document", File, accept=[".pdf", ".docx"]),
    ]
)
```

---

## 服务器

### AgentClawServer

工作流 HTTP 服务器。

```python
from agentclaw import AgentClawServer
```

#### 使用

```python
server = AgentClawServer(
    host="0.0.0.0",
    port=8000,
    workers=1,
    reload=False,       # 开发模式热重载
    enable_admin=True,  # Admin 管理界面
)
server.run()
```

#### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/workflows` | GET | 列出工作流 |
| `/api/models` | GET | 列出公开可用模型 |
| `/api/workflow/run` | POST | 执行工作流（Workflow API Key / 工作流级 API Key / Admin Token） |
| `/api/workflow/compress` | POST | 压缩会话上下文（Workflow API Key / Admin Token） |
| `/api/public/workflows/{workflow_id}` | GET | 获取匿名 Public Agent 元数据（需要启用公开发布和 `share_token`） |
| `/api/public/workflows/{workflow_id}/session` | POST | 打开同源匿名 Public Agent 会话（需要 `share_token`） |
| `/api/public/workflows/{workflow_id}/run` | POST | 匿名 Public Agent 执行入口（仅同源公开页面会话） |
| `/api/confirm/{confirm_id}` | POST | 确认危险操作（仅 Admin Token） |
| `/api/download/{token}` | GET | 下载工具生成的临时文件 |
| `/api/upload/status` | GET | 检查上传能力 |
| `/api/upload` | POST | 上传会话附件 |
| `/api/files/{file_id}` | GET | 读取已存储文件（Admin Token 或短期签名 URL） |
| `/api/channels` | GET | 列出已配置渠道（仅 Admin Token） |
| `/api/channels/push` | POST | 主动推送消息到渠道（仅 Admin Token） |
| `/api/conversations` | POST | 创建会话（仅 Admin Token） |
| `/api/conversations/{workflow_id}` | GET | 列出会话（仅 Admin Token） |
| `/api/conversations/{workflow_id}/{conversation_id}` | GET/PUT/DELETE | 获取/更新/删除会话（仅 Admin Token） |
| `/api/conversations/{workflow_id}/{conversation_id}/feedback` | GET/POST | 获取/提交反馈（仅 Admin Token） |

##### POST /api/workflow/run

以阻塞或流式模式执行工作流。

需要 `Authorization: Bearer <key>`。可用密钥包括：

- 全局 `WORKFLOW_API_KEY`
- 工作流配置中的 `workflow_api_key`，只允许执行该工作流
- `ADMIN_TOKEN`

Workflow API Key 不等同于 Admin Token，不能访问调度器、渠道推送、文件列表、Dashboard 管理、危险操作确认等管理能力。

**请求体（推荐）：**
```json
{
  "workflow_id": "my_workflow",
  "response_mode": "streaming",
  "conversation_id": "session_001",
  "user": "你好",
  "user_id": "user_123",
  "inputs": {
    "locale": "zh-CN"
  }
}
```

**字段语义：**
- `user`：消息文本（字符串），用于对话输入与 HumanNode 续跑输入。
- `user_id`：调用方身份元数据。
- `inputs`：结构化业务输入。

**归一化规则：**
- 若工作流配置了 `user_input="<field>"`，当 `inputs["<field>"]` 缺失时，顶层 `user` 会自动映射到该字段。
- 若同时提供 `user` 与 `inputs["<field>"]`，两者必须一致，否则返回 `400 INVALID_REQUEST`。
- HumanNode 续跑仍使用同一个接口和同一个 `conversation_id`，没有单独的公开 resume 接口。

##### 匿名 Public Agent

匿名 Public Agent 是浏览器分享页能力，不使用 `WORKFLOW_API_KEY`。只有满足以下条件时才可访问：

- 工作流显式开启 `public_share_enabled`
- 请求携带正确的 `share_token`（query 参数 `share_token` / `token`，或 JSON body 中的同名字段）
- 浏览器先从同源公开页面调用 `POST /api/public/workflows/{workflow_id}/session` 建立短期 HttpOnly cookie
- 后续匿名运行调用带 `X-AgentClaw-Public-Session: 1`，并保持同源 `Origin` / `Referer`

公开分享 URL 由 Dashboard 生成，形如：

```text
/dashboard/agent/my_workflow?share_token=<PUBLIC_SHARE_TOKEN>
```

典型接口顺序：

```bash
# 读取公开页所需元数据
curl "http://localhost:8000/api/public/workflows/my_workflow?share_token=<PUBLIC_SHARE_TOKEN>"

# 浏览器公开页先创建同源会话 cookie；普通跨站脚本调用会被拒绝
curl -X POST "http://localhost:8000/api/public/workflows/my_workflow/session?share_token=<PUBLIC_SHARE_TOKEN>" \
  -H "Origin: http://localhost:8000" \
  -H "Referer: http://localhost:8000/dashboard/agent/my_workflow?share_token=<PUBLIC_SHARE_TOKEN>"

# 公开页执行工作流。真实浏览器会自动带上上一步设置的 cookie
curl -X POST "http://localhost:8000/api/public/workflows/my_workflow/run" \
  -H "Content-Type: application/json" \
  -H "X-AgentClaw-Public-Session: 1" \
  -d '{
    "share_token": "<PUBLIC_SHARE_TOKEN>",
    "response_mode": "streaming",
    "conversation_id": "public_session_001",
    "user": "你好"
  }'
```

Public Agent 额外限制：

- 内置智能体（`__builtin__` 或标记为 builtin 的工作流）不能公开分享。
- 匿名执行会忽略 `user_id`、请求级模型切换和人工确认设置，并禁止文件附件/文件输入。
- `rate_limit` 仅作用于 Public Agent 匿名执行和匿名会话 API，格式示例：`10/min`、`100/hour`。
- `public_conversation_limit` 和 `public_message_limit` 分别限制每客户端可创建的公开会话数量和单次更新的消息数量。
- 如果部署在可信反向代理之后，并且代理会清理外部伪造的 `X-Forwarded-*` 头，可设置 `AGENTCLAW_TRUST_PROXY_HEADERS=1`；否则保持默认关闭。

##### GET /api/files/{file_id}

已存储文件可以通过两种方式读取：

- 管理端请求使用 `Authorization: Bearer <ADMIN_TOKEN>`
- 浏览器渲染、Markdown 图片或普通下载链接使用短期签名 URL，例如 `/api/files/{file_id}?token=...`

不要把裸 `/api/files/{file_id}` 当作永久公开 URL。`<img>`、Markdown 图片和普通 `<a>` 点击不会自动携带 Bearer header；框架返回的 `StoredFile.url` 会使用短期签名 URL，适合浏览器嵌入。

##### POST /api/confirm/{confirm_id}

确认或拒绝 Agent 请求的危险操作。

需要 `Authorization: Bearer <ADMIN_TOKEN>`；Workflow API Key 不能批准危险操作。

**请求体:**
```json
{
  "approved": true,
  "sudo_password": "user_password"  // 仅当 require_sudo=true 时需要
}
```

**响应:**
```json
{
  "success": true,
  "confirm_id": "uuid",
  "approved": true,
  "require_sudo": true,
  "sudo_received": true
}
```

**说明:**
- 当 Agent 调用 `confirm_action` 工具时,前端会收到 `confirm_request` SSE 事件
- 如果 `require_sudo=true`,前端应显示密码输入框
- 用户确认后调用此接口,将密码传递给后端
- 密码仅在当前会话有效,不会持久化

##### POST /api/channels/push

主动向已配置的渠道实例推送一条消息。

需要 `Authorization: Bearer <ADMIN_TOKEN>`。

**请求体：**
```json
{
  "channel": "feishu_sales",
  "user_id": "ou_xxx",
  "chat_id": "",
  "content": "您好，这是一条主动推送消息。"
}
```

**字段说明：**
- `channel`：渠道实例名；也兼容传渠道类型名，框架会尝试匹配第一个同类型渠道。
- `content`：要发送的消息文本。
- `user_id` / `chat_id`：二选一至少提供一个。

**成功响应：**
```json
{
  "status": "sent"
}
```

---

## 平台管理 API 概览

除登录校验等少数接口外，`/admin/...` 路径通常需要 `Authorization: Bearer <ADMIN_TOKEN>`。

如果你只关心已鉴权的工作流执行和会话附件上传，可使用上面的 `/api/workflow/run`、`/api/upload` 等接口。会话管理、渠道主动推送、文件列表、调度器、知识库、提示词、模型和追踪等管理能力需要 `ADMIN_TOKEN` 或 `/admin/...` 接口。匿名 Public Agent 只应通过公开分享页使用，不应把它当作通用后端集成 API。

| 模块 | 常用端点 | 用途 |
|------|----------|------|
| 工作流管理 | `GET /admin/workflows`、`GET /admin/workflows/{workflow_id}`、`POST /admin/workflows/register-file` | 查看工作流列表/详情，运行时热加载工作流文件 |
| 任务管理 | `GET /admin/tasks`、`POST /admin/tasks/{task_id}/cancel`、`DELETE /admin/tasks/cleanup` | 查看运行中任务、取消任务、清理已完成任务 |
| 知识库 | `GET/POST /admin/knowledgebases`、`POST /admin/knowledgebases/{id}/documents/upload`、`POST /admin/knowledgebases/{id}/search` | 管理知识库、上传文档、执行检索 |
| 渠道管理 | `GET/POST /admin/channels`、`POST /admin/channels/probe`、`POST /admin/channels/{channel_id}/restart`、`GET /admin/channels/logs` | 创建渠道、验证凭据、重启渠道、查看消息日志 |
| 追踪与监控 | `GET /admin/traces/summary`、`GET /admin/traces`、`GET /admin/traces/{trace_id}`、`GET /admin/traces/{trace_id}/timeline` | 查看执行摘要、追踪详情与时间线 |
| 提示词与模型 | `GET /admin/prompts/{workflow_id}`、`PUT /admin/prompts/{workflow_id}/{prompt_key}`、`GET /admin/models`、`PUT /admin/models/{model_id}` | 热更新提示词、查看和修改模型配置 |
| 系统与节点配置 | `GET/PUT /admin/settings/global`、`GET/PUT /admin/settings/workflows/{workflow_id}`、`GET/PUT /admin/settings/workflows/{workflow_id}/nodes/{node_id}` | 管理全局、工作流和节点级配置 |

补充说明：

- 渠道回调入口通常由平台配置使用：`/api/channels/{channel_name}/webhook`
- `/api/channels/push` 负责主动发消息，`/admin/channels/...` 负责渠道配置与排障
- 如果你在管理后台里操作“知识库、提示词、模型、追踪、工作流配置”，本质上调用的就是这些 `/admin/...` 接口

---

## 定时任务 API

定时任务 API 挂载在 `/api/scheduler/` 路径下，需要 `Authorization: Bearer <ADMIN_TOKEN>` 认证。

### 端点列表

| 端点 | 方法 | 说明 |
| ---- | ---- | ---- |
| `/api/scheduler/jobs` | GET | 列取任务（支持 `status`、`limit`、`offset` 查询参数） |
| `/api/scheduler/jobs` | POST | 创建任务 |
| `/api/scheduler/jobs/{id}` | GET | 获取任务详情 |
| `/api/scheduler/jobs/{id}` | PUT | 更新任务（部分更新） |
| `/api/scheduler/jobs/{id}` | DELETE | 删除任务 |
| `/api/scheduler/jobs/{id}/pause` | POST | 暂停任务 |
| `/api/scheduler/jobs/{id}/resume` | POST | 恢复任务 |
| `/api/scheduler/jobs/{id}/trigger` | POST | 手动触发一次 |
| `/api/scheduler/jobs/{id}/webhook` | POST | Webhook 外部触发 |
| `/api/scheduler/jobs/{id}/executions` | GET | 获取执行历史 |
| `/api/scheduler/jobs/{id}/executions/{eid}` | GET | 获取执行详情 |

### POST /api/scheduler/jobs

创建定时任务。

```json
{
    "name": "每日报表",
    "workflow_id": "report_workflow",
    "description": "可选描述",
    "trigger": {
        "type": "cron",
        "expression": "0 9 * * *",
        "timezone": "Asia/Shanghai"
    },
    "inputs": {
        "user_input": "生成报表"
    },
    "config": {
        "timeout": 600,
        "retry_count": 2,
        "retry_interval": 60,
        "concurrency": "skip"
    },
    "webhook": {
        "enabled": true,
        "secret": "your-secret",
        "allow_input_override": true
    }
}
```

**触发器类型：**

- `cron`：需要 `expression`（cron 表达式）、可选 `timezone`
- `interval`：支持 `weeks`、`days`、`hours`、`minutes`、`seconds`，可选 `start_date`、`end_date`
- `date`：需要 `run_date`（ISO 格式时间），可选 `timezone`
- 当 `webhook.enabled` 为 `true` 时，必须提供非空 `webhook.secret`。

**响应（201）：**

```json
{
    "id": "uuid",
    "name": "每日报表",
    "status": "enabled",
    "trigger": {"type": "cron", "expression": "0 9 * * *"},
    "next_run_at": "2026-03-18T09:00:00+08:00"
}
```

### POST /api/scheduler/jobs/{id}/webhook

通过 Webhook 触发任务执行。

**请求头：**

- `X-Webhook-Secret`：必须与任务配置的 `webhook.secret` 一致

**请求体（可选）：** 当 `webhook.allow_input_override = true` 时，请求体作为 inputs 覆盖。

```json
{
    "user_input": "webhook 传入的参数"
}
```

**响应（200）：**

```json
{
    "message": "Job triggered",
    "execution_id": "uuid"
}
```

**错误码：**

- `400`：Webhook 未启用
- `403`：Secret 不匹配
- `404`：任务不存在

### 执行记录模型

```python
{
    "id": "uuid",
    "job_id": "uuid",
    "status": "success",         # pending | running | success | failed | timeout
    "trigger_source": "webhook", # schedule | manual | webhook
    "started_at": "2026-03-17T09:00:00",
    "ended_at": "2026-03-17T09:00:05",
    "duration_ms": 5000,
    "inputs": {},
    "outputs": {"answer": "..."},
    "error": null,
    "retry_count": 0
}
```

---

## 异常

```python
from agentclaw import (
    AgentClawError,         # 基础异常
    WorkflowCancelledError, # 工作流被取消
    WorkflowTimeoutError,   # 超时
    NodeExecutionError,     # 节点执行失败
    ConfigError,            # 配置错误
)
```

---

*文档版本: 1.0.0*

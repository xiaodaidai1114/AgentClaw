# AgentClaw 最佳实践

> 使用声明式配置，让框架自动管理复杂逻辑

---

## 核心原则

1. **声明式优先**：使用 `LLMNode`、`HumanNode` 等声明式节点
2. **自动管理**：会话、消息历史、状态持久化都由框架自动管理
3. **约定优于配置**：合理默认值，减少必要配置

---

## 系统保留字段

框架使用以下系统保留字段（以 `__` 开头和结尾）：

| 字段名 | 说明 |
|--------|------|
| `__messages__` | 对话历史 |
| `__interrupted__` | 中断标记 |
| `__status__` | 状态 |

> ⚠️ 用户定义的 State 字段不应使用 `__` 开头的名称。

---

## 场景最佳实践

### 1. 简单 LLM 调用

```python
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="你是一个友好的助手"
))
```

### 2. 多轮对话

```python
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="你是一个友好的助手",
    use_context=True,           # 自动加载对话历史（默认）
    max_context_messages=20     # 限制历史条数
))

# 使用 thread_id 实现跨请求会话
result = await workflow.run(
    {"user_input": "你好"},
    thread_id="session_001"     # 状态自动持久化
)
```

### 3. 输出固定内容（开场白等）

```python
from agentclaw import output

@workflow.node("greeting")
async def greeting(state):
    # 临时提示（不保存到上下文）
    await output("处理中，请稍候...")
    return {}

@workflow.node("opening")
async def opening(state):
    # 角色设定/开场白（保存到上下文）
    opening = "喵～你好呀！我是你的小助手喵～"
    await output(opening, save_to_context=True)
    return {}
```


### 4. 流式输出

```python
# 使用 LLMNode（自动流式输出）
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="你是助手",
    stream=True  # 显式开启流式输出
))
```

### 5. Human-in-Loop（等待用户输入）

```python
# 对话场景：保存用户输入到对话历史
workflow.add_node(HumanNode(
    id="await_input",
    feedback_field="user_input",
    save_to_context=True,  # 默认值
))

# 审批场景：不保存到对话历史
workflow.add_node(HumanNode(
    id="approval",
    feedback_field="approved",
    save_to_context=False,
))
```

### 6. 工具调用

```python
from agentclaw import ToolKit

toolkit = ToolKit()

@toolkit.tool
async def search_database(query: str, limit: int = 10) -> str:
    """
    搜索数据库
    
    Args:
        query: 搜索关键词
        limit: 返回数量限制
    """
    return await db.search(query, limit)

workflow.use(toolkit)

workflow.add_node(LLMNode(
    id="agent",
    system_prompt="你是智能助手，可以使用工具完成任务",
    tools=["search_database"],
    tool_choice="auto",
    max_tool_rounds=5,
))
```

### 7. Skills 技能调用

```python
# 指定技能列表
workflow.add_node(LLMNode(
    id="agent",
    system_prompt="你是智能助手",
    skills=["pdf", "webapp-testing"],
))

# 自动匹配相关技能（推荐）
workflow.add_node(LLMNode(
    id="agent",
    system_prompt="你是智能助手",
    skills="*",  # 根据用户输入自动匹配
))
```

### 8. 条件路由

```python
workflow.add_router(
    after="classify",
    routes={
        "question": "handle_question",
        "complaint": "handle_complaint",
        "default": "__end__"
    },
    condition="result.intent"  # 支持嵌套字段
)
```

### 9. 节点间数据传递

```python
workflow.add_node(LLMNode(
    id="analyze",
    system_prompt="分析：{user_input}",  # 自动从 state 读取
    output_key="analysis"                 # 自动写入 state
))

workflow.add_node(LLMNode(
    id="summarize",
    system_prompt="基于分析结果({analysis})生成摘要"
))
```

> ⚠️ **变量转义**：`{variable}` 会被识别为变量并替换。如果需要输出字面量的花括号（如 JSON 格式示例），请使用双花括号 `{{}}` 进行转义：
> ```python
> system_prompt="""返回 JSON 格式：
> {{"intent": "question" | "complaint"}}"""  # {{}} 会被渲染为 {}
> ```

---

## 完整示例：多轮对话

```python
from agentclaw import Workflow, LLMNode, HumanNode, output


def create_chat_workflow() -> Workflow:
    workflow = Workflow(id="chat", name="多轮对话")
    
    # 1. 开场白
    @workflow.node("greeting")
    async def greeting(state):
        await output("你好！我是你的助手，有什么可以帮你的？", save_to_context=True)
        return {}
    
    # 2. 等待用户输入
    workflow.add_node(HumanNode(
        id="await_input",
        feedback_field="user_input",
    ))
    
    # 3. LLM 回复
    workflow.add_node(LLMNode(
        id="reply",
        system_prompt="你是一个友好的助手",
        use_context=True,
        stream=True,
    ))
    
    # 边配置
    workflow.add_edge("greeting", "await_input")
    workflow.add_edge("await_input", "reply")
    workflow.add_edge("reply", "await_input")  # 循环
    
    return workflow
```

---

## 关键配置速查

### LLMNode

| 配置 | 默认值 | 说明 |
|-----|-------|------|
| `use_context` | `True` | 加载对话历史 |
| `save_to_context` | `True` | 保存对话到历史 |
| `max_context_messages` | `None` | 最大历史消息数（默认继承 `MAX_CONTEXT_MESSAGES`） |
| `stream` | `False` | 是否开启流式输出 |
| `output_key` | 节点 ID | 输出存储键 |
| `output_format` | `"text"` | `text` / `json` |
| `tools` | `None` | 工具名称列表 |
| `skills` | `None` | 技能列表或 `"*"` 自动匹配 |
| `max_tool_rounds` | `None` | 最大工具调用轮数（默认继承 `MAX_TOOL_ROUNDS`） |

### HumanNode

| 配置 | 默认值 | 说明 |
|-----|-------|------|
| `feedback_field` | `"feedback"` | 等待用户提供的字段 |
| `save_to_context` | `True` | 保存用户输入到对话历史 |

### output() 函数

```python
from agentclaw import output
from agentclaw.utils.stream import fake_stream

await output("处理完成！")                              # 不保存到上下文
await output("你好！", save_to_context=True)            # 保存到上下文
await output(fake_stream("流式输出内容"), stream=True)  # 模拟流式输出
```

---

## 服务部署

```python
# server.py
import agents  # 导入 agents 模块，自动注册所有工作流

from agentclaw import AgentClawServer

server = AgentClawServer()
server.run()
```

或使用 CLI：

```bash
agentclaw serve
```

框架自动处理：
- Admin Token 自动生成
- 认证中间件自动注册
- Admin Dashboard 自动启用

### 生产环境

```bash
# .env
ADMIN_TOKEN=your-secure-token
WORKFLOW_API_KEY=sk-your-workflow-key
```

生产环境安全建议：

- 固定配置 `ADMIN_TOKEN` 和 `WORKFLOW_API_KEY`，不要依赖每次启动自动生成。
- `WORKFLOW_API_KEY` 只用于工作流执行，不是 Admin Token；调度器、渠道推送、文件列表和 Dashboard 管理接口仍只给 `ADMIN_TOKEN`。
- 对外分享 Agent 时，在工作流配置里显式开启「公开发布」，并设置合适的 `rate_limit`、`public_conversation_limit`、`public_message_limit`；默认保持关闭。
- 内置智能体不能公开分享，避免把内部能力暴露给匿名用户。
- 浏览器里展示上传文件或 Markdown 图片时使用短期签名 URL，不要把裸 `/api/files/{id}` 当永久公开链接。
- 公网反向代理场景只有在代理会清理伪造的 `X-Forwarded-*` 头时，才开启 `AGENTCLAW_TRUST_PROXY_HEADERS=1`。

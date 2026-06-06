# 快速开始

## 安装

安装 PyPI 包：

```bash
pip install agentclaw-ai
```

如果你使用 `uv`，可以安装同一个包：

```bash
uv pip install agentclaw-ai
```

默认安装已经包含 Redis、调度、文档解析、知识库、渠道、浏览器工具和
Windows 桌面辅助等运行依赖。浏览器自动化如果本机没有可用的
Chrome/Chromium/Edge，仍可能需要额外执行 `playwright install chromium`。

## 初始化项目

```bash
agentclaw init myproject
cd myproject
```

`agentclaw init` 会直接生成一套可运行的项目骨架：

- `.env`：面向用户的统一运行配置清单，按模块说明服务、鉴权、PG/Redis、工作流、调度、MCP 等配置项
- `models.json`：模型配置文件
- `agents/hello_world.py`：默认示例工作流
- `server.py`：服务入口

建议继续做两步：

```bash
# 1. 在 models.json 中填写模型连接信息，按需调整 .env 运行配置
# 2. 启动项目并打开 Dashboard
agentclaw up
```

如果你只想快速试跑，不接 PostgreSQL / Redis 也可以直接继续，服务会以内存模式启动。

## 第一个工作流

### 方式一：直接运行 `init` 生成的示例

```python
from agentclaw import Input, LLMNode, Workflow

workflow = Workflow(
    id="hello_world",
    name="Hello World",
    description="一个简单的问候工作流",
    inputs=[
        Input("user_input", str, required=True, description="请输入想让助手回答的内容"),
    ],
    user_input="user_input",
)

workflow.add_node(LLMNode(
    id="chat",
    system_prompt="你是一个友好的助手，用简洁的语言回答问题。",
    enable_memory=True,
    output_to_user=True,
))

workflow.publish()
```

启动服务后在 Dashboard 中运行：

```bash
agentclaw up
```

然后打开 `http://localhost:8000`，在前端调用默认生成的 `hello_world` 工作流。

### 方式二：手写一个工作流

```python
from agentclaw import Workflow, WorkflowContext

workflow = Workflow(id="calculator", name="计算器")

@workflow.node("parse_expression")
async def parse_expression(state: dict, context: WorkflowContext) -> dict:
    """解析数学表达式"""
    expression = state.get("user_input", "")
    # 简单解析逻辑
    return {"expression": expression, "parsed": True}

@workflow.node("calculate")
async def calculate(state: dict) -> dict:
    """执行计算"""
    try:
        result = eval(state["expression"])  # 仅示例，生产环境请使用安全的解析器
        return {"result": result}
    except Exception as e:
        return {"error": str(e)}

# 执行
async def main():
    result = await workflow.run({"user_input": "2 + 3 * 4"})
    print(f"结果: {result['state']['result']}")  # 结果: 14
```

## 条件路由

```python
from agentclaw import Workflow, LLMNode

workflow = Workflow(id="router_demo", name="路由示例")

# 分类节点
workflow.add_node(LLMNode(
    id="classify",
    system_prompt="分类用户意图，返回 JSON: {{\"intent\": \"question\" | \"complaint\" | \"other\"}}",
    output_format="json",
    output_key="classification"
))

# 根据分类结果路由
workflow.add_router(
    after="classify",
    routes={
        "question": "answer_question",
        "complaint": "handle_complaint",
        "default": "__end__"
    },
    condition=lambda s: s.get("classification", {}).get("intent", "other")
)

# 处理节点
workflow.add_node(LLMNode(id="answer_question", system_prompt="回答用户问题"))
workflow.add_node(LLMNode(id="handle_complaint", system_prompt="处理用户投诉"))
```

## 发布为 API

```python
# server.py
import agents  # noqa: F401

from agentclaw import AgentClawServer

if __name__ == "__main__":
    server = AgentClawServer()
    server.run()
```

访问 API：

```bash
agentclaw serve

# 流式
curl -X POST http://localhost:8000/api/workflow/run \
  -H "Authorization: Bearer <WORKFLOW_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_id": "hello_world",
    "response_mode": "streaming",
    "inputs": {"user_input": "你好"}
  }'

# 非流式
curl -X POST http://localhost:8000/api/workflow/run \
  -H "Authorization: Bearer <WORKFLOW_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_id": "hello_world",
    "response_mode": "blocking",
    "inputs": {"user_input": "你好"}
  }'
```

认证说明：

- `/api/workflow/run` 是带 Bearer 鉴权的工作流执行接口，可使用全局 `WORKFLOW_API_KEY`、`ADMIN_TOKEN`，或在该工作流开启 **发布 API** 后使用其独立 `workflow_api_key`。
- Workflow API Key 只用于执行工作流、上传会话附件等最小能力；调度器、渠道推送、文件列表、Dashboard 管理 API 仍需要 `ADMIN_TOKEN`。
- 匿名访问的 Public Agent 不使用 `WORKFLOW_API_KEY`，需要在 Dashboard 的工作流配置中显式开启公开发布，然后使用带 `share_token` 的 `/dashboard/agent/{workflow_id}` 链接。

兼容性说明：

- 推荐使用 `response_mode` 与 `inputs`
- 当前版本仍兼容 `mode` 与 `input_data`，但新文档统一使用新字段
- 统一执行端点为 `/api/workflow/run`

## 下一步

- [用户指南](./user_guide.md) - 完整使用教程
- [API 参考](./api_reference.md) - 完整 API 文档
- [最佳实践](./best_practices.md) - 推荐使用模式

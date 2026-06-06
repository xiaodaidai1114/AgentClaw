# Quick Start

## Installation

Install the PyPI package:

```bash
pip install agentclaw-ai
```

If you use `uv`, install the same package with:

```bash
uv pip install agentclaw-ai
```

The default install includes AgentClaw runtime integrations such as Redis,
scheduler, document parsing, knowledge bases, channels, browser tooling, and
Windows desktop helpers. Browser automation may still require
`playwright install chromium` if no compatible Chrome/Chromium/Edge executable
is available locally.

## Initialize a Project

```bash
agentclaw init myproject
cd myproject
```

`agentclaw init` now generates a runnable starter project for you:

- `.env` as the user-facing runtime configuration reference for server, auth, PG/Redis, workflow, scheduler, MCP, and related settings
- `models.json` for model configuration
- `agents/hello_world.py` as the default workflow
- `server.py` as the service entrypoint

Recommended next steps:

```bash
# 1. Put model connection details in models.json and adjust runtime settings in .env as needed
# 2. Start the project and open the dashboard
agentclaw up
```

You can also continue without PostgreSQL or Redis for a quick local run. AgentClaw will fall back to in-memory mode.

## Your First Workflow

### Method 1: Run the Generated `hello_world`

```python
from agentclaw import Input, LLMNode, Workflow

workflow = Workflow(
    id="hello_world",
    name="Hello World",
    description="A simple greeting workflow",
    inputs=[
        Input("user_input", str, required=True, description="What the assistant should answer"),
    ],
    user_input="user_input",
)

workflow.add_node(LLMNode(
    id="chat",
    system_prompt="You are a friendly assistant. Reply clearly and briefly.",
    enable_memory=True,
    output_to_user=True,
))

workflow.publish()
```

Start the service and run it from the Dashboard:

```bash
agentclaw up
```

Then open `http://localhost:8000` and use the generated `hello_world` workflow from the frontend.

### Method 2: Write a Workflow by Hand

```python
from agentclaw import Workflow, WorkflowContext

workflow = Workflow(id="calculator", name="Calculator")

@workflow.node("parse_expression")
async def parse_expression(state: dict, context: WorkflowContext) -> dict:
    """Parse math expression"""
    expression = state.get("user_input", "")
    return {"expression": expression, "parsed": True}

@workflow.node("calculate")
async def calculate(state: dict) -> dict:
    """Execute calculation"""
    try:
        result = eval(state["expression"])  # Example only, use safe parser in production
        return {"result": result}
    except Exception as e:
        return {"error": str(e)}

# Run
async def main():
    result = await workflow.run({"user_input": "2 + 3 * 4"})
    print(f"Result: {result['state']['result']}")  # Result: 14
```

## Conditional Routing

```python
from agentclaw import Workflow, LLMNode

workflow = Workflow(id="router_demo", name="Router Demo")

# Classification node
workflow.add_node(LLMNode(
    id="classify",
    system_prompt='Classify user intent, return JSON: {"intent": "question" | "complaint" | "other"}',
    output_format="json",
    output_key="classification"
))

# Route based on classification
workflow.add_router(
    after="classify",
    routes={
        "question": "answer_question",
        "complaint": "handle_complaint",
        "default": "__end__"
    },
    condition=lambda s: s.get("classification", {}).get("intent", "other")
)

# Handler nodes
workflow.add_node(LLMNode(id="answer_question", system_prompt="Answer the user's question"))
workflow.add_node(LLMNode(id="handle_complaint", system_prompt="Handle the user's complaint"))
```

## Deploy as API

```python
# server.py
import agents  # noqa: F401

from agentclaw import AgentClawServer

if __name__ == "__main__":
    server = AgentClawServer()
    server.run()
```

API calls:

```bash
agentclaw serve

# Streaming
curl -X POST http://localhost:8000/api/workflow/run \
  -H "Authorization: Bearer <WORKFLOW_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_id": "hello_world",
    "response_mode": "streaming",
    "inputs": {"user_input": "Hello"}
  }'

# Non-streaming
curl -X POST http://localhost:8000/api/workflow/run \
  -H "Authorization: Bearer <WORKFLOW_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_id": "hello_world",
    "response_mode": "blocking",
    "inputs": {"user_input": "Hello"}
  }'
```

Authentication notes:

- `/api/workflow/run` is an authenticated workflow execution endpoint. Use the global `WORKFLOW_API_KEY`, `ADMIN_TOKEN`, or a workflow-specific `workflow_api_key` after that workflow has **Publish API** enabled.
- A Workflow API Key only grants the minimal workflow execution and chat-attachment capabilities. Scheduler management, channel push, file listing, and Dashboard management APIs still require `ADMIN_TOKEN`.
- Anonymous Public Agent access does not use `WORKFLOW_API_KEY`. Enable public publishing explicitly in the Dashboard workflow configuration, then share the `/dashboard/agent/{workflow_id}?share_token=...` link.

Compatibility notes:

- Prefer `response_mode` together with `inputs`
- The current version still accepts `mode` and `input_data`, but the new docs use the newer fields consistently
- The unified execution endpoint is `/api/workflow/run`

## Next Steps

- [User Guide](./user_guide.md) - Complete tutorial
- [API Reference](./api_reference.md) - Full API documentation
- [Best Practices](./best_practices.md) - Recommended usage patterns

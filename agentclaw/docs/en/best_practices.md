# AgentClaw Best Practices

> Use declarative configuration, let the framework handle complexity

---

## Core Principles

1. **Declarative First**: Use `LLMNode`, `HumanNode` and other declarative nodes
2. **Auto Management**: Sessions, message history, state persistence are auto-managed
3. **Convention over Configuration**: Sensible defaults, minimal required config

---

## Reserved Fields

The framework uses these reserved fields (prefixed with `__`):

| Field | Description |
|-------|-------------|
| `__messages__` | Conversation history |
| `__interrupted__` | Interrupt flag |
| `__status__` | Status |

> ⚠️ User-defined state fields should not use `__` prefix.

---

## Best Practices by Scenario

### 1. Simple LLM Call

```python
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="You are a friendly assistant"
))
```

### 2. Multi-turn Conversation

```python
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="You are a friendly assistant",
    use_context=True,           # Auto-load conversation history (default)
    max_context_messages=20     # Limit history count
))

# Use thread_id for cross-request sessions
result = await workflow.run(
    {"user_input": "Hello"},
    thread_id="session_001"     # State auto-persisted
)
```

### 3. Output Fixed Content (Greetings, etc.)

```python
from agentclaw import output

@workflow.node("greeting")
async def greeting(state):
    # Temporary message (not saved to context)
    await output("Processing, please wait...")
    return {}

@workflow.node("opening")
async def opening(state):
    # Opening message (saved to context)
    opening = "Hello! I'm your assistant. How can I help?"
    await output(opening, save_to_context=True)
    return {}
```

### 4. Streaming Output

```python
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="You are an assistant",
    stream=True  # Explicitly enable streaming
))
```

### 5. Human-in-Loop

```python
# Chat scenario: save user input to history
workflow.add_node(HumanNode(
    id="await_input",
    feedback_field="user_input",
    save_to_context=True,  # Default
))

# Approval scenario: don't save to history
workflow.add_node(HumanNode(
    id="approval",
    feedback_field="approved",
    save_to_context=False,
))
```

### 6. Tool Calling

```python
from agentclaw import ToolKit

toolkit = ToolKit()

@toolkit.tool
async def search_database(query: str, limit: int = 10) -> str:
    """
    Search the database
    
    Args:
        query: Search keywords
        limit: Result limit
    """
    return await db.search(query, limit)

workflow.use(toolkit)

workflow.add_node(LLMNode(
    id="agent",
    system_prompt="You are an intelligent assistant with tools",
    tools=["search_database"],
    tool_choice="auto",
    max_tool_rounds=5,
))
```

### 7. Skills

```python
# Specify skill list
workflow.add_node(LLMNode(
    id="agent",
    system_prompt="You are an intelligent assistant",
    skills=["pdf", "webapp-testing"],
))

# Auto-match relevant skills (recommended)
workflow.add_node(LLMNode(
    id="agent",
    system_prompt="You are an intelligent assistant",
    skills="*",  # Auto-match based on user input
))
```

### 8. Conditional Routing

```python
workflow.add_router(
    after="classify",
    routes={
        "question": "handle_question",
        "complaint": "handle_complaint",
        "default": "__end__"
    },
    condition="result.intent"  # Supports nested fields
)
```

### 9. Data Passing Between Nodes

```python
workflow.add_node(LLMNode(
    id="analyze",
    system_prompt="Analyze: {user_input}",  # Auto-read from state
    output_key="analysis"                    # Auto-write to state
))

workflow.add_node(LLMNode(
    id="summarize",
    system_prompt="Based on analysis ({analysis}), generate summary"
))
```

> ⚠️ **Variable Escaping**: `{variable}` is recognized as a variable and replaced. To output literal braces (e.g., JSON format examples), use double braces `{{}}` to escape:
> ```python
> system_prompt="""Return JSON format:
> {{"intent": "question" | "complaint"}}"""  # {{}} renders as {}
> ```

---

## Complete Example: Multi-turn Chat

```python
from agentclaw import Workflow, LLMNode, HumanNode, output


def create_chat_workflow() -> Workflow:
    workflow = Workflow(id="chat", name="Multi-turn Chat")
    
    # 1. Greeting
    @workflow.node("greeting")
    async def greeting(state):
        await output("Hello! I'm your assistant. How can I help?", save_to_context=True)
        return {}
    
    # 2. Wait for user input
    workflow.add_node(HumanNode(
        id="await_input",
        feedback_field="user_input",
    ))
    
    # 3. LLM reply
    workflow.add_node(LLMNode(
        id="reply",
        system_prompt="You are a friendly assistant",
        use_context=True,
        stream=True,
    ))
    
    # Edges
    workflow.add_edge("greeting", "await_input")
    workflow.add_edge("await_input", "reply")
    workflow.add_edge("reply", "await_input")  # Loop
    
    return workflow
```

---

## Quick Reference

### LLMNode

| Config | Default | Description |
|--------|---------|-------------|
| `use_context` | `True` | Load conversation history |
| `save_to_context` | `True` | Save conversation to history |
| `max_context_messages` | `None` | Max history messages (inherits `MAX_CONTEXT_MESSAGES` by default) |
| `stream` | `False` | Whether to enable streaming output |
| `output_key` | node ID | Output storage key |
| `output_format` | `"text"` | `text` / `json` |
| `tools` | `None` | Tool name list |
| `skills` | `None` | Skill list or `"*"` for auto-match |
| `max_tool_rounds` | `None` | Max tool call rounds (inherits `MAX_TOOL_ROUNDS` by default) |

### HumanNode

| Config | Default | Description |
|--------|---------|-------------|
| `feedback_field` | `"feedback"` | Field to wait for |
| `save_to_context` | `True` | Save user input to history |

### output() Function

```python
from agentclaw import output
from agentclaw.utils.stream import fake_stream

await output("Done!")                                   # Not saved to context
await output("Hello!", save_to_context=True)            # Saved to context
await output(fake_stream("Streaming content"), stream=True)  # Simulated streaming
```

---

## Deployment

```python
# server.py
import agents  # Import agents module to auto-register all workflows

from agentclaw import AgentClawServer

server = AgentClawServer()
server.run()
```

Or use CLI:

```bash
agentclaw serve
```

Auto-handled:
- Admin Token auto-generated
- Auth middleware auto-registered
- Admin Dashboard auto-enabled

### Production

```bash
# .env
ADMIN_TOKEN=your-secure-token
WORKFLOW_API_KEY=sk-your-workflow-key
```

Production security recommendations:

- Set stable `ADMIN_TOKEN` and `WORKFLOW_API_KEY` values instead of relying on startup-generated secrets.
- `WORKFLOW_API_KEY` is a global workflow-execution key that can execute all workflows; it is not an Admin Token. Workflow-specific keys are accepted only when that workflow has Publish API enabled. Scheduler, channel push, file listing, and Dashboard management APIs still require `ADMIN_TOKEN`.
- When sharing an Agent publicly, enable "Public publishing" explicitly in workflow configuration and set appropriate `rate_limit`, `public_conversation_limit`, and `public_message_limit`; leave it off by default.
- Built-in agents cannot be publicly shared, which avoids exposing internal capabilities to anonymous users.
- Use short-lived signed URLs for browser-rendered uploads or Markdown images. Do not treat bare `/api/files/{id}` as a permanent public link.
- In public reverse-proxy deployments, enable `AGENTCLAW_TRUST_PROXY_HEADERS=1` only when the proxy strips spoofed `X-Forwarded-*` headers.

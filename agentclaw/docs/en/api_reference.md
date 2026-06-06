# AgentClaw API Reference

> User-facing API documentation for v1.0.0
>
> Note: this document is for end users and integrators. It only covers public `/api/...` and `/admin/...` endpoints. `/_internal/...` routes are internal relay paths and are not part of the external API surface.
>
> Internal agent/shell calls use the independent local internal relay. After startup, read `internal_url` from `.agentclaw/relay.json` in the project directory and call `{internal_url}/_internal` + the `/api/...` or `/admin/...` path documented below. The relay injects authentication server-side, so the caller sends only the business payload; public integrations still use the public paths below with their required Bearer authentication.

---

## Table of Contents

1. [Core Classes](#core-classes)
2. [Node Types](#node-types)
3. [Components](#components)
4. [Input Definition](#input-definition)
5. [Server](#server)
6. [Platform Management API Overview](#platform-management-api-overview)
7. [Scheduler API](#scheduler-api)
8. [Exceptions](#exceptions)

---

## Core Classes

### Workflow

Core class for workflow definition and execution.

```python
from agentclaw import Workflow
```

#### Constructor

```python
Workflow(
    id: str,                    # Unique identifier
    name: str,                  # Display name
    version: str = "1.0.0",     # Version
    description: str = "",      # Description
    timeout: int = 300,         # Timeout (seconds)
    inputs: Any = None,         # Input parameter definition
    user_input: str = None,     # User message field name (must exist in inputs and be string type)
    auth_required: bool = False,      # Reserved; does not change auth behavior in personal edition
    allowed_roles: list[str] = None,  # Reserved; no role checks in personal edition
    rate_limit: str = None,           # Public Agent anonymous rate limit, e.g. "10/min"
    public_share_enabled: bool = False,   # Enable anonymous public publishing; off by default
    public_share_token: str = None,       # Public share token, generated when publishing is enabled
    api_published: bool = True,           # Accept this workflow's API key on /api/workflow/run
    workflow_api_key: str = None,         # Workflow-specific execution key
    safe_guard_apply_api: bool = False,   # Check user input before API runs
    safe_guard_apply_public: bool = True, # Check user input on public agents/rooms
    public_conversation_limit: int = 20,  # Public Agent conversation quota per client
    public_message_limit: int = 200,      # Public Agent message quota per conversation update
    inject_as_agentic_capability: bool = True,  # Inject into built-in agent capability catalog
    tracing: bool = True,       # Enable tracing
    publish_as_mcp: bool = False,   # Publish as MCP Server
)
```

> `auth_required` and `allowed_roles` are reserved for a future multi-user/team edition. The current personal edition does not allow or deny requests based on them. For public deployments, use `ADMIN_TOKEN`, Workflow API Keys, and the Public Agent publishing switch.

#### Key Methods

| Method | Description |
|--------|-------------|
| `add_node(node)` | Add a node |
| `add_edge(from, to)` | Add an edge |
| `add_router(after, routes, condition)` | Add conditional routing |
| `add_conditional_edge(source, condition, targets)` | Add conditional edge |
| `use(component)` | Register component |
| `run(inputs, stream, thread_id)` | Execute workflow |
| `publish()` | Publish as API endpoint |
| `get_node(name)` | Get specific node |

#### run() Method

```python
result = await workflow.run(
    inputs={"user_input": "Hello"},
    stream=False,
    thread_id="session_001",
)

# Return value
{
    "outputs": [...],
    "state": {"node_id": "result"},
    "metadata": {"duration_ms": 1234}
}
```

---

## Node Types

### LLMNode

LLM call node.

```python
from agentclaw import LLMNode
```

#### Constructor

```python
LLMNode(
    id: str,                            # Node name
    system_prompt: str = None,          # System prompt
    user_prompt: str = None,            # User message template
    output_key: str = None,             # Output key in state
    output_format: str = "text",        # "text" or "json"
    output_to_user: bool = False,       # Stream to user
    model_id: str = None,               # Specific model ID
    model_params: dict = None,          # Model parameter overrides
    stream: bool = False,               # Streaming output
    tools: List[str] = None,            # Tool names to enable
    tool_choice: str = "auto",          # auto / required / none
    max_tool_rounds: int = None,        # Max tool call rounds
    skills: Union[List[str], str] = None,  # Skill list or "*"
    enable_builtin_skills: bool = False,   # Enable built-in skills (e.g. agent_creator)
    enable_builtin_tools: bool = False, # Enable built-in tools (includes planning tools)
    agent_style: str = "default",       # default / agentic
    use_context: bool = True,           # Use conversation history
    save_to_context: bool = True,       # Save to history
    max_context_messages: int = None,   # Max history messages
    enable_compression: bool = True,    # Enable context compression
    compression_threshold: int = 100000, # Compression threshold (token count)
    compression_model: str = None,      # Compression model
    images_key: str = "",               # Image key in state
    inject_files: bool = None,          # Inject __files__ into the prompt
    enable_memory: bool = False,        # Inject current workflow memory.md
    fallback_model_id: str = None,      # Node-level fallback model
    auto_fallback: bool = None,         # Node-level auto fallback
    fallback_threshold: int = None,     # Node-level failure threshold
)
```

#### Example

```python
# Basic node
LLMNode(id="chat", system_prompt="You are a friendly assistant")

# JSON output
LLMNode(
    id="classify",
    system_prompt='Classify intent and return: {"intent": "..."}',
    output_format="json"
)

# Tool-enabled node
LLMNode(
    id="agent",
    system_prompt="You can search and calculate",
    tools=["search", "calculate"]
)

# Skill-enabled node
LLMNode(
    id="doc_agent",
    system_prompt="You are a document assistant",
    skills=["pdf", "text-utils"]
)

# Auto-matched skills
LLMNode(
    id="smart_agent",
    system_prompt="You are a smart assistant",
    skills="*"
)
```

---

### HumanNode

Human-in-the-loop node.

```python
from agentclaw import HumanNode
```

#### Constructor

```python
HumanNode(
    id: str,
    feedback_field: str = "feedback",
    interrupt: bool = True,
    save_to_context: bool = True,
)
```

#### Example

```python
workflow.add_node(HumanNode(
    id="approval",
    feedback_field="approved"
))

# First run: pause at the approval node
result = await workflow.run({"content": "..."}, thread_id="s1")

# Resume after approval
result = await workflow.run({"approved": True}, thread_id="s1")
```

---

### CustomNode

Custom node base class.

```python
from agentclaw import CustomNode
```

#### Constructor

```python
CustomNode(
    id: str,
    output_key: str = None,
    output_to_user: bool = True,
    on_error: ErrorStrategy = ErrorStrategy.ABORT,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    fallback_value: Any = None,
)
```

#### Usage

```python
class MyNode(CustomNode):
    def __init__(self, id, prefix="", **kwargs):
        super().__init__(id, **kwargs)
        self.prefix = prefix

    def process(self, text):
        return {"result": self.prefix + text}
```

---

### @node Decorator

Function node decorator.

```python
from agentclaw import node

@node("upper")
def to_upper(text):
    return {"upper_text": text.upper()}

workflow.add_node(to_upper)
```

---

### ParallelGroup

Parallel execution group.

```python
from agentclaw import ParallelGroup
```

#### Constructor

```python
ParallelGroup(
    id: str,
    nodes: List[BaseNode],
    merge_strategy: str = "dict",  # dict / list / first / custom
    merge_func: Callable = None,
    timeout: int = None,
    on_partial_failure: str = "continue",
)
```

#### Example

```python
workflow.add_node(ParallelGroup(
    id="analysis",
    nodes=[
        LLMNode(id="sales", system_prompt="Analyze sales data"),
        LLMNode(id="risk", system_prompt="Analyze risk"),
    ],
    merge_strategy="dict"
))
# Results: state["sales"], state["risk"]
```

---

### MCPNode

MCP tool direct call node.

```python
from agentclaw import MCPNode
```

#### Constructor

```python
MCPNode(
    id: str,
    server: str,           # MCP Server name
    tool: str,             # Tool name
    output: str,           # Output parameter name
    arguments: dict = None,  # Tool arguments with {key} templates
    input_mapping: dict = None,
    output_to_user: bool = True,
)
```

#### Example

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

MCP pipeline node that executes multiple tools in sequence.

```python
from agentclaw import MCPPipelineNode

workflow.add_node(MCPPipelineNode(
    id="train_query",
    steps=[
        {"server": "12306", "tool": "get-current-date", "output": "query_date"},
        {"server": "12306", "tool": "get-tickets", "arguments": {"date": "{query_date}"}, "output": "tickets"},
    ],
))
```

---

### DocumentNode

Document parsing node.

```python
from agentclaw import DocumentNode
```

#### Constructor

```python
DocumentNode(
    id: str,
    input_key: str = "document",
    output_key: str = None,
    include_metadata: bool = False,
    max_length: int = 0,
)
```

---

### AgentNode

Sub-workflow node.

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

## Detailed Node Reference

### LLMNode

LLM call node.

```python
from agentclaw import LLMNode
```

#### Constructor

```python
LLMNode(
    id: str,
    system_prompt: str = None,
    user_prompt: str = None,
    output_key: str = None,
    output_format: str = "text",
    output_to_user: bool = False,
    model_id: str = None,
    model_params: dict = None,
    stream: bool = False,
    tools: List[str] = None,
    tool_choice: str = "auto",
    max_tool_rounds: int = None,
    skills: Union[List[str], str] = None,
    enable_builtin_skills: bool = False,
    enable_builtin_tools: bool = False,
    agent_style: str = "default",
    use_context: bool = True,
    save_to_context: bool = True,
    max_context_messages: int = None,
    images_key: str = "",
    fallback_model_id: str = None,
    auto_fallback: bool = None,
    fallback_threshold: int = None,
)
```

#### Example

```python
# Basic node
LLMNode(
    id="chat",
    system_prompt="You are a friendly assistant",
    output_to_user=True
)

# JSON output
LLMNode(
    id="classify",
    system_prompt='Classify intent and return: {"intent": "..."}',
    output_format="json",
    output_key="classification"
)

# With tools
LLMNode(
    id="agent",
    system_prompt="You can search and calculate",
    tools=["search", "calculate"],
    max_tool_rounds=5
)

# Auto-match skills
LLMNode(
    id="smart_agent",
    system_prompt="You are a smart assistant",
    skills="*"
)
```

---

### HumanNode

Human-in-the-loop node for approvals or input collection.

```python
from agentclaw import HumanNode
```

#### Constructor

```python
HumanNode(
    id: str,
    feedback_field: str = "feedback",
    interrupt: bool = True,
    save_to_context: bool = True,
)
```

#### Example

```python
workflow.add_node(HumanNode(
    id="approval",
    feedback_field="approved"
))

# First run: pause at approval
result = await workflow.run({"content": "..."}, thread_id="s1")

# Resume after approval
result = await workflow.run({"approved": True}, thread_id="s1")
```

---

### CustomNode

Custom node base class.

```python
from agentclaw import CustomNode
```

#### Constructor

```python
CustomNode(
    id: str,
    output_key: str = None,
    output_to_user: bool = True,
    on_error: ErrorStrategy = ErrorStrategy.ABORT,
    max_retries: int = 3,
    retry_delay: float = 1.0,
)
```

#### Example

```python
class CalcNode(CustomNode):
    def process(self, a, b):
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

### @node Decorator

Function-based node decorator.

```python
from agentclaw import node

@node("upper")
def to_upper(text):
    return {"upper_text": text.upper()}

@node("fetch")
async def fetch_data(url):
    data = await http_get(url)
    return {"data": data}

workflow.add_node(to_upper)
```

---

### ParallelGroup

Execute multiple nodes in parallel.

```python
from agentclaw import ParallelGroup
```

#### Constructor

```python
ParallelGroup(
    id: str,
    nodes: List[BaseNode],
    merge_strategy: str = "dict",
    merge_func: Callable = None,
    timeout: int = None,
)
```

#### Example

```python
workflow.add_node(ParallelGroup(
    id="analysis",
    nodes=[
        LLMNode(id="sales", system_prompt="Analyze sales data"),
        LLMNode(id="risk", system_prompt="Analyze risk"),
    ],
    merge_strategy="dict"
))
```

---

### MCPNode

Direct MCP tool invocation node.

```python
from agentclaw import MCPNode
```

#### Constructor

```python
MCPNode(
    id: str,
    server: str,
    tool: str,
    output: str,
    arguments: dict = None,
    input_mapping: dict = None,
    output_to_user: bool = True,
)
```

#### Example

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

MCP pipeline node for sequential tool execution.

```python
from agentclaw import MCPPipelineNode

workflow.add_node(MCPPipelineNode(
    id="train_query",
    steps=[
        {"server": "12306", "tool": "get-current-date", "output": "query_date"},
        {"server": "12306", "tool": "get-tickets", "arguments": {"date": "{query_date}"}, "output": "tickets"},
    ],
))
```

---

### DocumentNode

Document parsing node.

```python
from agentclaw import DocumentNode
```

#### Constructor

```python
DocumentNode(
    id: str,
    input_key: str = "document",
    output_key: str = None,
    include_metadata: bool = False,
    max_length: int = 0,
)
```

---

## Components

### LLMManager

Multi-model LLM manager.

```python
from agentclaw import LLMManager
```

#### Usage

```python
workflow.use(LLMManager())

# With fallback
workflow.use(LLMManager(
    default="qwen3-next",
    fallback="qwen3-32b",
    auto_fallback=True,
    fallback_threshold=3,
))
```

---

### PromptManager

Prompt template manager.

```python
from agentclaw import PromptManager
```

#### Usage

```python
pm = PromptManager()
pm.register("greeting", "Hello, {name}!")
workflow.use(pm)

LLMNode(id="greet", system_prompt="{@greeting}")
```

---

### ToolKit

Tool registration and management.

```python
from agentclaw import ToolKit
```

#### Decorator Registration

```python
toolkit = ToolKit()

@toolkit.tool
async def search(query: str) -> str:
    """Search the database"""
    return f"Results: {query}"

workflow.use(toolkit)
LLMNode(id="agent", tools=["search"])
```

---

## Input Definition

### Input

Input parameter definition.

```python
from agentclaw import Input
from agentclaw.inputs import Image, File, Audio
```

#### Constructor

```python
Input(
    name: str,
    type: Type = str,
    required: bool = False,
    default: Any = None,
    description: str = "",
    min: number = None,
    max: number = None,
    min_length: int = None,
    max_length: int = None,
    choices: List = None,
    accept: List[str] = None,  # File type constraints
    max_size: str = None,
)
```

#### Example

```python
workflow = Workflow(
    id="demo",
    inputs=[
        Input("query", str, required=True),
        Input("count", int, default=10, min=1, max=100),
        Input("mode", str, choices=["fast", "quality"]),
        Input("image", Image, description="Upload image"),
    ]
)
```

---

## Server

### AgentClawServer

HTTP server for workflow APIs.

```python
from agentclaw import AgentClawServer
```

#### Usage

```python
server = AgentClawServer(
    host="0.0.0.0",
    port=8000,
    workers=1,
    reload=False,
    enable_admin=True,
)
server.run()
```

#### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/workflows` | GET | List workflows |
| `/api/models` | GET | List public available models |
| `/api/workflow/run` | POST | Execute workflow (Workflow API Key / workflow-specific API key / Admin Token) |
| `/api/workflow/compress` | POST | Compress conversation context (Workflow API Key / Admin Token) |
| `/api/public/workflows/{workflow_id}` | GET | Get anonymous Public Agent metadata (requires public publishing and `share_token`) |
| `/api/public/workflows/{workflow_id}/session` | POST | Open a same-origin anonymous Public Agent session (requires `share_token`) |
| `/api/public/workflows/{workflow_id}/run` | POST | Anonymous Public Agent execution endpoint (same-origin public page session only) |
| `/api/confirm/{confirm_id}` | POST | Confirm or reject dangerous actions (Admin Token only) |
| `/api/download/{token}` | GET | Download temporary file generated by tools |
| `/api/upload/status` | GET | Check file upload availability |
| `/api/upload` | POST | Upload chat attachment |
| `/api/files/{file_id}` | GET | Read stored file (Admin Token or short-lived signed URL) |
| `/api/channels` | GET | List configured channels (Admin Token only) |
| `/api/channels/push` | POST | Proactively push a message to a channel (Admin Token only) |
| `/api/conversations` | POST | Create conversation (Admin Token only) |
| `/api/conversations/{workflow_id}` | GET | List conversations (Admin Token only) |
| `/api/conversations/{workflow_id}/{conversation_id}` | GET/PUT/DELETE | Get/Update/Delete conversation (Admin Token only) |
| `/api/conversations/{workflow_id}/{conversation_id}/feedback` | GET/POST | Get/Submit feedback (Admin Token only) |

##### POST /api/workflow/run

Run a workflow in blocking or streaming mode.

Requires `Authorization: Bearer <key>`. Accepted keys are:

- Global `WORKFLOW_API_KEY`
- The workflow's `workflow_api_key`, scoped to that workflow only and accepted only when that workflow has **Publish API** enabled
- `ADMIN_TOKEN`

A Workflow API Key is not an Admin Token. It cannot access scheduler management, channel push, file listing, Dashboard management, or dangerous-action confirmation.

**Request Body (recommended shape):**
```json
{
  "workflow_id": "my_workflow",
  "response_mode": "streaming",
  "conversation_id": "session_001",
  "user": "hello",
  "user_id": "user_123",
  "inputs": {
    "locale": "en-US"
  }
}
```

**Field semantics:**
- `user`: message text (string). Used for chat input and HumanNode continuation.
- `user_id`: caller identity metadata.
- `inputs`: structured workflow inputs.

**Normalization rules:**
- If workflow defines `user_input="<field>"`, top-level `user` is normalized into `inputs["<field>"]` when missing.
- If both `user` and `inputs["<field>"]` are present, they must be identical; otherwise API returns `400 INVALID_REQUEST`.
- HumanNode continuation uses the same endpoint with the same `conversation_id`; no separate public resume endpoint.

##### Anonymous Public Agent

Anonymous Public Agent access is a browser share-page flow and does not use `WORKFLOW_API_KEY`. It works only when all of the following are true:

- The workflow explicitly enables `public_share_enabled`
- The request provides the correct `share_token` as query parameter `share_token` / `token`, or in the JSON body
- The browser first opens a same-origin short-lived HttpOnly cookie through `POST /api/public/workflows/{workflow_id}/session`
- Later anonymous runs send `X-AgentClaw-Public-Session: 1` and keep same-origin `Origin` / `Referer`

Dashboard-generated share URLs look like:

```text
/dashboard/agent/my_workflow?share_token=<PUBLIC_SHARE_TOKEN>
```

Typical endpoint sequence:

```bash
# Read metadata needed by the public page
curl "http://localhost:8000/api/public/workflows/my_workflow?share_token=<PUBLIC_SHARE_TOKEN>"

# The browser public page opens a same-origin session cookie; ordinary cross-site scripts are rejected
curl -X POST "http://localhost:8000/api/public/workflows/my_workflow/session?share_token=<PUBLIC_SHARE_TOKEN>" \
  -H "Origin: http://localhost:8000" \
  -H "Referer: http://localhost:8000/dashboard/agent/my_workflow?share_token=<PUBLIC_SHARE_TOKEN>"

# Run the public workflow. A real browser automatically sends the cookie created above
curl -X POST "http://localhost:8000/api/public/workflows/my_workflow/run" \
  -H "Content-Type: application/json" \
  -H "X-AgentClaw-Public-Session: 1" \
  -d '{
    "share_token": "<PUBLIC_SHARE_TOKEN>",
    "response_mode": "streaming",
    "conversation_id": "public_session_001",
    "user": "Hello"
  }'
```

Additional Public Agent constraints:

- Built-in agents (`__builtin__` or workflows marked builtin) cannot be publicly shared.
- Anonymous runs ignore `user_id`, request-level model switching, and human confirmation settings, and reject file attachments/file inputs.
- `rate_limit` applies only to Public Agent anonymous run and public conversation APIs. Example formats: `10/min`, `100/hour`.
- `public_conversation_limit` and `public_message_limit` limit public conversation count per client and messages per conversation update.
- If you deploy behind a trusted reverse proxy that strips spoofed `X-Forwarded-*` headers, set `AGENTCLAW_TRUST_PROXY_HEADERS=1`; otherwise keep the default off.

##### GET /api/files/{file_id}

Stored files can be read in two ways:

- Admin requests use `Authorization: Bearer <ADMIN_TOKEN>`
- Browser rendering, Markdown images, or plain download links use a short-lived signed URL such as `/api/files/{file_id}?token=...`

Do not treat bare `/api/files/{file_id}` as a permanent public URL. `<img>`, Markdown images, and normal `<a>` clicks do not attach Bearer headers. Framework-generated `StoredFile.url` values use short-lived signed URLs and are safe for browser embedding.

##### POST /api/confirm/{confirm_id}

Approve or reject a dangerous operation requested by the agent.

Requires `Authorization: Bearer <ADMIN_TOKEN>`. A Workflow API Key cannot approve
dangerous actions.

**Request Body:**
```json
{
  "approved": true,
  "sudo_password": "user_password"
}
```

**Response:**
```json
{
  "success": true,
  "confirm_id": "uuid",
  "approved": true,
  "require_sudo": true,
  "sudo_received": true
}
```

Notes:
- `sudo_password` is only required when `require_sudo=true` in confirm request event
- Frontend receives `confirm_request` SSE event before calling this endpoint
- Password is session-scoped and not persisted

##### POST /api/channels/push

Send a proactive message to a configured channel instance.

Requires `Authorization: Bearer <ADMIN_TOKEN>`.

**Request Body:**
```json
{
  "channel": "feishu_sales",
  "user_id": "ou_xxx",
  "chat_id": "",
  "content": "Hello, this is a proactive push message."
}
```

**Field semantics:**
- `channel`: channel instance name; channel type names are also accepted for backward compatibility.
- `content`: message text to send.
- `user_id` / `chat_id`: provide at least one target.

**Success Response:**
```json
{
  "status": "sent"
}
```

---

## Platform Management API Overview

Except for a few endpoints such as auth verification, `/admin/...` routes typically require `Authorization: Bearer <ADMIN_TOKEN>`.

If you only need authenticated workflow execution and chat-attachment upload, use `/api/workflow/run`, `/api/upload`, and related endpoints above. Conversation management, proactive channel push, file listing, scheduler, knowledge base, prompt, model, and trace management require `ADMIN_TOKEN` or `/admin/...` APIs. Anonymous Public Agent access is intended for the generated share page, not as a general backend integration API.

| Area | Common endpoints | Purpose |
|------|------------------|---------|
| Workflow management | `GET /admin/workflows`, `GET /admin/workflows/{workflow_id}`, `POST /admin/workflows/register-file` | View workflow list/details and hot-register workflow files at runtime |
| Task management | `GET /admin/tasks`, `POST /admin/tasks/{task_id}/cancel`, `DELETE /admin/tasks/cleanup` | Inspect running tasks, cancel tasks, clean up finished tasks |
| Knowledge bases | `GET/POST /admin/knowledgebases`, `POST /admin/knowledgebases/{id}/documents/upload`, `POST /admin/knowledgebases/{id}/search` | Manage knowledge bases, upload documents, run retrieval |
| Channel management | `GET/POST /admin/channels`, `POST /admin/channels/probe`, `POST /admin/channels/{channel_id}/restart`, `GET /admin/channels/logs` | Create channels, validate credentials, restart channels, inspect message logs |
| Traces and monitoring | `GET /admin/traces/summary`, `GET /admin/traces`, `GET /admin/traces/{trace_id}`, `GET /admin/traces/{trace_id}/timeline` | View execution summaries, trace details, and timelines |
| Prompts and models | `GET /admin/prompts/{workflow_id}`, `PUT /admin/prompts/{workflow_id}/{prompt_key}`, `GET /admin/models`, `PUT /admin/models/{model_id}` | Hot-update prompts and inspect or modify model settings |
| System and node settings | `GET/PUT /admin/settings/global`, `GET/PUT /admin/settings/workflows/{workflow_id}`, `GET/PUT /admin/settings/workflows/{workflow_id}/nodes/{node_id}` | Manage global, workflow-level, and node-level settings |

Additional notes:

- Channel webhook callbacks are usually configured against `/api/channels/{channel_name}/webhook`
- `/api/channels/push` is for proactive sending, while `/admin/channels/...` is for channel configuration and troubleshooting
- When you use the admin dashboard to manage knowledge bases, prompts, models, traces, or workflow settings, it is backed by these `/admin/...` APIs

---

## Scheduler API

Scheduler API is mounted at `/api/scheduler/` and requires `Authorization: Bearer <ADMIN_TOKEN>` authentication.

### Endpoints

| Endpoint | Method | Description |
| -------- | ------ | ----------- |
| `/api/scheduler/jobs` | GET | List jobs (supports `status`, `limit`, `offset` query params) |
| `/api/scheduler/jobs` | POST | Create job |
| `/api/scheduler/jobs/{id}` | GET | Get job details |
| `/api/scheduler/jobs/{id}` | PUT | Update job (partial update) |
| `/api/scheduler/jobs/{id}` | DELETE | Delete job |
| `/api/scheduler/jobs/{id}/pause` | POST | Pause job |
| `/api/scheduler/jobs/{id}/resume` | POST | Resume job |
| `/api/scheduler/jobs/{id}/trigger` | POST | Trigger manually |
| `/api/scheduler/jobs/{id}/webhook` | POST | Webhook external trigger |
| `/api/scheduler/jobs/{id}/executions` | GET | Get execution history |
| `/api/scheduler/jobs/{id}/executions/{eid}` | GET | Get execution details |

### POST /api/scheduler/jobs

Create a scheduled job.

```json
{
    "name": "Daily Report",
    "workflow_id": "report_workflow",
    "description": "Optional description",
    "trigger": {
        "type": "cron",
        "expression": "0 9 * * *",
        "timezone": "Asia/Shanghai"
    },
    "inputs": {
        "user_input": "Generate report"
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

**Trigger types:**

- `cron`: requires `expression` (cron expression), optional `timezone`
- `interval`: supports `weeks`, `days`, `hours`, `minutes`, `seconds`, optional `start_date`, `end_date`
- `date`: requires `run_date` (ISO format), optional `timezone`
- If `webhook.enabled` is `true`, `webhook.secret` is required.

**Response (201):**

```json
{
    "id": "uuid",
    "name": "Daily Report",
    "status": "enabled",
    "trigger": {"type": "cron", "expression": "0 9 * * *"},
    "next_run_at": "2026-03-18T09:00:00+08:00"
}
```

### POST /api/scheduler/jobs/{id}/webhook

Trigger job execution via Webhook.

**Headers:**

- `X-Webhook-Secret`: must match the job's configured `webhook.secret`

**Request body (optional):** When `webhook.allow_input_override = true`, request body overrides inputs.

```json
{
    "user_input": "webhook parameter"
}
```

**Response (200):**

```json
{
    "message": "Job triggered",
    "execution_id": "uuid"
}
```

**Error codes:**

- `400`: Webhook not enabled
- `403`: Secret mismatch
- `404`: Job not found

### Execution Record Model

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

## Exceptions

```python
from agentclaw import (
    AgentClawError,         # Base exception
    WorkflowCancelledError, # Workflow cancelled
    WorkflowTimeoutError,   # Timeout
    NodeExecutionError,     # Node failed
    ConfigError,            # Config error
)
```

---

*Documentation Version: 1.0.0*

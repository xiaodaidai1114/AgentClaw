# Deployment Guide

## Quick Start

```bash
uv pip install -e .[all]
agentclaw init myproject
cd myproject
# Edit the generated .env and models.json
agentclaw up            # Startup wizard: manually choose Docker or Remote mode
# or
agentclaw up --mode remote  # Skip the wizard and use Remote mode directly
```

## Three Deployment Modes

| Mode | External dependencies | Best for | Startup |
|------|------------------------|----------|---------|
| **One-command startup** | Docker | Personal development, desktop assistants, quick trials | `agentclaw up` or `start.sh` |
| **Remote database** | Existing PG/Redis | Team development, cloud databases | `agentclaw up --mode remote` |
| **Full Docker** | Docker | Remote servers, API services, secure sandboxes | `docker compose up` |

---

## Mode 1: One-command Startup

> **Docker manages the database automatically, while the Agent runs locally with full capabilities.**

`agentclaw up` opens a startup wizard where the user manually chooses Docker
mode or Remote mode. After choosing Docker mode, it first checks whether the
target directory is already an AgentClaw project. If not, it asks for a
startup/create path (relative or absolute, defaulting to the current path),
initializes the project, prompts for required runtime keys (blank values are
generated automatically), then starts PostgreSQL + Redis + Adminer in Docker and
launches the Agent service locally. Because the Agent runs on the host machine,
it can fully access local files, MCP tools, and Skills.

If the project already exists and Docker infrastructure is already running,
`agentclaw up` skips `docker compose up` and only starts the server. If Docker
infrastructure is not running, it automatically runs `docker compose up -d`.

**Option A: CLI**

```bash
agentclaw up
# 🐳 Starting infrastructure (PostgreSQL + Redis + Milvus + Adminer)...
#    ✅ PostgreSQL started (localhost:5432)
#    ✅ Redis started (localhost:6379)
#    ✅ Milvus started (localhost:19530)
#    ✅ Adminer started (localhost:8080)
# 🚀 Starting AgentClaw server...
```

```bash
agentclaw up -p 9000          # Custom AgentClaw API + Dashboard port
agentclaw up --reload         # Development mode with hot reload
```

**Option B: Shell Scripts**

```bash
# Start (project directory defaults to current directory)
./agentclaw/docker/start.sh ./myproject

# Stop
./agentclaw/docker/stop.sh
```

The scripts support custom host and port through environment variables:

```bash
FA_PORT=9000 FA_HOST=0.0.0.0 ./agentclaw/docker/start.sh
```

Docker infrastructure host ports can be changed in the project `.env` file or
the current shell environment:

```bash
PORT=9000              # AgentClaw API + Dashboard; same as agentclaw up -p 9000
PG_PORT=6003           # PostgreSQL host port
REDIS_PORT=6004        # Redis host port
MINIO_API_PORT=19000
MINIO_CONSOLE_PORT=19001
MILVUS_PORT=19531
MILVUS_HTTP_PORT=9092
ADMINER_PORT=18080
agentclaw up --mode docker
```

**If Docker is unavailable:**

```bash
agentclaw up
# ❌ Docker is unavailable, so docker mode cannot start
#    Install Docker and retry, or use: agentclaw up --mode remote
```

**Service Ports**

| Service | Port | Description |
|---------|------|-------------|
| AgentClaw | `PORT` / `-p`, default 8000 | API + Dashboard, running as a host process |
| PostgreSQL | `PG_PORT`, default 5432 | Database container mapped to the host |
| Redis | `REDIS_PORT`, default 6379 | Cache container mapped to the host |
| MinIO API | `MINIO_API_PORT`, default 9000 | Object storage API used by Milvus |
| MinIO Console | `MINIO_CONSOLE_PORT`, default 9001 | MinIO management console |
| Milvus | `MILVUS_PORT`, default 19530 | Vector database gRPC/API port |
| Milvus HTTP | `MILVUS_HTTP_PORT`, default 9091 | Milvus HTTP/metrics port |
| Adminer | `ADMINER_PORT`, default 8080 | Database management UI |

**Best for:** personal development, desktop assistants, demos, and quick full-feature experience

---

## Mode 2: Remote Database

> **Run the service locally while connecting to an existing PostgreSQL / Redis instance.**

Remote mode does not start Docker. It uses PostgreSQL / Redis from the current
`.env` file or system environment variables. Existing projects start directly.
If the target directory is not an AgentClaw project yet, it initializes the
project and asks for optional PG / Redis connection values. Leaving PG_HOST or
REDIS_HOST blank means the corresponding service is not connected.

```bash
# .env
PG_HOST=your-pg-host
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=your-password
PG_DATABASE=agentclaw

# Redis (optional, enables prompt hot reload and multi-instance sync)
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password
```

```bash
agentclaw up --mode remote
# 🚀 Starting AgentClaw server...
#    Storage: PostgreSQL (your-pg-host:5432)
#    Cache: Redis (your-redis-host:6379)
```

**Characteristics**

- The service still runs locally, with full access to host files, MCP tools, and Skills.
- Data is stored in the remote database and can be shared across instances.
- Good fit for cloud databases such as RDS, Supabase, or Neon.
- Docker is not required.

**Feature Comparison**

| Feature | PG only | PG + Redis |
|---------|:-------:|:----------:|
| All core features | ✅ | ✅ |
| Multi-instance deployment | ✅ | ✅ |
| Distributed scheduler lock | ✅ | ✅ |
| High-concurrency writes | ✅ | ✅ |
| Prompt hot reload | ❌ | ✅ |
| Multi-instance prompt sync | ❌ | ✅ |

**Best for:** team development, staging, and environments that already have database infrastructure

---

## Mode 3: Full Docker

> **Equivalent to running an independent Linux server, with the Agent operating entirely inside the container.**

AgentClaw, PostgreSQL, and Redis all run inside Docker. Every MCP tool call, Skill script execution, and file operation happens inside the container's Linux environment, not on the host machine.

```bash
cd myproject
docker compose up -d
```

**Characteristics**

- The container is the server: the Agent has a full filesystem, network access, and process capabilities inside the container.
- MCP tools and Skill scripts operate inside the container, not on the host.
- Container isolation keeps Agent actions from affecting the host, which is safer and easier to control.
- Data is persisted through Docker named volumes, so container recreation does not lose data.

**Good fit for**

- Remote server deployments managed through API / Dashboard
- Long-running scheduled jobs
- External API services and multi-tenant platforms
- Security-sensitive scenarios that require sandbox isolation

**Not a good fit for**

- Desktop assistant scenarios, because the Agent cannot access your local files or open host applications
- Development assistance that needs interaction with the host machine
- Interactive debugging workflows such as `pdb` breakpoints

**Service Ports**

| Service | Port | Description |
|---------|------|-------------|
| AgentClaw | 8000 | API + Dashboard (public) |
| PostgreSQL | - | Internal container access only |
| Redis | - | Internal container access only |

---

## Feature Dependency Matrix

### No External Dependency Required

The following features work whether or not PostgreSQL / Redis is configured:

| Feature | Description |
|---------|-------------|
| Workflow execution | Define and run workflows, orchestration, conditional routing, and parallel execution |
| LLM calls | Call model APIs such as OpenAI / Anthropic |
| MCP tools | MCP server integration over stdio / SSE |
| Skills | Skill discovery and script execution |
| Model configuration | `models.json` model management |
| Prompt (file mode) | Load prompt templates from files or memory |
| HumanNode | Human approval / input nodes |
| Admin Dashboard UI | Static admin page is accessible, though data pages are empty |
| API execution endpoint | `/api/workflow/run` workflow execution endpoint (requires Workflow API Key or Admin Token) |

### Requires PostgreSQL

Without PostgreSQL (`PG_HOST` not set), the following features are disabled or downgraded:

| Feature | Behavior without PG | Impact |
|---------|---------------------|--------|
| **Execution tracing** | Falls back to `NoopTracer` with no logs recorded | Dashboard trace pages stay empty; no historical runs or performance analysis |
| **Session persistence** | Falls back to in-memory `MemorySaver` | Multi-turn state is lost after a service restart |
| **Persistent scheduler** | Falls back to `MemoryJobStore` | Job definitions and execution history are lost after restart |
| **Scheduler distributed lock** | Falls back to `NoopLock` | Duplicate runs may occur in multi-instance deployments |
| **Conversation history** | Returns empty data | Dashboard and public agent conversations cannot be saved or restored |
| **Message feedback** | Unavailable | Users cannot like/dislike or submit feedback |
| **Prompt database mode** | Only default prompts from file / memory are available | You cannot create, edit, or roll back prompts through the Admin API |
| **Prompt version history** | Not recorded | `prompt_history` is unavailable |
| **File uploads** | Files are saved locally but metadata is not tracked | No deduplication, no retrieval by file ID, and the upload status endpoint returns `503` |
| **Dashboard metrics** | Metrics stay empty | Homepage counts, success rate, and trend charts show no data |
| **Workflow metrics** | Unavailable | Per-workflow stats and trend analysis are unavailable |
| **User memory** | Unavailable | `user_memories` cannot persist user preferences across sessions |
| **Node-level logs** | Not recorded | You cannot inspect per-node inputs, outputs, duration, or retry count |
| **LLM call logs** | Not recorded | No visibility into token usage, latency, or model selection details |

> **Affected database tables (11 total):** `workflow_logs`, `node_logs`, `llm_logs`, `prompts`, `prompt_history`, `user_memories`, `files`, `scheduled_jobs`, `job_executions`, `agent_conversations`, `message_feedback`

### Requires Redis

Without Redis (`REDIS_HOST` not set), the following features are unavailable:

| Feature | Behavior without Redis | Impact |
|---------|------------------------|--------|
| **Prompt hot reload** | Hot reload is disabled automatically | Prompt changes require a service restart |
| **Multi-instance prompt sync** | Each instance loads prompts independently | Some instances may keep using stale prompts |

> Redis has a relatively small scope here. It mainly affects prompt hot reload. In single-instance deployments where prompt changes are rare, Redis is optional.

---

## Database Tables Overview

The following 11 tables are created automatically in PostgreSQL on first connection through `CREATE TABLE IF NOT EXISTS`:

| Table | Purpose |
|-------|---------|
| `workflow_logs` | Workflow execution records (status, duration, errors) |
| `node_logs` | Node-level execution logs (inputs, outputs, duration) |
| `llm_logs` | LLM call details (tokens, latency, model) |
| `prompts` | Prompt template content |
| `prompt_history` | Prompt version history |
| `user_memories` | Long-term user memory (KV storage) |
| `files` | Uploaded file metadata (hash-based deduplication) |
| `scheduled_jobs` | Scheduled job definitions |
| `job_executions` | Scheduled execution history |
| `agent_conversations` | Agent conversation history |
| `message_feedback` | Message feedback records |

---

## Environment Variable Reference

The `.env` generated by `agentclaw init` / `agentclaw up` includes the user-facing runtime configuration reference, grouped by module and documented inline. Internal and compatibility variables remain registered in `agentclaw/env_config.py`, so runtime configuration docs do not drift across files.

**Core variables**

Configure model API keys in each model entry's `api_key` field in project `models.json`; do not put them in the default `.env`.

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 8000 | HTTP server port; explicit CLI `--port` overrides it |
| `HOST` | 0.0.0.0 | HTTP server bind address; explicit CLI `--host` overrides it |
| `PG_HOST` | Not set | PostgreSQL host; when unset, database-backed features are unavailable |
| `PG_PORT` | 5432 | PostgreSQL port |
| `PG_USER` | postgres | PostgreSQL username |
| `PG_PASSWORD` | - | PostgreSQL password |
| `PG_DATABASE` | agentclaw | Database name |
| `REDIS_HOST` | Not set | Redis host; when unset, prompt hot reload is disabled |
| `REDIS_PORT` | 6379 | Redis port |
| `ADMIN_TOKEN` | Auto-generated | Admin dashboard auth token |
| `WORKFLOW_API_KEY` | Auto-generated | Default `/api/workflow/run` execution Bearer key; no Admin permissions. Workflows can set their own `workflow_api_key` |
| `MCP_TOKEN` | Auto-generated | MCP auth token; send it as `Authorization: Bearer <MCP_TOKEN>`. If missing, AgentClaw generates one and writes it to the project `.env`; URL query tokens are disabled by default. |
| `AGENTCLAW_TRUST_PROXY_HEADERS` | false | Whether to trust reverse-proxy `X-Forwarded-*` headers. Enable only when the trusted proxy strips spoofed headers |
| `AGENTCLAW_CONTENT_SECURITY_POLICY` | Built-in policy | Override the default CSP security header; leave empty for built-in policy |
| `AGENTCLAW_DUMP_LLM_FAILURE_PAYLOAD` | false | Failed LLM request payload dump switch; off by default |
| `SCHEDULER_ENABLED` | true | Whether to enable the scheduler |
| `SCHEDULER_TIMEZONE` | Asia/Shanghai | Scheduler timezone |

---

## Public Deployment And Security Boundaries

The Dashboard can be deployed publicly, but the entry points have different access models:

| Entry point | Auth/access model | Purpose |
|-------------|-------------------|---------|
| `/admin/...` and Dashboard management pages | `ADMIN_TOKEN` | Manage workflows, scheduler, channels, knowledge bases, models, prompts, traces, and settings |
| `/api/workflow/run`, `/api/upload` | `WORKFLOW_API_KEY`, workflow-specific `workflow_api_key`, or `ADMIN_TOKEN` | Workflow execution and chat attachment upload for trusted callers |
| `/dashboard/agent/{workflow_id}?share_token=...` | Explicit workflow public publishing + `share_token` + same-origin Public Session | Anonymous Public Agent share page |

Notes:

- No workflow is publicly published by default. Enable "Public publishing" explicitly in the Dashboard workflow configuration.
- Built-in agents cannot be publicly shared.
- Workflow API Keys cannot access scheduler management, channel push, file listing, Dashboard management, or dangerous-action confirmation.
- Public Agent anonymous runs and public conversations use the workflow's `rate_limit`, `public_conversation_limit`, and `public_message_limit`.
- `/api/files/{file_id}` requires Admin Token or a short-lived signed URL. Markdown images and normal browser download links should use framework-generated signed URLs, not bare file URLs.
- The server adds security headers by default: `Content-Security-Policy`, `frame-ancestors 'none'`, `Referrer-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and related policies. Override `AGENTCLAW_CONTENT_SECURITY_POLICY` only when you intentionally need extra asset origins.
- `AGENTCLAW_DUMP_LLM_FAILURE_PAYLOAD` is off by default. Enable it only for local debugging; dumps are redacted but may still include business context.
- Public Agent same-origin checks and rate limiting do not trust `X-Forwarded-*` by default. Set `AGENTCLAW_TRUST_PROXY_HEADERS=1` only behind a trusted reverse proxy that overwrites or strips spoofed forwarded headers.

Reverse proxy recommendations:

- Serve the Dashboard and API from the same origin, for example `https://agent.example.com/dashboard` and `https://agent.example.com/api/...`.
- Strip externally supplied `X-Forwarded-For`, `X-Forwarded-Proto`, and `X-Forwarded-Host`, then set them at the proxy layer.
- Do not expose the independent local internal relay to the public internet; `/_internal/*` is not an external API.

---

## Roadmap

### SQLite Lightweight Backend

Planned support for SQLite as an alternative to PostgreSQL will provide a full-feature experience with zero external dependencies:

- No PostgreSQL, Redis, or Docker required
- All 11 tables created in SQLite with full functionality
- Automatic fallback to SQLite when PG is not configured and Docker is unavailable
- Well suited to personal development, demos, and teaching scenarios

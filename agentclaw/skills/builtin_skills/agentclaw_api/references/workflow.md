# 工作流执行、对话管理、文件上传

> 内部 agent/shell 调用使用本机 internal relay。先读取 `<project_dir>/.agentclaw/relay.json` 的 `internal_url` 作为 `{BASE_URL}`，实际 URL 为 `{BASE_URL}/_internal` + 下方文档路径。

## 工作流执行

### 列出工作流

`GET /api/workflows`

返回:
```json
{
  "workflows": [
    {"id": "my_agent", "name": "我的助手", "version": "1.0", "node_count": 3}
  ]
}
```

### 执行工作流（核心接口）

`POST /api/workflow/run`

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `workflow_id` | string | 是 | - | 要执行的工作流 ID |
| `user` | string | 否 | - | 用户文本输入，也用于 HumanNode 续传 |
| `user_id` | string | 否 | - | 调用者标识（用于追踪） |
| `response_mode` | string | 否 | `blocking` | 响应模式: `blocking`(同步) / `streaming`(SSE 流) |
| `conversation_id` | string | 否 | 自动创建 | 会话 ID，用于多轮对话。省略则创建新会话 |
| `inputs` | object | 否 | `{}` | 工作流结构化输入参数，键值对形式 |

**请求示例:**
```json
{
  "workflow_id": "my_agent",
  "user": "你好",
  "user_id": "user_001",
  "response_mode": "blocking",
  "conversation_id": "session_001",
  "inputs": {"locale": "zh-CN"}
}
```

**Blocking 响应:**
```json
{
  "event": "message",
  "task_id": "uuid",
  "message_id": "uuid",
  "conversation_id": "session_001",
  "answer": "你好！有什么可以帮你的？",
  "metadata": {
    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    "trace_id": "trace_uuid",
    "interrupted": false,
    "status": "completed"
  }
}
```

**响应字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `event` | string | 事件类型，固定 `message` |
| `task_id` | string | 任务 ID |
| `message_id` | string | 消息 ID |
| `conversation_id` | string | 会话 ID（多轮对话使用） |
| `answer` | string | 模型回复内容 |
| `metadata.usage` | object | Token 用量: `{prompt_tokens, completion_tokens, total_tokens}` |
| `metadata.trace_id` | string | 追踪 ID（可用于查询追踪详情） |
| `metadata.interrupted` | boolean | 是否被中断（HumanNode 等待输入时为 true） |
| `metadata.status` | string | 状态: `completed` / `waiting_for_input` / `error` |

### HumanNode 交互续传

当响应中 `metadata.interrupted == true` 或 `metadata.status == "waiting_for_input"` 时，表示工作流在等待人工输入。使用**相同 `conversation_id`** 再次调用 `/api/workflow/run`，通过 `user` 字段传入用户响应：

```json
{
  "workflow_id": "approval_flow",
  "response_mode": "blocking",
  "conversation_id": "session_001",
  "user": "approved"
}
```

### 确认危险操作

`POST /api/confirm/{confirm_id}`

当工作流触发需要确认的危险操作时调用。

**路径参数:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `confirm_id` | string | 确认操作 ID（从 SSE `confirm_request` 事件获取） |

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `approved` | boolean | 是 | 是否批准操作 |
| `sudo_password` | string | 否 | Sudo 密码（仅在 `require_sudo=true` 时需要） |

```json
{"approved": true}
```

### SSE 流模式事件序列

使用 `response_mode: "streaming"` 时返回 `text/event-stream`，事件按以下顺序触发：

| 顺序 | 事件类型 | 说明 |
|------|---------|------|
| 1 | `workflow_started` | 工作流开始 |
| 2 | `node_started` | 节点开始执行 |
| 3 | `message` | 文本 token 片段（流式输出） |
| 4 | `reasoning` | 模型推理内容 |
| 5 | `tool_start` / `tool` | 工具调用开始 / 工具调用结果 |
| 6 | `confirm_request` | 需要人工确认（包含 confirm_id） |
| 7 | `node_finished` | 节点执行结束 |
| 8 | `message_end` | 消息结束 |
| 9 | `workflow_finished` | 工作流结束，`data.status`: `succeeded` / `failed` / `cancelled` / `interrupted` |
| 10 | `error` | 错误事件 |

### 上下文压缩

`POST /api/workflow/compress`

压缩对话上下文，减少 Token 消耗。

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `workflow_id` | string | 是 | 工作流 ID |
| `conversation_id` | string | 是 | 会话 ID |

**响应字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 是否成功 |
| `compressed` | boolean | 是否实际执行了压缩 |
| `original_count` | int | 压缩前消息数 |
| `compressed_count` | int | 压缩后消息数 |
| `summary` | string | 压缩摘要 |

### 上下文截断（编辑重试）

`POST /api/workflow/truncate`

截断对话到指定消息位置，用于编辑重试。

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `workflow_id` | string | 是 | 工作流 ID |
| `conversation_id` | string | 是 | 会话 ID |
| `message_index` | int | 是 | 截断到的消息索引位置 |

---

## 对话管理

### 列出对话

`GET /api/conversations/{workflow_id}`

**查询参数:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `source` | string | 按来源筛选（如 `admin`） |

返回:
```json
{
  "conversations": [ConversationInfo]
}
```

**ConversationInfo 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 对话 ID |
| `workflow_id` | string | 工作流 ID |
| `title` | string | 对话标题 |
| `source` | string | 来源（`admin` / 其他） |
| `created_at` | int | 创建时间（Unix 毫秒时间戳） |
| `updated_at` | int | 更新时间（Unix 毫秒时间戳） |

### 创建对话

`POST /api/conversations`

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `workflow_id` | string | 是 | - | 工作流 ID |
| `title` | string | 否 | `New conversation` | 对话标题 |
| `source` | string | 否 | `admin` | 来源标识 |

### 获取对话详情（含消息）

`GET /api/conversations/{workflow_id}/{conversation_id}`

返回完整对话，包含所有消息。

**ConversationMessage 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `role` | string | 消息角色: `user` / `assistant` |
| `content` | string | 消息内容 |
| `timestamp` | int | Unix 毫秒时间戳 |
| `toolCalls` | ToolCallDetail[] | 工具调用详情（仅 assistant 消息） |
| `prompt_tokens` | int | 该消息的输入 Token 数 |
| `completion_tokens` | int | 该消息的输出 Token 数 |

**ToolCallDetail 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 工具调用 ID |
| `name` | string | 工具名称 |
| `arguments` | string | 工具参数（JSON 字符串） |
| `result` | string | 执行结果 |
| `status` | string | `succeeded` / `failed` / `cancelled` / `timeout` |
| `duration_ms` | float | 执行耗时(ms) |

### 更新对话

`PUT /api/conversations/{workflow_id}/{conversation_id}`

**请求参数（全部可选）:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `title` | string | 新标题 |
| `messages` | array | 消息列表（覆盖） |

### 删除对话

`DELETE /api/conversations/{workflow_id}/{conversation_id}`

### 提交消息反馈

`POST /api/conversations/{workflow_id}/{conversation_id}/feedback`

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message_index` | int | 是 | 消息在对话中的索引（从 0 开始） |
| `feedback` | string/null | 是 | `"like"` / `"dislike"` / `null`(取消反馈) |

### 获取对话反馈

`GET /api/conversations/{workflow_id}/{conversation_id}/feedback`

返回:
```json
{
  "feedbacks": {"0": "like", "3": "dislike"}
}
```

键为消息索引（字符串形式），值为反馈类型。

---

## 文件上传下载

### 检查上传能力

`GET /api/upload/status`

返回:
```json
{"available": true, "max_size": 52428800}
```

`max_size` 单位为字节（默认 50MB）。

### 上传文件

`POST /api/upload`

Content-Type: `multipart/form-data`

**表单字段:**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | 要上传的文件 |

**响应字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 文件 ID（用于后续下载） |
| `original_name` | string | 原始文件名 |
| `file_path` | string | 存储路径 |
| `mime_type` | string | MIME 类型 |
| `size` | int | 文件大小(字节) |

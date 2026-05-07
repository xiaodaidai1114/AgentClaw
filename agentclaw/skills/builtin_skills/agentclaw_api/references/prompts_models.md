# 提示词与模型管理

> 内部 agent/shell 调用使用本机 internal relay。先读取 `<project_dir>/.agentclaw/relay.json` 的 `internal_url` 作为 `{BASE_URL}`，实际 URL 为 `{BASE_URL}/_internal` + 下方文档路径。

## 提示词管理

### 列出提示词

`GET /admin/prompts/{workflow_id}`

返回:
```json
{
  "prompts": [PromptInfo]
}
```

**PromptInfo 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `workflow_id` | string | 工作流 ID |
| `prompt_key` | string | 提示词键名（如 `system_prompt`） |
| `content` | string | 当前内容 |
| `default_content` | string | 默认内容（重置时恢复到此值） |
| `is_custom` | boolean | 是否已被用户自定义修改 |
| `version` | int | 当前版本号 |
| `variables` | string[] | 内容中的变量占位符列表（如 `["name", "context"]`） |
| `created_at` | datetime | 创建时间 |
| `updated_by` | string | 最后修改者 |

### 获取单个提示词

`GET /admin/prompts/{workflow_id}/{prompt_key}`

返回: `PromptInfo`（字段同上）

### 更新提示词（热加载）

`PUT /admin/prompts/{workflow_id}/{prompt_key}`

更新后立即生效，无需重启工作流。

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `content` | string | 是 | 新的提示词内容，支持 `{variable_name}` 变量占位符 |

```json
{"content": "你是一个专业的{role}助手，请使用{language}回答问题。"}
```

### 重置为默认值

`POST /admin/prompts/{workflow_id}/{prompt_key}/reset`

将提示词恢复为代码中定义的默认内容。

### 版本历史

`GET /admin/prompts/{workflow_id}/{prompt_key}/history`

返回:
```json
{
  "history": [
    {
      "version": 3,
      "content": "提示词内容...",
      "created_at": "2026-04-08T10:00:00Z",
      "updated_by": "admin"
    }
  ]
}
```

### 回滚到指定版本

`POST /admin/prompts/{workflow_id}/{prompt_key}/rollback`

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `version` | int | 是 | 目标版本号（从历史中获取） |

```json
{"version": 3}
```

---

## 模型管理

### 列出可用模型

`GET /admin/models/available`

返回可用的模型列表（仅已配置的）:

```json
{
  "models": [
    {"id": "gpt-4o", "provider": "openai", "model": "gpt-4o", "model_type": "chat", "supports_vision": true}
  ]
}
```

### 列出所有模型（含降级状态）

`GET /admin/models`

返回:
```json
{
  "models": [ModelInfo],
  "fallback_state": FallbackState
}
```

**ModelInfo 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 模型 ID |
| `provider` | string | 提供商（openai, anthropic 等） |
| `model` | string | 模型名称 |
| `model_type` | string | 类型: `chat` / `embedding` / `rerank` |
| `supports_vision` | boolean | 是否支持视觉输入；视觉能力属于 chat 模型的能力选项 |
| `temperature` | float | 采样温度，默认 0.1 |
| `max_tokens` | int | 最大输出 Token 数，默认 8192 |
| `timeout` | int | 超时时间(秒)，默认 240 |
| `status` | string | 状态: `primary` / `fallback` / `standby` / `disabled` |
| `is_current` | boolean | 是否为当前活跃模型 |

**FallbackState 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `is_fallback` | boolean | 是否处于降级状态 |
| `fallback_reason` | string | 降级原因 |
| `fallback_until` | datetime | 降级截止时间 |
| `failure_count` | int | 连续失败次数 |
| `current_model_id` | string | 当前使用的模型 ID |
| `default_model_id` | string | 默认主模型 ID |
| `fallback_model_id` | string | 降级备用模型 ID |

### 获取单个模型

`GET /admin/models/{model_id}`

返回: `ModelInfo`（字段同上）

### 更新模型配置

`PUT /admin/models/{model_id}`

**请求参数（全部可选）:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `temperature` | float | 采样温度（0.0 ~ 2.0） |
| `max_tokens` | int | 最大输出 Token 数 |
| `timeout` | int | 超时时间(秒) |

```json
{"temperature": 0.3, "max_tokens": 4096, "timeout": 120}
```

### 切换节点模型

`PUT /admin/workflows/{workflow_id}/nodes/{node_id}/model`

将指定工作流中的某个 LLM 节点切换到其他模型。

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model_id` | string | 是 | 目标模型 ID |

```json
{"model_id": "gpt-4o-mini"}
```

### 手动降级

`POST /admin/models/{model_id}/fallback`

手动将模型切换到降级状态，使用备用模型。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `reason` | string | 否 | `手动触发` | 降级原因 |

```json
{"reason": "主模型响应过慢"}
```

### 恢复主模型

`POST /admin/models/{model_id}/recover`

从降级状态恢复，重新使用主模型。

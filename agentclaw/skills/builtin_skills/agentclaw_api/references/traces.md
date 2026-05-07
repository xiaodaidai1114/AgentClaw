# 追踪与监控

> 内部 agent/shell 调用使用本机 internal relay。先读取 `<project_dir>/.agentclaw/relay.json` 的 `internal_url` 作为 `{BASE_URL}`，实际 URL 为 `{BASE_URL}/_internal` + 下方文档路径。

## 追踪摘要

`GET /admin/traces/summary`

返回:
```json
{
  "total": 1500,
  "success": 1400,
  "error": 80,
  "running": 5,
  "timeout": 15,
  "avg_duration_ms": 2300
}
```

## 列出追踪

`GET /admin/traces`

**查询参数:**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `workflow_id` | string | - | 按工作流 ID 筛选 |
| `status` | string | - | 按状态筛选: `running` / `success` / `error` / `timeout` |
| `start_time` | string | - | 起始时间（ISO 8601 格式） |
| `end_time` | string | - | 结束时间（ISO 8601 格式） |
| `page` | int | 1 | 页码 |
| `limit` | int | 20 | 每页条数 |

返回:
```json
{
  "traces": [TraceRecord],
  "total": 150,
  "page": 1,
  "limit": 20
}
```

**TraceRecord 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 追踪 ID |
| `workflow_id` | string | 工作流 ID |
| `thread_id` | string | 会话/线程 ID |
| `conversation_id` | string | 同 thread_id（别名） |
| `user_id` | string | 用户标识 |
| `name` | string | 工作流名称 |
| `status` | string | `running` / `success` / `error` / `timeout` |
| `duration_ms` | float | 执行耗时(ms) |
| `start_time` | datetime | 开始时间 |
| `end_time` | datetime | 结束时间 |
| `error` | string | 错误信息（仅 error 状态） |
| `total_tokens` | int | 总 Token 数 |
| `prompt_tokens` | int | 输入 Token 数 |
| `completion_tokens` | int | 输出 Token 数 |
| `llm_calls` | int | LLM 调用次数 |

## 追踪详情

`GET /admin/traces/{trace_id}`

返回 `TraceDetail`，包含完整的节点日志和 LLM 调用日志。

**TraceDetail 额外字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `input_data` | object | 工作流输入数据 |
| `node_logs` | NodeLog[] | 节点执行日志列表 |
| `llm_logs` | LLMLog[] | LLM 调用日志列表 |
| `internal_traces` | object[] | 内部追踪数据 |

**NodeLog 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 节点日志 ID |
| `name` | string | 节点名称 |
| `node_type` | string | 节点类型: `llm` / `function` / `human` / `parallel` |
| `status` | string | `running` / `success` / `error` / `timeout` |
| `duration_ms` | float | 执行耗时(ms) |
| `start_time` | datetime | 开始时间 |
| `end_time` | datetime | 结束时间 |
| `input_data` | object | 节点输入 |
| `output_data` | object | 节点输出 |
| `error` | string | 错误信息 |

**LLMLog 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 日志 ID |
| `model_id` | string | 模型 ID |
| `model_name` | string | 模型名称 |
| `prompt_tokens` | int | 输入 Token 数 |
| `completion_tokens` | int | 输出 Token 数 |
| `total_tokens` | int | 总 Token 数 |
| `latency_ms` | float | 延迟(ms) |
| `status` | string | `success` / `error` |
| `error` | string | 错误信息 |
| `created_at` | datetime | 调用时间 |
| `metadata` | object | 元数据（工具调用等） |
| `node_log_id` | string | 关联的节点日志 ID |

## 追踪时间线

`GET /admin/traces/{trace_id}/timeline`

返回按时间排序的事件序列，用于可视化执行流程。

```json
{
  "trace_id": "trace_uuid",
  "events": [
    {
      "timestamp": "2026-04-08T10:00:00Z",
      "event_type": "node_start",
      "name": "llm_node",
      "status": "running",
      "duration_ms": null,
      "metadata": {}
    }
  ]
}
```

**event_type 取值:** `node_start` / `node_end` / `llm_call`

---

## 仪表盘

### 仪表盘统计

`GET /admin/dashboard/stats`

返回:
```json
{
  "workflow_count": 10,
  "total_executions_24h": 500,
  "success_rate": 95.0,
  "avg_duration_ms": 2100,
  "running_count": 3
}
```

### 仪表盘趋势

`GET /admin/dashboard/trends`

**查询参数:**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `time_range` | string | `24h` | 时间范围: `24h` / `7d` / `30d` |

# 定时任务

> 内部 agent/shell 调用使用本机 internal relay。先读取 `<project_dir>/.agentclaw/relay.json` 的 `internal_url` 作为 `{BASE_URL}`，实际 URL 为 `{BASE_URL}/_internal` + 下方文档路径。

## 创建任务

`POST /api/scheduler/jobs`

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | string | 是 | - | 任务名称 |
| `workflow_id` | string | 是 | - | 绑定的工作流 ID |
| `trigger` | TriggerConfig | 是 | - | 触发器配置（见下文） |
| `inputs` | object | 否 | `{}` | 工作流输入参数 |
| `description` | string | 否 | - | 任务描述 |
| `config` | JobConfig | 否 | 见下文 | 执行配置 |
| `webhook` | WebhookConfig | 否 | 见下文 | Webhook 触发配置 |

**请求示例:**
```json
{
  "name": "每日报告",
  "description": "每天早上 9 点生成日报",
  "workflow_id": "daily_report",
  "trigger": {
    "type": "cron",
    "expression": "0 9 * * *",
    "timezone": "Asia/Shanghai"
  },
  "inputs": {"report_type": "daily"},
  "config": {
    "timeout": 600,
    "retry_count": 2
  }
}
```

---

## 触发器配置 (TriggerConfig)

| 字段 | 类型 | 必填条件 | 说明 |
|------|------|---------|------|
| `type` | string | 始终必填 | 触发器类型: `cron` / `interval` / `date` |

### Cron 类型

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `expression` | string | 是 | - | Cron 表达式（5 字段: 分 时 日 月 周） |
| `timezone` | string | 否 | `Asia/Shanghai` | 时区 |

```json
{"type": "cron", "expression": "0 9 * * *", "timezone": "Asia/Shanghai"}
```

### Interval 类型

至少填写一个时间字段。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `weeks` | int | 否 | 间隔周数 |
| `days` | int | 否 | 间隔天数 |
| `hours` | int | 否 | 间隔小时数 |
| `minutes` | int | 否 | 间隔分钟数 |
| `seconds` | int | 否 | 间隔秒数 |
| `start_date` | datetime | 否 | 开始日期 |
| `end_date` | datetime | 否 | 结束日期 |

```json
{"type": "interval", "hours": 1}
```

### Date 类型（一次性）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `run_date` | datetime | 是 | 执行时间（ISO 8601 格式） |

```json
{"type": "date", "run_date": "2026-04-10T10:00:00"}
```

---

## 执行配置 (JobConfig)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `timeout` | int | 300 | 执行超时时间(秒) |
| `retry_count` | int | 0 | 失败重试次数 |
| `retry_interval` | int | 60 | 重试间隔(秒) |
| `concurrency` | string | `skip` | 并发策略: `skip`(跳过) / `queue`(排队) / `parallel`(并行) |
| `max_instances` | int | 1 | 最大并发实例数 |

---

## Webhook 配置 (WebhookConfig)

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | boolean | `false` | 是否启用 Webhook 触发 |
| `secret` | string | - | Webhook Secret（用于验证请求） |
| `allow_input_override` | boolean | `true` | 是否允许 Webhook 请求体覆盖工作流输入 |

---

## 列出任务

`GET /api/scheduler/jobs`

**查询参数:**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `status` | string | - | 按状态筛选: `enabled` / `disabled` / `paused` |
| `workflow_id` | string | - | 按工作流 ID 筛选 |
| `page` | int | 1 | 页码 |
| `limit` | int | 20 | 每页条数 |

返回:
```json
{
  "jobs": [JobResponse],
  "total": 10
}
```

**JobResponse 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 任务 ID |
| `name` | string | 任务名称 |
| `description` | string | 任务描述 |
| `workflow_id` | string | 绑定的工作流 ID |
| `trigger` | TriggerConfig | 触发器配置 |
| `inputs` | object | 工作流输入参数 |
| `status` | string | 任务状态: `enabled` / `disabled` / `paused` |
| `config` | JobConfig | 执行配置 |
| `webhook` | WebhookConfig | Webhook 配置 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |
| `last_run_at` | datetime | 上次执行时间 |
| `next_run_at` | datetime | 下次执行时间 |
| `run_count` | int | 总执行次数 |
| `fail_count` | int | 失败次数 |

## 获取任务详情

`GET /api/scheduler/jobs/{job_id}`

返回: `JobResponse`（字段同上）

## 更新任务

`PUT /api/scheduler/jobs/{job_id}`

**请求参数（全部可选）:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | string | 任务名称 |
| `workflow_id` | string | 绑定的工作流 ID |
| `trigger` | TriggerConfig | 触发器配置 |
| `inputs` | object | 工作流输入参数 |
| `config` | JobConfig | 执行配置 |
| `description` | string | 任务描述 |
| `status` | string | 任务状态: `enabled` / `disabled` / `paused` |
| `webhook` | WebhookConfig | Webhook 配置 |

## 删除任务

`DELETE /api/scheduler/jobs/{job_id}`

## 暂停 / 恢复 / 立即触发

- **暂停:** `POST /api/scheduler/jobs/{job_id}/pause`
- **恢复:** `POST /api/scheduler/jobs/{job_id}/resume`
- **立即触发:** `POST /api/scheduler/jobs/{job_id}/trigger`

立即触发返回:
```json
{
  "execution_id": "exec_uuid",
  "message": "Job triggered successfully"
}
```

## Webhook 触发

`POST /api/scheduler/jobs/{job_id}/webhook`

通过外部 HTTP 请求触发任务执行（需在任务中启用 `webhook.enabled=true`）。

**请求 Header:**

| Header | 说明 |
|--------|------|
| `X-Webhook-Secret` | Webhook Secret（如果任务配置了 `webhook.secret`） |

**请求 Body:** JSON（可选）

当 `webhook.allow_input_override=true` 时，请求体会作为工作流输入参数覆盖任务默认的 `inputs`。

---

## 执行历史

### 列出执行记录

`GET /api/scheduler/jobs/{job_id}/executions`

**查询参数:**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | 1 | 页码 |
| `limit` | int | 20 | 每页条数 |

返回:
```json
{
  "executions": [JobExecutionResponse],
  "total": 15,
  "page": 1,
  "limit": 20
}
```

**JobExecutionResponse 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 执行记录 ID |
| `job_id` | string | 任务 ID |
| `status` | string | 执行状态: `pending` / `running` / `success` / `failed` / `timeout` / `cancelled` |
| `trigger_source` | string | 触发来源: `schedule` / `manual` / `webhook` |
| `started_at` | datetime | 开始时间 |
| `ended_at` | datetime | 结束时间 |
| `duration_ms` | int | 执行耗时(ms) |
| `inputs` | object | 本次执行的输入参数 |
| `outputs` | object | 执行输出结果 |
| `error` | string | 错误信息（仅 failed 状态） |
| `retry_count` | int | 已重试次数 |

### 获取执行详情

`GET /api/scheduler/jobs/{job_id}/executions/{execution_id}`

返回: `JobExecutionResponse`（字段同上）

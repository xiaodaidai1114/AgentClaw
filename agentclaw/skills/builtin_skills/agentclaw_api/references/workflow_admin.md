# 工作流管理与任务管理 (Admin)

> 内部 agent/shell 调用使用本机 internal relay。先读取 `<project_dir>/.agentclaw/relay.json` 的 `internal_url` 作为 `{BASE_URL}`，实际 URL 为 `{BASE_URL}/_internal` + 下方文档路径。

## 工作流管理

### 列出工作流（含统计）

`GET /admin/workflows`

返回:
```json
{
  "workflows": [WorkflowInfo]
}
```

**WorkflowInfo 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 工作流 ID |
| `name` | string | 工作流名称 |
| `version` | string | 版本号 |
| `description` | string | 描述 |
| `node_count` | int | 节点数量 |
| `is_builtin` | boolean | 是否为内置工作流 |
| `stats_24h` | object | 最近 24h 统计: `{execution_count, success_rate, avg_duration_ms}` |

### 获取工作流详情（结构 + 统计）

`GET /admin/workflows/{workflow_id}`

返回:
```json
{
  "workflow": WorkflowStructure,
  "stats": WorkflowStats
}
```

**WorkflowStructure 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 工作流 ID |
| `name` | string | 工作流名称 |
| `version` | string | 版本号 |
| `description` | string | 描述 |
| `nodes` | WorkflowNode[] | 节点列表 |
| `edges` | WorkflowEdge[] | 边列表 |
| `node_order` | string[] | 节点执行顺序 |
| `input_schema` | object | 工作流输入 Schema |
| `user_input_field` | string | 用户输入字段名 |
| `welcome` | string | 前端开场白 |

**WorkflowNode 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 节点 ID |
| `name` | string | 节点名称 |
| `type` | string | 节点类型: `llm` / `function` / `human` / `parallel` |
| `model_id` | string | 关联模型 ID（仅 llm 类型） |
| `has_prompt` | boolean | 是否有提示词 |
| `interrupt` | boolean | 是否中断等待 |

**WorkflowEdge 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | string | 起始节点 ID |
| `target` | string | 目标节点 ID |
| `type` | string | 边类型: `normal` / `conditional` |
| `condition` | string | 条件表达式（仅 conditional 类型） |

**WorkflowStats 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `total_count` | int | 总执行数 |
| `success_count` | int | 成功数 |
| `error_count` | int | 失败数 |
| `timeout_count` | int | 超时数 |
| `running_count` | int | 运行中数 |
| `success_rate` | float | 成功率(%) |
| `avg_duration_ms` | float | 平均耗时(ms) |
| `p95_duration_ms` | float | P95 耗时(ms) |
| `p99_duration_ms` | float | P99 耗时(ms) |

### 工作流统计

`GET /admin/workflows/{workflow_id}/stats`

**查询参数:**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `time_range` | string | `24h` | 时间范围: `24h` / `7d` / `30d` |

### 工作流趋势

`GET /admin/workflows/{workflow_id}/trends`

**查询参数:**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `time_range` | string | `7d` | 时间范围: `24h` / `7d` / `30d` |

### 热加载工作流文件

`POST /admin/workflows/register-file`

从文件系统加载/重新加载工作流，无需重启服务。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `file_path` | string | 是 | - | 工作流 Python 文件路径 |
| `workflow_id` | string | 否 | - | 指定工作流 ID（不传则从文件推断） |
| `force_replace` | boolean | 否 | `false` | 是否强制替换已有工作流 |

```json
{
  "file_path": "workflows/new_agent.py",
  "workflow_id": "new_agent",
  "force_replace": true
}
```

### 工具配置

控制工作流中 skill 和 tool 的启禁用。

**获取当前配置:** `GET /admin/workflows/{workflow_id}/tool-config`

**更新配置:** `PUT /admin/workflows/{workflow_id}/tool-config`

**请求参数:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `disabled_skills` | string[] | 禁用的 skill 名称列表 |
| `disabled_tools` | string[] | 禁用的 tool 名称列表 |

```json
{
  "disabled_skills": ["coding_skill"],
  "disabled_tools": ["dangerous_tool"]
}
```

**重置为默认:** `POST /admin/workflows/{workflow_id}/tool-config/reset`

---

## 任务管理

### 列出运行中任务

`GET /admin/tasks`

**查询参数:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `workflow_id` | string | 按工作流 ID 筛选（可选） |

### 取消任务

`POST /admin/tasks/{task_id}/cancel`

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `reason` | string | 否 | 取消原因 |

```json
{"reason": "手动取消"}
```

### 清理已完成任务

`DELETE /admin/tasks/cleanup`

清理所有已完成/已失败的任务记录。

# 渠道管理

> 内部 agent/shell 调用使用本机 internal relay。先读取 `<project_dir>/.agentclaw/relay.json` 的 `internal_url` 作为 `{BASE_URL}`，实际 URL 为 `{BASE_URL}/_internal` + 下方文档路径。

## 列出渠道

`GET /admin/channels`

返回:
```json
{
  "channels": [ChannelResponse],
  "total": 1
}
```

**ChannelResponse 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 渠道 ID |
| `name` | string | 渠道实例名称 |
| `type` | string | 渠道类型: `feishu` / `dingtalk` / `wecom` / `qq` |
| `workflow_id` | string | 绑定的工作流 ID，默认 `__builtin__` |
| `user_input_field` | string | 用户消息注入的输入字段名，默认 `user_input` |
| `thread_mode` | string | 会话模式: `per_user`(按用户隔离) / `per_chat`(按群隔离) / `shared`(共享) |
| `enabled` | boolean | 是否启用 |
| `config` | object | 平台特定配置（app_id, app_secret 等） |
| `running` | boolean | 当前是否运行中 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

## 创建渠道

`POST /admin/channels`

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | string | 是 | - | 渠道实例名称（唯一标识，如 feishu_sales） |
| `type` | string | 是 | - | 渠道类型: `feishu` / `dingtalk` / `wecom` / `qq` |
| `workflow_id` | string | 否 | `__builtin__` | 绑定的工作流 ID |
| `user_input_field` | string | 否 | `user_input` | 用户消息注入的输入字段名 |
| `thread_mode` | string | 否 | `per_user` | 会话模式: `per_user` / `per_chat` / `shared` |
| `enabled` | boolean | 否 | `true` | 是否启用 |
| `config` | object | 否 | `{}` | 平台特定配置 |

**config 字段（按 type 不同）:**

飞书 (`feishu`):
```json
{"app_id": "cli_xxx", "app_secret": "xxx"}
```

钉钉 (`dingtalk`):
```json
{"app_key": "xxx", "app_secret": "xxx"}
```

企微 (`wecom`):
```json
{"corp_id": "xxx", "agent_id": "xxx", "secret": "xxx"}
```

**请求示例:**
```json
{
  "name": "销售飞书",
  "type": "feishu",
  "workflow_id": "sales_agent",
  "user_input_field": "user_input",
  "thread_mode": "per_user",
  "enabled": true,
  "config": {
    "app_id": "cli_xxx",
    "app_secret": "xxx"
  }
}
```

## 获取渠道

`GET /admin/channels/{channel_id}`

返回: `ChannelResponse`（字段同上）

## 更新渠道

`PUT /admin/channels/{channel_id}`

**请求参数（全部可选）:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `workflow_id` | string | 绑定的工作流 ID |
| `user_input_field` | string | 用户消息注入的输入字段名 |
| `thread_mode` | string | 会话模式: `per_user` / `per_chat` / `shared` |
| `enabled` | boolean | 是否启用 |
| `config` | object | 平台特定配置 |

## 删除渠道

`DELETE /admin/channels/{channel_id}`

## 重启渠道

`POST /admin/channels/{channel_id}/restart`

重启指定渠道的 Bot 连接。

## 验证渠道凭据

`POST /admin/channels/probe`

在创建渠道前验证配置是否有效。

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 渠道类型: `feishu` / `dingtalk` / `wecom` / `qq` |
| `config` | object | 是 | 平台配置（同创建渠道的 config） |

```json
{
  "type": "feishu",
  "config": {"app_id": "cli_xxx", "app_secret": "xxx"}
}
```

## 主动推送消息

`POST /api/channels/push`

用于从 AgentClaw 后端主动向已配置渠道发送消息。只有实际发送成功时才会返回成功。

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `channel` | string | 是 | 渠道名称，优先使用实例名，如 `feishu_sales` |
| `content` | string | 是 | 要推送的文本内容 |
| `user_id` | string | 否 | 目标用户 ID |
| `chat_id` | string | 否 | 目标群/会话 ID |

说明：
- `user_id` 和 `chat_id` 至少要传一个。
- 传实例名时会直接命中对应渠道；若传渠道类型名，则会向后兼容匹配该类型的第一个实例。
- 返回 `200` 表示渠道适配器已经成功接受并发送消息；发送异常会返回 `500`。

**请求示例:**

```json
{
  "channel": "feishu_sales",
  "user_id": "ou_xxx",
  "content": "您好，这是一条主动推送消息"
}
```

```json
{
  "channel": "qq_bot",
  "chat_id": "group_openid_xxx",
  "content": "群通知：任务已完成"
}
```

**返回说明:**

| HTTP 状态码 | 含义 |
|-------------|------|
| `200` | 发送成功，返回 `{"status":"sent"}` |
| `400` | 缺少 `channel` / `content`，或 `user_id`、`chat_id` 均为空 |
| `404` | 指定渠道不存在 |
| `500` | 渠道发送失败，返回适配器错误信息 |

**各渠道目标规则:**

| 渠道 | 私聊推送 | 群推送 |
|------|----------|--------|
| 飞书 | 传 `user_id=open_id` | 传 `chat_id=chat_id`，优先按群发 |
| 钉钉 | 传 `user_id=sender_id` | 传 `chat_id=open_conversation_id` |
| 企业微信 | 传 `user_id`；bot 模式下会走 WebSocket 主动发送 | 传 `chat_id`；若 bot 模式配置了 `webhook_key`，优先走群 webhook |
| QQ | 传 `user_id=user_openid` | 传 `chat_id=group_openid` |

**建议:**
- 主动推送优先使用渠道实例名，不要只传类型名，避免在一对多场景下命中错误实例。
- 如果需要群发，请尽量提供明确的 `chat_id`，不要只传 `user_id`。
- 飞书、钉钉、QQ、企业微信的 ID 都是平台侧标识，不是 AgentClaw 内部用户 ID。

---

## 渠道消息日志

### 全局日志

`GET /admin/channels/logs`

**查询参数:**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `channel_id` | string | - | 按渠道 ID 筛选 |
| `status` | string | - | 按状态筛选: `pending` / `success` / `error` / `timeout` |
| `page` | int | 1 | 页码 |
| `limit` | int | 20 | 每页条数 |

返回:
```json
{
  "logs": [ChannelLogResponse],
  "total": 100,
  "page": 1,
  "limit": 20
}
```

**ChannelLogResponse 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 日志 ID |
| `channel_id` | string | 渠道 ID |
| `channel_name` | string | 渠道名称 |
| `user_id` | string | 发送消息的用户 |
| `chat_id` | string | 群聊 ID |
| `message` | string | 用户消息内容 |
| `reply` | string | Bot 回复内容 |
| `workflow_id` | string | 触发的工作流 ID |
| `status` | string | 处理状态: `pending` / `success` / `error` / `timeout` |
| `duration_ms` | int | 处理耗时(ms) |
| `error` | string | 错误信息 |
| `created_at` | datetime | 消息时间 |

### 单渠道日志

`GET /admin/channels/{channel_id}/logs`

参数同全局日志（无需传 channel_id）。

### 日志统计

`GET /admin/channels/logs/stats`

**查询参数:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `channel_id` | string | 按渠道 ID 筛选（可选） |

返回:
```json
{
  "total": 1000,
  "success": 950,
  "error": 30,
  "timeout": 20,
  "avg_duration_ms": 1500.5
}
```

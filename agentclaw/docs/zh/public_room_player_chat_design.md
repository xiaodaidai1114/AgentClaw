# 公开房间玩家聊天设计

## 背景

公开房间当前已经支持多个匿名玩家加入同一个 Agent 会话，并共享同一条智能体对话历史。现有消息流只有一条：玩家向智能体发送输入，智能体回复，消息写入 `agent_conversations(source="public_room")`。

新增玩家聊天框后，需要把“玩家之间闲聊”和“玩家与智能体交互”分开。玩家聊天不会调用智能体，不进入 LangGraph checkpoint，不影响工作流上下文，也不应该污染后台的智能体会话记录。

第一版目标是提供一个轻量、可用、边界清晰的公开房间聊天能力。

## 目标

1. 公开房间页面增加一个悬浮可拖动的玩家聊天框。
2. 玩家聊天只在公开房间模式显示，普通公开 Agent 页面不显示。
3. 玩家聊天消息保存到新的 PostgreSQL 表。
4. 玩家聊天不调用智能体，不写入 `agent_conversations.messages`。
5. 智能体运行期间，玩家聊天仍然可以发送。
6. 只有已加入房间的成员可以读取和发送玩家聊天。
7. 前端轮询获取新聊天消息，第一版不引入 WebSocket。

## 非目标

1. 第一版不做内容安全围栏，不接入内容安全库，不做敏感词、PII、URL、密钥等自动打码。
2. 第一版不做聊天消息撤回、删除、举报和后台审核页面。
3. 第一版不支持图片、文件、语音或富文本。
4. 第一版不把聊天消息同步给智能体作为上下文。
5. 第一版不做跨房间全局聊天室。

## 基础校验边界

虽然第一版不做内容安全围栏，仍需要保留基础工程校验：

- 必须是已加入公开房间的匿名成员。
- 必须有有效 same-origin public session。
- 消息内容必须是字符串。
- 去除首尾空白后不能为空。
- 限制单条消息最大长度，建议默认 500 字符。
- 前端按纯文本渲染，不使用 `v-html`。
- 后端不返回 `owner_id`、token、内部锁状态等私有字段。
- 服务端保留发送限流，避免刷屏。

这些校验用于权限隔离、接口稳定性和资源保护，不属于内容审核或内容安全围栏。

## 数据模型

新增表 `agent_public_room_chat_messages`。

```sql
CREATE TABLE IF NOT EXISTS agent_public_room_chat_messages (
    id VARCHAR(80) PRIMARY KEY,
    room_id VARCHAR(80) NOT NULL,
    owner_id VARCHAR(100) NOT NULL,
    nickname VARCHAR(80) NOT NULL,
    content TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    deleted_at BIGINT,
    CONSTRAINT fk_public_room_chat_room
        FOREIGN KEY (room_id) REFERENCES agent_public_rooms(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_public_room_chat_room_created
    ON agent_public_room_chat_messages(room_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_public_room_chat_owner_created
    ON agent_public_room_chat_messages(room_id, owner_id, created_at DESC);
```

字段说明：

- `id`：聊天消息 id，建议格式为 `chat_` + urlsafe 随机值。
- `room_id`：所属公开房间。
- `owner_id`：发送者匿名 owner id，仅后端使用，不返回前端。
- `nickname`：发送时的房间昵称快照。
- `content`：纯文本聊天内容。
- `created_at`：毫秒时间戳。
- `deleted_at`：预留软删除字段，第一版不提供删除入口。

不新增 `raw_content`、`moderation_status`、`moderation_labels` 字段，因为第一版不做安全围栏和内容审核。

## 后端模块

建议新增独立服务文件，避免 `public_room_service.py` 继续膨胀：

```text
agentclaw/api/schemas/public_room_chat.py
agentclaw/api/services/public_room_chat_service.py
```

路由可以继续放在现有：

```text
agentclaw/api/routers/public/rooms.py
```

### Schema

`PublicRoomChatSendRequest`：

```json
{
  "content": "玩家聊天内容"
}
```

`PublicRoomChatMessage`：

```json
{
  "id": "chat_xxx",
  "room_id": "room_xxx",
  "nickname": "玩家A",
  "content": "玩家聊天内容",
  "created_at": 1710000000000
}
```

### Service

`PublicRoomChatService` 负责：

- 创建 `agent_public_room_chat_messages` 表和索引。
- 发送聊天消息。
- 按房间读取最近聊天消息。
- 校验并规范化聊天内容。
- 不接触智能体 conversation messages。

建议方法：

```python
async def send_message(room_id: str, owner_id: str, nickname: str, content: str) -> dict
async def list_messages(room_id: str, after_id: str = "", limit: int = 100) -> list[dict]
```

`send_message` 只接受已经由 room 路由确认过的成员身份。service 本身不重新解析 cookie。

## API 设计

新增两个 public room API：

```text
GET /api/public/rooms/{room_id}/chat?after_id=&limit=100
POST /api/public/rooms/{room_id}/chat
```

### GET chat

要求：

- 房间存在。
- 当前 public session 有效。
- 当前匿名用户已经加入该房间。

返回：

```json
{
  "messages": [
    {
      "id": "chat_xxx",
      "room_id": "room_xxx",
      "nickname": "玩家A",
      "content": "大家先别急着问",
      "created_at": 1710000000000
    }
  ]
}
```

`after_id` 用于增量读取。第一版可以实现为：

- 如果 `after_id` 为空，返回最近 `limit` 条，并按 `created_at ASC` 给前端展示。
- 如果 `after_id` 不为空，先查出该消息的 `created_at`，再返回同房间中更晚的消息。
- 如果 `after_id` 不存在或不属于该房间，返回最近 `limit` 条，不暴露错误细节。

### POST chat

请求：

```json
{
  "content": "玩家聊天内容"
}
```

返回：

```json
{
  "message": {
    "id": "chat_xxx",
    "room_id": "room_xxx",
    "nickname": "玩家A",
    "content": "玩家聊天内容",
    "created_at": 1710000000000
  }
}
```

错误：

- `400 INVALID_REQUEST`：内容为空、类型错误。
- `413 PAYLOAD_TOO_LARGE`：内容超过最大长度。
- `403 FORBIDDEN`：未加入房间或 public session 无效。
- `404 NOT_FOUND`：房间不存在。
- `429 RATE_LIMITED`：发送过于频繁。
- `503 PUBLIC_ROOM_INFRA_REQUIRED`：PG 或 Redis 不可用。

## 限流

玩家聊天会比智能体 run 更高频，必须独立限流。

建议默认值：

- `chat-send`: 30/min per room + owner。
- `chat-list`: 120/min per room + owner。

可新增环境变量：

```text
AGENTCLAW_PUBLIC_ROOM_CHAT_SEND_RATE_LIMIT=30/min
AGENTCLAW_PUBLIC_ROOM_CHAT_LIST_RATE_LIMIT=120/min
AGENTCLAW_PUBLIC_ROOM_CHAT_MAX_LENGTH=500
```

如果暂时不新增解析逻辑，也可以复用现有 public rate limit，但建议 action key 独立，避免聊天轮询挤占智能体 run 的限额。

## 前端交互

公开房间页面新增一个玩家聊天浮层。

### 桌面端

- 默认在右下角显示一个“玩家聊天”悬浮按钮。
- 点击后展开聊天面板。
- 面板建议宽度 340px，高度 480px。
- 顶部是拖动手柄，显示标题、未读数或成员提示、最小化按钮。
- 中间是消息列表。
- 底部是输入框和发送按钮。
- 面板可拖动，位置按 room id 保存到 `localStorage`。
- 拖动时限制在 viewport 内，窗口尺寸变化时自动夹回可见范围。

### 移动端

- 不做自由拖动。
- 默认右下角悬浮按钮。
- 点击后打开底部抽屉。
- 抽屉高度约为 60%-70% viewport。
- 关闭后保留未读数。

### 和智能体输入的关系

- 智能体正在运行时，主输入框仍按现有逻辑禁用。
- 玩家聊天输入不受 `publicRoomBusy` 影响。
- 玩家聊天发送只调用 `/api/public/rooms/{room_id}/chat`，不能调用 `/run`。
- 玩家聊天消息不显示在主智能体消息列表里。
- 主智能体消息列表不显示玩家聊天。

## 前端状态

在 `AgentChat.vue` 的公开房间模式中增加状态：

```js
publicRoomChatOpen: false
publicRoomChatMessages: []
publicRoomChatLastId: ''
publicRoomChatUnread: 0
publicRoomChatPollingTimer: null
publicRoomChatDraft: ''
publicRoomChatSending: false
publicRoomChatPosition: { x: null, y: null }
```

建议新增 API 封装：

```js
publicRoomsApi.listChat(roomId, afterId, limit)
publicRoomsApi.sendChat(roomId, content)
```

轮询策略：

- 已加入公开房间后启动聊天轮询。
- 面板打开时每 2 秒拉取。
- 面板关闭时每 8-10 秒拉取，或者暂停轮询只在打开时拉取。推荐第一版关闭时仍低频轮询，用于未读数。
- 发送成功后立即追加返回的 message，并更新 `publicRoomChatLastId`。

## 数据流

发送聊天：

```text
玩家输入聊天内容
  -> 前端 POST /api/public/rooms/{room_id}/chat
  -> 后端校验 public session 和 room membership
  -> 后端规范化 content
  -> 写入 agent_public_room_chat_messages
  -> 返回公开字段
  -> 前端追加到聊天面板
```

读取聊天：

```text
前端定时 GET /api/public/rooms/{room_id}/chat?after_id=<last_id>
  -> 后端校验 public session 和 room membership
  -> 查询该 room 的新聊天消息
  -> 返回公开字段
  -> 前端合并去重并更新未读数
```

智能体 run：

```text
主输入 POST /api/public/rooms/{room_id}/run
  -> 只写 agent_conversations(source="public_room")
  -> 不读取、不写入 agent_public_room_chat_messages
```

## 测试计划

### 后端

新增或扩展 `agentclaw/test/api/test_public_room_api.py`：

- 成员能发送聊天消息。
- 未加入成员发送聊天返回 403。
- 未加入成员读取聊天返回 403。
- A 房间消息不会出现在 B 房间。
- 发送空内容返回 400。
- 发送超长内容返回 413 或 400，按实现保持一致。
- 发送聊天不会修改 `agent_conversations.messages`。
- 房间 `status=running` 时仍能发送聊天。
- GET chat 不返回 `owner_id`。
- POST chat 不接受文件字段。

### 前端

新增或扩展公开房间相关测试：

- 公开房间模式显示玩家聊天入口。
- 普通公开 Agent 页面不显示玩家聊天入口。
- 点击入口展开聊天面板。
- 发送聊天调用 `publicRoomsApi.sendChat`，不调用 `publicRoomsApi.run`。
- `publicRoomBusy=true` 时聊天输入仍可用。
- 收到新聊天消息后未读数增加。
- 移动端使用底部抽屉布局。

## 后续扩展

安全围栏暂不做，但后续可以平滑扩展：

- 增加 `moderation_status`、`moderation_labels`、`masked_content` 字段。
- 接入内容安全库或本地规则。
- 增加后台查看、删除、封禁。
- 增加 WebSocket/SSE，替代短轮询。
- 增加用户正在聊天输入提示。

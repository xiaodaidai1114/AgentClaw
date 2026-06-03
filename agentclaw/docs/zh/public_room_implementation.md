# 公开多人会话实现文档

## 背景与目标

公开 Agent 页面当前有两种访问形态：

- 普通公开链接：用户无需登录，通过 `agentclaw_public_user` cookie 形成匿名身份，每个匿名用户只能访问自己的公开会话。
- 智能体广场：发布到广场的 Agent 可以匿名打开，但实际聊天仍然是每个匿名用户自己的会话。

新增“公开多人会话”时，不能破坏上面的隔离逻辑。公开多人会话应作为显式创建的房间能力存在：用户主动创建一个公开房间，输入昵称后生成可分享链接，其他人通过该链接加入同一个房间并共享同一条会话历史。

公开多人会话第一版强制要求 PostgreSQL 与 Redis 同时可用。没有 PostgreSQL 或 Redis 时，公开多人会话 API 应返回 `503 PUBLIC_ROOM_INFRA_REQUIRED`，前端隐藏或禁用创建公开会话入口。该功能不提供内存 fallback，因为多人房间需要跨请求、跨进程共享状态，并且需要可靠的运行锁。

第一版目标：

1. API 层先提供完整的公开房间语义：创建、加入、读取状态、typing、房间运行锁、房间运行。
2. 普通公开会话继续按匿名 `owner_id` 隔离。
3. 房间消息由后端追加和维护，不允许前端任意覆盖整段 messages。
4. 大模型运行期间房间加锁，其他成员不能发送。
5. 房间状态支持短轮询，其他成员可以看到最新消息、成员、typing 和运行状态。
6. 公开页面隐藏节点状态、工具调用、推理过程；后台记录保留可审计的来源和房间标识。

非目标：

- 第一版不做 WebSocket。
- 第一版不做后台房间管理页面。
- 第一版不支持成员删除他人消息。
- 第一版不支持一个房间切换多个 Agent。
- 第一版不让 public room token 访问任意 workflow，只能访问绑定房间。

## 总体架构

新增 `PublicRoom` 层，位于 public API 下面，但不要复用现有 public conversation 的 owner 校验。

推荐新增文件：

```text
agentclaw/api/schemas/public_room.py
agentclaw/api/services/public_room_service.py
agentclaw/api/routers/public/rooms.py
```

挂载路径：

```text
/api/public/workflows/{workflow_id}/rooms
/api/public/rooms/{room_id}/bootstrap
/api/public/rooms/{room_id}/join
/api/public/rooms/{room_id}/state
/api/public/rooms/{room_id}/typing
/api/public/rooms/{room_id}/run
```

核心边界：

- 普通公开会话：`source = "public"`，`owner_id = <当前匿名用户 owner hash>`。
- 公开多人房间会话：`source = "public_room"`，`owner_id = "room:<room_id>"`。
- 房间成员身份：由 `(room_id, public_owner_id)` 表示，昵称只作为展示字段。
- 房间能力凭证：`room_token`，只存 hash，只能访问对应 room。
- 房间运行线程：使用 `owner_id = "room:<room_id>"` 生成 runtime thread id，确保所有成员共享同一个 LangGraph checkpoint。

## 安全原则

公开多人会话属于公网匿名能力，必须遵循以下规则：

1. **不放开普通 public conversation 隔离。**  
   现有 `/api/conversations/{workflow_id}/{conversation_id}` 的 public 路由仍然必须校验当前匿名 `owner_id`。不能因为 room 功能让任意用户用 `conversation_id` 读取普通公开会话。

2. **room token 是能力凭证。**  
   创建房间时返回一次明文 `room_token`，后端只存 `room_token_hash`。后续 bootstrap/join 通过 `X-AgentClaw-Room-Token` 校验。不要把 room token 写入日志、数据库明文字段、conversation messages 或 trace metadata。

3. **URL token 只用于前端启动。**  
   分享链接可以携带 `room_token`，但前端读取后应存入 session/local storage，并立刻清理 URL。API 请求使用 header，不使用 query/body 传 token。

4. **同源 public session 仍然必需。**  
   所有 room API 都必须要求：
   - `X-AgentClaw-Public-Session: 1`
   - 有效 `agentclaw_public_session` cookie
   - same-origin referer/origin 校验通过
   - 有效 `agentclaw_public_user` cookie

5. **创建 room 必须先验证 workflow 公开访问权限。**  
   非广场 Agent 必须带有效 workflow share token。广场 Agent 可以通过广场提供的 share token 创建。room 创建成功后，别人加入 room 只需要 room token，不再需要 workflow share token。

6. **成员必须 join 后才能读状态和发送。**  
   `state`、`typing`、`run` 均要求当前 public owner 已经是 room member。只有 `bootstrap` 允许未加入用户用 room token 获取最小房间信息。

7. **大模型运行必须有房间级锁。**  
   同一 room 同一时间只允许一个 run。其他成员发送时返回 `409 ROOM_BUSY`。不能只靠前端禁用按钮，后端必须原子校验。

8. **消息由后端追加，不信任前端完整 messages。**  
   第一版不提供 public room 的通用 `PUT messages` 接口。发送消息走 room run API，由后端追加 user message、收集 assistant final message，并递增 room version。

9. **公开输出只返回脱敏消息。**  
   public room state 不返回 `owner_id`、`public_user_id`、token hash、节点输入输出、工具调用参数、reasoning、trace id。后台可通过 trace 系统审计，但公开 API 不暴露。

10. **昵称需要严格规范化。**  
    nickname 去除首尾空白、控制字符，限制长度，默认最大 24 个字符。空昵称拒绝。前端正常转义展示，不允许作为 HTML。

11. **轮询需要专用限流。**  
    state polling 不应使用默认 `30/min`，否则 2 秒轮询刚好打满限制。建议专用默认值：
    - state: `90/min` per public owner + room
    - typing: `30/min` per public owner + room
    - create/join/run: 继续使用更严格的公开入口限流

12. **运行锁要有过期恢复。**  
    如果进程崩溃导致 room 卡在 running，后端应在 `running_started_at` 超过 `AGENTCLAW_PUBLIC_ROOM_STALE_RUN_SECONDS` 后允许抢占恢复。默认建议 1800 秒。

## 数据库结构

### agent_public_rooms

公开多人会话强制依赖 PostgreSQL。room 元数据、participants 和 conversation messages 必须落 PG；没有 PostgreSQL 时不启用该功能。

建议 DDL：

```sql
CREATE TABLE IF NOT EXISTS agent_public_rooms (
    id VARCHAR(80) PRIMARY KEY,
    workflow_id VARCHAR(100) NOT NULL,
    conversation_id VARCHAR(50) NOT NULL UNIQUE,
    room_token_hash VARCHAR(128) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'idle',
    running_by VARCHAR(100),
    running_nickname VARCHAR(80),
    running_started_at BIGINT,
    created_by VARCHAR(100),
    version BIGINT NOT NULL DEFAULT 1,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    revoked_at BIGINT
);

CREATE INDEX IF NOT EXISTS idx_agent_public_rooms_workflow
    ON agent_public_rooms(workflow_id);

CREATE INDEX IF NOT EXISTS idx_agent_public_rooms_updated
    ON agent_public_rooms(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_public_rooms_conversation
    ON agent_public_rooms(conversation_id);
```

字段说明：

- `id`：`room_` + urlsafe 随机值，至少 24 字节随机熵。
- `workflow_id`：绑定的 Agent。
- `conversation_id`：绑定的共享 conversation，创建 room 时同步创建。
- `room_token_hash`：`sha256(room_token)` 或 HMAC hash，不存明文。
- `status`：`idle | running`。
- `running_by`：当前运行成员的 public owner hash，仅后端使用。
- `running_nickname`：公开可展示的运行成员昵称。
- `running_started_at`：运行开始时间，供 stale lock 恢复。
- `created_by`：创建者 public owner hash，仅后端使用。
- `version`：房间消息、运行状态变化时递增。typing 不递增 version。
- `revoked_at`：预留吊销房间能力，第一版可以只读写空值。

### agent_public_room_participants

建议 DDL：

```sql
CREATE TABLE IF NOT EXISTS agent_public_room_participants (
    room_id VARCHAR(80) NOT NULL,
    owner_id VARCHAR(100) NOT NULL,
    nickname VARCHAR(80) NOT NULL,
    joined_at BIGINT NOT NULL,
    last_seen_at BIGINT NOT NULL,
    PRIMARY KEY (room_id, owner_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_public_room_participants_seen
    ON agent_public_room_participants(room_id, last_seen_at DESC);
```

字段说明：

- `room_id`：房间 id。
- `owner_id`：`public_owner_id_from_request(request)` 的结果。
- `nickname`：规范化后的展示昵称。
- `last_seen_at`：每次 state、typing、run 时刷新。

### agent_conversations 记录格式

公开多人房间继续复用 `agent_conversations` 存储对话内容，但必须用新的 source 区分：

```text
id: <room.conversation_id>
workflow_id: <room.workflow_id>
title: "[公开会话] <首条用户消息前 20 字>"
messages: <sanitized public room messages>
source: "public_room"
owner_id: "room:<room_id>"
user_id: null
tenant_id: null
checkpoint_expired_at: 按现有 checkpoint TTL 策略设置
created_at: 毫秒时间戳
updated_at: 毫秒时间戳
```

后台列表行为：

- 默认后台 `source=admin` 查询不显示 public room。
- 后台如需查看公开房间记录，应通过 `source=public_room` 查询。
- 公开房间记录可以在后台统计里单独归类，不能混入普通 `source=public` 的匿名单人公开会话。

### messages JSON 格式

公开房间的 `agent_conversations.messages` 应存公开可展示的脱敏消息，而不是前端传回的完整 `AgentChat` 消息对象。

用户消息：

```json
{
  "role": "user",
  "content": "这里是用户输入",
  "timestamp": 1710000000000,
  "sender_type": "public_room_participant",
  "sender": {
    "nickname": "玩家A"
  },
  "public_room": {
    "room_id": "room_xxx"
  }
}
```

助手消息：

```json
{
  "role": "assistant",
  "content": "这里是 Agent 回复",
  "timestamp": 1710000005000,
  "sender_type": "agent",
  "public_room": {
    "room_id": "room_xxx"
  },
  "deliveryStatus": "ok"
}
```

错误或取消消息：

```json
{
  "role": "assistant",
  "content": "请求失败或已取消",
  "timestamp": 1710000005000,
  "sender_type": "agent",
  "public_room": {
    "room_id": "room_xxx"
  },
  "deliveryStatus": "failed",
  "deliveryReason": "model_error"
}
```

必须从 public room messages 中移除：

- `nodeSteps`
- `toolCalls`
- `reasoning`
- `reasoningExpanded`
- `stepsExpanded`
- `sourcesExpanded`
- `trace_id`
- `owner_id`
- `public_user_id`
- `room_token`
- `share_token`
- 原始工具输入输出

如果未来需要后台审计完整过程，应通过现有 trace/log 系统查看，而不是把内部过程写进公开房间 messages。

## Redis 结构

公开多人会话强制依赖 Redis。Redis 用于 typing 状态、房间运行锁和高频临时状态；没有 Redis 时不启用该功能。

```text
agentclaw:public-room-typing:{room_id}:{owner_id}
agentclaw:public-room-lock:{room_id}
```

typing value：

```json
{
  "nickname": "玩家A",
  "updated_at": 1710000000000
}
```

typing TTL 默认 6 秒，可通过 `AGENTCLAW_PUBLIC_ROOM_TYPING_TTL_SECONDS` 配置。

lock value：

```json
{
  "owner_id": "owner_hash",
  "nickname": "玩家A",
  "started_at": 1710000000000
}
```

lock TTL 默认 1800 秒，可通过 `AGENTCLAW_PUBLIC_ROOM_RUN_LOCK_TTL_SECONDS` 配置。

基础设施缺失时：

- `PublicRoomService` 初始化或每个 room API 入口必须检查 PostgreSQL 与 Redis。
- PostgreSQL 不可用时返回 `503 PUBLIC_ROOM_INFRA_REQUIRED`。
- Redis 不可用时返回 `503 PUBLIC_ROOM_INFRA_REQUIRED`。
- 不允许降级到进程内内存。
- 不允许仅用 PostgreSQL 模拟运行锁或 typing，因为这会让公网多人房间在多进程部署下行为不稳定。

## API 设计

### 创建房间

```http
POST /api/public/workflows/{workflow_id}/rooms
X-AgentClaw-Public-Session: 1
X-AgentClaw-Share-Token: <workflow_share_token>

{
  "nickname": "玩家A"
}
```

验证：

1. workflow 存在。
2. workflow 不是 builtin。
3. workflow 已开启 public share，且 share token 有效。
4. public page session 有效。
5. nickname 合法。
6. 创建频率未超过公开限流。

返回：

```json
{
  "room": {
    "id": "room_xxx",
    "workflow_id": "turtle_soup",
    "conversation_id": "conv_xxx",
    "status": "idle",
    "version": 1,
    "created_at": 1710000000000,
    "updated_at": 1710000000000
  },
  "room_token": "room_secret_xxx",
  "participant": {
    "nickname": "玩家A"
  }
}
```

创建动作同时：

- 创建 `agent_public_rooms` 记录。
- 创建 `agent_public_room_participants` 创建者成员记录。
- 创建 `agent_conversations` 记录，`source = "public_room"`，`owner_id = "room:<room_id>"`。

### 房间 bootstrap

```http
GET /api/public/rooms/{room_id}/bootstrap
X-AgentClaw-Public-Session: 1
X-AgentClaw-Room-Token: <room_token>
```

用途：

- 打开 room 链接时获取最小 workflow 元信息和房间状态。
- 未 join 的用户也可以调用，但必须带有效 room token。

返回：

```json
{
  "workflow": {
    "id": "turtle_soup",
    "name": "海龟汤主持人",
    "description": "生成原创海龟汤并主持多轮猜谜",
    "welcome": "欢迎来到海龟汤，请先选择想玩的汤型",
    "form_config": [],
    "input_schema": {},
    "user_input_field": "user",
    "chat_audio": {
      "enabled": false,
      "speech_input_enabled": false,
      "tts_enabled": false
    }
  },
  "room": {
    "id": "room_xxx",
    "workflow_id": "turtle_soup",
    "conversation_id": "conv_xxx",
    "status": "idle",
    "version": 1,
    "updated_at": 1710000000000
  },
  "joined": false
}
```

### 加入房间

```http
POST /api/public/rooms/{room_id}/join
X-AgentClaw-Public-Session: 1
X-AgentClaw-Room-Token: <room_token>

{
  "nickname": "玩家B"
}
```

返回：

```json
{
  "room": {
    "id": "room_xxx",
    "workflow_id": "turtle_soup",
    "conversation_id": "conv_xxx",
    "status": "idle",
    "version": 1,
    "updated_at": 1710000000000
  },
  "participant": {
    "nickname": "玩家B"
  },
  "participants": [
    {
      "nickname": "玩家A",
      "last_seen_at": 1710000000000
    },
    {
      "nickname": "玩家B",
      "last_seen_at": 1710000001000
    }
  ],
  "typing": [],
  "conversation": {
    "id": "conv_xxx",
    "messages": [],
    "updated_at": 1710000000000
  }
}
```

### 获取房间状态

```http
GET /api/public/rooms/{room_id}/state?since_version=12
X-AgentClaw-Public-Session: 1
```

要求：

- 当前 public owner 必须已经 join。
- 每次调用刷新 `last_seen_at`。

有消息或运行状态变化：

```json
{
  "room": {
    "id": "room_xxx",
    "status": "running",
    "running_nickname": "玩家A",
    "version": 13,
    "updated_at": 1710000003000
  },
  "participants": [
    {
      "nickname": "玩家A",
      "last_seen_at": 1710000003000
    }
  ],
  "typing": [
    {
      "nickname": "玩家B"
    }
  ],
  "conversation": {
    "id": "conv_xxx",
    "messages": [],
    "updated_at": 1710000003000
  },
  "messages_changed": true
}
```

仅 typing 或 participant 变化：

```json
{
  "room": {
    "id": "room_xxx",
    "status": "idle",
    "version": 13,
    "updated_at": 1710000003000
  },
  "participants": [],
  "typing": [],
  "conversation": null,
  "messages_changed": false
}
```

### 上报 typing

```http
POST /api/public/rooms/{room_id}/typing
X-AgentClaw-Public-Session: 1

{
  "typing": true
}
```

规则：

- 当前 public owner 必须已经 join。
- nickname 从 membership 读取，不相信前端传入。
- `typing=false` 时删除 typing key。
- typing TTL 到期后自动消失。

### 房间运行

```http
POST /api/public/rooms/{room_id}/run
X-AgentClaw-Public-Session: 1

{
  "response_mode": "streaming",
  "inputs": {
    "user": "问题内容"
  },
  "user": "问题内容"
}
```

规则：

- 当前 public owner 必须已经 join。
- 不接受前端传 `workflow_id` 覆盖 room workflow。
- 不接受前端传 `conversation_id` 覆盖 room conversation。
- 不接受文件输入，沿用当前 public run 的文件限制。
- 运行前原子获取 room lock。
- 获取锁失败返回 `409 ROOM_BUSY`。

`409` 响应：

```json
{
  "error": "Public room is busy",
  "code": "ROOM_BUSY",
  "running_nickname": "玩家A"
}
```

运行开始时：

1. 追加一条 user message 到 room conversation。
2. 设置 room `status = "running"`。
3. 设置 `running_by`、`running_nickname`、`running_started_at`。
4. `version += 1`。

运行结束时：

1. 从 SSE 中收集公开可见的 assistant content。
2. 追加一条 sanitized assistant message。
3. 设置 room `status = "idle"`。
4. 清理 running 字段。
5. `version += 1`。

运行异常或取消时：

1. 追加一条 sanitized assistant error message，或只更新 room status。
2. 释放 room lock。
3. `version += 1`。

运行输入注入：

- 传给 workflow 的 `user` 默认保持原始用户输入，避免破坏现有 workflow。
- 额外注入：

```json
{
  "__public_room__": {
    "room_id": "room_xxx",
    "nickname": "玩家A"
  }
}
```

需要昵称上下文的 workflow 可以自行读取 `__public_room__`。第一版不默认把昵称拼进用户输入，避免影响既有 Agent 判定逻辑。

## PublicRoomService 方法边界

建议 `PublicRoomService` 提供以下方法：

```python
class PublicRoomService:
    async def create_room(self, workflow_id: str, creator_owner_id: str, nickname: str) -> dict:
        raise NotImplementedError

    async def get_room(self, room_id: str) -> dict | None:
        raise NotImplementedError

    async def verify_room_token(self, room_id: str, room_token: str) -> bool:
        raise NotImplementedError

    async def join_room(self, room_id: str, owner_id: str, nickname: str) -> dict:
        raise NotImplementedError

    async def require_member(self, room_id: str, owner_id: str) -> dict:
        raise NotImplementedError

    async def get_state(self, room_id: str, owner_id: str, since_version: int | None) -> dict:
        raise NotImplementedError

    async def set_typing(self, room_id: str, owner_id: str, typing: bool) -> None:
        raise NotImplementedError

    async def acquire_run_lock(self, room_id: str, owner_id: str, nickname: str) -> dict:
        raise NotImplementedError

    async def release_run_lock(self, room_id: str, owner_id: str, *, failed: bool = False) -> None:
        raise NotImplementedError

    async def append_user_message(self, room_id: str, owner_id: str, content: str) -> dict:
        raise NotImplementedError

    async def append_assistant_message(self, room_id: str, content: str, status: str = "ok") -> dict:
        raise NotImplementedError
```

注意：

- `append_*` 方法内部必须读取 room 绑定的 `conversation_id`，不能信任调用方传入。
- 所有返回给 public API 的 messages 都走 sanitize。
- conversation messages 必须从 PostgreSQL `agent_conversations` 读取和追加。
- typing 与运行锁必须通过 Redis 读写。
- 如果 PostgreSQL 或 Redis 不可用，service 方法应返回明确的基础设施错误，由 router 转换为 `503 PUBLIC_ROOM_INFRA_REQUIRED`。

## execution.py 集成点

不要让前端直接调用普通 public run 再自行保存 room messages。房间运行应新增 room run 路由，内部复用工作流执行能力。

建议在 `_run_workflow_request` 增加一个明确的 room context，而不是用临时 body 字段绕过校验：

```python
public_room_context = {
    "room_id": room_id,
    "workflow_id": room["workflow_id"],
    "conversation_id": room["conversation_id"],
    "owner_id": f"room:{room_id}",
    "participant_owner_id": owner_id,
    "nickname": participant["nickname"],
}
```

room mode 下：

- `forced_workflow_id = room.workflow_id`
- `thread_id = room.conversation_id`
- `runtime_thread_id = public_runtime_thread_id(workflow_id, f"room:{room_id}", conversation_id)`
- 跳过普通 public conversation owner 校验
- 保留 public session、文件限制、输入大小限制、限流
- 在 run 前后调用 `PublicRoomService` 追加消息和更新锁

SSE 事件处理：

- 发起者仍然收到完整流式文本。
- 其他成员通过 state 轮询看到 room running。
- 第一版可以只在运行结束后把 assistant final message 写入 room conversation。
- 如果后续要让其他成员看到流式草稿，可以在 `_stream_workflow` 中加 `public_room_sink`，每 1 秒持久化一次 sanitized draft，但这不是第一版必需。

## 前端接入边界

API 层完成后，再改 public Agent 页面。

`PublicAgent.vue`：

- 读取 `room_id`、`room_token`。
- 若 URL 有 `room_token`，存入 session/local storage 后清理 URL。
- 传给 `AgentChat`：
  - `public-room-id`
  - `public-room-token`

`AgentChat.vue`：

- 无 `room_id`：保持当前普通公开会话逻辑。
- 有 `room_id`：
  - bootstrap room
  - 无昵称时弹昵称输入
  - join room
  - 启动 state polling
  - send 时调用 room run
  - typing 节流调用 room typing
  - state 返回 messages 时只更新 `messages`，不覆盖 `inputText`
  - room running 时禁用发送

公开模式隐藏过程：

- `hasProcessMessages` 在 public mode 下返回 false。
- `ChatMessage` public mode 下不展示 `nodeSteps`、`toolCalls`、`reasoning`。
- `StreamingMessage` public mode 下不展示过程卡片，只显示普通回复状态。
- 后台 `AgentChat` 不受影响。

## 测试计划

API 测试优先：

1. 创建 room 必须有有效 workflow share token。
2. room token 只对对应 room 有效。
3. 未 join 成员不能调用 state、typing、run。
4. A 创建 room，B 用 room token join 后可以读取同一 conversation。
5. 普通 `source=public` conversation 仍然按 owner 隔离。
6. room run 忽略前端传入的 workflow_id/conversation_id。
7. room running 时第二个 run 返回 409。
8. run 结束后释放锁并递增 version。
9. typing true 后其他成员 state 可见，TTL 后消失。
10. public room state 返回的 messages 不包含 nodeSteps/toolCalls/reasoning/token/hash。
11. PostgreSQL 不可用时 room API 返回 `503 PUBLIC_ROOM_INFRA_REQUIRED`。
12. Redis 不可用时 room API 返回 `503 PUBLIC_ROOM_INFRA_REQUIRED`。
13. PostgreSQL DDL 是幂等的。

前端测试：

1. 普通公开页面无 room_id 时保持原有会话逻辑。
2. room 链接会读取并清理 room_token。
3. 未加入 room 时展示昵称输入。
4. polling 更新 messages 不覆盖输入框草稿。
5. `status=running` 时禁用发送并显示运行提示。
6. typing 状态显示其他成员昵称。
7. public mode 不渲染过程展开按钮、nodeSteps、toolCalls、reasoning。
8. 发送 room message 调用 `/api/public/rooms/{room_id}/run`，不调用普通 public workflow run。

## 配置项

建议新增：

```text
AGENTCLAW_PUBLIC_ROOM_TOKEN_BYTES=32
AGENTCLAW_PUBLIC_ROOM_NICKNAME_MAX_LENGTH=24
AGENTCLAW_PUBLIC_ROOM_MAX_PARTICIPANTS=50
AGENTCLAW_PUBLIC_ROOM_TYPING_TTL_SECONDS=6
AGENTCLAW_PUBLIC_ROOM_RUN_LOCK_TTL_SECONDS=1800
AGENTCLAW_PUBLIC_ROOM_STALE_RUN_SECONDS=1800
AGENTCLAW_PUBLIC_ROOM_STATE_RATE_LIMIT=90/min
AGENTCLAW_PUBLIC_ROOM_TYPING_RATE_LIMIT=30/min
AGENTCLAW_PUBLIC_ROOM_CREATE_RATE_LIMIT=10/hour
```

默认值必须保守，避免公网匿名入口被刷爆。

## 实施顺序

第一阶段，只做 API：

1. 新增 public room schemas。
2. 新增 `PublicRoomService`，强制检查 PostgreSQL 与 Redis，不提供内存 fallback。
3. 新增 room token hash、nickname normalize、message sanitize 工具。
4. 新增 `agent_public_rooms`、`agent_public_room_participants` 幂等建表。
5. 新增 room create/bootstrap/join/state/typing API。
6. 新增 room run API 与 execution 集成。
7. 完成 API 测试。

第二阶段，再做 public Agent 页面：

1. `PublicAgent.vue` 接 room 参数和 URL token 清理。
2. `AgentChat.vue` 增加 room mode。
3. 增加昵称弹层、创建公开会话、复制房间链接。
4. 增加 polling、typing、running 禁发。
5. 公开模式隐藏过程。
6. 完成前端测试和 build。

## 风险与规避

1. **猜 conversation_id 读取房间。**  
   规避：room conversation 只能通过 room API 读取，普通 public conversation API 继续 owner 隔离。

2. **room token 泄漏到日志。**  
   规避：API 只收 header，不收 query/body；前端清理 URL；日志过滤 token header。

3. **多人并发覆盖 messages。**  
   规避：第一版不提供 public room messages overwrite；消息由后端 append。

4. **运行中并发写 checkpoint。**  
   规避：后端 room run lock，使用 Redis `SET NX EX` 原子获取锁。

5. **进程崩溃导致房间永久 running。**  
   规避：running stale timeout。

6. **公开 API 泄露节点状态。**  
   规避：room state 只返回 sanitized messages；公开页面也隐藏过程。

7. **轮询流量过大。**  
   规避：`since_version` 无变化不返回 messages；后台标签页降频；专用限流。

8. **无 PostgreSQL 或 Redis 时状态不可靠。**  
   规避：公开多人会话强制要求 PostgreSQL 与 Redis。基础设施缺失时 API 返回 `503 PUBLIC_ROOM_INFRA_REQUIRED`，前端隐藏或禁用入口。

9. **昵称 XSS。**  
   规避：后端去控制字符和长度限制；前端文本转义展示。

10. **room 访问绕过 workflow 公开配置。**  
    规避：创建 room 时必须验证 workflow public share；room 存在后用 room token 访问该 room，但不能枚举或访问其它 workflow。

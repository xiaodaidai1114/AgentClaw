"""Service for anonymous public multi-user rooms."""

from __future__ import annotations

import hashlib
import asyncio
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Optional

from agentclaw.database import get_database
from agentclaw.utils.security import safe_compare_digest


PUBLIC_ROOM_SOURCE = "public_room"
PUBLIC_ROOM_INFRA_ERROR = "PUBLIC_ROOM_INFRA_REQUIRED"
PUBLIC_ROOM_BUSY = "ROOM_BUSY"
PUBLIC_ROOM_NICKNAME_TAKEN = "PUBLIC_ROOM_NICKNAME_TAKEN"
PUBLIC_ROOM_MAX_EXPIRES_DAYS = 30

_SECRET_MESSAGE_KEYS = {
    "toolCalls",
    "reasoning",
    "reasoningExpanded",
    "stepsExpanded",
    "sourcesExpanded",
    "trace_id",
    "owner_id",
    "public_user_id",
    "room_token",
    "share_token",
}


def _format_node_elapsed(value: Any) -> str | None:
    try:
        elapsed = float(value)
    except (TypeError, ValueError):
        return None
    if elapsed < 0:
        return None
    if elapsed < 1:
        return f"{round(elapsed * 1000)}ms"
    return f"{elapsed:.1f}s"


def sanitize_public_room_node_step(step: Any) -> dict[str, Any] | None:
    if not isinstance(step, dict):
        return None
    node_id = str(step.get("id") or step.get("node_id") or step.get("node") or "").strip()
    if not node_id:
        return None
    node_type = str(step.get("type") or step.get("node_type") or "").strip() or "unknown"
    status = str(step.get("status") or "succeeded").strip() or "succeeded"
    elapsed = step.get("elapsed")
    if elapsed is None:
        elapsed = _format_node_elapsed(step.get("elapsed_time"))
    else:
        elapsed = str(elapsed)
    return {
        "id": node_id,
        "name": str(step.get("name") or step.get("title") or node_id),
        "type": node_type,
        "typeLabel": str(step.get("typeLabel") or step.get("type_label") or node_type),
        "status": status,
        "elapsed": elapsed,
        "parallelGroupId": step.get("parallelGroupId") or step.get("parallel_group_id"),
    }


def sanitize_public_room_node_steps(value: Any) -> list[dict[str, Any]]:
    decoded = _decode_json(value, [])
    if not isinstance(decoded, list):
        return []
    return [
        sanitized
        for step in decoded
        if (sanitized := sanitize_public_room_node_step(step))
    ]


class PublicRoomInfraError(RuntimeError):
    """Raised when PostgreSQL or Redis is unavailable for public rooms."""


class PublicRoomAccessError(RuntimeError):
    """Raised when room token or membership is invalid."""


class PublicRoomBusyError(RuntimeError):
    def __init__(self, running_nickname: str = ""):
        self.running_nickname = running_nickname
        super().__init__("Public room is busy")


class PublicRoomNicknameTakenError(RuntimeError):
    """Raised when another member already uses the requested nickname."""


def _now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def _day_ms() -> int:
    return 24 * 60 * 60 * 1000


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip() or 0)
    except ValueError:
        value = 0
    return value if value > 0 else default


def _token_bytes() -> int:
    return _env_int("AGENTCLAW_PUBLIC_ROOM_TOKEN_BYTES", 32)


def _nickname_max_length() -> int:
    return _env_int("AGENTCLAW_PUBLIC_ROOM_NICKNAME_MAX_LENGTH", 24)


def _typing_ttl_seconds() -> int:
    return _env_int("AGENTCLAW_PUBLIC_ROOM_TYPING_TTL_SECONDS", 6)


def _lock_ttl_seconds() -> int:
    return _env_int("AGENTCLAW_PUBLIC_ROOM_RUN_LOCK_TTL_SECONDS", 1800)


def normalize_public_room_expires_days(value: int | str | None) -> int:
    try:
        days = int(value or 7)
    except (TypeError, ValueError):
        days = 7
    return max(1, min(days, PUBLIC_ROOM_MAX_EXPIRES_DAYS))


def _event_ping_seconds() -> int:
    return _env_int("AGENTCLAW_PUBLIC_ROOM_EVENT_PING_SECONDS", 15)


def normalize_public_room_nickname(value: str) -> str:
    text = "".join(ch for ch in str(value or "").strip() if ch.isprintable())
    text = " ".join(text.split())
    max_len = _nickname_max_length()
    if len(text) > max_len:
        text = text[:max_len]
    return text


def hash_room_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def verify_room_token_hash(expected_hash: str, token: str) -> bool:
    return safe_compare_digest(expected_hash, hash_room_token(token))


def public_room_owner_id(room_id: str) -> str:
    return f"room:{room_id}"


def _room_id() -> str:
    return f"room_{secrets.token_urlsafe(_token_bytes())}"


def _room_token() -> str:
    return f"room_secret_{secrets.token_urlsafe(_token_bytes())}"


def _conversation_id() -> str:
    return f"conv_{secrets.token_hex(12)}"


def _decode_json(value: Any, fallback: Any):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return fallback
    return fallback


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _room_event_channel(room_id: str) -> str:
    return f"agentclaw:public-room-events:{room_id}"


def sanitize_public_room_message(message: Any, room_id: str) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None
    role = str(message.get("role") or "").strip()
    if role not in {"user", "assistant"}:
        return None
    sanitized = {
        "role": role,
        "content": str(message.get("content") or ""),
        "timestamp": int(message.get("timestamp") or _now_ms()),
        "public_room": {"room_id": room_id},
    }
    if role == "user":
        sender = message.get("sender")
        nickname = ""
        if isinstance(sender, dict):
            nickname = normalize_public_room_nickname(sender.get("nickname") or "")
        sanitized["sender_type"] = "public_room_participant"
        sanitized["sender"] = {"nickname": nickname}
    else:
        sanitized["sender_type"] = "agent"
        status = str(message.get("deliveryStatus") or "ok")
        sanitized["deliveryStatus"] = status
        if message.get("deliveryReason"):
            sanitized["deliveryReason"] = str(message.get("deliveryReason"))
        node_steps = sanitize_public_room_node_steps(message.get("nodeSteps"))
        if node_steps:
            sanitized["nodeSteps"] = node_steps
    for key in _SECRET_MESSAGE_KEYS:
        sanitized.pop(key, None)
    return sanitized


def sanitize_public_room_messages(messages: Any, room_id: str) -> list[dict[str, Any]]:
    return [
        sanitized
        for message in _decode_json(messages, [])
        if (sanitized := sanitize_public_room_message(message, room_id))
    ]


@dataclass
class PublicRoomService:
    _tables_ready: bool = False

    async def _get_pool(self):
        db = get_database()
        pool = getattr(db, "pg_pool", None) if db else None
        if not pool:
            raise PublicRoomInfraError("PostgreSQL is required for public rooms")
        return pool

    def _get_redis(self):
        db = get_database()
        getter = getattr(db, "get_sync_redis_client", None) if db else None
        client = getter() if callable(getter) else None
        if not client:
            raise PublicRoomInfraError("Redis is required for public rooms")
        return client

    async def publish_room_event(self, room_id: str, event: dict[str, Any]) -> None:
        redis = self._get_redis()
        payload = {
            **event,
            "room_id": room_id,
            "created_at": int(event.get("created_at") or _now_ms()),
        }
        redis.publish(_room_event_channel(room_id), _json_dumps(payload))

    async def iter_room_events(self, room_id: str) -> AsyncIterator[dict[str, Any]]:
        redis = self._get_redis()
        pubsub = redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(_room_event_channel(room_id))
        last_ping = time.monotonic()
        ping_seconds = _event_ping_seconds()
        try:
            while True:
                message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                if message and message.get("type") == "message":
                    yield _decode_json(message.get("data"), {})
                    last_ping = time.monotonic()
                    continue
                if time.monotonic() - last_ping >= ping_seconds:
                    yield {"event": "ping", "room_id": room_id, "created_at": _now_ms()}
                    last_ping = time.monotonic()
                await asyncio.sleep(0.1)
        finally:
            try:
                pubsub.unsubscribe(_room_event_channel(room_id))
                close = getattr(pubsub, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass

    async def ensure_infra(self) -> None:
        await self._get_pool()
        self._get_redis()

    async def _ensure_tables(self) -> None:
        if self._tables_ready:
            return
        pool = await self._get_pool()
        await pool.execute(
            """
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
                expires_at BIGINT,
                revoked_at BIGINT
            )
            """
        )
        await pool.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_public_room_participants (
                room_id VARCHAR(80) NOT NULL,
                owner_id VARCHAR(100) NOT NULL,
                nickname VARCHAR(80) NOT NULL,
                joined_at BIGINT NOT NULL,
                last_seen_at BIGINT NOT NULL,
                kicked_at BIGINT,
                PRIMARY KEY (room_id, owner_id)
            )
            """
        )
        await pool.execute("ALTER TABLE agent_public_rooms ADD COLUMN IF NOT EXISTS expires_at BIGINT")
        await pool.execute(
            f"UPDATE agent_public_rooms SET expires_at = created_at + {PUBLIC_ROOM_MAX_EXPIRES_DAYS * _day_ms()} WHERE expires_at IS NULL"
        )
        await pool.execute("ALTER TABLE agent_public_room_participants ADD COLUMN IF NOT EXISTS kicked_at BIGINT")
        await pool.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_public_rooms_workflow ON agent_public_rooms(workflow_id)"
        )
        await pool.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_public_rooms_expires ON agent_public_rooms(expires_at)"
        )
        await pool.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_public_room_participants_seen ON agent_public_room_participants(room_id, last_seen_at DESC)"
        )
        self._tables_ready = True

    async def create_room(
        self,
        workflow_id: str,
        creator_owner_id: str,
        nickname: str,
        expires_in_days: int | str | None = 7,
    ) -> dict[str, Any]:
        await self.ensure_infra()
        await self._ensure_tables()
        nickname = normalize_public_room_nickname(nickname)
        if not nickname:
            raise ValueError("nickname is required")
        pool = await self._get_pool()
        now = _now_ms()
        expires_at = now + normalize_public_room_expires_days(expires_in_days) * _day_ms()
        room_id = _room_id()
        token = _room_token()
        conversation_id = _conversation_id()
        room = await pool.fetchrow(
            """
            INSERT INTO agent_public_rooms (
                id, workflow_id, conversation_id, room_token_hash,
                created_by, created_at, updated_at, expires_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $6, $7)
            RETURNING id, workflow_id, conversation_id, room_token_hash, status,
                      running_by, running_nickname, running_started_at,
                      created_by, version, created_at, updated_at, expires_at, revoked_at
            """,
            room_id,
            workflow_id,
            conversation_id,
            hash_room_token(token),
            creator_owner_id,
            now,
            expires_at,
        )
        participant = await self.join_room(room_id, creator_owner_id, nickname, verify_existing=False)
        conv = {
            "id": conversation_id,
            "workflow_id": workflow_id,
            "title": "公开会话",
            "messages": _json_dumps([]),
            "source": PUBLIC_ROOM_SOURCE,
            "owner_id": public_room_owner_id(room_id),
            "user_id": None,
            "tenant_id": None,
            "checkpoint_expired_at": None,
            "created_at": now,
            "updated_at": now,
        }
        if hasattr(pool, "insert_conversation"):
            await pool.insert_conversation(conv)
        else:
            await pool.execute(
                """
                INSERT INTO agent_conversations (
                    id, workflow_id, title, messages, source,
                    owner_id, user_id, tenant_id, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                conversation_id,
                workflow_id,
                conv["title"],
                conv["messages"],
                PUBLIC_ROOM_SOURCE,
                public_room_owner_id(room_id),
                None,
                None,
                now,
                now,
            )
        room_payload = self.public_room_payload(dict(room))
        return {"room": room_payload, "room_token": token, "participant": participant}

    async def get_room(
        self,
        room_id: str,
        *,
        include_expired: bool = False,
        include_revoked: bool = False,
    ) -> dict[str, Any] | None:
        await self.ensure_infra()
        await self._ensure_tables()
        pool = await self._get_pool()
        room = await pool.fetchrow(
            """
            SELECT id, workflow_id, conversation_id, room_token_hash, status,
                   running_by, running_nickname, running_started_at,
                   created_by, version, created_at, updated_at, expires_at, revoked_at
            FROM agent_public_rooms
            WHERE id = $1
            """,
            room_id,
        )
        if not room:
            return None
        room = dict(room)
        if not include_revoked and room.get("revoked_at"):
            return None
        expires_at = int(room.get("expires_at") or 0)
        if not include_expired and expires_at <= _now_ms():
            return None
        return room

    async def verify_room_token(self, room_id: str, room_token: str) -> bool:
        room = await self.get_room(room_id)
        if not room:
            return False
        return verify_room_token_hash(str(room.get("room_token_hash") or ""), room_token)

    async def join_room(self, room_id: str, owner_id: str, nickname: str, *, verify_existing: bool = True) -> dict[str, Any]:
        await self.ensure_infra()
        await self._ensure_tables()
        if verify_existing and not await self.get_room(room_id):
            raise PublicRoomAccessError("Room not found")
        nickname = normalize_public_room_nickname(nickname)
        if not nickname:
            raise ValueError("nickname is required")
        pool = await self._get_pool()
        now = _now_ms()
        await self._ensure_member_not_kicked(room_id, owner_id)
        redis = self._get_redis()
        lock_key = self._join_lock_key(room_id)
        if not redis.set(lock_key, owner_id, nx=True, ex=10):
            raise PublicRoomNicknameTakenError("Public room join is busy")
        try:
            await self._ensure_nickname_available(room_id, owner_id, nickname)
            if hasattr(pool, "insert_participant"):
                participant = await pool.insert_participant(room_id, owner_id, nickname, now)
            else:
                participant = await pool.fetchrow(
                    """
                    INSERT INTO agent_public_room_participants (
                        room_id, owner_id, nickname, joined_at, last_seen_at
                    )
                    VALUES ($1, $2, $3, $4, $4)
                    ON CONFLICT (room_id, owner_id)
                    DO UPDATE SET nickname = $3, last_seen_at = $4
                    RETURNING room_id, owner_id, nickname, joined_at, last_seen_at, kicked_at
                    """,
                    room_id,
                    owner_id,
                    nickname,
                    now,
                )
        finally:
            redis.delete(lock_key)
        return self.public_participant_payload(dict(participant))

    async def require_member(self, room_id: str, owner_id: str) -> dict[str, Any]:
        await self.ensure_infra()
        await self._ensure_tables()
        pool = await self._get_pool()
        participant = await pool.fetchrow(
            """
            SELECT room_id, owner_id, nickname, joined_at, last_seen_at, kicked_at
            FROM agent_public_room_participants
            WHERE room_id = $1 AND owner_id = $2
            """,
            room_id,
            owner_id,
        )
        if not participant or participant.get("kicked_at"):
            raise PublicRoomAccessError("Public room membership is required")
        return dict(participant)

    async def touch_member(self, room_id: str, owner_id: str) -> None:
        pool = await self._get_pool()
        now = _now_ms()
        participant = await self.require_member(room_id, owner_id)
        if hasattr(pool, "insert_participant"):
            await pool.insert_participant(room_id, owner_id, participant["nickname"], now)
            return
        await pool.execute(
            """
            UPDATE agent_public_room_participants
            SET last_seen_at = $3
            WHERE room_id = $1 AND owner_id = $2
            """,
            room_id,
            owner_id,
            now,
        )

    async def list_participants(self, room_id: str) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            SELECT nickname, last_seen_at
            FROM agent_public_room_participants
            WHERE room_id = $1 AND kicked_at IS NULL
            ORDER BY last_seen_at DESC
            LIMIT 50
            """,
            room_id,
        )
        return [self.public_participant_payload(dict(row)) for row in rows]

    def _typing_key(self, room_id: str, owner_id: str) -> str:
        return f"agentclaw:public-room-typing:{room_id}:{owner_id}"

    def _typing_prefix(self, room_id: str) -> str:
        return f"agentclaw:public-room-typing:{room_id}:"

    async def set_typing(self, room_id: str, owner_id: str, typing: bool) -> None:
        participant = await self.require_member(room_id, owner_id)
        redis = self._get_redis()
        key = self._typing_key(room_id, owner_id)
        if not typing:
            redis.delete(key)
            return
        redis.setex(
            key,
            _typing_ttl_seconds(),
            _json_dumps({"nickname": participant["nickname"], "updated_at": _now_ms()}),
        )

    async def list_typing(self, room_id: str, exclude_owner_id: str = "") -> list[dict[str, Any]]:
        redis = self._get_redis()
        typing = []
        for key in redis.scan_iter(match=f"{self._typing_prefix(room_id)}*"):
            key_text = key.decode("utf-8") if isinstance(key, bytes) else str(key)
            owner_id = key_text.rsplit(":", 1)[-1]
            if owner_id == exclude_owner_id:
                continue
            payload = _decode_json(redis.get(key), {})
            nickname = normalize_public_room_nickname(payload.get("nickname") if isinstance(payload, dict) else "")
            if nickname:
                typing.append({"nickname": nickname, "last_seen_at": int(payload.get("updated_at") or 0)})
        return typing

    async def get_conversation(self, room: dict[str, Any]) -> dict[str, Any]:
        pool = await self._get_pool()
        conv = await pool.fetchrow(
            """
            SELECT id, workflow_id, title, messages,
                   COALESCE(source, 'admin') as source,
                   owner_id, user_id, tenant_id,
                   checkpoint_expired_at,
                   created_at, updated_at
            FROM agent_conversations
            WHERE id = $1 AND workflow_id = $2
              AND COALESCE(source, 'admin') = $3
              AND owner_id = $4
            """,
            room["conversation_id"],
            room["workflow_id"],
            PUBLIC_ROOM_SOURCE,
            public_room_owner_id(room["id"]),
        )
        if not conv:
            return {"id": room["conversation_id"], "messages": [], "updated_at": int(room.get("updated_at") or 0)}
        conv = dict(conv)
        return {
            "id": conv["id"],
            "messages": sanitize_public_room_messages(conv.get("messages"), room["id"]),
            "updated_at": int(conv.get("updated_at") or 0),
        }

    async def _set_conversation_messages(self, room: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
        pool = await self._get_pool()
        now = _now_ms()
        title = "公开会话"
        first_user = next((msg for msg in messages if msg.get("role") == "user"), None)
        if first_user:
            content = str(first_user.get("content") or "")
            title = "[公开会话] " + content[:20] + ("..." if len(content) > 20 else "")
        messages_json = _json_dumps(messages)
        row = await pool.fetchrow(
            """
            UPDATE agent_conversations
            SET title = $3, messages = $4, updated_at = $5
            WHERE id = $1 AND workflow_id = $2
              AND COALESCE(source, 'admin') = $6
              AND owner_id = $7
            RETURNING id, workflow_id, title, messages,
                      COALESCE(source, 'admin') as source,
                      owner_id, user_id, tenant_id,
                      checkpoint_expired_at,
                      created_at, updated_at
            """,
            room["conversation_id"],
            room["workflow_id"],
            title,
            messages_json,
            now,
            PUBLIC_ROOM_SOURCE,
            public_room_owner_id(room["id"]),
        )
        return dict(row) if row else {"id": room["conversation_id"], "messages": messages_json, "updated_at": now}

    async def _bump_room_version(self, room_id: str) -> dict[str, Any]:
        pool = await self._get_pool()
        now = _now_ms()
        await pool.execute(
            """
            UPDATE agent_public_rooms
            SET version = version + 1, updated_at = $2
            WHERE id = $1
            """,
            room_id,
            now,
        )
        return await self.get_room(room_id) or {}

    async def append_user_message(self, room_id: str, owner_id: str, content: str) -> dict[str, Any]:
        room = await self.get_room(room_id)
        if not room:
            raise PublicRoomAccessError("Room not found")
        participant = await self.require_member(room_id, owner_id)
        conv = await self.get_conversation(room)
        messages = list(conv.get("messages") or [])
        messages.append(
            {
                "role": "user",
                "content": str(content or ""),
                "timestamp": _now_ms(),
                "sender_type": "public_room_participant",
                "sender": {"nickname": participant["nickname"]},
                "public_room": {"room_id": room_id},
            }
        )
        await self._set_conversation_messages(room, messages)
        await self._bump_room_version(room_id)
        return messages[-1]

    async def append_assistant_message(
        self,
        room_id: str,
        content: str,
        status: str = "ok",
        reason: str = "",
        node_steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        room = await self.get_room(room_id)
        if not room:
            raise PublicRoomAccessError("Room not found")
        conv = await self.get_conversation(room)
        messages = list(conv.get("messages") or [])
        message = {
            "role": "assistant",
            "content": str(content or ""),
            "timestamp": _now_ms(),
            "sender_type": "agent",
            "public_room": {"room_id": room_id},
            "deliveryStatus": status,
        }
        if reason:
            message["deliveryReason"] = reason
        safe_node_steps = sanitize_public_room_node_steps(node_steps or [])
        if safe_node_steps:
            message["nodeSteps"] = safe_node_steps
        messages.append(message)
        await self._set_conversation_messages(room, messages)
        await self._bump_room_version(room_id)
        return message

    def _lock_key(self, room_id: str) -> str:
        return f"agentclaw:public-room-lock:{room_id}"

    def _join_lock_key(self, room_id: str) -> str:
        return f"agentclaw:public-room-join-lock:{room_id}"

    async def _ensure_member_not_kicked(self, room_id: str, owner_id: str) -> None:
        pool = await self._get_pool()
        participant = await pool.fetchrow(
            """
            SELECT room_id, owner_id, nickname, joined_at, last_seen_at, kicked_at
            FROM agent_public_room_participants
            WHERE room_id = $1 AND owner_id = $2
            """,
            room_id,
            owner_id,
        )
        if participant and participant.get("kicked_at"):
            raise PublicRoomAccessError("Public room member was removed")

    async def _ensure_nickname_available(self, room_id: str, owner_id: str, nickname: str) -> None:
        pool = await self._get_pool()
        existing = await pool.fetchrow(
            """
            SELECT room_id, owner_id, nickname, joined_at, last_seen_at, kicked_at
            FROM agent_public_room_participants
            WHERE room_id = $1 AND nickname = $2
              AND kicked_at IS NULL
            LIMIT 1
            """,
            room_id,
            nickname,
        )
        if existing and existing["owner_id"] != owner_id:
            raise PublicRoomNicknameTakenError("Nickname is already used in this public room")

    async def acquire_run_lock(self, room_id: str, owner_id: str, nickname: str) -> dict[str, Any]:
        room = await self.get_room(room_id)
        if not room:
            raise PublicRoomAccessError("Room not found")
        if room.get("status") == "running":
            raise PublicRoomBusyError(str(room.get("running_nickname") or ""))
        redis = self._get_redis()
        payload = _json_dumps({"owner_id": owner_id, "nickname": nickname, "started_at": _now_ms()})
        acquired = redis.set(self._lock_key(room_id), payload, nx=True, ex=_lock_ttl_seconds())
        if not acquired:
            existing = _decode_json(redis.get(self._lock_key(room_id)), {})
            raise PublicRoomBusyError(str(existing.get("nickname") or room.get("running_nickname") or ""))
        pool = await self._get_pool()
        now = _now_ms()
        status = await pool.execute(
            """
            UPDATE agent_public_rooms
            SET status = 'running',
                running_by = $2,
                running_nickname = $3,
                running_started_at = $4,
                version = version + 1,
                updated_at = $4
            WHERE id = $1 AND status <> 'running'
            """,
            room_id,
            owner_id,
            nickname,
            now,
        )
        if str(status).upper().startswith("UPDATE 0"):
            redis.delete(self._lock_key(room_id))
            fresh = await self.get_room(room_id) or {}
            raise PublicRoomBusyError(str(fresh.get("running_nickname") or ""))
        return await self.get_room(room_id) or room

    async def release_run_lock(self, room_id: str, owner_id: str, *, failed: bool = False) -> None:
        redis = self._get_redis()
        redis.delete(self._lock_key(room_id))
        pool = await self._get_pool()
        now = _now_ms()
        await pool.execute(
            """
            UPDATE agent_public_rooms
            SET status = 'idle',
                running_by = NULL,
                running_nickname = NULL,
                running_started_at = NULL,
                version = version + 1,
                updated_at = $3
            WHERE id = $1 AND running_by = $2
            """,
            room_id,
            owner_id,
            now,
        )

    async def get_state(self, room_id: str, owner_id: str, since_version: int | None = None) -> dict[str, Any]:
        room = await self.get_room(room_id)
        if not room:
            raise PublicRoomAccessError("Room not found")
        await self.touch_member(room_id, owner_id)
        room = await self.get_room(room_id) or room
        messages_changed = since_version is None or int(room.get("version") or 0) != int(since_version or 0)
        conversation = await self.get_conversation(room) if messages_changed else None
        return {
            "room": self.public_room_payload(room),
            "participants": await self.list_participants(room_id),
            "typing": await self.list_typing(room_id, exclude_owner_id=owner_id),
            "conversation": conversation,
            "messages_changed": messages_changed,
        }

    @staticmethod
    def admin_room_status(room: dict[str, Any]) -> str:
        if room.get("revoked_at"):
            return "deleted"
        expires_at = int(room.get("expires_at") or 0)
        if expires_at and expires_at <= _now_ms():
            return "expired"
        if str(room.get("status") or "") == "running":
            return "running"
        return "active"

    async def list_admin_rooms(
        self,
        *,
        workflow_id: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        await self.ensure_infra()
        await self._ensure_tables()
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            SELECT id, workflow_id, conversation_id, room_token_hash, status,
                   running_by, running_nickname, running_started_at,
                   created_by, version, created_at, updated_at, expires_at, revoked_at
            FROM agent_public_rooms
            ORDER BY updated_at DESC
            """
        )
        normalized_status = str(status or "").strip()
        rooms = []
        for row in rows:
            room = dict(row)
            if workflow_id and room.get("workflow_id") != workflow_id:
                continue
            lifecycle_status = self.admin_room_status(room)
            if normalized_status and lifecycle_status != normalized_status:
                continue
            participant_count = await pool.fetchval(
                """
                SELECT COUNT(*)
                FROM agent_public_room_participants
                WHERE room_id = $1 AND kicked_at IS NULL
                """,
                room["id"],
            )
            rooms.append(
                {
                    **self.public_room_payload(room),
                    "lifecycle_status": lifecycle_status,
                    "participant_count": int(participant_count or 0),
                    "revoked_at": int(room.get("revoked_at") or 0) or None,
                }
            )
        total = len(rooms)
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 50), 100))
        offset = (page - 1) * page_size
        return {"rooms": rooms[offset : offset + page_size], "total": total, "page": page, "page_size": page_size}

    async def get_admin_room_detail(self, room_id: str) -> dict[str, Any] | None:
        room = await self.get_room(room_id, include_expired=True, include_revoked=True)
        if not room:
            return None
        return {
            "room": {
                **self.public_room_payload(room),
                "lifecycle_status": self.admin_room_status(room),
                "revoked_at": int(room.get("revoked_at") or 0) or None,
            },
            "participants": await self.list_admin_participants(room_id),
            "conversation": await self.get_conversation(room),
        }

    async def list_admin_participants(self, room_id: str) -> list[dict[str, Any]]:
        await self.ensure_infra()
        await self._ensure_tables()
        pool = await self._get_pool()
        rows = await pool.fetch(
            """
            SELECT room_id, owner_id, nickname, joined_at, last_seen_at, kicked_at
            FROM agent_public_room_participants
            WHERE room_id = $1
            ORDER BY kicked_at ASC NULLS FIRST, last_seen_at DESC
            """,
            room_id,
        )
        return [
            {
                "owner_id": str(row.get("owner_id") or ""),
                "nickname": str(row.get("nickname") or ""),
                "joined_at": int(row.get("joined_at") or 0),
                "last_seen_at": int(row.get("last_seen_at") or 0),
                "kicked_at": int(row.get("kicked_at") or 0) or None,
            }
            for row in map(dict, rows)
        ]

    async def kick_participant(self, room_id: str, owner_id: str) -> bool:
        await self.ensure_infra()
        await self._ensure_tables()
        pool = await self._get_pool()
        now = _now_ms()
        status = await pool.execute(
            """
            UPDATE agent_public_room_participants
            SET kicked_at = $3, last_seen_at = $3
            WHERE room_id = $1 AND owner_id = $2 AND kicked_at IS NULL
            """,
            room_id,
            owner_id,
            now,
        )
        success = not str(status).upper().startswith("UPDATE 0")
        if success:
            await self._bump_room_version(room_id)
        return success

    async def revoke_room(self, room_id: str) -> bool:
        await self.ensure_infra()
        await self._ensure_tables()
        redis = self._get_redis()
        redis.delete(self._lock_key(room_id))
        pool = await self._get_pool()
        now = _now_ms()
        status = await pool.execute(
            """
            UPDATE agent_public_rooms
            SET revoked_at = $2,
                status = 'idle',
                running_by = NULL,
                running_nickname = NULL,
                running_started_at = NULL,
                version = version + 1,
                updated_at = $2
            WHERE id = $1 AND revoked_at IS NULL
            """,
            room_id,
            now,
        )
        return not str(status).upper().startswith("UPDATE 0")

    @staticmethod
    def public_room_payload(room: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": room["id"],
            "workflow_id": room["workflow_id"],
            "conversation_id": room["conversation_id"],
            "status": room.get("status") or "idle",
            "running_nickname": room.get("running_nickname"),
            "version": int(room.get("version") or 1),
            "created_at": int(room.get("created_at") or 0),
            "updated_at": int(room.get("updated_at") or 0),
            "expires_at": int(room.get("expires_at") or 0),
        }

    @staticmethod
    def public_participant_payload(participant: dict[str, Any]) -> dict[str, Any]:
        return {
            "nickname": str(participant.get("nickname") or ""),
            "last_seen_at": int(participant.get("last_seen_at") or 0),
        }


_public_room_service: Optional[PublicRoomService] = None


def get_public_room_service() -> PublicRoomService:
    global _public_room_service
    if _public_room_service is None:
        _public_room_service = PublicRoomService()
    return _public_room_service


def reset_public_room_service() -> None:
    global _public_room_service
    _public_room_service = None

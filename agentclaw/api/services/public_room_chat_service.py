"""Service for public room player-to-player chat messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
import secrets
from typing import Any, Optional

from agentclaw.api.services.public_sensitive_words_service import mask_public_sensitive_words
from agentclaw.api.services.safety_guard_service import MASKED_PUBLIC_CONTENT, check_public_content_safety
from agentclaw.database import get_database


def _now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip() or 0)
    except ValueError:
        value = 0
    return value if value > 0 else default


def _message_id() -> str:
    return f"chat_{secrets.token_urlsafe(18)}"


def public_room_chat_max_length() -> int:
    return _env_int("AGENTCLAW_PUBLIC_ROOM_CHAT_MAX_LENGTH", 500)


def public_room_chat_cooldown_seconds() -> int:
    raw_value = os.getenv("AGENTCLAW_PUBLIC_ROOM_CHAT_COOLDOWN_SECONDS", "").strip()
    if not raw_value:
        return 2
    try:
        value = int(raw_value)
    except ValueError:
        return 2
    return max(0, value)


class PublicRoomChatThrottleError(RuntimeError):
    def __init__(self, retry_after: int):
        self.retry_after = max(1, int(retry_after or 1))
        super().__init__(f"发送太频繁，请 {self.retry_after} 秒后再试")


def normalize_public_room_chat_content(value: Any) -> str:
    text = "".join(ch for ch in str(value or "").strip() if ch.isprintable())
    text = " ".join(text.split())
    max_len = public_room_chat_max_length()
    if not text:
        raise ValueError("content is required")
    if len(text) > max_len:
        raise ValueError(f"content exceeds {max_len} characters")
    return text


@dataclass
class PublicRoomChatService:
    _tables_ready: bool = False

    @staticmethod
    def _cooldown_key(room_id: str, owner_id: str) -> str:
        digest = hashlib.sha256(f"{room_id}:{owner_id}".encode("utf-8")).hexdigest()[:32]
        return f"agentclaw:public-room-chat-cooldown:{digest}"

    async def _get_pool(self):
        db = get_database()
        pool = getattr(db, "pg_pool", None) if db else None
        if not pool:
            from agentclaw.api.services.public_room_service import PublicRoomInfraError

            raise PublicRoomInfraError("PostgreSQL is required for public rooms")
        return pool

    @staticmethod
    def _get_redis_client():
        db = get_database()
        client_getter = getattr(db, "get_sync_redis_client", None) if db else None
        return client_getter() if callable(client_getter) else None

    @staticmethod
    def _redis_retry_after(client: Any, key: str, default_seconds: int) -> int:
        ttl = getattr(client, "ttl", None)
        if not callable(ttl):
            return default_seconds
        try:
            value = int(ttl(key))
        except Exception:
            return default_seconds
        return value if value > 0 else default_seconds

    async def _ensure_tables(self) -> None:
        if self._tables_ready:
            return
        pool = await self._get_pool()
        await pool.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_public_room_chat_messages (
                id VARCHAR(80) PRIMARY KEY,
                sequence_id BIGSERIAL,
                room_id VARCHAR(80) NOT NULL,
                owner_id VARCHAR(100) NOT NULL,
                nickname VARCHAR(80) NOT NULL,
                content TEXT NOT NULL,
                created_at BIGINT NOT NULL,
                deleted_at BIGINT,
                CONSTRAINT fk_public_room_chat_room
                    FOREIGN KEY (room_id) REFERENCES agent_public_rooms(id)
                    ON DELETE CASCADE
            )
            """
        )
        await pool.execute(
            "ALTER TABLE agent_public_room_chat_messages ADD COLUMN IF NOT EXISTS sequence_id BIGSERIAL"
        )
        await pool.execute(
            "CREATE INDEX IF NOT EXISTS idx_public_room_chat_room_created ON agent_public_room_chat_messages(room_id, created_at DESC)"
        )
        await pool.execute(
            "CREATE INDEX IF NOT EXISTS idx_public_room_chat_room_sequence ON agent_public_room_chat_messages(room_id, sequence_id ASC)"
        )
        await pool.execute(
            "CREATE INDEX IF NOT EXISTS idx_public_room_chat_owner_created ON agent_public_room_chat_messages(room_id, owner_id, created_at DESC)"
        )
        self._tables_ready = True

    async def _check_participant_cooldown(self, pool, room_id: str, owner_id: str, now: int) -> None:
        cooldown_seconds = public_room_chat_cooldown_seconds()
        if cooldown_seconds <= 0:
            return
        client = self._get_redis_client()
        if client:
            key = self._cooldown_key(room_id, owner_id)
            try:
                if not client.set(key, str(now), nx=True, ex=cooldown_seconds):
                    raise PublicRoomChatThrottleError(self._redis_retry_after(client, key, cooldown_seconds))
                return
            except PublicRoomChatThrottleError:
                raise
            except Exception:
                pass
        row = await pool.fetchrow(
            """
            SELECT created_at
            FROM agent_public_room_chat_messages
            WHERE room_id = $1 AND owner_id = $2 AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            room_id,
            owner_id,
        )
        if not row:
            return
        last_created_at = int(row.get("created_at") or 0)
        if not last_created_at:
            return
        cooldown_ms = cooldown_seconds * 1000
        elapsed_ms = max(0, now - last_created_at)
        if elapsed_ms < cooldown_ms:
            retry_after = max(1, int((cooldown_ms - elapsed_ms + 999) // 1000))
            raise PublicRoomChatThrottleError(retry_after)

    @staticmethod
    def public_message_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("id") or ""),
            "room_id": str(row.get("room_id") or ""),
            "nickname": str(row.get("nickname") or ""),
            "content": str(row.get("content") or ""),
            "created_at": int(row.get("created_at") or 0),
        }

    async def send_message(
        self,
        room_id: str,
        owner_id: str,
        nickname: str,
        content: Any,
        *,
        workflow: Any | None = None,
    ) -> dict[str, Any]:
        await self._ensure_tables()
        pool = await self._get_pool()
        now = _now_ms()
        content = normalize_public_room_chat_content(content)
        content = mask_public_sensitive_words(content)
        await self._check_participant_cooldown(pool, room_id, owner_id, now)
        if workflow is not None:
            guard = await check_public_content_safety(workflow, content, surface="public")
            if guard.violated:
                content = MASKED_PUBLIC_CONTENT
        row = await pool.fetchrow(
            """
            INSERT INTO agent_public_room_chat_messages (
                id, room_id, owner_id, nickname, content, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, room_id, owner_id, nickname, content, created_at, deleted_at
            """,
            _message_id(),
            room_id,
            owner_id,
            nickname,
            content,
            now,
        )
        return self.public_message_payload(dict(row))

    async def list_messages(self, room_id: str, after_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        await self._ensure_tables()
        pool = await self._get_pool()
        limit = max(1, min(int(limit or 100), 200))
        after_sequence_id = 0
        if after_id:
            cursor = await pool.fetchrow(
                """
                SELECT id, sequence_id
                FROM agent_public_room_chat_messages
                WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL
                """,
                after_id,
                room_id,
            )
            if cursor:
                after_sequence_id = int(cursor.get("sequence_id") or 0)
        if after_sequence_id:
            rows = await pool.fetch(
                """
                SELECT id, room_id, owner_id, nickname, content, created_at, deleted_at
                FROM agent_public_room_chat_messages
                WHERE room_id = $1 AND deleted_at IS NULL AND sequence_id > $2
                ORDER BY sequence_id ASC
                LIMIT $3
                """,
                room_id,
                after_sequence_id,
                limit,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT id, room_id, owner_id, nickname, content, created_at, deleted_at
                FROM agent_public_room_chat_messages
                WHERE room_id = $1 AND deleted_at IS NULL
                ORDER BY sequence_id ASC
                LIMIT $2
                """,
                room_id,
                limit,
            )
        return [self.public_message_payload(dict(row)) for row in rows]


_public_room_chat_service: Optional[PublicRoomChatService] = None


def get_public_room_chat_service() -> PublicRoomChatService:
    global _public_room_chat_service
    if _public_room_chat_service is None:
        _public_room_chat_service = PublicRoomChatService()
    return _public_room_chat_service


def reset_public_room_chat_service() -> None:
    global _public_room_chat_service
    _public_room_chat_service = None

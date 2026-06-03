"""Service for public room player-to-player chat messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
import secrets
from typing import Any, Optional

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

    async def _get_pool(self):
        db = get_database()
        pool = getattr(db, "pg_pool", None) if db else None
        if not pool:
            from agentclaw.api.services.public_room_service import PublicRoomInfraError

            raise PublicRoomInfraError("PostgreSQL is required for public rooms")
        return pool

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

    @staticmethod
    def public_message_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("id") or ""),
            "room_id": str(row.get("room_id") or ""),
            "nickname": str(row.get("nickname") or ""),
            "content": str(row.get("content") or ""),
            "created_at": int(row.get("created_at") or 0),
        }

    async def send_message(self, room_id: str, owner_id: str, nickname: str, content: Any) -> dict[str, Any]:
        await self._ensure_tables()
        pool = await self._get_pool()
        now = _now_ms()
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
            normalize_public_room_chat_content(content),
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

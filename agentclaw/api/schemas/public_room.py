"""Schemas for anonymous public multi-user rooms."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PublicRoomCreateRequest(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=80)


class PublicRoomJoinRequest(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=80)


class PublicRoomTypingRequest(BaseModel):
    typing: bool = True


class PublicRoomChatSendRequest(BaseModel):
    content: str = Field(..., min_length=1)


class PublicRoomSummary(BaseModel):
    id: str
    workflow_id: str
    conversation_id: str
    status: str = "idle"
    version: int = 1
    updated_at: int = 0
    created_at: Optional[int] = None
    running_nickname: Optional[str] = None


class PublicRoomParticipant(BaseModel):
    nickname: str
    last_seen_at: int = 0


class PublicRoomConversation(BaseModel):
    id: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: int = 0


class PublicRoomCreateResponse(BaseModel):
    room: PublicRoomSummary
    room_token: str
    participant: PublicRoomParticipant


class PublicRoomBootstrapResponse(BaseModel):
    workflow: dict[str, Any]
    room: PublicRoomSummary
    joined: bool = False


class PublicRoomStateResponse(BaseModel):
    room: PublicRoomSummary
    participants: list[PublicRoomParticipant] = Field(default_factory=list)
    typing: list[PublicRoomParticipant] = Field(default_factory=list)
    conversation: Optional[PublicRoomConversation] = None
    messages_changed: bool = False

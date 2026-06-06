from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.api


def _public_page_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "origin": "http://testserver",
        "sec-fetch-site": "same-origin",
        "x-agentclaw-public-session": "1",
    }
    if extra:
        headers.update(extra)
    return headers


def _open_public_session(client, workflow_id: str = "wf-public"):
    return client.post(
        f"/api/public/workflows/{workflow_id}/session?share_token=share-test",
        headers={
            "origin": "http://testserver",
            "sec-fetch-site": "same-origin",
        },
    )


class FakeRedis:
    def __init__(self):
        self.values: dict[str, object] = {}
        self.published: list[tuple[str, str]] = []
        self.pubsub_messages: list[dict] = []

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def setex(self, key, _ttl, value):
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        existed = key in self.values
        self.values.pop(key, None)
        return 1 if existed else 0

    def scan_iter(self, match=None):
        prefix = str(match or "").rstrip("*")
        for key in list(self.values):
            if not match or key.startswith(prefix):
                yield key

    def expire(self, key, _ttl):
        return key in self.values

    def publish(self, channel, message):
        self.published.append((channel, message))
        return 1

    def pubsub(self, ignore_subscribe_messages=True):
        redis = self

        class FakePubSub:
            def subscribe(self, *_channels):
                redis.pubsub_messages.append({"type": "message", "data": json.dumps({"event": "ping"})})

            def get_message(self, timeout=0):
                if redis.pubsub_messages:
                    return redis.pubsub_messages.pop(0)
                return None

            def unsubscribe(self, *_channels):
                return None

            def close(self):
                return None

        return FakePubSub()


class FakeSafetyGuardManager:
    safe_guard_id = "guard"
    safe_guard_prompt = "This custom prompt must be ignored"
    safe_guard_rules = "block unsafe content"

    def __init__(self, decision: str):
        self.decision = decision
        self.calls: list[tuple[list[dict], dict]] = []

    async def invoke(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.decision


class FakePublicRoomPool:
    def __init__(self):
        self.rooms: dict[str, dict] = {}
        self.participants: dict[tuple[str, str], dict] = {}
        self.conversations: dict[str, dict] = {}
        self.chat_messages: dict[str, dict] = {}
        self.chat_sequence = 0
        self.execute_calls: list[tuple[str, tuple]] = []

    async def execute(self, query: str, *params):
        self.execute_calls.append((query, params))
        if "CREATE TABLE" in query or "CREATE INDEX" in query or "ALTER TABLE" in query:
            return "OK"
        if "UPDATE agent_public_rooms" in query and "status = 'running'" in query:
            room_id, owner_id, nickname, now = params[:4]
            room = self.rooms.get(room_id)
            if not room or room.get("status") == "running":
                return "UPDATE 0"
            room.update(
                {
                    "status": "running",
                    "running_by": owner_id,
                    "running_nickname": nickname,
                    "running_started_at": now,
                    "updated_at": now,
                    "version": room.get("version", 1) + 1,
                }
            )
            return "UPDATE 1"
        if "UPDATE agent_public_rooms" in query and "status = 'idle'" in query:
            room_id, owner_id, now = params[:3]
            room = self.rooms.get(room_id)
            if not room or room.get("running_by") != owner_id:
                return "UPDATE 0"
            room.update(
                {
                    "status": "idle",
                    "running_by": None,
                    "running_nickname": None,
                    "running_started_at": None,
                    "updated_at": now,
                    "version": room.get("version", 1) + 1,
                }
            )
            return "UPDATE 1"
        return "OK"

    async def fetchrow(self, query: str, *params):
        if "INSERT INTO agent_public_rooms" in query:
            room = {
                "id": params[0],
                "workflow_id": params[1],
                "conversation_id": params[2],
                "room_token_hash": params[3],
                "status": "idle",
                "running_by": None,
                "running_nickname": None,
                "running_started_at": None,
                "created_by": params[4],
                "version": 1,
                "created_at": params[5],
                "updated_at": params[5],
                "revoked_at": None,
            }
            self.rooms[room["id"]] = room
            return dict(room)
        if "SELECT" in query and "FROM agent_public_rooms" in query and "WHERE id = $1" in query:
            return self.rooms.get(params[0])
        if "SELECT" in query and "FROM agent_public_rooms" in query and "WHERE conversation_id = $1" in query:
            return next((room for room in self.rooms.values() if room["conversation_id"] == params[0]), None)
        if "SELECT" in query and "FROM agent_public_room_participants" in query:
            return self.participants.get((params[0], params[1]))
        if "SELECT" in query and "FROM agent_conversations" in query:
            return self.conversations.get(params[0])
        if "UPDATE agent_conversations" in query and "RETURNING" in query:
            conversation_id, workflow_id, title, messages_json, now = params[:5]
            conv = self.conversations.get(conversation_id)
            if not conv or conv["workflow_id"] != workflow_id:
                return None
            conv.update({"title": title, "messages": messages_json, "updated_at": now})
            return dict(conv)
        if "INSERT INTO agent_public_room_chat_messages" in query:
            self.chat_sequence += 1
            message = {
                "id": params[0],
                "room_id": params[1],
                "owner_id": params[2],
                "nickname": params[3],
                "content": params[4],
                "created_at": params[5],
                "sequence_id": self.chat_sequence,
                "deleted_at": None,
            }
            self.chat_messages[message["id"]] = message
            return dict(message)
        if "SELECT id, sequence_id" in query and "FROM agent_public_room_chat_messages" in query:
            message = self.chat_messages.get(params[0])
            if message and message["room_id"] == params[1] and not message.get("deleted_at"):
                return {"id": message["id"], "sequence_id": message["sequence_id"]}
            return None
        if "SELECT created_at" in query and "FROM agent_public_room_chat_messages" in query and "owner_id = $2" in query:
            room_id, owner_id = params[:2]
            messages = [
                message
                for message in self.chat_messages.values()
                if message["room_id"] == room_id
                and message["owner_id"] == owner_id
                and not message.get("deleted_at")
            ]
            if not messages:
                return None
            return {"created_at": max(int(message["created_at"]) for message in messages)}
        return None

    async def fetch(self, query: str, *params):
        if "FROM agent_public_room_chat_messages" in query:
            room_id = params[0]
            if "sequence_id >" in query:
                after_sequence_id = int(params[1])
                limit = int(params[2])
                messages = [
                    dict(message)
                    for message in self.chat_messages.values()
                    if message["room_id"] == room_id
                    and not message.get("deleted_at")
                    and int(message["sequence_id"]) > after_sequence_id
                ]
            else:
                limit = int(params[1])
                messages = [
                    dict(message)
                    for message in self.chat_messages.values()
                    if message["room_id"] == room_id and not message.get("deleted_at")
                ]
            return sorted(messages, key=lambda item: item["sequence_id"])[:limit]
        if "FROM agent_public_room_participants" in query:
            room_id = params[0]
            return [
                dict(participant)
                for (rid, _owner), participant in self.participants.items()
                if rid == room_id
            ]
        return []

    async def fetchval(self, query: str, *params):
        if "SELECT created_at" in query and "agent_public_room_chat_messages" in query:
            message = self.chat_messages.get(params[0])
            if message and message["room_id"] == params[1] and not message.get("deleted_at"):
                return message["created_at"]
            return None
        if "COUNT(*)" in query and "agent_public_room_participants" in query:
            room_id = params[0]
            return sum(1 for rid, _owner in self.participants if rid == room_id)
        return None

    async def executemany(self, query: str, params):
        for item in params:
            await self.execute(query, *item)

    async def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def insert_participant(self, room_id: str, owner_id: str, nickname: str, now: int):
        participant = {
            "room_id": room_id,
            "owner_id": owner_id,
            "nickname": nickname,
            "joined_at": now,
            "last_seen_at": now,
        }
        self.participants[(room_id, owner_id)] = participant
        return dict(participant)

    async def insert_conversation(self, conv: dict):
        self.conversations[conv["id"]] = dict(conv)
        return dict(conv)


def _install_infra(monkeypatch, pool: FakePublicRoomPool | None = None, redis: FakeRedis | None = None):
    from agentclaw.api.services import conversation_service
    from agentclaw.api.services import public_room_service

    pool = pool or FakePublicRoomPool()
    redis = redis or FakeRedis()
    db = SimpleNamespace(pg_pool=pool, get_sync_redis_client=lambda: redis)
    monkeypatch.setattr(public_room_service, "get_database", lambda: db)
    try:
        from agentclaw.api.services import public_room_chat_service
    except ImportError:
        public_room_chat_service = None
    if public_room_chat_service:
        monkeypatch.setattr(public_room_chat_service, "get_database", lambda: db)
        public_room_chat_service.reset_public_room_chat_service()
    monkeypatch.setattr(conversation_service, "get_database", lambda: db)
    public_room_service.reset_public_room_service()
    return pool, redis


def _install_public_workflow(monkeypatch, rate_limit=None, llm_manager=None):
    from agentclaw.api.registry import WorkflowRegistry

    fake_rate_limit = rate_limit
    fake_llm_manager = llm_manager

    class FakeWorkflow:
        id = "wf-public"
        name = "Public workflow"
        description = "Visible workflow"
        welcome = "Welcome"
        public_share_enabled = True
        public_share_token = "share-test"
        rate_limit = fake_rate_limit
        chat_audio = {
            "enabled": True,
            "speech_input_enabled": True,
            "tts_enabled": True,
            "speech2text_model_id": "",
            "tts_model_id": "",
            "tts_voice": "",
        }
        _input_schema = None
        _llm_manager = fake_llm_manager
        run_calls = 0

        def get_input_schema(self):
            return None

        def get_form_config(self):
            return []

        def get_user_input_field(self):
            return "question"

        async def run(self, *, inputs, context, thread_id):
            self.run_calls += 1
            if context.request_stream:
                from agentclaw.runtime.streaming.context import get_output_channel

                channel = get_output_channel()
                if channel:
                    await channel.push_node_started("secret-node", node_type="llm")
                    await channel.push_reasoning("hidden reasoning")
                    await channel.push_message("answer::")
                    await channel.push_tool_start("tool-1", "secret-tool", "{}")
                    await channel.push_tool("tool-1", "secret-tool", "{}", "secret-result")
                    await channel.push_message(inputs["question"])
                    await channel.push_node_finished("secret-node", status="succeeded")
            return {
                "state": {
                    "__messages__": [
                        {
                            "role": "assistant",
                            "content": f"answer::{inputs['question']}",
                            "nodeSteps": [{"id": "secret-node"}],
                            "toolCalls": [{"name": "secret-tool"}],
                            "reasoning": "hidden reasoning",
                        }
                    ],
                    "__status__": "completed",
                },
                "metadata": {},
            }

    workflow = FakeWorkflow()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: workflow if workflow_id == "wf-public" else None),
    )
    return workflow


def _create_room(client):
    session = _open_public_session(client)
    assert session.status_code == 200
    response = client.post(
        "/api/public/workflows/wf-public/rooms",
        headers=_public_page_headers({"x-agentclaw-share-token": "share-test"}),
        json={"nickname": " 玩家A "},
    )
    assert response.status_code == 200
    return response.json()


def test_public_room_requires_postgres_and_redis(public_api_client, monkeypatch):
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.services import public_room_service

    class FakeWorkflow:
        id = "wf-public"
        public_share_enabled = True
        public_share_token = "share-test"

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: FakeWorkflow() if workflow_id == "wf-public" else None),
    )
    monkeypatch.setattr(public_room_service, "get_database", lambda: None)
    public_room_service.reset_public_room_service()

    session = _open_public_session(public_api_client)
    assert session.status_code == 200
    response = public_api_client.post(
        "/api/public/workflows/wf-public/rooms",
        headers=_public_page_headers({"x-agentclaw-share-token": "share-test"}),
        json={"nickname": "玩家A"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "PUBLIC_ROOM_INFRA_REQUIRED"


def test_public_room_create_join_state_typing_and_sanitized_messages(public_api_client, monkeypatch):
    from fastapi.testclient import TestClient

    _install_public_workflow(monkeypatch)
    _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room = created["room"]
    room_token = created["room_token"]

    assert room["id"].startswith("room_")
    assert len(room_token) >= 24
    assert created["participant"]["nickname"] == "玩家A"

    second_client = TestClient(public_api_client.app)
    assert _open_public_session(second_client).status_code == 200
    joined = second_client.post(
        f"/api/public/rooms/{room['id']}/join",
        headers=_public_page_headers({"x-agentclaw-room-token": room_token}),
        json={"nickname": "玩家B"},
    )
    assert joined.status_code == 200
    assert {p["nickname"] for p in joined.json()["participants"]} == {"玩家A", "玩家B"}

    typing = public_api_client.post(
        f"/api/public/rooms/{room['id']}/typing",
        headers=_public_page_headers(),
        json={"typing": True},
    )
    assert typing.status_code == 200
    typing_state = second_client.get(
        f"/api/public/rooms/{room['id']}/state?since_version={room['version']}",
        headers=_public_page_headers(),
    )
    assert typing_state.status_code == 200
    assert any(item["nickname"] == "玩家A" for item in typing_state.json()["typing"])

    run = public_api_client.post(
        f"/api/public/rooms/{room['id']}/run",
        headers=_public_page_headers(),
        json={
            "response_mode": "blocking",
            "workflow_id": "evil",
            "conversation_id": "conv-evil",
            "user": "hello",
            "inputs": {"question": "hello"},
        },
    )
    assert run.status_code == 200
    assert run.json()["conversation_id"] == room["conversation_id"]
    assert run.json()["answer"] == "answer::hello"

    state = second_client.get(
        f"/api/public/rooms/{room['id']}/state?since_version=0",
        headers=_public_page_headers(),
    )
    assert state.status_code == 200
    payload = state.json()
    assert payload["messages_changed"] is True
    messages = payload["conversation"]["messages"]
    assert messages[0]["role"] == "user"
    assert messages[0]["sender"]["nickname"] == "玩家A"
    assert messages[1]["content"] == "answer::hello"
    assert messages[1]["nodeSteps"] == [
        {
            "id": "secret-node",
            "name": "secret-node",
            "type": "llm",
            "typeLabel": "llm",
            "status": "succeeded",
            "elapsed": "0ms",
            "parallelGroupId": None,
        }
    ]
    serialized = json.dumps(messages, ensure_ascii=False)
    assert "toolCalls" not in serialized
    assert "hidden reasoning" not in serialized
    assert "secret-tool" not in serialized
    assert "secret-result" not in serialized
    assert "owner_id" not in serialized
    assert "room_token" not in serialized


def test_public_room_link_opens_session_without_workflow_share_token(public_api_client, monkeypatch):
    from fastapi.testclient import TestClient

    _install_public_workflow(monkeypatch)
    _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room = created["room"]
    room_token = created["room_token"]

    invited_client = TestClient(public_api_client.app)
    session = invited_client.post(
        f"/api/public/rooms/{room['id']}/session",
        headers=_public_page_headers({"x-agentclaw-room-token": room_token}),
    )
    assert session.status_code == 200

    joined = invited_client.post(
        f"/api/public/rooms/{room['id']}/join",
        headers=_public_page_headers({"x-agentclaw-room-token": room_token}),
        json={"nickname": "玩家B"},
    )
    assert joined.status_code == 200
    assert {p["nickname"] for p in joined.json()["participants"]} == {"玩家A", "玩家B"}


def test_public_room_text_to_speech_uses_room_membership_without_workflow_share_token(public_api_client, monkeypatch):
    from agentclaw.api.routers.public import audio as public_audio_router

    class FakeAudioService:
        def __init__(self):
            self.calls = []

        async def synthesize(self, text, voice=None, model_id=None):
            from agentclaw.audio.types import AudioStream

            self.calls.append(("synthesize", text, voice, model_id))

            async def chunks():
                yield b"room-audio"

            return AudioStream(chunks=chunks(), mime_type="audio/mpeg", ext="mp3")

    _install_public_workflow(monkeypatch)
    _install_infra(monkeypatch)
    service = FakeAudioService()
    monkeypatch.setattr(public_audio_router, "get_database", lambda: None)
    public_audio_router._memory_tts_cache.clear()
    public_api_client.app.dependency_overrides[public_audio_router.get_audio_service] = lambda: service

    created = _create_room(public_api_client)
    room = created["room"]

    response = public_api_client.post(
        f"/api/public/rooms/{room['id']}/text-to-speech",
        headers=_public_page_headers(),
        json={"text": "hello", "model_id": "browser-model", "voice": "browser-voice"},
    )

    assert response.status_code == 200
    assert response.content == b"room-audio"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert service.calls == [("synthesize", "hello", None, None)]


def test_public_room_audio_rejects_non_members(public_api_client, monkeypatch):
    from fastapi.testclient import TestClient

    _install_public_workflow(monkeypatch)
    _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room_id = created["room"]["id"]

    stranger = TestClient(public_api_client.app)
    assert _open_public_session(stranger).status_code == 200
    response = stranger.post(
        f"/api/public/rooms/{room_id}/text-to-speech",
        headers=_public_page_headers(),
        json={"text": "hello"},
    )

    assert response.status_code == 403


def test_public_room_rejects_non_members_and_invalid_room_token(public_api_client, monkeypatch):
    from fastapi.testclient import TestClient

    _install_public_workflow(monkeypatch)
    _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room_id = created["room"]["id"]

    second_client = TestClient(public_api_client.app)
    assert _open_public_session(second_client).status_code == 200

    bad_join = second_client.post(
        f"/api/public/rooms/{room_id}/join",
        headers=_public_page_headers({"x-agentclaw-room-token": "bad-token"}),
        json={"nickname": "玩家B"},
    )
    state = second_client.get(f"/api/public/rooms/{room_id}/state", headers=_public_page_headers())
    run = second_client.post(
        f"/api/public/rooms/{room_id}/run",
        headers=_public_page_headers(),
        json={"response_mode": "blocking", "user": "hello", "inputs": {"question": "hello"}},
    )

    assert bad_join.status_code == 403
    assert state.status_code == 403
    assert run.status_code == 403


def test_public_room_events_require_joined_member(public_api_client, monkeypatch):
    from fastapi.testclient import TestClient

    _install_public_workflow(monkeypatch)
    _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room_id = created["room"]["id"]

    stranger = TestClient(public_api_client.app)
    assert _open_public_session(stranger).status_code == 200
    response = stranger.get(
        f"/api/public/rooms/{room_id}/events",
        headers=_public_page_headers(),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_public_room_events_allow_native_eventsource_cookie_session(public_api_client, monkeypatch):
    from starlette.requests import Request
    from agentclaw.api.routers.public.rooms import _room_and_event_member_or_error

    _install_public_workflow(monkeypatch)
    _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room_id = created["room"]["id"]
    public_session = public_api_client.cookies.get("agentclaw_public_session")
    public_user = public_api_client.cookies.get("agentclaw_public_user")
    scope = {
        "type": "http",
        "method": "GET",
        "path": f"/api/public/rooms/{room_id}/events",
        "scheme": "http",
        "server": ("testserver", 80),
        "headers": [
            (b"host", b"testserver"),
            (b"origin", b"http://testserver"),
            (b"sec-fetch-site", b"same-origin"),
            (b"cookie", f"agentclaw_public_session={public_session}; agentclaw_public_user={public_user}".encode("utf-8")),
        ],
    }
    request = Request(scope)

    room, participant, error = await _room_and_event_member_or_error(room_id, request)

    assert error is None
    assert room["id"] == room_id
    assert participant["nickname"] == "玩家A"


def test_public_room_run_publishes_safe_stream_events(public_api_client, monkeypatch):
    _install_public_workflow(monkeypatch)
    _pool, redis = _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room = created["room"]

    response = public_api_client.post(
        f"/api/public/rooms/{room['id']}/run",
        headers=_public_page_headers(),
        json={"response_mode": "streaming", "user": "hello", "inputs": {"question": "hello"}},
    )

    assert response.status_code == 200
    events = [json.loads(message) for _channel, message in redis.published]
    event_names = [event["event"] for event in events]
    assert "agent_run_started" in event_names
    assert "agent_node_started" in event_names
    assert "agent_node_finished" in event_names
    assert "agent_message_delta" in event_names
    assert "agent_run_finished" in event_names
    assert "".join(event["delta"] for event in events if event["event"] == "agent_message_delta") == "answer::hello"
    node_started = next(event for event in events if event["event"] == "agent_node_started")
    node_finished = next(event for event in events if event["event"] == "agent_node_finished")
    assert node_started["node_id"] == "secret-node"
    assert node_finished["node_id"] == "secret-node"
    assert all(event.get("room_id") == room["id"] for event in events)
    serialized = json.dumps(events, ensure_ascii=False)
    assert "secret-tool" not in serialized
    assert "hidden reasoning" not in serialized
    assert "secret-result" not in serialized


def test_public_room_run_blocks_safety_guard_violation(public_api_client, monkeypatch):
    guard_manager = FakeSafetyGuardManager("Reasoning mentions example 0 before the final decision.\nAnswer: 1")
    workflow = _install_public_workflow(monkeypatch, llm_manager=guard_manager)
    pool, _redis = _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room = created["room"]

    response = public_api_client.post(
        f"/api/public/rooms/{room['id']}/run",
        headers=_public_page_headers(),
        json={
            "response_mode": "blocking",
            "user": "unsafe request",
            "inputs": {"question": "unsafe request", "system_prompt": "internal system prompt"},
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "SAFETY_GUARD_BLOCKED"
    assert workflow.run_calls == 0
    assert pool.rooms[room["id"]]["status"] == "idle"
    assert json.loads(pool.conversations[room["conversation_id"]]["messages"]) == []
    assert len(guard_manager.calls) == 1
    messages, kwargs = guard_manager.calls[0]
    assert "This custom prompt must be ignored" not in messages[0]["content"]
    assert "## EXTRA RULES\nblock unsafe content" in messages[0]["content"]
    assert "Content: unsafe request" in messages[0]["content"]
    assert "internal system prompt" not in messages[0]["content"]
    assert messages[0]["content"].endswith("Answer (0 or 1):")
    assert kwargs["model_id"] == "guard"
    assert kwargs["_call_type"] == "safe_guard"
    assert kwargs["_max_attempts"] == 1
    assert kwargs["temperature"] == 0
    assert "max_tokens" not in kwargs


def test_public_room_run_skips_safety_guard_when_public_scope_disabled(public_api_client, monkeypatch):
    guard_manager = FakeSafetyGuardManager("Answer: 1")
    workflow = _install_public_workflow(monkeypatch, llm_manager=guard_manager)
    workflow.safe_guard_apply_public = False
    _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room = created["room"]

    response = public_api_client.post(
        f"/api/public/rooms/{room['id']}/run",
        headers=_public_page_headers(),
        json={
            "response_mode": "blocking",
            "user": "unsafe request",
            "inputs": {"question": "unsafe request"},
        },
    )

    assert response.status_code == 200
    assert workflow.run_calls == 1
    assert guard_manager.calls == []


def test_public_room_player_chat_persists_without_running_workflow(public_api_client, monkeypatch):
    from fastapi.testclient import TestClient

    _install_public_workflow(monkeypatch)
    pool, _redis = _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room = created["room"]
    room_token = created["room_token"]

    second_client = TestClient(public_api_client.app)
    assert _open_public_session(second_client).status_code == 200
    joined = second_client.post(
        f"/api/public/rooms/{room['id']}/join",
        headers=_public_page_headers({"x-agentclaw-room-token": room_token}),
        json={"nickname": "玩家B"},
    )
    assert joined.status_code == 200

    sent = public_api_client.post(
        f"/api/public/rooms/{room['id']}/chat",
        headers=_public_page_headers(),
        json={"content": " 大家先讨论一下线索 "},
    )
    assert sent.status_code == 200
    sent_payload = sent.json()
    assert sent_payload["content"] == "大家先讨论一下线索"
    assert sent_payload["nickname"] == "玩家A"
    assert "owner_id" not in sent_payload

    listed = second_client.get(
        f"/api/public/rooms/{room['id']}/chat",
        headers=_public_page_headers(),
    )
    assert listed.status_code == 200
    assert listed.json()["messages"] == [sent_payload]

    conversation = pool.conversations[room["conversation_id"]]
    assert json.loads(conversation["messages"]) == []


def test_public_room_player_chat_masks_safety_guard_violation(public_api_client, monkeypatch):
    from agentclaw.api.services.safety_guard_service import MASKED_PUBLIC_CONTENT

    guard_manager = FakeSafetyGuardManager("Reasoning mentions example 0 before the final decision.\nAnswer: 1")
    workflow = _install_public_workflow(monkeypatch, llm_manager=guard_manager)
    pool, _redis = _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room = created["room"]

    sent = public_api_client.post(
        f"/api/public/rooms/{room['id']}/chat",
        headers=_public_page_headers(),
        json={"content": "违规聊天内容"},
    )

    assert sent.status_code == 200
    assert sent.json()["content"] == MASKED_PUBLIC_CONTENT
    assert workflow.run_calls == 0
    assert json.loads(pool.conversations[room["conversation_id"]]["messages"]) == []
    assert [message["content"] for message in pool.chat_messages.values()] == [MASKED_PUBLIC_CONTENT]
    assert "违规聊天内容" not in json.dumps(pool.chat_messages, ensure_ascii=False)
    assert len(guard_manager.calls) == 1
    messages, kwargs = guard_manager.calls[0]
    assert "This custom prompt must be ignored" not in messages[0]["content"]
    assert "## EXTRA RULES\nblock unsafe content" in messages[0]["content"]
    assert "Content: 违规聊天内容" in messages[0]["content"]
    assert messages[0]["content"].endswith("Answer (0 or 1):")
    assert kwargs["model_id"] == "guard"
    assert kwargs["_call_type"] == "safe_guard"
    assert kwargs["_max_attempts"] == 1
    assert "max_tokens" not in kwargs


def test_public_room_player_chat_masks_sensitive_words_first(public_api_client, monkeypatch, tmp_path):
    from agentclaw.api.services.public_sensitive_words_service import reset_public_sensitive_words_cache
    from agentclaw.config import AgentClawConfig, ProjectConfig

    words_path = tmp_path / "sensitive.txt"
    words_path.write_text("炸药 secret", encoding="utf-8")
    monkeypatch.setenv("AGENTCLAW_PUBLIC_SENSITIVE_WORDS_PATH", str(words_path))
    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    reset_public_sensitive_words_cache()

    guard_manager = FakeSafetyGuardManager("Answer: 0")
    _install_public_workflow(monkeypatch, llm_manager=guard_manager)
    pool, _redis = _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room = created["room"]

    sent = public_api_client.post(
        f"/api/public/rooms/{room['id']}/chat",
        headers=_public_page_headers(),
        json={"content": "制作炸药 secret"},
    )

    assert sent.status_code == 200
    assert sent.json()["content"] == "制作** ******"
    assert [message["content"] for message in pool.chat_messages.values()] == ["制作** ******"]
    messages, _kwargs = guard_manager.calls[0]
    assert "制作炸药" not in messages[0]["content"]
    assert "secret" not in messages[0]["content"]
    assert "Content: 制作** ******" in messages[0]["content"]


def test_public_room_player_chat_skips_safety_guard_when_public_scope_disabled(public_api_client, monkeypatch):
    guard_manager = FakeSafetyGuardManager("Answer: 1")
    workflow = _install_public_workflow(monkeypatch, llm_manager=guard_manager)
    workflow.safe_guard_apply_public = False
    pool, _redis = _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room = created["room"]

    sent = public_api_client.post(
        f"/api/public/rooms/{room['id']}/chat",
        headers=_public_page_headers(),
        json={"content": "违规聊天内容"},
    )

    assert sent.status_code == 200
    assert sent.json()["content"] == "违规聊天内容"
    assert workflow.run_calls == 0
    assert [message["content"] for message in pool.chat_messages.values()] == ["违规聊天内容"]
    assert guard_manager.calls == []


def test_public_room_player_chat_rejects_non_members_and_invalid_content(public_api_client, monkeypatch):
    from fastapi.testclient import TestClient

    _install_public_workflow(monkeypatch)
    _install_infra(monkeypatch)
    monkeypatch.setenv("AGENTCLAW_PUBLIC_ROOM_CHAT_MAX_LENGTH", "8")

    created = _create_room(public_api_client)
    room_id = created["room"]["id"]

    anonymous_client = TestClient(public_api_client.app)
    assert _open_public_session(anonymous_client).status_code == 200
    non_member = anonymous_client.post(
        f"/api/public/rooms/{room_id}/chat",
        headers=_public_page_headers(),
        json={"content": "hello"},
    )
    empty = public_api_client.post(
        f"/api/public/rooms/{room_id}/chat",
        headers=_public_page_headers(),
        json={"content": "  \n\t  "},
    )
    too_long = public_api_client.post(
        f"/api/public/rooms/{room_id}/chat",
        headers=_public_page_headers(),
        json={"content": "123456789"},
    )

    assert non_member.status_code == 403
    assert empty.status_code == 400
    assert too_long.status_code == 400


def test_public_room_player_chat_remains_available_while_room_is_busy(public_api_client, monkeypatch):
    _install_public_workflow(monkeypatch)
    pool, _redis = _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room_id = created["room"]["id"]
    pool.rooms[room_id]["status"] = "running"
    pool.rooms[room_id]["running_nickname"] = "玩家A"

    response = public_api_client.post(
        f"/api/public/rooms/{room_id}/chat",
        headers=_public_page_headers(),
        json={"content": "主持人生成期间也能聊"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "主持人生成期间也能聊"


def test_public_room_player_chat_throttles_same_participant_but_not_others(public_api_client, monkeypatch):
    from fastapi.testclient import TestClient
    from agentclaw.api.services import public_room_chat_service

    _install_public_workflow(monkeypatch)
    _install_infra(monkeypatch)
    monkeypatch.setenv("AGENTCLAW_PUBLIC_ROOM_CHAT_COOLDOWN_SECONDS", "2")
    now_values = iter([1710000000000, 1710000000500, 1710000000500])
    monkeypatch.setattr(public_room_chat_service, "_now_ms", lambda: next(now_values))

    created = _create_room(public_api_client)
    room = created["room"]
    room_token = created["room_token"]

    second_client = TestClient(public_api_client.app)
    assert _open_public_session(second_client).status_code == 200
    assert second_client.post(
        f"/api/public/rooms/{room['id']}/join",
        headers=_public_page_headers({"x-agentclaw-room-token": room_token}),
        json={"nickname": "玩家B"},
    ).status_code == 200

    first = public_api_client.post(
        f"/api/public/rooms/{room['id']}/chat",
        headers=_public_page_headers(),
        json={"content": "第一条"},
    )
    repeated = public_api_client.post(
        f"/api/public/rooms/{room['id']}/chat",
        headers=_public_page_headers(),
        json={"content": "刷屏"},
    )
    other_participant = second_client.post(
        f"/api/public/rooms/{room['id']}/chat",
        headers=_public_page_headers(),
        json={"content": "玩家B正常发言"},
    )

    assert first.status_code == 200
    assert repeated.status_code == 429
    assert repeated.headers["Retry-After"] == "2"
    assert repeated.json()["code"] == "RATE_LIMITED"
    assert repeated.json()["error"] == "发送太频繁，请 2 秒后再试"
    assert other_participant.status_code == 200


def test_public_room_player_chat_after_id_does_not_skip_same_millisecond_messages(public_api_client, monkeypatch):
    from fastapi.testclient import TestClient
    from agentclaw.api.services import public_room_chat_service

    _install_public_workflow(monkeypatch)
    _install_infra(monkeypatch)
    monkeypatch.setattr(public_room_chat_service, "_now_ms", lambda: 1710000000000)
    chat_ids = iter(["chat_z", "chat_a"])
    monkeypatch.setattr(public_room_chat_service, "_message_id", lambda: next(chat_ids))

    created = _create_room(public_api_client)
    room = created["room"]
    room_token = created["room_token"]

    second_client = TestClient(public_api_client.app)
    assert _open_public_session(second_client).status_code == 200
    assert second_client.post(
        f"/api/public/rooms/{room['id']}/join",
        headers=_public_page_headers({"x-agentclaw-room-token": room_token}),
        json={"nickname": "玩家B"},
    ).status_code == 200

    first = public_api_client.post(
        f"/api/public/rooms/{room['id']}/chat",
        headers=_public_page_headers(),
        json={"content": "第一条"},
    )
    second = second_client.post(
        f"/api/public/rooms/{room['id']}/chat",
        headers=_public_page_headers(),
        json={"content": "第二条"},
    )
    after_first = public_api_client.get(
        f"/api/public/rooms/{room['id']}/chat?after_id={first.json()['id']}",
        headers=_public_page_headers(),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert [item["id"] for item in after_first.json()["messages"]] == ["chat_a"]


def test_public_room_player_chat_uses_separate_default_rate_limits(public_api_client, monkeypatch):
    from agentclaw.api.routers.public import rooms

    _install_public_workflow(monkeypatch)
    _install_infra(monkeypatch)
    monkeypatch.setenv("AGENTCLAW_PUBLIC_ROOM_CHAT_LIST_RATE_LIMIT", "2/min")
    monkeypatch.setenv("AGENTCLAW_PUBLIC_ROOM_CHAT_SEND_RATE_LIMIT", "1/min")

    created = _create_room(public_api_client)
    room_id = created["room"]["id"]

    list_first = public_api_client.get(f"/api/public/rooms/{room_id}/chat", headers=_public_page_headers())
    list_second = public_api_client.get(f"/api/public/rooms/{room_id}/chat", headers=_public_page_headers())
    list_third = public_api_client.get(f"/api/public/rooms/{room_id}/chat", headers=_public_page_headers())
    send_first = public_api_client.post(
        f"/api/public/rooms/{room_id}/chat",
        headers=_public_page_headers(),
        json={"content": "第一条"},
    )
    send_second = public_api_client.post(
        f"/api/public/rooms/{room_id}/chat",
        headers=_public_page_headers(),
        json={"content": "第二条"},
    )

    assert rooms.public_room_chat_list_rate_limit() == "2/min"
    assert rooms.public_room_chat_send_rate_limit() == "1/min"
    assert list_first.status_code == 200
    assert list_second.status_code == 200
    assert list_third.status_code == 429
    assert send_first.status_code == 200
    assert send_second.status_code == 429


def test_public_room_player_chat_keeps_workflow_rate_limit_priority(public_api_client, monkeypatch):
    _install_public_workflow(monkeypatch, rate_limit="1/min")
    _install_infra(monkeypatch)
    monkeypatch.setenv("AGENTCLAW_PUBLIC_ROOM_CHAT_LIST_RATE_LIMIT", "120/min")

    created = _create_room(public_api_client)
    room_id = created["room"]["id"]

    first = public_api_client.get(f"/api/public/rooms/{room_id}/chat", headers=_public_page_headers())
    second = public_api_client.get(f"/api/public/rooms/{room_id}/chat", headers=_public_page_headers())

    assert first.status_code == 200
    assert second.status_code == 429


def test_public_room_run_lock_returns_busy(public_api_client, monkeypatch):
    _install_public_workflow(monkeypatch)
    pool, _redis = _install_infra(monkeypatch)

    created = _create_room(public_api_client)
    room = created["room"]
    room_id = room["id"]
    room_record = pool.rooms[room_id]
    room_record["status"] = "running"
    room_record["running_nickname"] = "玩家A"

    response = public_api_client.post(
        f"/api/public/rooms/{room_id}/run",
        headers=_public_page_headers(),
        json={"response_mode": "blocking", "user": "hello", "inputs": {"question": "hello"}},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ROOM_BUSY"
    assert response.json()["running_nickname"] == "玩家A"

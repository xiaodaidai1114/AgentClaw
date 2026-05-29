from __future__ import annotations

import pytest
import anyio

from agentclaw.api.services.conversation_service import ConversationService


pytestmark = pytest.mark.unit


def _run(async_fn, *args, **kwargs):
    async def call():
        return await async_fn(*args, **kwargs)

    return anyio.run(call)


def test_conversation_service_returns_stable_fallbacks_without_database(monkeypatch):
    from agentclaw.api.services import conversation_service

    monkeypatch.setattr(conversation_service, "get_database", lambda: None)
    service = ConversationService()

    created = _run(
        service.create_conversation,
        workflow_id="wf-1",
        title="No DB",
        source="public",
        owner_id="owner-1",
        user_id="user-1",
        tenant_id="tenant-1",
    )
    listed = _run(
        service.list_conversations,
        workflow_id="wf-1",
        source="public",
        page=2,
        page_size=5,
    )
    fetched = _run(service.get_conversation, "wf-1", created["id"])
    updated = _run(service.update_conversation, "wf-1", created["id"])
    deleted = _run(service.delete_conversation, "wf-1", created["id"])
    feedback_submitted = _run(service.submit_feedback, created["id"], 0, "like")
    feedback = _run(service.get_feedback, created["id"])
    summary = _run(service.get_feedback_summary_map, ["wf-1", "", "wf-2"])

    assert created["id"].startswith("conv_")
    assert len(created["id"]) >= len("conv_") + 24
    assert created["messages"] == []
    assert created["source"] == "public"
    assert created["owner_id"] == "owner-1"
    assert created["user_id"] == "user-1"
    assert created["tenant_id"] == "tenant-1"
    assert listed == {"conversations": [], "total": 0, "page": 2, "page_size": 5}
    assert fetched is None
    assert updated is None
    assert deleted is True
    assert feedback_submitted is False
    assert feedback == {}
    assert summary == {
        "wf-1": {"like_count": 0, "dislike_count": 0},
        "wf-2": {"like_count": 0, "dislike_count": 0},
    }


class FakeConversationPool:
    def __init__(self, delete_result: str = "DELETE 1"):
        self.execute_calls: list[tuple[str, tuple]] = []
        self.fetchrow_calls: list[tuple[str, tuple]] = []
        self.fetch_calls: list[tuple[str, tuple]] = []
        self.delete_result = delete_result

    async def execute(self, query: str, *params):
        self.execute_calls.append((query, params))
        if "DELETE FROM agent_conversations" in query:
            return self.delete_result
        return "OK"

    async def fetchrow(self, query: str, *params):
        self.fetchrow_calls.append((query, params))
        if "COUNT(*) as cnt" in query:
            return {"cnt": 1}
        if "RETURNING id" in query:
            return {
                "id": params[0],
                "workflow_id": params[1],
                "title": "Updated title",
                "messages": '[{"role": "assistant", "content": "updated"}]',
                "source": "public",
                "owner_id": "owner-1",
                "user_id": "user-1",
                "tenant_id": "tenant-1",
                "created_at": 1000,
                "updated_at": params[2],
            }
        if "FROM agent_conversations" in query:
            return {
                "id": params[0],
                "workflow_id": params[1],
                "title": "Public conversation",
                "messages": '[{"role": "user", "content": "hello"}]',
                "source": params[2] if len(params) > 2 else "admin",
                "owner_id": "owner-1",
                "user_id": "user-1",
                "tenant_id": "tenant-1",
                "created_at": 1000,
                "updated_at": 2000,
            }
        return None

    async def fetch(self, query: str, *params):
        self.fetch_calls.append((query, params))
        if "FROM message_feedback" in query:
            return [
                {"message_index": 0, "feedback": "like"},
                {"message_index": 2, "feedback": "dislike"},
            ]
        if "LEFT JOIN message_feedback" in query:
            return [
                {"workflow_id": "wf-1", "like_count": 2, "dislike_count": 1},
            ]
        return [
            {
                "id": "conv-1",
                "workflow_id": params[0],
                "title": "Public conversation",
                "messages": '[{"role": "user", "content": "hello"}]',
                "source": params[1],
                "owner_id": "owner-1",
                "user_id": "user-1",
                "tenant_id": "tenant-1",
                "created_at": 1000,
                "updated_at": 2000,
            }
        ]


def test_conversation_service_preserves_source_and_identity_fields_with_database(
    monkeypatch,
):
    from agentclaw.api.services import conversation_service

    pool = FakeConversationPool()
    monkeypatch.setattr(
        conversation_service,
        "get_database",
        lambda: type("FakeDB", (), {"pg_pool": pool})(),
    )
    service = ConversationService()

    created = _run(
        service.create_conversation,
        workflow_id="wf-1",
        title="Created title",
        source="public",
        owner_id="owner-1",
        user_id="user-1",
        tenant_id="tenant-1",
    )
    listed = _run(
        service.list_conversations,
        workflow_id="wf-1",
        source="public",
        page=1,
        page_size=10,
    )
    fetched = _run(service.get_conversation, "wf-1", "conv-1", source="public")
    updated = _run(
        service.update_conversation,
        "wf-1",
        "conv-1",
        title="Updated title",
        messages=[{"role": "assistant", "content": "updated"}],
        source="public",
    )
    deleted = _run(service.delete_conversation, "wf-1", "conv-1", source="public")
    feedback_written = _run(service.submit_feedback, "conv-1", 0, "like")
    feedback_deleted = _run(service.submit_feedback, "conv-1", 0, None)
    feedback = _run(service.get_feedback, "conv-1")
    summary = _run(service.get_feedback_summary_map, ["wf-1", "wf-2"])

    assert created["source"] == "public"
    assert created["owner_id"] == "owner-1"
    assert created["user_id"] == "user-1"
    assert created["tenant_id"] == "tenant-1"
    assert listed["total"] == 1
    assert "messages" not in listed["conversations"][0]
    assert listed["conversations"][0]["source"] == "public"
    assert fetched["source"] == "public"
    assert fetched["messages"] == [{"role": "user", "content": "hello"}]
    assert updated["title"] == "Updated title"
    assert updated["messages"] == [{"role": "assistant", "content": "updated"}]
    assert deleted is True
    assert feedback_written is True
    assert feedback_deleted is True
    assert feedback == {0: "like", 2: "dislike"}
    assert summary == {
        "wf-1": {"like_count": 2, "dislike_count": 1},
        "wf-2": {"like_count": 0, "dislike_count": 0},
    }

    list_query = next(
        query
        for query, params in pool.fetch_calls
        if "FROM agent_conversations" in query
    )
    assert "messages" not in list_query.split("FROM agent_conversations", 1)[0]
    assert any(
        "COALESCE(source, 'admin') = $2" in query and params[:2] == ("wf-1", "public")
        for query, params in pool.fetch_calls
    )
    assert any(
        "COALESCE(source, 'admin') = $3" in query and params == ("conv-1", "wf-1", "public")
        for query, params in pool.fetchrow_calls
    )


def test_delete_conversation_returns_false_when_no_database_row_was_deleted(monkeypatch):
    from agentclaw.api.services import conversation_service

    pool = FakeConversationPool(delete_result="DELETE 0")
    monkeypatch.setattr(
        conversation_service,
        "get_database",
        lambda: type("FakeDB", (), {"pg_pool": pool})(),
    )
    service = ConversationService()

    deleted = _run(service.delete_conversation, "wf-1", "conv-missing", source="admin")

    assert deleted is False


def test_conversation_service_can_include_messages_when_requested(monkeypatch):
    from agentclaw.api.services import conversation_service

    pool = FakeConversationPool()
    monkeypatch.setattr(
        conversation_service,
        "get_database",
        lambda: type("FakeDB", (), {"pg_pool": pool})(),
    )
    service = ConversationService()

    listed = _run(
        service.list_conversations,
        workflow_id="wf-1",
        source="public",
        page=1,
        page_size=10,
        include_messages=True,
    )

    list_query = next(
        query
        for query, params in pool.fetch_calls
        if "FROM agent_conversations" in query
    )
    assert "messages" in list_query.split("FROM agent_conversations", 1)[0]
    assert listed["conversations"][0]["messages"] == [{"role": "user", "content": "hello"}]


def test_conversation_service_detects_checkpoint_expiration(monkeypatch):
    from agentclaw.api.services import conversation_service

    class ExpiredPool(FakeConversationPool):
        async def fetchrow(self, query: str, *params):
            self.fetchrow_calls.append((query, params))
            if "checkpoint_expired_at" in query:
                return {"checkpoint_expired_at": 1779950000000}
            return await super().fetchrow(query, *params)

    pool = ExpiredPool()
    monkeypatch.setattr(
        conversation_service,
        "get_database",
        lambda: type("FakeDB", (), {"pg_pool": pool})(),
    )
    service = ConversationService()

    expired = _run(service.is_checkpoint_expired, "wf-1", "conv-1", source="public", owner_id="owner-1")

    assert expired is True
    query, params = pool.fetchrow_calls[-1]
    assert "checkpoint_expired_at" in query
    assert "owner_id" in query
    assert params == ("conv-1", "wf-1", "public", "owner-1")

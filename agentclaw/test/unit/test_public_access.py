from hashlib import sha256
from types import SimpleNamespace

import pytest

from agentclaw.api.routers.public import access as public_access
from agentclaw.api.routers.public import session as public_session
from agentclaw.api.routers.public.access import _session_identity
from agentclaw.api.routers.public.session import PUBLIC_SESSION_COOKIE


pytestmark = pytest.mark.unit


def test_session_identity_uses_stable_digest():
    request = SimpleNamespace(cookies={PUBLIC_SESSION_COOKIE: "session-token"})

    assert _session_identity(request) == sha256(b"session-token").hexdigest()[:16]


def test_session_identity_uses_anon_without_cookie():
    request = SimpleNamespace(cookies={})

    assert _session_identity(request) == "anon"


def test_public_user_cookie_round_trips_and_rejects_tampering():
    cookie = public_session.public_user_cookie_value("pu_test")

    assert public_session.public_user_id_from_cookie(cookie) == "pu_test"
    assert public_session.public_user_id_from_cookie(cookie + "x") == ""


def test_public_conversation_owner_binding_rejects_other_owner_and_reset_clears_memory(monkeypatch):
    monkeypatch.setattr(public_session, "_redis_client", lambda: None)
    public_session.reset_public_user_state()
    owner_1 = public_session.public_owner_id_from_user_id("pu_1")
    owner_2 = public_session.public_owner_id_from_user_id("pu_2")

    assert public_session.bind_public_conversation_owner("wf", "conv", owner_1) is True
    assert public_session.verify_public_conversation_owner("wf", "conv", owner_1) is True
    assert public_session.verify_public_conversation_owner("wf", "conv", owner_2) is False

    public_access.reset_public_rate_limiter()

    assert public_session.verify_public_conversation_owner("wf", "conv", owner_2) is True


def test_public_owner_id_from_request_requires_registered_public_user(monkeypatch):
    monkeypatch.setattr(public_session, "_redis_client", lambda: None)
    public_session.reset_public_user_state()
    cookie = public_session.public_user_cookie_value("pu_unregistered")
    request = SimpleNamespace(cookies={public_session.PUBLIC_USER_COOKIE: cookie})

    assert public_session.public_owner_id_from_request(request) == ""

    public_session.ensure_public_user_id(request)

    assert public_session.public_owner_id_from_request(request) == public_session.public_owner_id_from_user_id("pu_unregistered")


def test_public_conversation_owner_redis_key_does_not_collide_on_colons(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.values = {}

        def get(self, key):
            return self.values.get(key)

        def setex(self, key, _ttl, value):
            self.values[key] = value

    redis = FakeRedis()
    monkeypatch.setattr(public_session, "_redis_client", lambda: redis)
    public_session.reset_public_user_state()
    owner_1 = public_session.public_owner_id_from_user_id("pu_1")
    owner_2 = public_session.public_owner_id_from_user_id("pu_2")

    assert public_session.bind_public_conversation_owner("wf:a", "b", owner_1) is True
    assert public_session.bind_public_conversation_owner("wf", "a:b", owner_2) is True
    assert public_session.verify_public_conversation_owner("wf:a", "b", owner_1) is True
    assert public_session.verify_public_conversation_owner("wf", "a:b", owner_2) is True
    assert len(redis.values) == 2


def test_public_user_and_owner_fall_back_to_memory_when_redis_becomes_unavailable(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.values = {}
            self.fail = False

        def get(self, key):
            if self.fail:
                raise RuntimeError("redis unavailable")
            return self.values.get(key)

        def setex(self, key, _ttl, value):
            if self.fail:
                raise RuntimeError("redis unavailable")
            self.values[key] = value

    redis = FakeRedis()
    monkeypatch.setattr(public_session, "_redis_client", lambda: redis)
    public_session.reset_public_user_state()
    cookie = public_session.public_user_cookie_value("pu_redis")
    request = SimpleNamespace(cookies={public_session.PUBLIC_USER_COOKIE: cookie})
    owner_id = public_session.public_owner_id_from_user_id("pu_redis")
    other_owner_id = public_session.public_owner_id_from_user_id("pu_other")

    public_session.ensure_public_user_id(request)
    assert public_session.bind_public_conversation_owner("wf", "conv", owner_id) is True

    redis.fail = True

    assert public_session.public_owner_id_from_request(request) == owner_id
    assert public_session.verify_public_conversation_owner("wf", "conv", owner_id) is True
    assert public_session.verify_public_conversation_owner("wf", "conv", other_owner_id) is False


def test_public_memory_rate_limit_fallback_is_bounded(monkeypatch):
    monkeypatch.setenv("AGENTCLAW_PUBLIC_MEMORY_RATE_LIMIT_MAX_KEYS", "2")
    public_access.reset_public_rate_limiter()
    workflow = SimpleNamespace(rate_limit="10/min")

    for index in range(3):
        request = SimpleNamespace(
            headers={},
            cookies={PUBLIC_SESSION_COOKIE: f"session-{index}"},
            client=SimpleNamespace(host=f"127.0.0.{index}"),
        )

        assert public_access.check_public_rate_limit(workflow, "wf", request, "run") is None

    assert len(public_access._rate_limit_buckets) <= 2


def test_public_memory_conversation_quota_fallback_expires_and_is_bounded(monkeypatch):
    monkeypatch.setenv("AGENTCLAW_PUBLIC_MEMORY_CONVERSATION_QUOTA_TTL_SECONDS", "1")
    monkeypatch.setenv("AGENTCLAW_PUBLIC_MEMORY_CONVERSATION_QUOTA_MAX_KEYS", "2")
    public_access.reset_public_rate_limiter()
    workflow = SimpleNamespace(public_conversation_limit=10)
    now = 1000.0
    monkeypatch.setattr(public_access.time, "monotonic", lambda: now)

    expired_request = SimpleNamespace(headers={}, cookies={PUBLIC_SESSION_COOKIE: "old"}, client=SimpleNamespace(host="old"))
    assert public_access.check_public_conversation_quota(workflow, "wf", expired_request) is None

    now = 1003.0
    for index in range(3):
        request = SimpleNamespace(
            headers={},
            cookies={PUBLIC_SESSION_COOKIE: f"session-{index}"},
            client=SimpleNamespace(host=f"10.0.0.{index}"),
        )

        assert public_access.check_public_conversation_quota(workflow, "wf", request) is None

    assert len(public_access._conversation_quota_counts) <= 2
    assert all(key[1] != "old" for key in public_access._conversation_quota_counts)


def test_public_user_and_owner_memory_fallback_is_bounded(monkeypatch):
    monkeypatch.setenv("AGENTCLAW_PUBLIC_MEMORY_SESSION_MAX_KEYS", "1")
    monkeypatch.setattr(public_session, "_redis_client", lambda: None)
    public_session.reset_public_user_state()

    public_session._register_public_user("pu_1")
    public_session._register_public_user("pu_2")
    owner_1 = public_session.public_owner_id_from_user_id("pu_1")
    owner_2 = public_session.public_owner_id_from_user_id("pu_2")
    assert public_session.bind_public_conversation_owner("wf", "conv-1", owner_1) is True
    assert public_session.bind_public_conversation_owner("wf", "conv-2", owner_2) is True

    assert len(public_session._public_users) <= 1
    assert len(public_session._public_conversation_owners) <= 1


def test_public_runtime_thread_id_is_scoped_by_owner_and_not_raw_conversation_id():
    thread_1 = public_session.public_runtime_thread_id("wf", "owner-1", "conv-shared")
    thread_2 = public_session.public_runtime_thread_id("wf", "owner-2", "conv-shared")

    assert thread_1 != "conv-shared"
    assert thread_1 != thread_2
    assert thread_1.startswith("public:v1:")


def test_default_public_rate_limit_is_enabled_when_env_is_unset(monkeypatch):
    monkeypatch.delenv("AGENTCLAW_PUBLIC_DEFAULT_RATE_LIMIT", raising=False)

    assert public_access.default_public_rate_limit() == "30/min"


def test_public_share_token_can_come_from_header_without_query_or_body():
    request = SimpleNamespace(
        query_params={},
        headers={"x-agentclaw-share-token": "share-test"},
    )

    assert public_access.public_share_token_from_request(request, {}) == "share-test"


def test_public_cookie_secure_can_be_forced_by_env(monkeypatch):
    request = SimpleNamespace(url=SimpleNamespace(scheme="http"), headers={})

    monkeypatch.setenv("AGENTCLAW_PUBLIC_COOKIE_SECURE", "true")
    assert public_session.public_cookie_secure(request) is True

    monkeypatch.setenv("AGENTCLAW_PUBLIC_COOKIE_SECURE", "false")
    assert public_session.public_cookie_secure(request) is False


def test_public_cookie_secure_uses_trusted_forwarded_proto(monkeypatch):
    request = SimpleNamespace(
        url=SimpleNamespace(scheme="http"),
        headers={"x-forwarded-proto": "https"},
    )

    monkeypatch.delenv("AGENTCLAW_PUBLIC_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("AGENTCLAW_TRUST_PROXY_HEADERS", "true")

    assert public_session.public_cookie_secure(request) is True

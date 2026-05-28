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

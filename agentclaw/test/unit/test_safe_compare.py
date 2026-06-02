from __future__ import annotations

import pytest


pytestmark = pytest.mark.unit


def test_auth_token_verifiers_reject_non_ascii_without_raising():
    from agentclaw.api.auth.token import AdminTokenManager, WorkflowAPIKeyManager

    AdminTokenManager._token = "admin-token"
    WorkflowAPIKeyManager._api_key = "workflow-key"
    try:
        assert AdminTokenManager.get_instance().verify("中文") is False
        assert WorkflowAPIKeyManager.get_instance().verify("中文") is False
    finally:
        AdminTokenManager.reset_instance()
        WorkflowAPIKeyManager.reset_instance()


def test_signed_file_token_rejects_non_ascii_signature_without_raising():
    from agentclaw.api.files.signing import verify_file_access_token

    assert verify_file_access_token("file-1", "9999999999.中文") is False


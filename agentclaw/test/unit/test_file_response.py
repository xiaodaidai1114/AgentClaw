import pytest

from agentclaw.api.files.response import (
    content_disposition_header,
    file_response_headers,
    is_browser_safe_inline_type,
)


pytestmark = pytest.mark.unit


def test_content_disposition_sanitizes_header_breaks_and_keeps_utf8_filename():
    header = content_disposition_header('报告\r\nX-Leak: yes "final".txt')

    assert header.startswith('attachment; filename="')
    assert "\r" not in header
    assert "\n" not in header
    assert "X-Leak" not in header
    assert "filename*=UTF-8''%E6%8A%A5%E5%91%8A" in header


def test_file_response_headers_allow_safe_inline_images():
    headers = file_response_headers("image.png", "image/png")

    assert headers["Content-Disposition"].startswith("inline;")
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_file_response_headers_force_active_content_to_attachment():
    headers = file_response_headers("vector.svg", "image/svg+xml")

    assert headers["Content-Disposition"].startswith("attachment;")
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert not is_browser_safe_inline_type("text/html; charset=utf-8")
    assert is_browser_safe_inline_type("application/pdf")

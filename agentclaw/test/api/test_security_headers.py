from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentclaw.api.security_headers import SecurityHeadersMiddleware


def test_security_headers_are_added_to_api_responses():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    response = TestClient(app).get("/ok")

    assert response.status_code == 200
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "microphone=(self)" in response.headers["permissions-policy"]
    assert "geolocation=()" in response.headers["permissions-policy"]

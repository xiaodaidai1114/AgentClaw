import anyio
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agentclaw.api.upload_limits import (
    RequestBodyLimitMiddleware,
    UploadTooLarge,
    UploadSizeLimitMiddleware,
    read_upload_file_limited,
)


pytestmark = pytest.mark.boundary


class ChunkedUpload:
    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)
        self.read_calls = 0

    async def read(self, _size: int) -> bytes:
        self.read_calls += 1
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def test_read_upload_file_limited_allows_exact_limit():
    upload = ChunkedUpload([b"12", b"345"])

    data = anyio.run(read_upload_file_limited, upload, 5, 2)

    assert data == b"12345"
    assert upload.read_calls == 3


def test_read_upload_file_limited_raises_as_soon_as_limit_is_exceeded():
    upload = ChunkedUpload([b"12", b"3456", b"unread"])

    with pytest.raises(UploadTooLarge):
        anyio.run(read_upload_file_limited, upload, 5, 2)

    assert upload.read_calls == 2


def test_request_body_limit_allows_exact_content_length():
    app = FastAPI()
    state = {"called": False}
    app.add_middleware(RequestBodyLimitMiddleware, max_size=5, path_prefixes=("/",))

    @app.post("/api/workflow/run")
    async def handler(request: Request):
        state["called"] = True
        return {"size": len(await request.body())}

    response = TestClient(app).post("/api/workflow/run", content=b"12345")

    assert response.status_code == 200
    assert response.json() == {"size": 5}
    assert state["called"] is True


def test_request_body_limit_respects_excluded_prefixes():
    app = FastAPI()
    state = {"called": False}
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_size=5,
        path_prefixes=("/",),
        excluded_path_prefixes=("/api/upload",),
    )

    @app.post("/api/upload/file")
    async def handler(request: Request):
        state["called"] = True
        return {"size": len(await request.body())}

    response = TestClient(app).post("/api/upload/file", content=b"123456789")

    assert response.status_code == 200
    assert response.json() == {"size": 9}
    assert state["called"] is True


def test_upload_size_limit_rejects_oversized_upload_before_handler_runs():
    app = FastAPI()
    state = {"called": False}
    app.add_middleware(
        UploadSizeLimitMiddleware,
        max_size=5,
        path_prefixes=("/api/upload",),
        overhead_allowance=0,
    )

    @app.post("/api/upload")
    async def handler(request: Request):
        state["called"] = True
        return {"size": len(await request.body())}

    response = TestClient(app).post("/api/upload", content=b"123456")

    assert response.status_code == 413
    assert response.json() == {"detail": "File size exceeds limit"}
    assert state["called"] is False

"""
企业工具接入框架测试

覆盖：load_specs（示例加载）/ ToolSpec 字段 / 三类 executor（python/cli/http）
/ 错误处理 / build_server / 不破坏顶层 import
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentclaw.tools import (
    HandlerSpec,
    PERMISSION_READ_ONLY,
    ToolExecutor,
    ToolSpec,
    build_server,
    load_specs,
)


pytestmark = pytest.mark.unit

PROJECT_SPECS = Path(__file__).resolve().parents[3] / "tools" / "specs"


# ------------------------------------------------------------------
# 加载 + 规范
# ------------------------------------------------------------------

def test_load_specs_loads_all_examples():
    specs = load_specs(PROJECT_SPECS)
    names = {s.name for s in specs}
    assert names == {"format_json", "ping_host", "query_order"}


def test_load_specs_missing_dir_returns_empty(tmp_path):
    assert load_specs(tmp_path / "nonexistent") == []


def test_spec_fields_python():
    specs = {s.name: s for s in load_specs(PROJECT_SPECS)}
    fj = specs["format_json"]
    assert fj.handler.type == "python"
    assert fj.handler.module == "json"
    assert fj.handler.function == "dumps"
    assert fj.permission == PERMISSION_READ_ONLY


def test_spec_fields_http_with_auth_env():
    specs = {s.name: s for s in load_specs(PROJECT_SPECS)}
    qo = specs["query_order"]
    assert qo.handler.type == "http"
    assert qo.handler.auth_env == "ORDER_API_KEY"
    assert "{order_id}" in qo.handler.url
    assert qo.domain == "sales"


def test_spec_fields_cli():
    specs = {s.name: s for s in load_specs(PROJECT_SPECS)}
    ph = specs["ping_host"]
    assert ph.handler.type == "cli"
    assert ph.handler.command == "ping"
    assert "{host}" in ph.handler.args[-1]


# ------------------------------------------------------------------
# 执行器：python
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_python_call():
    spec = ToolSpec(
        name="t", description="d", input_schema={"type": "object"},
        handler=HandlerSpec(type="python", module="json", function="dumps"),
    )
    r = await ToolExecutor([spec]).execute("t", {"obj": {"a": 1, "b": 2}})
    assert '"a"' in r and "1" in r and "2" in r


@pytest.mark.asyncio
async def test_executor_python_async_function():
    """支持 async 函数"""
    spec = ToolSpec(
        name="t", description="d", input_schema={"type": "object"},
        handler=HandlerSpec(type="python", module="asyncio", function="sleep"),
    )
    r = await ToolExecutor([spec]).execute("t", {"delay": 0})
    assert "None" in r or r == "None"  # asyncio.sleep(0) 返回 None


# ------------------------------------------------------------------
# 执行器：cli
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_cli_runs_subprocess():
    spec = ToolSpec(
        name="t", description="d", input_schema={"type": "object"},
        handler=HandlerSpec(type="cli", command=sys.executable, args=["-c", "print('hello-tools')"]),
    )
    r = await ToolExecutor([spec]).execute("t", {})
    assert "hello-tools" in r


@pytest.mark.asyncio
async def test_executor_cli_with_param_substitution():
    spec = ToolSpec(
        name="t", description="d", input_schema={"type": "object"},
        handler=HandlerSpec(
            type="cli", command=sys.executable,
            args=["-c", "print({n})", "{n}"],  # 简单占位替换演示
        ),
    )
    # 这里用 print(42) 形式：args 占位替换
    r = await ToolExecutor([spec]).execute("t", {"n": "42"})
    assert "42" in r


# ------------------------------------------------------------------
# 执行器：http（mock，不依赖网络）
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_http_with_url_substitution(monkeypatch):
    class FakeResp:
        status_code = 200
        text = '{"ok": true}'
    class FakeClient:
        def __init__(self, timeout=None):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def request(self, method, url, headers=None, json=None):
            FakeClient.last_url = url
            return FakeResp()
    monkeypatch.setattr("agentclaw.tools.executor.httpx.AsyncClient", FakeClient)
    spec = ToolSpec(
        name="t", description="d", input_schema={"type": "object"},
        handler=HandlerSpec(type="http", method="GET", url="https://x.test/items/{id}"),
    )
    r = await ToolExecutor([spec]).execute("t", {"id": "42"})
    assert FakeClient.last_url == "https://x.test/items/42"
    assert "HTTP 200" in r and '"ok"' in r


# ------------------------------------------------------------------
# 错误处理
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_unknown_tool_returns_error():
    r = await ToolExecutor([]).execute("nonexistent", {})
    assert "[Error]" in r and "未知工具" in r


@pytest.mark.asyncio
async def test_executor_python_missing_module_returns_error():
    spec = ToolSpec(
        name="t", description="d", input_schema={"type": "object"},
        handler=HandlerSpec(type="python", module="nonexistent_module_xyz", function="f"),
    )
    r = await ToolExecutor([spec]).execute("t", {})
    assert "[Error]" in r


# ------------------------------------------------------------------
# MCP server 构建 + 不破坏 import
# ------------------------------------------------------------------

def test_build_server():
    server = build_server(PROJECT_SPECS)
    assert server.name == "enterprise-tools"


def test_import_agentclaw_unaffected():
    import agentclaw  # noqa: F401
    from agentclaw.tools import ToolSpec  # noqa: F401

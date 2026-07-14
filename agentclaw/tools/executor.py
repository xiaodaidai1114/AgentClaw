"""
ToolExecutor - 异构工具执行器

按 HandlerSpec.type 执行：
- python: importlib 反射调用（支持 sync/async 函数）
- http:   httpx 异步请求（url/body 占位替换 + auth_env Bearer 注入）
- cli:    subprocess（command/args 占位替换，捕获 stdout/stderr）

返回字符串（供 MCP 返回给 AI）。异常捕获，返回 [Error] 前缀，不抛出。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import subprocess
from typing import Any, Dict

import httpx

from .spec import HandlerSpec, ToolSpec


def _fill_template(template: str, params: Dict[str, Any]) -> str:
    """{param} 占位替换；缺少的 key 保留原样不报错"""
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        return template


class ToolExecutor:
    """按 ToolSpec.handler 执行工具调用"""

    def __init__(self, specs) -> None:
        self._specs: Dict[str, ToolSpec] = {s.name: s for s in specs}

    def has(self, name: str) -> bool:
        return name in self._specs

    def list_specs(self):
        return list(self._specs.values())

    async def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        spec = self._specs.get(name)
        if spec is None:
            return f"[Error] 未知工具: {name}"
        h = spec.handler
        try:
            if h.type == "python":
                return await self._exec_python(h, arguments)
            if h.type == "http":
                return await self._exec_http(h, arguments)
            if h.type == "cli":
                return await self._exec_cli(h, arguments)
            return f"[Error] 不支持的 handler 类型: {h.type}"
        except Exception as e:
            return f"[Error] 工具 '{name}' 执行失败: {type(e).__name__}: {e}"

    # ------------------------------------------------------------------
    async def _exec_python(self, h: HandlerSpec, args: Dict[str, Any]) -> str:
        mod = importlib.import_module(h.module)
        fn = getattr(mod, h.function)
        result = fn(**args)
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False, default=str)[:4000]
        return str(result)[:4000]

    async def _exec_http(self, h: HandlerSpec, args: Dict[str, Any]) -> str:
        url = _fill_template(h.url, args)
        headers = dict(h.headers)
        if h.auth_env:
            token = os.getenv(h.auth_env, "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        body = None
        if h.body_template:
            body = json.loads(_fill_template(h.body_template, args))
        async with httpx.AsyncClient(timeout=h.timeout) as client:
            r = await client.request(h.method.upper(), url, headers=headers, json=body)
        return f"HTTP {r.status_code}\n{r.text[:3000]}"

    async def _exec_cli(self, h: HandlerSpec, args: Dict[str, Any]) -> str:
        cmd = [h.command] + [_fill_template(a, args) for a in h.args]
        # 用 subprocess.run（同步）在 to_thread 跑：agentclaw 在 Windows 用 selector
        # event loop，不支持 asyncio.create_subprocess_exec（NotImplementedError）。
        # to_thread 用线程池跑同步 subprocess，绕过该限制。
        def _run():
            try:
                r = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=h.timeout, cwd=h.cwd or None,
                    encoding="utf-8", errors="replace",
                )
                return r.stdout or "", r.stderr or ""
            except subprocess.TimeoutExpired:
                return None, f"CLI 超时（{h.timeout}s）: {' '.join(cmd)}"

        out, err = await asyncio.to_thread(_run)
        if out is None:
            return f"[Error] {err}"
        out = out[:3000]
        err = err[:500]
        return (out + (f"\n[stderr]\n{err}" if err else "")).strip() or "(无输出)"

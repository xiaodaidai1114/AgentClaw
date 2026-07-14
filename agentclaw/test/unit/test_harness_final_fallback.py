"""
harness_final 兜底逻辑单元测试。

背景：post-tool 控制器判 finish 后，harness_final（无工具路径）若模型仍输出
工具调用（DSML）被 manager 拦截丢弃，最终回复会为空/极短，用户感知“卡住”。
LLMNode._is_final_response_degraded 用于识别这种情况，触发回退 continue。
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.unit


def test_final_response_degraded_detects_empty():
    from agentclaw.node.llm import LLMNode

    assert LLMNode._is_final_response_degraded("") is True
    assert LLMNode._is_final_response_degraded("   \n  \t ") is True


def test_final_response_degraded_detects_very_short_residual():
    from agentclaw.node.llm import LLMNode

    # DSML 拦截后常见的残缺/引导式输出（如「让我验证...」这类未真正收尾的文本）
    assert LLMNode._is_final_response_degraded("让我验证导入") is True
    assert LLMNode._is_final_response_degraded("接下来检查语法") is True


def test_final_response_not_degraded_for_normal_reply():
    from agentclaw.node.llm import LLMNode

    assert LLMNode._is_final_response_degraded(
        "这是一个正常完整的最终回复，任务已经全部完成。"
    ) is False
    assert LLMNode._is_final_response_degraded(
        "销售线索分析助手已创建、注册并测试通过，工作流 ID 为 sales_lead_analysis_agent。"
    ) is False


def test_fallback_constants_reasonable():
    from agentclaw.node.llm import (
        _HARNESS_FINAL_DEGRADED_MAX_LEN,
        _HARNESS_FINAL_FALLBACK_MAX,
    )

    assert _HARNESS_FINAL_DEGRADED_MAX_LEN > 0
    assert _HARNESS_FINAL_FALLBACK_MAX >= 1  # 至少允许 1 次回退，避免一次退化就放弃


def test_dsml_contextvar_default_is_false():
    """DSML 标志 contextvar 默认 False，可 set/get/reset"""
    from agentclaw.model.manager import _last_stream_dsml_intercepted

    token = _last_stream_dsml_intercepted.set(False)
    try:
        assert _last_stream_dsml_intercepted.get() is False
        _last_stream_dsml_intercepted.set(True)
        assert _last_stream_dsml_intercepted.get() is True
    finally:
        _last_stream_dsml_intercepted.reset(token)


@pytest.mark.asyncio
async def test_generate_final_returns_dsml_flag_when_intercepted():
    """_generate_harness_final_response 返回 (response, dsml_intercepted)；
    无工具流式拦截到 DSML 时 dsml_intercepted=True（替代纯长度代理，准确捕获
    “final 有效输出 >20 但 DSML 被部分丢弃”的情况）。"""
    from unittest.mock import MagicMock

    from agentclaw.node.llm import LLMNode
    from agentclaw.model.manager import _last_stream_dsml_intercepted

    node = LLMNode.__new__(LLMNode)

    async def fake_stream(messages, **kwargs):
        yield "正常回复内容，但模型其实还想调用工具"
        # 模拟 manager 在无工具路径拦截到 DSML
        _last_stream_dsml_intercepted.set(True)

    ctx = MagicMock()
    ctx.llm_manager.stream = fake_stream
    ctx.check_cancelled = lambda: None

    response, dsml = await node._generate_harness_final_response(
        context=ctx,
        messages=[],
        model_id=None,
        images=None,
        params={},
        push_to_user=False,
    )
    assert response == "正常回复内容，但模型其实还想调用工具"
    assert dsml is True


@pytest.mark.asyncio
async def test_generate_final_returns_false_when_no_dsml():
    """无 DSML 拦截时 dsml_intercepted=False（正常 final 不触发回退）"""
    from unittest.mock import MagicMock

    from agentclaw.node.llm import LLMNode

    node = LLMNode.__new__(LLMNode)

    async def fake_stream(messages, **kwargs):
        yield "这是一个完全正常的最终回复，任务已全部完成。"

    ctx = MagicMock()
    ctx.llm_manager.stream = fake_stream
    ctx.check_cancelled = lambda: None

    response, dsml = await node._generate_harness_final_response(
        context=ctx, messages=[], model_id=None,
        images=None, params={}, push_to_user=False,
    )
    assert "正常" in response
    assert dsml is False

"""
Channel webhook 路由

一对多模型：通过 {channel_name} 路径参数区分不同实例。
每个实例有独立的 webhook URL，注册到各平台回调配置中。

示例：
- POST /api/channels/feishu_sales/webhook    — 飞书销售机器人回调
- POST /api/channels/feishu_support/webhook  — 飞书客服机器人回调
- POST /api/channels/dingtalk_main/webhook   — 钉钉主机器人回调
- GET  /api/channels/wecom_hr/webhook        — 企业微信 URL 验证
- POST /api/channels/qq_bot/webhook          — QQ 机器人回调
- POST /api/channels/push                    — 主动推送消息
- GET  /api/channels                         — 列出所有 Channel 状态
"""

import asyncio
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from agentclaw.api.auth.dependencies import require_admin_auth
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/channels", tags=["channels"])

# ChannelManager 全局引用，在 server.py 启动时注入
_channel_manager = None


def set_channel_manager(manager):
    global _channel_manager
    _channel_manager = manager


def get_channel_manager():
    return _channel_manager


def _get_channel(name: str):
    if not _channel_manager:
        return None
    return _channel_manager.get(name)


def _local_webhook_secret(channel) -> str:
    secret = getattr(channel, "webhook_secret", "") or ""
    config = getattr(channel, "config", None)
    if not secret and isinstance(config, dict):
        secret = config.get("webhook_secret", "") or ""
    return str(secret)


def _verify_local_webhook_secret(channel, request: Request) -> bool:
    secret = _local_webhook_secret(channel)
    if not secret:
        return False
    supplied = request.headers.get("X-Webhook-Secret", "")
    return bool(supplied) and secrets.compare_digest(supplied, secret)


def _webhook_forbidden(message: str = "webhook authentication required") -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": message})


def _feishu_has_platform_verification(channel) -> bool:
    return bool(getattr(channel, "encrypt_key", "") or getattr(channel, "verification_token", ""))


def _dingtalk_has_platform_verification(channel) -> bool:
    return bool(getattr(channel, "callback_secret", ""))


def _wecom_has_platform_verification(channel, body: str, request: Request) -> bool:
    return bool(getattr(channel, "token", "") and request.query_params.get("msg_signature", ""))


# ============================================================
# 通用 webhook 处理（按 channel_name 分发）
# ============================================================

@router.post("/{channel_name}/webhook")
async def channel_webhook(channel_name: str, request: Request):
    """通用 webhook 入口，按 channel_name 分发到对应适配器"""
    channel = _get_channel(channel_name)
    if not channel:
        return JSONResponse(status_code=404, content={"error": f"channel not found: {channel_name}"})

    ch_type = channel.channel_type

    if ch_type == "feishu":
        return await _handle_feishu(channel, request)
    elif ch_type == "dingtalk":
        return await _handle_dingtalk(channel, request)
    elif ch_type == "wecom":
        return await _handle_wecom_post(channel, request)
    elif ch_type == "qq":
        return await _handle_qq(channel, request)
    else:
        if not _verify_local_webhook_secret(channel, request):
            return _webhook_forbidden()
        # 通用 JSON 处理
        body = await request.json()
        asyncio.create_task(channel.handle_message(body))
        return JSONResponse(content={"status": "ok"})


@router.get("/{channel_name}/webhook")
async def channel_webhook_verify(
    channel_name: str,
    request: Request,
    msg_signature: str = Query(""),
    timestamp: str = Query(""),
    nonce: str = Query(""),
    echostr: str = Query(""),
):
    """GET 验证入口（企业微信 URL 验证等）"""
    channel = _get_channel(channel_name)
    if not channel:
        return JSONResponse(status_code=404, content={"error": f"channel not found: {channel_name}"})

    if channel.channel_type == "wecom":
        result = channel.verify_url(msg_signature, timestamp, nonce, echostr)
        if result:
            return PlainTextResponse(content=result)
        return JSONResponse(status_code=403, content={"error": "verification failed"})

    return JSONResponse(status_code=400, content={"error": "GET not supported for this channel type"})


# ============================================================
# 平台特定处理逻辑
# ============================================================

async def _handle_feishu(channel, request: Request):
    if not _feishu_has_platform_verification(channel) and not _verify_local_webhook_secret(channel, request):
        return _webhook_forbidden()
    body = await request.json()
    challenge_resp = channel.verify_callback(body, dict(request.headers))
    if challenge_resp:
        if "error" in challenge_resp:
            return JSONResponse(status_code=403, content=challenge_resp)
        return JSONResponse(content=challenge_resp)
    asyncio.create_task(channel.handle_message(body))
    return JSONResponse(content={"code": 0})


async def _handle_dingtalk(channel, request: Request):
    has_platform_verification = _dingtalk_has_platform_verification(channel)
    if not has_platform_verification and not _verify_local_webhook_secret(channel, request):
        return _webhook_forbidden()
    body = await request.json()
    timestamp = request.headers.get("timestamp", "")
    sign = request.headers.get("sign", "")
    if has_platform_verification and not channel.verify_callback(timestamp, sign):
        logger.warning(
            "[%s] DingTalk callback signature verification failed "
            "(timestamp=%s, sign=%s, has_callback_secret=%s, body_keys=%s)",
            getattr(channel, "name", "dingtalk"),
            bool(timestamp),
            bool(sign),
            bool(getattr(channel, "callback_secret", "")),
            list(body.keys())[:10] if isinstance(body, dict) else type(body).__name__,
        )
        return JSONResponse(status_code=403, content={"error": "signature verification failed"})
    asyncio.create_task(channel.handle_message(body))
    return JSONResponse(content={"errcode": 0, "errmsg": "ok"})


async def _handle_wecom_post(channel, request: Request):
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    has_platform_verification = _wecom_has_platform_verification(channel, body_str, request)
    if not has_platform_verification and not _verify_local_webhook_secret(channel, request):
        return _webhook_forbidden()
    msg_signature = request.query_params.get("msg_signature", "")
    timestamp = request.query_params.get("timestamp", "")
    nonce = request.query_params.get("nonce", "")
    msg_dict = channel.parse_xml_message(
        body_str,
        msg_signature=msg_signature,
        timestamp=timestamp,
        nonce=nonce,
    )
    if msg_dict is None:
        return PlainTextResponse(status_code=403, content="signature verification failed")
    if not msg_dict:
        return PlainTextResponse(content="success")
    asyncio.create_task(channel.handle_message(msg_dict))
    return PlainTextResponse(content="success")


async def _handle_qq(channel, request: Request):
    if not _verify_local_webhook_secret(channel, request):
        return _webhook_forbidden()
    body = await request.json()
    verify_callback = getattr(channel, "verify_callback", None)
    verify_resp = verify_callback(body) if verify_callback else None
    if verify_resp:
        return JSONResponse(content=verify_resp)
    asyncio.create_task(channel.handle_message(body))
    return JSONResponse(content={"op": 12})


# ============================================================
# 主动推送接口
# ============================================================

@router.post("/push", dependencies=[Depends(require_admin_auth)])
async def push_message(request: Request):
    """
    主动推送消息到指定 Channel。

    Body:
    {
        "channel": "feishu_sales",   // Channel 名称
        "user_id": "xxx",
        "chat_id": "",
        "content": "消息内容"
    }
    """
    if not _channel_manager:
        return JSONResponse(status_code=503, content={"error": "no channels configured"})

    body = await request.json()
    channel_name = body.get("channel", "")
    user_id = body.get("user_id", "")
    chat_id = body.get("chat_id", "")
    content = body.get("content", "")

    if not channel_name or not content:
        return JSONResponse(status_code=400, content={"error": "channel and content are required"})
    if not user_id and not chat_id:
        return JSONResponse(status_code=400, content={"error": "user_id or chat_id is required"})

    result = await _channel_manager.push_message(channel_name, user_id, content, chat_id)
    if result.get("ok"):
        return JSONResponse(content={"status": "sent"})
    if result.get("code") == "not_found":
        return JSONResponse(status_code=404, content={"error": result.get("error", "channel not found")})
    if result.get("code") == "invalid_target":
        return JSONResponse(status_code=400, content={"error": result.get("error", "invalid target")})
    return JSONResponse(status_code=500, content={"error": result.get("error", "send failed")})


# ============================================================
# 管理接口（公开只读）
# ============================================================

@router.get("", dependencies=[Depends(require_admin_auth)])
async def list_channels():
    """列出所有 Channel 状态"""
    if not _channel_manager:
        return JSONResponse(content={"channels": []})

    channels = []
    for name, ch in _channel_manager.list_all().items():
        channels.append({
            "name": name,
            "type": ch.channel_type,
            "workflow_id": ch.workflow_id,
            "user_input_field": ch.user_input_field,
            "running": ch._running,
            "thread_mode": ch.thread_mode,
        })

    return JSONResponse(content={"channels": channels})

"""
渠道凭据验证 (Probe)

参照 OpenClaw extensions/feishu/src/probe.ts 模式。
通过调用各平台 API 验证凭据是否有效，返回机器人/账号信息。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import aiohttp

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
LARK_API_BASE = "https://open.larksuite.com/open-apis"
DINGTALK_API_BASE = "https://api.dingtalk.com"
WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"
QQ_API_BASE = "https://api.sgroup.qq.com"

PROBE_TIMEOUT = aiohttp.ClientTimeout(total=10)


@dataclass
class ProbeResult:
    """凭据验证结果"""
    ok: bool
    bot_name: str = ""
    bot_id: str = ""
    error: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


async def probe_feishu(
    app_id: str,
    app_secret: str,
    domain: str = "feishu",
) -> ProbeResult:
    """
    验证飞书凭据。

    1. POST /auth/v3/tenant_access_token/internal → 获取 token
    2. GET /bot/v3/info → 获取机器人信息
    """
    base = LARK_API_BASE if domain == "lark" else FEISHU_API_BASE

    try:
        async with aiohttp.ClientSession(timeout=PROBE_TIMEOUT) as session:
            # Step 1: 获取 tenant_access_token
            token_url = f"{base}/auth/v3/tenant_access_token/internal/"
            async with session.post(
                token_url,
                json={"app_id": app_id, "app_secret": app_secret},
            ) as resp:
                data = await resp.json()
                if data.get("code") != 0:
                    return ProbeResult(
                        ok=False,
                        error=f"Token error: {data.get('msg', f'code {data.get('code')}')}",
                    )
                token = data["tenant_access_token"]

            # Step 2: 获取机器人信息
            bot_url = f"{base}/bot/v3/info"
            async with session.get(
                bot_url,
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                data = await resp.json()
                if data.get("code") != 0:
                    return ProbeResult(
                        ok=False,
                        error=f"Bot info error: {data.get('msg', f'code {data.get('code')}')}",
                    )
                bot = data.get("bot") or data.get("data", {}).get("bot", {})
                return ProbeResult(
                    ok=True,
                    bot_name=bot.get("bot_name", ""),
                    bot_id=bot.get("open_id", ""),
                )
    except aiohttp.ClientError as e:
        return ProbeResult(ok=False, error=f"Connection error: {e}")
    except Exception as e:
        return ProbeResult(ok=False, error=str(e))


async def probe_dingtalk(
    app_key: str,
    app_secret: str,
) -> ProbeResult:
    """
    验证钉钉凭据（v1.0 API）。

    POST /v1.0/oauth2/accessToken → 获取 access_token
    """
    try:
        async with aiohttp.ClientSession(timeout=PROBE_TIMEOUT) as session:
            url = f"{DINGTALK_API_BASE}/v1.0/oauth2/accessToken"
            async with session.post(
                url, json={"appKey": app_key, "appSecret": app_secret}
            ) as resp:
                data = await resp.json()
                token = data.get("accessToken")
                if not token:
                    return ProbeResult(
                        ok=False,
                        error=f"DingTalk error: {data.get('message', data.get('errmsg', 'no accessToken'))}",
                    )
                return ProbeResult(
                    ok=True,
                    bot_id=app_key,
                    extra={"access_token": token},
                )
    except Exception as e:
        return ProbeResult(ok=False, error=str(e))


async def probe_wecom(
    corp_id: str,
    corp_secret: str,
    bot_id: str = "",
    secret: str = "",
    mode: str = "",
) -> ProbeResult:
    """验证企业微信凭据。bot 模式当前提示保存后直接启动验证。"""
    resolved_mode = mode or ("bot" if bot_id or secret else "app")
    if resolved_mode == "webhook":
        return ProbeResult(ok=True, extra={"note": "Webhook mode does not require credential probe"})
    if resolved_mode == "bot":
        if bot_id and secret:
            return ProbeResult(
                ok=True,
                bot_id=bot_id,
                extra={"note": "WeCom bot mode is validated during channel startup"},
            )
        return ProbeResult(ok=False, error="Missing bot_id or secret")

    try:
        async with aiohttp.ClientSession(timeout=PROBE_TIMEOUT) as session:
            url = f"{WECOM_API_BASE}/gettoken"
            async with session.get(
                url, params={"corpid": corp_id, "corpsecret": corp_secret}
            ) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    return ProbeResult(
                        ok=False,
                        error=f"WeCom error: {data.get('errmsg', '')}",
                    )
                return ProbeResult(ok=True, extra={"access_token": data.get("access_token", "")})
    except Exception as e:
        return ProbeResult(ok=False, error=str(e))


async def probe_qq(
    app_id: str,
    app_secret: str = "",
    client_secret: str = "",
) -> ProbeResult:
    """验证 QQ 机器人凭据：获取 access_token"""
    secret = app_secret or client_secret
    try:
        async with aiohttp.ClientSession(timeout=PROBE_TIMEOUT) as session:
            url = "https://bots.qq.com/app/getAppAccessToken"
            async with session.post(
                url, json={"appId": app_id, "clientSecret": secret}
            ) as resp:
                data = await resp.json()
                if "access_token" not in data:
                    return ProbeResult(
                        ok=False,
                        error=f"QQ error: {data.get('message', 'no access_token')}",
                    )
                return ProbeResult(ok=True, extra={"access_token": data["access_token"]})
    except Exception as e:
        return ProbeResult(ok=False, error=str(e))


async def probe_channel(channel_type: str, config: dict) -> ProbeResult:
    """
    统一入口：根据渠道类型分发到对应 probe 实现。

    config 为平台配置字段（与 channels 表的 config JSONB 一致）。
    """
    if channel_type == "feishu":
        return await probe_feishu(
            app_id=config.get("app_id", ""),
            app_secret=config.get("app_secret", ""),
            domain=config.get("domain", "feishu"),
        )
    elif channel_type == "dingtalk":
        return await probe_dingtalk(
            app_key=config.get("app_key", ""),
            app_secret=config.get("app_secret", ""),
        )
    elif channel_type == "wecom":
        return await probe_wecom(
            corp_id=config.get("corp_id", ""),
            corp_secret=config.get("corp_secret", ""),
            bot_id=config.get("bot_id", ""),
            secret=config.get("secret", ""),
            mode=config.get("mode", ""),
        )
    elif channel_type == "qq":
        return await probe_qq(
            app_id=config.get("app_id", ""),
            app_secret=config.get("app_secret", ""),
            client_secret=config.get("client_secret", ""),
        )
    else:
        return ProbeResult(ok=False, error=f"Unknown channel type: {channel_type}")

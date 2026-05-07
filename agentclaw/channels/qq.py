"""
QQ Channel 适配器

基于 QQ Bot WebSocket 长连接接收消息
支持：私聊(C2C)、群聊(GROUP)、频道(GUILD)
认证：AppID + AppSecret → access_token
API: https://bot.q.qq.com/wiki/

参考：OpenClaw @sliverp/qqbot 插件实现
"""

import asyncio
import json
import time
from typing import Optional

import aiohttp

from agentclaw.channels import ChannelBase, ChannelMessage
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

QQ_API_BASE = "https://api.sgroup.qq.com"
QQ_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"

# WebSocket intents
INTENTS_PUBLIC_GUILD = 1 << 30  # 频道公开消息
INTENTS_DIRECT_MESSAGE = 1 << 12  # 频道私信
INTENTS_GROUP_AND_C2C = 1 << 25  # 群聊和私聊
FULL_INTENTS = INTENTS_PUBLIC_GUILD | INTENTS_DIRECT_MESSAGE | INTENTS_GROUP_AND_C2C


class QQChannel(ChannelBase):
    """QQ Channel 适配器（WebSocket 模式）"""

    channel_type = "qq"

    def __init__(
        self,
        server_base_url: str = "http://127.0.0.1:8000",
        api_key: str = "",
        thread_mode: str = "per_user",
        app_id: str = "",
        app_secret: str = "",
        client_secret: str = "",
        sandbox: bool = False,
        **kwargs,
    ):
        super().__init__(server_base_url=server_base_url, api_key=api_key, thread_mode=thread_mode, **kwargs)
        self.app_id = app_id
        self.app_secret = app_secret or client_secret
        self.client_secret = self.app_secret
        self.sandbox = sandbox

        self._access_token: str = ""
        self._token_expires_at: float = 0
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session_id: Optional[str] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._ws_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动 WebSocket 连接"""
        if not self.app_id or not self.app_secret:
            logger.error("QQ channel: missing app_id or app_secret")
            return

        await self._refresh_token()
        self._running = True
        self._ws_task = asyncio.create_task(self._run_websocket())
        logger.info(f"QQ channel started (app_id={self.app_id})")

    async def on_message(self, raw_event: dict | ChannelMessage) -> Optional[ChannelMessage]:
        """兼容统一入口；WebSocket 主路径直接透传 ChannelMessage。"""
        if isinstance(raw_event, ChannelMessage):
            return raw_event

        if not isinstance(raw_event, dict):
            return None

        event_type = raw_event.get("t") or raw_event.get("event_type") or ""
        data = raw_event.get("d") or raw_event.get("data") or raw_event
        return await self._parse_event(event_type, data, raw_event)

    async def stop(self):
        """停止 WebSocket 连接"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._ws:
            await self._ws.close()
        if self._ws_task:
            self._ws_task.cancel()
        logger.info("QQ channel stopped")

    async def _run_websocket(self):
        """WebSocket 主循环（带重连）"""
        reconnect_count = 0
        while self._running:
            try:
                gateway_url = await self._get_gateway_url()
                if not gateway_url:
                    logger.error("QQ: failed to get gateway URL")
                    await asyncio.sleep(5)
                    continue

                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(gateway_url) as ws:
                        self._ws = ws
                        logger.info(f"QQ WebSocket connected: {gateway_url}")
                        reconnect_count = 0

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle_ws_message(json.loads(msg.data))
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                logger.warning(f"QQ WebSocket closed/error: {msg.type}")
                                break

            except Exception as e:
                logger.error(f"QQ WebSocket error: {e}")
                reconnect_count += 1
                delay = min(reconnect_count * 2, 60)
                logger.info(f"QQ reconnecting in {delay}s...")
                await asyncio.sleep(delay)

        self._ws = None

    async def _handle_ws_message(self, payload: dict):
        """处理 WebSocket 消息"""
        op = payload.get("op")

        # op=10: Hello
        if op == 10:
            d = payload.get("d", {})
            heartbeat_interval = d.get("heartbeat_interval", 41250)
            logger.info(f"QQ Hello received, heartbeat_interval={heartbeat_interval}ms")
            await self._send_identify()
            self._start_heartbeat(heartbeat_interval / 1000)
            return

        # op=11: Heartbeat ACK
        if op == 11:
            return

        # op=0: Dispatch
        if op == 0:
            self._session_id = payload.get("s")
            event_type = payload.get("t")
            data = payload.get("d", {})

            msg = await self._parse_event(event_type, data, payload)
            if msg:
                asyncio.create_task(self._process_channel_message(msg))

    async def _send_identify(self):
        """发送鉴权"""
        if not self._ws:
            return

        identify_payload = {
            "op": 2,
            "d": {
                "token": f"QQBot {self._access_token}",
                "intents": FULL_INTENTS,
                "shard": [0, 1],
            }
        }
        await self._ws.send_json(identify_payload)
        logger.info("QQ Identify sent")

    def _start_heartbeat(self, interval: float):
        """启动心跳"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(interval))

    async def _heartbeat_loop(self, interval: float):
        """心跳循环"""
        try:
            while self._running and self._ws:
                await asyncio.sleep(interval)
                if self._ws:
                    await self._ws.send_json({"op": 1, "d": self._session_id})
        except asyncio.CancelledError:
            pass

    async def _parse_event(self, event_type: str, data: dict, raw: dict) -> Optional[ChannelMessage]:
        """解析事件为 ChannelMessage"""
        # C2C 私聊
        if event_type == "C2C_MESSAGE_CREATE":
            text = data.get("content", "").strip()
            user_openid = data.get("author", {}).get("user_openid", "")
            msg_id = data.get("id", "")

            return ChannelMessage(
                channel="qq",
                user_id=user_openid,
                chat_id="",
                message=text,
                message_type="text",
                reply_context={
                    "event_type": event_type,
                    "user_openid": user_openid,
                    "msg_id": msg_id,
                },
                raw=raw,
            )

        # 群聊 @消息
        if event_type == "GROUP_AT_MESSAGE_CREATE":
            text = data.get("content", "").strip()
            member_openid = data.get("author", {}).get("member_openid", "")
            group_openid = data.get("group_openid", "")
            msg_id = data.get("id", "")

            return ChannelMessage(
                channel="qq",
                user_id=member_openid,
                chat_id=group_openid,
                message=text,
                message_type="text",
                reply_context={
                    "event_type": event_type,
                    "group_openid": group_openid,
                    "msg_id": msg_id,
                },
                raw=raw,
            )

        # 频道 @消息
        if event_type in ("AT_MESSAGE_CREATE", "MESSAGE_CREATE"):
            text = data.get("content", "").strip()
            user_id = data.get("author", {}).get("id", "")
            channel_id = data.get("channel_id", "")
            msg_id = data.get("id", "")

            return ChannelMessage(
                channel="qq",
                user_id=user_id,
                chat_id=channel_id,
                message=text,
                message_type="text",
                reply_context={
                    "event_type": event_type,
                    "channel_id": channel_id,
                    "msg_id": msg_id,
                },
                raw=raw,
            )

        return None

    async def send_reply(self, msg: ChannelMessage, content: str):
        """发送回复消息"""
        await self._ensure_token()

        event_type = msg.reply_context.get("event_type", "")
        msg_id = msg.reply_context.get("msg_id", "")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"QQBot {self._access_token}",
        }

        # C2C 私聊
        if event_type == "C2C_MESSAGE_CREATE":
            user_openid = msg.reply_context.get("user_openid", "")
            url = f"{QQ_API_BASE}/v2/users/{user_openid}/messages"
            payload = {"content": content, "msg_type": 0, "msg_id": msg_id}

        # 群聊
        elif event_type == "GROUP_AT_MESSAGE_CREATE":
            group_openid = msg.reply_context.get("group_openid", "")
            url = f"{QQ_API_BASE}/v2/groups/{group_openid}/messages"
            payload = {"content": content, "msg_type": 0, "msg_id": msg_id}

        # 主动私聊
        elif event_type == "PROACTIVE_C2C":
            user_openid = msg.reply_context.get("user_openid", "") or msg.user_id
            url = f"{QQ_API_BASE}/v2/users/{user_openid}/messages"
            payload = {"content": content, "msg_type": 0}

        # 主动群聊
        elif event_type == "PROACTIVE_GROUP":
            group_openid = msg.reply_context.get("group_openid", "") or msg.chat_id
            url = f"{QQ_API_BASE}/v2/groups/{group_openid}/messages"
            payload = {"content": content, "msg_type": 0}

        # 频道
        elif event_type in ("AT_MESSAGE_CREATE", "MESSAGE_CREATE"):
            channel_id = msg.reply_context.get("channel_id", "")
            url = f"{QQ_API_BASE}/channels/{channel_id}/messages"
            payload = {"content": content, "msg_id": msg_id}

        else:
            raise RuntimeError(f"QQ unknown event_type: {event_type}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status not in (200, 201):
                        body = await resp.text()
                        raise RuntimeError(f"QQ send_reply failed {resp.status}: {body}")
                    return True
        except Exception as e:
            logger.error(f"QQ send_reply error: {e}")
            raise

    def build_push_context(self, user_id: str, chat_id: str = "") -> dict:
        if chat_id:
            return {
                "event_type": "PROACTIVE_GROUP",
                "group_openid": chat_id,
            }
        return {
            "event_type": "PROACTIVE_C2C",
            "user_openid": user_id,
        }

    async def _get_gateway_url(self) -> Optional[str]:
        """获取 WebSocket Gateway URL"""
        await self._ensure_token()
        url = f"{QQ_API_BASE}/gateway"
        headers = {"Authorization": f"QQBot {self._access_token}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("url")
                    logger.error(f"QQ get gateway failed: {resp.status}")
        except Exception as e:
            logger.error(f"QQ get gateway error: {e}")
        return None

    async def _refresh_token(self):
        """刷新 access_token"""
        payload = {"appId": self.app_id, "clientSecret": self.app_secret}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(QQ_TOKEN_URL, json=payload) as resp:
                    data = await resp.json()
                    token = data.get("access_token")
                    if token:
                        self._access_token = token
                        expires_in = int(data.get("expires_in", 7200))
                        self._token_expires_at = time.time() + expires_in - 300
                        logger.info(f"QQ token refreshed, expires in {expires_in}s")
                    else:
                        logger.error(f"QQ token refresh failed: {data}")
        except Exception as e:
            logger.error(f"QQ token refresh error: {e}")

    async def _ensure_token(self):
        """确保 token 有效"""
        if time.time() >= self._token_expires_at:
            await self._refresh_token()

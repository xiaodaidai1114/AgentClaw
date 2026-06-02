"""
钉钉 (DingTalk) Channel 适配器

接收方式：
- HTTP 回调 (Outgoing Robot) — 无需额外依赖
- Stream 模式 — 需安装 dingtalk-stream Python SDK (`pip install dingtalk-stream`)

发送方式：
- sessionWebhook（回调自带，优先使用）
- Robot API v1.0 — 单聊 (batchSendOTO) + 群聊 (orgGroupSend)

认证方式：appKey + appSecret → access_token (v1.0 OAuth2)

参考：OpenClaw 社区插件 @largezhou/ddingtalk
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any, Optional
from urllib.parse import quote_plus, unquote

import aiohttp

from agentclaw.channels import ChannelBase, ChannelMessage
from agentclaw.logger.config import get_logger
from agentclaw.utils.security import safe_compare_digest

logger = get_logger(__name__)

DINGTALK_API_BASE = "https://api.dingtalk.com"
DINGTALK_OAPI_BASE = "https://oapi.dingtalk.com"


class DingTalkChannel(ChannelBase):
    """
    钉钉 Channel 适配器

    支持两种接入模式：
    - stream (默认): WebSocket Stream 模式，需 `pip install dingtalk-stream`
    - callback: HTTP 回调，不需要额外依赖

    配置字段 (config JSONB):
        app_key: str        — 钉钉应用 AppKey (必填)
        app_secret: str     — 钉钉应用 AppSecret (必填)
        robot_code: str     — 机器人编码 (默认使用 app_key)
        callback_secret: str — 回调签名密钥（HTTP 回调模式可选）
        mode: str           — 接入模式 callback | stream (默认 stream)
    """

    channel_type = "dingtalk"

    def __init__(
        self,
        server_base_url: str = "http://127.0.0.1:8000",
        api_key: str = "",
        thread_mode: str = "per_user",
        # 钉钉配置
        app_key: str = "",
        app_secret: str = "",
        robot_code: str = "",
        callback_secret: str = "",
        mode: str = "stream",  # callback | stream
        card_template_id: str = "",  # AI Card 模板 ID（流式输出）
        card_template_key: str = "content",  # AI Card 模板字段名
        **kwargs,
    ):
        super().__init__(server_base_url=server_base_url, api_key=api_key, thread_mode=thread_mode, **kwargs)
        self.app_key = app_key
        self.app_secret = app_secret
        self.robot_code = robot_code or app_key
        self.callback_secret = callback_secret
        self.mode = mode
        self.card_template_id = card_template_id
        self.card_template_key = card_template_key

        self._access_token: str = ""
        self._token_expires_at: float = 0
        self._stream_client = None  # dingtalk-stream DWClient
        self._stream_variant: str = ""
        self._background_tasks: set = set()

        # 流式输出状态（AI Card）
        self._streaming_card_ids: dict[str, str] = {}      # thread_id → card_instance_id
        self._streaming_last_content: dict[str, str] = {}   # thread_id → 上次发送内容

    async def _read_http_response(self, resp: aiohttp.ClientResponse) -> tuple[Optional[dict[str, Any]], str]:
        """Best-effort parse for DingTalk API responses."""
        text = await resp.text()
        if not text:
            return None, ""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None, text
        if isinstance(data, dict):
            return data, text
        return None, text

    def _resolve_robot_code(self, msg: Optional[ChannelMessage] = None) -> str:
        """Prefer the runtime robotCode from DingTalk callbacks over static config."""
        if msg:
            reply_context = msg.reply_context or {}
            runtime_robot_code = str(reply_context.get("robot_code", "")).strip()
            if runtime_robot_code:
                return runtime_robot_code
        return self.robot_code

    def _build_card_stream_key(self, msg: ChannelMessage) -> str:
        """
        Build a transport-level key for AI Card state.

        This must not reuse workflow thread_id directly: `thread_mode=shared`
        is useful for context, but it would incorrectly make all conversations
        share the same DingTalk card instance.
        """
        reply_context = msg.reply_context or {}
        existing = str(reply_context.get("stream_key", "")).strip()
        if existing:
            return existing

        conversation_type = str(reply_context.get("conversation_type", "1"))
        open_conversation_id = str(reply_context.get("open_conversation_id", "")).strip()
        conversation_id = str(reply_context.get("conversation_id", "")).strip()
        sender_id = str(reply_context.get("sender_id", "") or msg.user_id).strip()
        message_id = (
            str(reply_context.get("message_id", "")).strip()
            or str((msg.raw or {}).get("messageId", "")).strip()
            or str((msg.raw or {}).get("msgId", "")).strip()
            or uuid.uuid4().hex
        )

        if conversation_type == "2":
            target = open_conversation_id or conversation_id or msg.chat_id or "group"
            return f"dingtalk_group_{target}_{message_id}"

        target = sender_id or "user"
        return f"dingtalk_direct_{target}_{message_id}"

    # ============================================================
    # 生命周期
    # ============================================================

    async def start(self):
        self._running = True
        if self.app_key and self.app_secret:
            await self._ensure_token()

        stream_active = False
        if self.mode == "stream":
            stream_active = await self._start_stream()
            if not self.card_template_id:
                logger.info(
                    f"[{self.name}] DingTalk streaming updates disabled: missing card_template_id; "
                    "will send final reply only"
                )

        logger.info(
            f"[{self.name}] DingTalk channel started "
            f"(mode={self.mode}, stream_active={stream_active})"
        )

    async def stop(self):
        self._running = False

        # 取消所有后台任务
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

        if self._stream_client and hasattr(self._stream_client, "disconnect"):
            try:
                self._stream_client.disconnect()
            except Exception as e:
                logger.debug(f"[{self.name}] DingTalk stream disconnect: {e}")

        logger.info(f"[{self.name}] DingTalk channel stopped")

    # ============================================================
    # Stream 模式
    # ============================================================

    def _track_background_task(self, task: asyncio.Task):
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _start_stream(self) -> bool:
        """启动 dingtalk-stream WebSocket 监听"""
        try:
            import dingtalk_stream as sdk
        except ImportError:
            logger.error(
                "[%s] dingtalk-stream not installed. Install with: pip install dingtalk-stream",
                self.name
            )
            return False

        modern_exports = all(
            hasattr(sdk, attr)
            for attr in ("DingTalkStreamClient", "Credential", "CallbackHandler", "ChatbotMessage", "AckMessage")
        )
        legacy_exports = all(hasattr(sdk, attr) for attr in ("DWClient", "TOPIC_ROBOT"))

        if modern_exports:
            client = sdk.DingTalkStreamClient(
                sdk.Credential(self.app_key, self.app_secret)
            )

            channel = self

            class RobotMessageHandler(sdk.CallbackHandler):
                async def process(self, callback_message):
                    try:
                        chatbot_message = sdk.ChatbotMessage.from_dict(callback_message.data)
                        raw_event = chatbot_message.to_dict()
                        channel._track_background_task(asyncio.create_task(channel.handle_message(raw_event)))
                        return sdk.AckMessage.STATUS_OK, "ok"
                    except Exception as e:
                        logger.error(f"[{channel.name}] Stream message callback error: {e}", exc_info=True)
                        return sdk.AckMessage.STATUS_SYSTEM_EXCEPTION, "error"

            handler = RobotMessageHandler()
            client.register_callback_handler(sdk.ChatbotMessage.TOPIC, handler)
            delegate_topic = getattr(sdk.ChatbotMessage, "DELEGATE_TOPIC", "")
            if delegate_topic:
                client.register_callback_handler(delegate_topic, handler)

            self._stream_client = client
            self._stream_variant = "modern"
        elif legacy_exports:
            client = sdk.DWClient({
                "clientId": self.app_key,
                "clientSecret": self.app_secret,
            })

            def _on_robot_message(message):
                """Stream 消息回调（旧版 SDK，同步）"""
                try:
                    data = json.loads(message.data)
                    client.socketCallBackResponse(message.headers.get("messageId", ""), {"status": "SUCCESS"})
                    channel_task = asyncio.create_task(self.handle_message(data))
                    self._track_background_task(channel_task)
                except Exception as e:
                    logger.error(f"[{self.name}] Stream message callback error: {e}", exc_info=True)

            client.register_callback_listener(sdk.TOPIC_ROBOT, _on_robot_message)
            self._stream_client = client
            self._stream_variant = "legacy"
        else:
            logger.error(
                "[%s] Unsupported dingtalk-stream SDK exports. Available exports: %s",
                self.name,
                ", ".join(sorted(name for name in dir(sdk) if not name.startswith("_"))),
            )
            return False

        self._track_background_task(asyncio.create_task(self._run_stream_loop(client, self._stream_variant)))
        return True

    async def _run_modern_stream_loop(self, client):
        """新版 dingtalk-stream SDK 连接循环，由当前进程托管重连与停止。"""
        import websockets

        client.pre_start()

        while self._running:
            keepalive_task = None
            try:
                connection = await asyncio.get_running_loop().run_in_executor(None, client.open_connection)
                if not connection:
                    logger.warning(f"[{self.name}] Stream open connection failed")
                else:
                    uri = f"{connection['endpoint']}?ticket={quote_plus(connection['ticket'])}"
                    logger.info(f"[{self.name}] DingTalk stream endpoint acquired")
                    async with websockets.connect(uri) as websocket:
                        client.websocket = websocket
                        keepalive_task = asyncio.create_task(client.keepalive(websocket))
                        while self._running:
                            raw_message = await websocket.recv()
                            json_message = json.loads(raw_message)
                            await client.background_task(json_message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[{self.name}] Stream connection error: {e}")
            finally:
                if keepalive_task:
                    keepalive_task.cancel()
                    await asyncio.gather(keepalive_task, return_exceptions=True)
                websocket = getattr(client, "websocket", None)
                if websocket is not None:
                    try:
                        await websocket.close()
                    except Exception:
                        pass
                    client.websocket = None

            if self._running:
                logger.info(f"[{self.name}] Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    async def _run_stream_loop(self, client, variant: str):
        """Stream 连接自动重连循环"""
        logger.info(f"[{self.name}] Starting DingTalk stream connection... (variant={variant})")
        if variant == "modern":
            await self._run_modern_stream_loop(client)
            return

        while self._running:
            try:
                await asyncio.get_event_loop().run_in_executor(None, client.connect)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[{self.name}] Stream connection error: {e}")

            if self._running:
                logger.info(f"[{self.name}] Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    # ============================================================
    # 消息解析
    # ============================================================

    async def on_message(self, raw_event: dict) -> Optional[ChannelMessage]:
        """解析钉钉消息（回调模式 + Stream 模式共用）"""
        msg_type = raw_event.get("msgtype", "text")

        # 提取文本
        text = ""
        if msg_type == "text":
            text = (raw_event.get("text") or {}).get("content", "").strip()
        elif msg_type == "richText":
            # 富文本提取纯文本部分
            content = raw_event.get("content") or {}
            rich_text = content.get("richText") or []
            parts = []
            for element in rich_text:
                t = element.get("text", "")
                if t:
                    parts.append(t)
            text = "\n".join(parts).strip()

        if not text:
            logger.debug(f"[{self.name}] Ignored empty message (type={msg_type})")
            return None

        sender_id = raw_event.get("senderStaffId") or raw_event.get("senderId", "")
        sender_nick = raw_event.get("senderNick", "")
        conversation_type = raw_event.get("conversationType", "1")  # "1"=单聊 "2"=群聊
        conversation_id = raw_event.get("conversationId", "")
        open_conversation_id = raw_event.get("openConversationId", "")
        session_webhook = raw_event.get("sessionWebhook", "")
        message_id = raw_event.get("messageId") or raw_event.get("msgId") or uuid.uuid4().hex

        # 群聊用 openConversationId（用于主动发消息）
        chat_id = ""
        if conversation_type == "2":
            chat_id = open_conversation_id or conversation_id

        logger.info(
            f"[{self.name}] Received message from {sender_nick}({sender_id}) "
            f"type={conversation_type} text={text[:50]}..."
        )

        return ChannelMessage(
            channel="dingtalk",
            user_id=sender_id,
            chat_id=chat_id,
            message=text,
            message_type="text",
            reply_context={
                "conversation_id": conversation_id,
                "conversation_type": conversation_type,
                "open_conversation_id": open_conversation_id,
                "session_webhook": session_webhook,
                "sender_nick": sender_nick,
                "sender_id": sender_id,
                "robot_code": raw_event.get("robotCode", ""),
                "message_id": message_id,
                "stream_key": (
                    f"dingtalk_group_{chat_id}_{message_id}"
                    if conversation_type == "2"
                    else f"dingtalk_direct_{sender_id}_{message_id}"
                ),
            },
            raw=raw_event,
        )

    # ============================================================
    # 消息发送
    # ============================================================

    async def send_reply(self, msg: ChannelMessage, content: str):
        """
        发送消息到钉钉

        优先级:
        1. sessionWebhook（回调自带，最简单，支持群聊+单聊）
        2. Robot API v1.0（主动发消息，需 access_token）
        """
        logger.info(f"[{self.name}] send_reply called, content_len={len(content)}")
        session_webhook = msg.reply_context.get("session_webhook", "")

        # 优先用 sessionWebhook
        if session_webhook:
            logger.debug(f"[{self.name}] Sending reply via sessionWebhook")
            success = await self._reply_via_webhook(session_webhook, content)
            if success:
                logger.info(f"[{self.name}] Reply sent successfully via webhook")
                return True
            logger.warning(f"[{self.name}] sessionWebhook failed, falling back to Robot API")

        # 降级: Robot API
        conversation_type = msg.reply_context.get("conversation_type", "1")
        robot_code = self._resolve_robot_code(msg)
        if conversation_type == "2":
            # 群聊
            group_id = (
                msg.reply_context.get("open_conversation_id")
                or msg.reply_context.get("conversation_id")
                or msg.chat_id
                or ""
            )
            if group_id:
                logger.debug(f"[{self.name}] Sending group message to {group_id}")
                return await self._send_group_message(group_id, content, robot_code=robot_code)
        else:
            # 单聊
            sender_id = msg.reply_context.get("sender_id") or msg.user_id or ""
            if sender_id:
                logger.debug(f"[{self.name}] Sending OTO message to {sender_id}")
                return await self._send_oto_message(sender_id, content, robot_code=robot_code)
        raise RuntimeError("DingTalk send reply failed: missing target conversation")

    def build_push_context(self, user_id: str, chat_id: str = "") -> dict:
        message_id = uuid.uuid4().hex
        return {
            "sender_id": user_id,
            "conversation_id": chat_id,
            "open_conversation_id": chat_id,
            "conversation_type": "2" if chat_id else "1",
            "message_id": message_id,
            "stream_key": (
                f"dingtalk_group_{chat_id}_{message_id}"
                if chat_id
                else f"dingtalk_direct_{user_id}_{message_id}"
            ),
        }

    async def _reply_via_webhook(self, webhook_url: str, content: str) -> bool:
        """通过 sessionWebhook 回复（markdown 格式）"""
        title = content[:10].replace("\n", " ")
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": content,
            },
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload) as resp:
                    data = await resp.json()
                    if data.get("errcode") == 0:
                        return True
                    logger.error(f"[{self.name}] Webhook reply error: {data}")
                    return False
        except Exception as e:
            logger.error(f"[{self.name}] Webhook reply exception: {e}")
            return False

    async def _send_oto_message(self, user_id: str, content: str, robot_code: str = ""):
        """
        通过 Robot API v1.0 发送单聊消息

        POST /v1.0/robot/oToMessages/batchSend
        """
        await self._ensure_token()

        url = f"{DINGTALK_API_BASE}/v1.0/robot/oToMessages/batchSend"
        headers = {
            "Content-Type": "application/json",
            "x-acs-dingtalk-access-token": self._access_token,
        }
        title = content[:20].replace("\n", " ")
        payload = {
            "robotCode": robot_code or self.robot_code,
            "userIds": [user_id],
            "msgKey": "sampleMarkdown",
            "msgParam": json.dumps({"title": title, "text": content}, ensure_ascii=False),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    if resp.status == 200 and data.get("success") is not False:
                        logger.info(f"[{self.name}] OTO message sent to {user_id}")
                        return True
                    else:
                        body = await resp.text()
                        raise RuntimeError(f"DingTalk OTO send failed {resp.status}: {body}")
        except Exception as e:
            logger.error(f"[{self.name}] OTO send exception: {e}")
            raise

    async def _send_group_message(self, open_conversation_id: str, content: str, robot_code: str = ""):
        """
        通过 Robot API v1.0 发送群聊消息

        POST /v1.0/robot/groupMessages/send
        """
        await self._ensure_token()

        url = f"{DINGTALK_API_BASE}/v1.0/robot/groupMessages/send"
        headers = {
            "Content-Type": "application/json",
            "x-acs-dingtalk-access-token": self._access_token,
        }
        title = content[:20].replace("\n", " ")
        payload = {
            "robotCode": robot_code or self.robot_code,
            "openConversationId": open_conversation_id,
            "msgKey": "sampleMarkdown",
            "msgParam": json.dumps({"title": title, "text": content}, ensure_ascii=False),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    if resp.status == 200 and data.get("success") is not False:
                        logger.info(f"[{self.name}] Group message sent to {open_conversation_id}")
                        return True
                    else:
                        body = await resp.text()
                        raise RuntimeError(f"DingTalk group send failed {resp.status}: {body}")
        except Exception as e:
            logger.error(f"[{self.name}] Group send exception: {e}")
            raise

    # ============================================================
    # 流式输出（AI Card）
    # ============================================================

    async def _send_streaming_update(self, msg: ChannelMessage, content: str):
        """流式中间更新：通过 AI Card 实时更新内容"""
        if not self.card_template_id:
            return

        stream_key = self._build_card_stream_key(msg)

        # 内容去重
        if self._streaming_last_content.get(stream_key) == content:
            return
        self._streaming_last_content[stream_key] = content

        await self._ensure_token()

        card_id = self._streaming_card_ids.get(stream_key)
        if not card_id:
            card_id = await self._create_ai_card(msg)
            if card_id:
                self._streaming_card_ids[stream_key] = card_id
            else:
                return

        await self._update_ai_card(card_id, content, is_final=False)

    async def _send_streaming_final(self, msg: ChannelMessage, content: str):
        """流式结束：最终更新 AI Card 或回退到普通消息"""
        logger.info(f"[{self.name}] _send_streaming_final called, content_len={len(content)}")
        self._streaming_sent = True
        stream_key = self._build_card_stream_key(msg)

        card_id = self._streaming_card_ids.get(stream_key)
        logger.info(f"[{self.name}] stream_key={stream_key}, card_id={card_id}, has_template={bool(self.card_template_id)}")

        if card_id:
            logger.info(f"[{self.name}] Updating AI Card: {card_id}")
            await self._ensure_token()
            ok = await self._update_ai_card(card_id, content, is_final=True)
            logger.info(f"[{self.name}] AI Card update result: {ok}")
            if not ok:
                logger.info(f"[{self.name}] AI Card update failed, calling send_reply")
                await self.send_reply(msg, content)
        else:
            logger.info(f"[{self.name}] No card_id, calling send_reply directly")
            await self.send_reply(msg, content)

        # 清理流式状态
        self._streaming_card_ids.pop(stream_key, None)
        self._streaming_last_content.pop(stream_key, None)
        logger.info(f"[{self.name}] _send_streaming_final cleanup done")

    async def _create_ai_card(self, msg: ChannelMessage) -> Optional[str]:
        """创建钉钉 AI Card 并投递到会话，返回 card_instance_id"""
        conversation_type = msg.reply_context.get("conversation_type", "1")
        open_conversation_id = (
            msg.reply_context.get("open_conversation_id")
            or msg.reply_context.get("conversation_id")
            or msg.chat_id
            or ""
        )
        sender_id = msg.reply_context.get("sender_id", "")
        robot_code = self._resolve_robot_code(msg)

        card_instance_id = f"card_{uuid.uuid4().hex[:24]}"

        if conversation_type == "2" and open_conversation_id:
            open_space_id = f"dtv1.card//IM_GROUP.{open_conversation_id}"
        else:
            open_space_id = f"dtv1.card//IM_ROBOT.{sender_id}"

        create_body = {
            "cardTemplateId": self.card_template_id,
            "outTrackId": card_instance_id,
            "cardData": {"cardParamMap": {self.card_template_key: "思考中..."}},
            "callbackType": "STREAM",
            "openSpaceId": open_space_id,
            "userIdType": 1,
        }

        if conversation_type == "2":
            create_body["imGroupOpenSpaceModel"] = {"supportForward": True}
            create_body["imGroupOpenDeliverModel"] = {"robotCode": robot_code}
        else:
            create_body["imRobotOpenSpaceModel"] = {"supportForward": True}
            create_body["imRobotOpenDeliverModel"] = {
                "spaceType": "IM_ROBOT",
                "robotCode": robot_code,
            }

        url = f"{DINGTALK_API_BASE}/v1.0/card/instances/createAndDeliver"
        headers = {
            "Content-Type": "application/json",
            "x-acs-dingtalk-access-token": self._access_token,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=create_body, headers=headers) as resp:
                    data, body = await self._read_http_response(resp)
                    if resp.status != 200:
                        logger.warning(f"[{self.name}] AI Card create failed {resp.status}: {body}")
                        return None
                    if data and data.get("success") is False:
                        logger.warning(f"[{self.name}] AI Card create error: {data}")
                        return None
                    if data:
                        logger.info(
                            f"[{self.name}] AI Card created: outTrackId={card_instance_id}, "
                            f"response={json.dumps(data, ensure_ascii=False)[:500]}"
                        )
                    else:
                        logger.info(
                            f"[{self.name}] AI Card created: outTrackId={card_instance_id}, "
                            f"raw_response={body[:500]}"
                        )
                    return card_instance_id
        except Exception as e:
            logger.warning(f"[{self.name}] AI Card create exception: {e}")
            return None

    async def _update_ai_card(self, card_instance_id: str, content: str, is_final: bool = False) -> bool:
        """更新钉钉 AI Card 内容"""
        stream_body = {
            "outTrackId": card_instance_id,
            "guid": uuid.uuid4().hex,
            "key": self.card_template_key,
            "content": content,
            "isFull": True,
            "isFinalize": is_final,
            "isError": False,
        }

        url = f"{DINGTALK_API_BASE}/v1.0/card/streaming"
        headers = {
            "Content-Type": "application/json",
            "x-acs-dingtalk-access-token": self._access_token,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(url, json=stream_body, headers=headers) as resp:
                    data, body = await self._read_http_response(resp)
                    if resp.status != 200:
                        logger.warning(f"[{self.name}] AI Card update failed {resp.status}: {body}")
                        return False
                    if data and data.get("success") is False:
                        logger.warning(f"[{self.name}] AI Card update error: {data}")
                        return False
                    logger.debug(
                        f"[{self.name}] AI Card update ok: outTrackId={card_instance_id}, "
                        f"final={is_final}, response={(json.dumps(data, ensure_ascii=False) if data else body)[:500]}"
                    )
                    return True
        except Exception as e:
            logger.warning(f"[{self.name}] AI Card update exception: {e}")
            return False

    # ============================================================
    # Token 管理 (v1.0 API)
    # ============================================================

    async def _refresh_token(self):
        """获取 access_token (新版 v1.0 接口)"""
        url = f"{DINGTALK_API_BASE}/v1.0/oauth2/accessToken"
        payload = {"appKey": self.app_key, "appSecret": self.app_secret}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    data = await resp.json()
                    token = data.get("accessToken")
                    if token:
                        self._access_token = token
                        expire = data.get("expireIn", 7200)
                        self._token_expires_at = time.time() + expire - 300  # 提前 5 分钟刷新
                        logger.info(f"[{self.name}] Token refreshed, expires in {expire}s")
                    else:
                        logger.error(f"[{self.name}] Token refresh failed: {data}")
        except Exception as e:
            logger.error(f"[{self.name}] Token refresh exception: {e}")

    async def _ensure_token(self):
        """确保 token 有效，仅在过期时刷新"""
        if not self._access_token or time.time() >= self._token_expires_at:
            await self._refresh_token()

    # ============================================================
    # 签名验证
    # ============================================================

    def verify_callback(self, timestamp: str, sign: str) -> bool:
        """验证钉钉回调签名"""
        if not self.callback_secret:
            return True

        if not timestamp or not sign:
            logger.warning(
                f"[{self.name}] DingTalk callback missing signature headers "
                f"(timestamp={bool(timestamp)}, sign={bool(sign)})"
            )
            return False

        string_to_sign = f"{timestamp}\n{self.callback_secret}"
        hmac_code = hmac.new(
            self.callback_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        computed_sign = base64.b64encode(hmac_code).decode("utf-8")
        return safe_compare_digest(computed_sign, unquote(sign))

"""
飞书 (Feishu / Lark) Channel 适配器

接收方式：
1. Event Stream (长连接，无需公网 IP) - 使用 lark-oapi SDK (独立进程)
2. HTTP 回调（Event Subscription，需要公网 IP）

发送方式：POST /open-apis/im/v1/messages
认证方式：app_id + app_secret → tenant_access_token
"""

import asyncio
import hashlib
import json
import multiprocessing
import time
import warnings
from typing import Optional

import aiohttp

from agentclaw.channels import ChannelBase, ChannelMessage
from agentclaw.logger.config import get_logger
from agentclaw.config import get_config
from agentclaw.runtime.resource_manager import get_resource_manager

logger = get_logger(__name__)

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API\..*",
    category=UserWarning,
    module=r"lark_oapi\.ws\.pb\.google",
)

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        P2ImChatAccessEventBotP2pChatEnteredV1,
        P2ImMessageMessageReadV1,
        P2ImMessageReceiveV1,
    )
    LARK_SDK_AVAILABLE = True
except ImportError:
    LARK_SDK_AVAILABLE = False
    logger.warning("lark-oapi not installed, Stream mode unavailable. Install: pip install lark-oapi")


def _run_lark_ws_process(
    app_id: str,
    app_secret: str,
    redis_channel: str,
    status_channel: str,
    redis_host: str,
    redis_port: int,
    redis_password: str,
):
    """独立进程运行 lark WebSocket 客户端"""
    import asyncio
    import sys
    import logging

    from agentclaw.database.manager import DatabaseManager, RedisConfig
    from agentclaw.logger.config import get_logger, setup_logging

    setup_logging(level="INFO")
    proc_logger = get_logger(__name__)
    logging.getLogger("lark").setLevel(logging.CRITICAL)
    logging.getLogger("lark_oapi").setLevel(logging.CRITICAL)

    redis_client = None
    ignored_event_types = {
        "im.chat.access_event.bot_p2p_chat_entered_v1",
        "im.message.message_read_v1",
    }

    def publish_status(stage: str, detail: str = "", **extra):
        payload = {"stage": stage, "detail": detail, "app_id": app_id, **extra}
        try:
            if redis_client is not None:
                redis_client.publish(status_channel, json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            proc_logger.error(f"Publish status failed: {e}")

    proc_logger.info(f"Starting with app_id={app_id}, redis_channel={redis_channel}")

    asyncio.set_event_loop(asyncio.new_event_loop())

    for mod in list(sys.modules.keys()):
        if mod.startswith('lark_oapi'):
            del sys.modules[mod]

    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        P2ImChatAccessEventBotP2pChatEnteredV1,
        P2ImMessageMessageReadV1,
        P2ImMessageReceiveV1,
    )

    proc_logger.info(f"Connecting to Redis {redis_host}:{redis_port}")
    redis_config = RedisConfig(host=redis_host, port=redis_port, password=redis_password or "")
    redis_client = DatabaseManager.create_sync_redis_client(redis_config)
    publish_status("starting")
    publish_status("redis_connected")

    try:
        original_connect = lark.ws.client.Client._connect

        async def wrapped_connect(self, *args, **kwargs):
            publish_status("ws_connecting")
            result = await original_connect(self, *args, **kwargs)
            publish_status("ws_connected")
            return result

        lark.ws.client.Client._connect = wrapped_connect
    except Exception as e:
        proc_logger.warning(f"Patch _connect failed: {e}")

    def message_handler(data: P2ImMessageReceiveV1):
        try:
            msg_data = {
                "message_id": data.event.message.message_id,
                "message_type": data.event.message.message_type,
                "chat_id": data.event.message.chat_id,
                "chat_type": data.event.message.chat_type,
                "content": data.event.message.content,
                "mentions": [{"key": m.key} for m in (data.event.message.mentions or [])],
                "sender_id": data.event.sender.sender_id.open_id if data.event.sender.sender_id else "",
            }
            proc_logger.info(f"Publishing message: {msg_data['message_id']}")
            redis_client.publish(redis_channel, json.dumps(msg_data, ensure_ascii=False))
            publish_status("message_received", message_id=msg_data["message_id"])
        except Exception as e:
            proc_logger.error(f"Error publishing message: {e}")
            publish_status("error", detail=str(e))

    def _ignore_bot_p2p_entered(_: P2ImChatAccessEventBotP2pChatEnteredV1):
        return None

    def _ignore_message_read(_: P2ImMessageMessageReadV1):
        return None

    def _extract_event_type(payload: bytes) -> str:
        try:
            data = json.loads(payload.decode("utf-8"))
        except Exception:
            return ""
        header = data.get("header") or {}
        if isinstance(header, dict):
            event_type = header.get("event_type")
            if isinstance(event_type, str):
                return event_type
        event = data.get("event") or {}
        if isinstance(event, dict):
            event_type = event.get("type")
            if isinstance(event_type, str):
                return event_type
        return ""

    try:
        proc_logger.info("Creating WebSocket client")
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(message_handler)
            .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(_ignore_bot_p2p_entered)
            .register_p2_im_message_message_read_v1(_ignore_message_read)
            .build()
        )
        original_do_without_validation = event_handler.do_without_validation

        def wrapped_do_without_validation(payload: bytes):
            event_type = _extract_event_type(payload)
            try:
                return original_do_without_validation(payload)
            except Exception as e:
                if event_type in ignored_event_types:
                    proc_logger.debug(f"Ignored Feishu event {event_type}: {e}")
                    return None
                raise

        event_handler.do_without_validation = wrapped_do_without_validation
        ws_client = lark.ws.Client(app_id, app_secret, event_handler=event_handler, log_level=lark.LogLevel.ERROR)

        proc_logger.info("Starting WebSocket connection")
        ws_client.start()
        publish_status("exited", detail="ws_client.start returned unexpectedly")
    except Exception as e:
        proc_logger.exception(f"WebSocket worker crashed: {e}")
        publish_status("error", detail=str(e), exc_type=type(e).__name__)
        raise



class FeishuChannel(ChannelBase):
    """飞书 Channel 适配器（支持 Stream 和 Callback 模式）"""

    channel_type = "feishu"

    def __init__(
        self,
        server_base_url: str = "http://127.0.0.1:8000",
        api_key: str = "",
        thread_mode: str = "per_user",
        app_id: str = "",
        app_secret: str = "",
        verification_token: str = "",
        encrypt_key: str = "",
        bot_name: str = "",
        mode: str = "stream",
        **kwargs,
    ):
        super().__init__(server_base_url=server_base_url, api_key=api_key, thread_mode=thread_mode, **kwargs)
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self.encrypt_key = encrypt_key
        self.bot_name = bot_name
        self.mode = mode

        self._tenant_access_token: str = ""
        self._token_expires_at: float = 0
        self._processed_message_ids: set = set()
        self._background_tasks: set = set()

        # 流式输出状态
        self._streaming_message_ids: dict[str, str] = {}   # thread_id → message_id
        self._streaming_last_content: dict[str, str] = {}  # thread_id → 上次发送内容（去重）

        self._ws_process: Optional[multiprocessing.Process] = None
        self._redis_channel = f"feishu:{self.app_id}:messages"
        self._status_channel = f"feishu:{self.app_id}:status"
        self._redis_task: Optional[asyncio.Task] = None
        self._status_task: Optional[asyncio.Task] = None
        self._pubsub = None
        self._status_pubsub = None
        self._process_resource_id: Optional[str] = None
        self._task_resource_id: Optional[str] = None
        self._status_task_resource_id: Optional[str] = None
        self._owner = f"channel:feishu:{self.app_id or 'unknown'}:{id(self)}"
        self._startup_timeout = 15.0
        self._startup_grace_period = 2.0
        self._worker_status = "stopped"

    async def start(self):
        """启动渠道"""
        if self._running:
            logger.info(f"[{self.name}] Already running (app_id={self.app_id})")
            return

        self._running = True
        self._worker_status = "starting"

        if self.mode == "stream":
            if not LARK_SDK_AVAILABLE:
                logger.error(f"[{self.name}] lark-oapi SDK not available, cannot start Stream mode")
                self._running = False
                self._worker_status = "failed"
                return

            config = get_config()
            if not config.redis or not config.redis.host:
                logger.error(f"[{self.name}] Redis not configured, cannot start Stream mode")
                self._running = False
                self._worker_status = "failed"
                return

            rm = get_resource_manager()

            self._status_task = asyncio.create_task(self._status_subscribe_loop(), name=f"feishu-status-{self.app_id}")
            self._status_task_resource_id = await rm.register_task(
                name=f"feishu_status_{self.app_id}",
                task=self._status_task,
                owner=self._owner,
            )

            ctx = multiprocessing.get_context("spawn")
            self._ws_process = ctx.Process(
                target=_run_lark_ws_process,
                args=(
                    self.app_id,
                    self.app_secret,
                    self._redis_channel,
                    self._status_channel,
                    config.redis.host,
                    config.redis.port,
                    config.redis.password or "",
                ),
                daemon=True,
                name=f"feishu-ws-{self.app_id}",
            )
            self._ws_process.start()
            self._process_resource_id = await rm.register_process(
                name=f"feishu_ws_{self.app_id}",
                process=self._ws_process,
                owner=self._owner,
            )

            self._redis_task = asyncio.create_task(self._redis_subscribe_loop(), name=f"feishu-redis-{self.app_id}")
            self._task_resource_id = await rm.register_task(
                name=f"feishu_redis_{self.app_id}",
                task=self._redis_task,
                owner=self._owner,
            )

            await self._wait_for_worker_ready()
            logger.info(f"[{self.name}] Started in Stream mode (app_id={self.app_id}, status={self._worker_status})")
        else:
            self._worker_status = "running"
            logger.info(f"[{self.name}] Started in Callback mode (app_id={self.app_id})")

    async def stop(self):
        if not self._running and not self._ws_process and not self._redis_task and not self._status_task:
            return

        self._running = False
        self._worker_status = "stopping"

        # 取消所有后台任务
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

        rm = get_resource_manager()

        if self._status_task_resource_id:
            await rm.unregister(self._status_task_resource_id, cleanup=True)
            self._status_task_resource_id = None
        elif self._status_task:
            self._status_task.cancel()
            try:
                await self._status_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._task_resource_id:
            await rm.unregister(self._task_resource_id, cleanup=True)
            self._task_resource_id = None
        elif self._redis_task:
            self._redis_task.cancel()
            try:
                await self._redis_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._status_pubsub:
            try:
                await self._status_pubsub.unsubscribe(self._status_channel)
                await self._status_pubsub.close()
            except Exception as e:
                logger.warning(f"[{self.name}] Status pubsub cleanup failed: {e}")
            finally:
                self._status_pubsub = None

        if self._pubsub:
            try:
                await self._pubsub.unsubscribe(self._redis_channel)
                await self._pubsub.close()
            except Exception as e:
                logger.warning(f"[{self.name}] Pubsub cleanup failed: {e}")
            finally:
                self._pubsub = None

        if self._process_resource_id:
            await rm.unregister(self._process_resource_id, cleanup=True)
            self._process_resource_id = None
        elif self._ws_process:
            self._ws_process.terminate()
            self._ws_process.join(timeout=5)
            if self._ws_process.is_alive():
                self._ws_process.kill()
                self._ws_process.join(timeout=2)

        self._status_task = None
        self._redis_task = None
        self._ws_process = None
        self._worker_status = "stopped"
        logger.info(f"[{self.name}] Feishu channel stopped")

    async def _wait_for_worker_ready(self):
        deadline = time.time() + self._startup_timeout
        grace_deadline = time.time() + min(self._startup_timeout, self._startup_grace_period)
        while time.time() < deadline:
            if self._worker_status == "running":
                return
            if self._worker_status == "failed":
                raise RuntimeError(f"[{self.name}] Worker failed to start (app_id={self.app_id})")
            if self._ws_process and not self._ws_process.is_alive():
                self._worker_status = "failed"
                raise RuntimeError(
                    f"[{self.name}] Worker exited unexpectedly (app_id={self.app_id}, exitcode={self._ws_process.exitcode})"
                )
            if time.time() >= grace_deadline and self._ws_process and self._ws_process.is_alive():
                if self._worker_status == "starting":
                    self._worker_status = "connecting"
                logger.info(
                    f"[{self.name}] Worker still connecting after {self._startup_grace_period:.1f}s, "
                    f"continuing startup asynchronously (status={self._worker_status})"
                )
                return
            await asyncio.sleep(0.2)

        if self._ws_process and self._ws_process.is_alive():
            if self._worker_status == "starting":
                self._worker_status = "connecting"
            logger.warning(
                f"[{self.name}] Worker startup timed out after {self._startup_timeout:.1f}s, "
                "keeping process alive and waiting for async status updates"
            )
            return

        self._worker_status = "failed"
        raise TimeoutError(f"[{self.name}] Worker startup timeout after {self._startup_timeout}s")

    async def _status_subscribe_loop(self):
        from agentclaw.database import get_database

        db = get_database()
        if db is None:
            raise RuntimeError(f"[{self.name}] Database manager unavailable for status subscription")
        if not db.is_redis_available():
            raise RuntimeError(f"[{self.name}] Redis unavailable for status subscription")

        client = await db.get_redis_client()
        if client is None:
            raise RuntimeError(f"[{self.name}] Redis client unavailable for status subscription")

        pubsub = client.pubsub()
        self._status_pubsub = pubsub
        logger.info(f"[{self.name}] Status subscriber connecting: {self._status_channel}")
        await pubsub.subscribe(self._status_channel)
        logger.info(f"[{self.name}] Status subscriber subscribed: {self._status_channel}")

        try:
            while self._running:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message or message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    stage = data.get("stage", "")
                    detail = data.get("detail", "")
                    logger.info(f"[{self.name}] Worker status: {stage} ({detail})")
                    if stage == "ws_connected":
                        self._worker_status = "running"
                    elif stage in {"starting", "redis_connected", "ws_connecting"}:
                        self._worker_status = "connecting"
                    elif stage == "error":
                        self._worker_status = "failed"
                    elif stage == "exited":
                        self._worker_status = "failed"
                except Exception as e:
                    logger.error(f"[{self.name}] Error handling worker status: {e}", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[{self.name}] Status subscriber crashed: {e}", exc_info=True)
            self._worker_status = "failed"
            raise
        finally:
            try:
                await pubsub.unsubscribe(self._status_channel)
                await pubsub.close()
            except Exception as e:
                logger.warning(f"[{self.name}] Status pubsub final cleanup failed: {e}")
            finally:
                if self._status_pubsub is pubsub:
                    self._status_pubsub = None

    async def _redis_subscribe_loop(self):
        """订阅Redis消息"""
        from agentclaw.database import get_database

        db = get_database()
        if db is None:
            raise RuntimeError(f"[{self.name}] Database manager unavailable for message subscription")
        if not db.is_redis_available():
            raise RuntimeError(f"[{self.name}] Redis unavailable for message subscription")

        client = await db.get_redis_client()
        if client is None:
            raise RuntimeError(f"[{self.name}] Redis client unavailable for message subscription")

        pubsub = client.pubsub()
        self._pubsub = pubsub
        logger.info(f"[{self.name}] Message subscriber connecting: {self._redis_channel}")
        await pubsub.subscribe(self._redis_channel)
        logger.info(f"[{self.name}] Message subscriber subscribed: {self._redis_channel}")

        try:
            while self._running:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await self._handle_redis_message(data)
                    except Exception as e:
                        logger.error(f"[{self.name}] Error handling Redis message: {e}", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[{self.name}] Message subscriber crashed: {e}", exc_info=True)
            self._worker_status = "failed"
            raise
        finally:
            try:
                await pubsub.unsubscribe(self._redis_channel)
                await pubsub.close()
            except Exception as e:
                logger.warning(f"[{self.name}] Pubsub final cleanup failed: {e}")
            finally:
                if self._pubsub is pubsub:
                    self._pubsub = None

    async def _handle_redis_message(self, data: dict):
        """处理从Redis接收的消息"""
        message_id = data.get("message_id", "")
        if message_id in self._processed_message_ids:
            logger.debug(f"[{self.name}] Duplicate message ignored: {message_id}")
            return
        self._processed_message_ids.add(message_id)
        if len(self._processed_message_ids) > 1000:
            self._processed_message_ids = set(list(self._processed_message_ids)[-500:])

        if data.get("message_type") != "text":
            logger.debug(f"[{self.name}] Ignored non-text message: {data.get('message_type')}")
            return

        try:
            content = json.loads(data.get("content", "{}"))
            text = content.get("text", "")
        except:
            text = data.get("content", "")

        for mention in data.get("mentions", []):
            if mention.get("key"):
                text = text.replace(mention["key"], "").strip()

        if not text:
            return

        chat_type = data.get("chat_type", "")
        sender_id = data.get("sender_id", "")

        logger.info(
            f"[{self.name}] Received message from {sender_id} "
            f"type={chat_type} text={text[:50]}..."
        )

        channel_msg = ChannelMessage(
            channel="feishu",
            user_id=sender_id,
            chat_id=data.get("chat_id", "") if chat_type == "group" else "",
            message=text,
            message_type="text",
            reply_context={"chat_id": data.get("chat_id", ""), "chat_type": chat_type, "message_id": message_id},
            raw=data,
        )
        # 直接处理已解析的消息，绕过 on_message()
        await self._process_channel_message(channel_msg)

    async def on_message(self, raw_event: dict) -> Optional[ChannelMessage]:
        """解析飞书 HTTP 回调事件"""
        if "challenge" in raw_event:
            return None

        header = raw_event.get("header", {})
        event = raw_event.get("event", {})

        if header.get("event_type") != "im.message.receive_v1":
            return None

        message = event.get("message", {})
        sender = event.get("sender", {})
        message_id = message.get("message_id", "")

        if message_id in self._processed_message_ids:
            logger.debug(f"[{self.name}] Duplicate callback message ignored: {message_id}")
            return None
        self._processed_message_ids.add(message_id)
        if len(self._processed_message_ids) > 1000:
            self._processed_message_ids = set(list(self._processed_message_ids)[-500:])

        if message.get("message_type") != "text":
            logger.debug(f"[{self.name}] Ignored non-text callback: {message.get('message_type')}")
            return None

        try:
            content = json.loads(message.get("content", "{}"))
            text = content.get("text", "")
        except:
            text = message.get("content", "")

        mentions = message.get("mentions", [])
        for mention in mentions:
            if mention.get("key"):
                text = text.replace(mention["key"], "").strip()

        if not text:
            return None

        chat_type = message.get("chat_type", "")
        sender_id = sender.get("sender_id", {}).get("open_id", "")

        logger.info(
            f"[{self.name}] Received callback from {sender_id} "
            f"type={chat_type} text={text[:50]}..."
        )

        return ChannelMessage(
            channel="feishu",
            user_id=sender_id,
            chat_id=message.get("chat_id", "") if chat_type == "group" else "",
            message=text,
            message_type="text",
            reply_context={"chat_id": message.get("chat_id", ""), "chat_type": chat_type, "message_id": message_id},
            raw=raw_event,
        )

    async def send_reply(self, msg: ChannelMessage, content: str):
        """发送消息到飞书"""
        await self._ensure_token()

        chat_id = msg.reply_context.get("chat_id", "")
        open_id = msg.reply_context.get("open_id", "") or msg.user_id

        if chat_id:
            url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=chat_id"
            payload = {"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": content}, ensure_ascii=False)}
        elif open_id:
            url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id"
            payload = {"receive_id": open_id, "msg_type": "text", "content": json.dumps({"text": content}, ensure_ascii=False)}
        else:
            raise RuntimeError("Cannot send Feishu reply: no chat_id/open_id in reply_context")

        headers = {"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {self._tenant_access_token}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"Feishu send reply failed {resp.status}: {body}")
                    else:
                        data = await resp.json()
                        if data.get("code") != 0:
                            raise RuntimeError(f"Feishu send reply error: {data}")
                        else:
                            logger.info(f"[{self.name}] Reply sent to {chat_id or open_id}")
                            return True
        except Exception as e:
            logger.error(f"[{self.name}] Send reply exception: {e}")
            raise

    # ── 流式输出 ──────────────────────────────────────────────

    async def _send_streaming_update(self, msg: ChannelMessage, content: str):
        """流式中间更新：创建或更新飞书消息"""
        stream_key = self._build_thread_id(msg)

        # 内容去重
        if self._streaming_last_content.get(stream_key) == content:
            return
        self._streaming_last_content[stream_key] = content

        await self._ensure_token()
        chat_id = msg.reply_context.get("chat_id", "")
        if not chat_id:
            return

        message_id = self._streaming_message_ids.get(stream_key)

        if message_id:
            # 更新已有消息
            ok = await self._update_feishu_message(message_id, content, show_cursor=True)
            if not ok:
                # 更新失败，清除缓存，下次重建
                self._streaming_message_ids.pop(stream_key, None)
        else:
            # 首次：创建消息，缓存 message_id
            new_id = await self._create_feishu_message(chat_id, content)
            if new_id:
                self._streaming_message_ids[stream_key] = new_id

    async def _send_streaming_final(self, msg: ChannelMessage, content: str):
        """流式结束：最终更新并清理状态"""
        self._streaming_sent = True
        stream_key = self._build_thread_id(msg)

        await self._ensure_token()
        chat_id = msg.reply_context.get("chat_id", "")
        message_id = self._streaming_message_ids.get(stream_key)

        if message_id and chat_id:
            # 最终更新
            ok = await self._update_feishu_message(message_id, content, show_cursor=False)
            if not ok:
                # 更新失败，回退到新消息
                await self.send_reply(msg, content)
        elif chat_id:
            # 没有中间消息（内容太短未触发 update），直接发送
            await self.send_reply(msg, content)

        # 清理流式状态
        self._streaming_message_ids.pop(stream_key, None)
        self._streaming_last_content.pop(stream_key, None)

    async def _create_feishu_message(self, chat_id: str, content: str) -> Optional[str]:
        """创建飞书消息，返回 message_id"""
        feishu_content = self._build_text_message_content(content, show_cursor=True)
        url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=chat_id"
        headers = {"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {self._tenant_access_token}"}
        payload = {"receive_id": chat_id, "msg_type": "text", "content": feishu_content}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"[{self.name}] Streaming create failed {resp.status}: {body}")
                        return None
                    data = await resp.json()
                    if data.get("code") != 0:
                        logger.error(f"[{self.name}] Streaming create error: {data}")
                        return None
                    message_id = data.get("data", {}).get("message_id")
                    logger.debug(f"[{self.name}] Streaming message created: {message_id}")
                    return message_id
        except Exception as e:
            logger.error(f"[{self.name}] Streaming create exception: {e}")
            return None

    def _build_text_message_content(self, content: str, *, show_cursor: bool) -> str:
        """构造飞书 text 消息内容字符串。"""
        display_content = f"{content} ▍" if show_cursor else content
        return json.dumps({"text": display_content}, ensure_ascii=False)

    async def _update_feishu_message(self, message_id: str, content: str, *, show_cursor: bool) -> bool:
        """更新飞书 text 消息内容。"""
        feishu_content = self._build_text_message_content(content, show_cursor=show_cursor)
        url = f"{FEISHU_API_BASE}/im/v1/messages/{message_id}"
        headers = {"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {self._tenant_access_token}"}
        payload = {"msg_type": "text", "content": feishu_content}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(f"[{self.name}] Streaming update failed {resp.status}: {body}")
                        return False
                    data = await resp.json()
                    if data.get("code") != 0:
                        logger.warning(f"[{self.name}] Streaming update error: {data}")
                        return False
                    return True
        except Exception as e:
            logger.warning(f"[{self.name}] Streaming update exception: {e}")
            return False

    async def _refresh_token(self):
        """获取/刷新 tenant_access_token"""
        from agentclaw.database import get_database

        db = get_database()

        # 先尝试从Redis获取
        if db and db.is_redis_available():
            cache_key = f"feishu:token:{self.app_id}"
            cached = await db.redis_get(cache_key)
            if cached:
                self._tenant_access_token = cached
                client = await db.get_redis_client()
                ttl = await client.ttl(cache_key)
                self._token_expires_at = time.time() + ttl
                logger.debug(f"[{self.name}] Token loaded from cache, expires in {ttl}s")
                return

        url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal/"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        try:
            timeout = aiohttp.ClientTimeout(total=10, connect=5, sock_connect=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    data = await resp.json()
                    if data.get("code") == 0:
                        self._tenant_access_token = data["tenant_access_token"]
                        expire = data.get("expire", 7200)
                        self._token_expires_at = time.time() + expire - 300

                        # 存储到Redis
                        if db and db.is_redis_available():
                            cache_key = f"feishu:token:{self.app_id}"
                            await db.redis_set(cache_key, self._tenant_access_token, ex=expire - 300)

                        logger.info(f"[{self.name}] Token refreshed, expires in {expire}s")
                    else:
                        logger.error(f"[{self.name}] Token refresh failed: {data}")
        except Exception as e:
            logger.error(f"[{self.name}] Token refresh exception: {e}")

    async def _ensure_token(self):
        """确保 token 有效，仅在过期时刷新"""
        if not self._tenant_access_token or time.time() >= self._token_expires_at:
            await self._refresh_token()

    def build_push_context(self, user_id: str, chat_id: str = "") -> dict:
        """飞书主动推送：优先 chat_id，私聊可直接回 open_id"""
        return {
            "chat_id": chat_id,
            "open_id": user_id,
            "chat_type": "p2p" if not chat_id else "group",
        }

    def verify_callback(self, body: dict, headers: dict = None) -> Optional[dict]:
        """验证飞书回调请求，返回 challenge 响应或 None"""
        body_token = body.get("token")
        if (
            self.verification_token
            and body_token != self.verification_token
            and (body_token is not None or not self.encrypt_key)
        ):
            logger.warning(f"[{self.name}] Verification token mismatch")
            return {"error": "verification token mismatch"}

        if "challenge" in body:
            return {"challenge": body["challenge"]}

        if self.encrypt_key and headers:
            timestamp = headers.get("X-Lark-Request-Timestamp", "")
            nonce = headers.get("X-Lark-Request-Nonce", "")
            signature = headers.get("X-Lark-Signature", "")
            body_str = json.dumps(body, ensure_ascii=False)
            verify_str = f"{timestamp}{nonce}{self.encrypt_key}{body_str}"
            computed = hashlib.sha256(verify_str.encode("utf-8")).hexdigest()
            if computed != signature:
                logger.warning(f"[{self.name}] Signature verification failed")
                return {"error": "signature mismatch"}

        return None

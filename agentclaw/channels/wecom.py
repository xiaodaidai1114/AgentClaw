"""
企业微信 (WeCom) Channel 适配器

优先模式：
1. 智能体机器人 API 模式（bot_id + secret + WebSocket，默认）
2. 群机器人 Webhook（仅发送）

兼容保留：
3. 自建应用回调模式（Corp ID / Token / AES）仅保留底层验签与发送能力，
   不再作为默认接入方式，也不在管理后台作为主配置入口暴露。
"""

import asyncio
import base64
import hashlib
import json
import os
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import aiohttp

from agentclaw.channels import ChannelBase, ChannelMessage
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"
DEFAULT_WECOM_WS_URL = "wss://openws.work.weixin.qq.com"
WECOM_THINKING_PLACEHOLDER = "<think></think>"


class WeComChannel(ChannelBase):
    """企业微信 Channel 适配器"""

    channel_type = "wecom"

    def __init__(
        self,
        server_base_url: str = "http://127.0.0.1:8000",
        api_key: str = "",
        thread_mode: str = "per_user",
        mode: str = "",
        bot_id: str = "",
        secret: str = "",
        websocket_url: str = DEFAULT_WECOM_WS_URL,
        webhook_key: str = "",
        # 兼容保留：旧自建应用配置
        corp_id: str = "",
        corp_secret: str = "",
        agent_id: str = "",
        token: str = "",
        aes_key: str = "",
        encoding_aes_key: str = "",
        **kwargs,
    ):
        super().__init__(server_base_url=server_base_url, api_key=api_key, thread_mode=thread_mode, **kwargs)

        self.bot_id = bot_id
        self.secret = secret
        self.websocket_url = websocket_url or DEFAULT_WECOM_WS_URL
        self.webhook_key = webhook_key

        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.agent_id = agent_id
        self.token = token
        self.aes_key = aes_key or encoding_aes_key

        if mode:
            self.mode = mode
        elif self.bot_id or self.secret:
            self.mode = "bot"
        elif self.webhook_key:
            self.mode = "webhook"
        elif self.corp_id or self.corp_secret or self.agent_id or self.token or self.aes_key:
            self.mode = "app"
        else:
            self.mode = "bot"

        self._access_token: str = ""
        self._token_expires_at: float = 0
        self._crypto = None

        self._worker_process: Optional[asyncio.subprocess.Process] = None
        self._worker_stdout_task: Optional[asyncio.Task] = None
        self._worker_stderr_task: Optional[asyncio.Task] = None
        self._stdin_lock = asyncio.Lock()
        self._worker_status = "stopped"
        self._startup_timeout = 15.0
        self._startup_grace_period = 2.0

        self._processed_message_ids: set[str] = set()
        self._streaming_last_content: dict[str, str] = {}
        self._background_tasks: set[asyncio.Task] = set()

    async def start(self):
        if self._running:
            return

        self._running = True

        if self.mode == "bot":
            await self._start_bot_worker()
            logger.info("[%s] WeCom bot channel started (bot_id=%s)", self.name or "wecom", self.bot_id)
            return

        if self.mode == "app" and self.corp_id and self.corp_secret:
            await self._refresh_token()
        if self.mode == "app" and self.aes_key and self.token:
            self._init_crypto()

        self._worker_status = "running"
        logger.info("[%s] WeCom channel started (mode=%s)", self.name or "wecom", self.mode)

    async def stop(self):
        self._running = False
        self._worker_status = "stopping"

        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

        process = self._worker_process
        if process:
            try:
                await self._send_worker_command({"type": "shutdown"})
            except Exception:
                pass

            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

        self._worker_process = None
        self._worker_stdout_task = None
        self._worker_stderr_task = None
        self._worker_status = "stopped"
        logger.info("[%s] WeCom channel stopped", self.name or "wecom")

    async def on_message(self, raw_event: dict) -> Optional[ChannelMessage]:
        """解析企业微信回调消息（仅兼容旧 app 模式）"""
        msg_type = raw_event.get("MsgType", "text")
        content = raw_event.get("Content", "")
        from_user = raw_event.get("FromUserName", "")
        agent_id = raw_event.get("AgentID", "")

        if msg_type != "text" or not content:
            return None

        return ChannelMessage(
            channel="wecom",
            user_id=from_user,
            chat_id="",
            message=content.strip(),
            message_type="text",
            reply_context={
                "from_user": from_user,
                "agent_id": agent_id,
            },
            raw=raw_event,
        )

    async def send_reply(self, msg: ChannelMessage, content: str):
        if self.mode == "webhook":
            return await self._send_via_webhook(content)

        if self.mode == "bot":
            req_id = msg.reply_context.get("req_id", "")
            chat_id = (
                msg.reply_context.get("chat_id", "")
                or msg.chat_id
                or msg.reply_context.get("from_user", "")
                or msg.user_id
            )
            is_group_push = bool(chat_id and chat_id != (msg.user_id or msg.reply_context.get("from_user", "")))
            if req_id:
                await self._send_worker_command(
                    {
                        "type": "reply",
                        "req_id": req_id,
                        "content": content,
                        "finish": True,
                    }
                )
                return True
            elif is_group_push and self.webhook_key:
                # In WeCom AI bot mode, proactive sendMessage often surfaces as an app reminder
                # instead of a visible group chat bubble. Prefer the group webhook when configured.
                return await self._send_via_webhook(content)
            elif chat_id:
                if not is_group_push:
                    logger.info(
                        "[%s] WeCom proactive direct send uses bot WebSocket path; "
                        "the message may appear only as an app reminder in the client",
                        self.name or "wecom",
                    )
                elif not self.webhook_key:
                    logger.info(
                        "[%s] WeCom proactive group send uses bot WebSocket path because webhook_key is not configured; "
                        "the message may appear only as an app reminder in the client",
                        self.name or "wecom",
                    )
                await self._send_worker_command(
                    {
                        "type": "send",
                        "chat_id": chat_id,
                        "content": content,
                    }
                )
                return True
            else:
                raise RuntimeError("WeCom send reply failed: missing req_id/chat_id")

        from_user = msg.reply_context.get("from_user", "")
        if from_user:
            return await self._send_app_message(from_user, content)
        raise RuntimeError("WeCom send reply failed: missing target user")

    def build_push_context(self, user_id: str, chat_id: str = "") -> dict:
        if self.mode == "bot":
            return {"from_user": user_id, "chat_id": chat_id or user_id}
        return {"from_user": user_id, "agent_id": self.agent_id}

    async def _send_streaming_update(self, msg: ChannelMessage, content: str):
        if self.mode != "bot":
            return

        req_id = msg.reply_context.get("req_id", "")
        if not req_id:
            return

        if self._streaming_last_content.get(req_id) == content:
            return
        self._streaming_last_content[req_id] = content

        await self._send_worker_command(
            {
                "type": "reply",
                "req_id": req_id,
                "content": content,
                "finish": False,
            }
        )

    async def _prime_streaming_reply(self, msg: Optional[ChannelMessage]):
        """Send an early placeholder to reserve the WeCom reply window."""
        if self.mode != "bot" or not msg:
            return

        req_id = msg.reply_context.get("req_id", "")
        if not req_id or req_id in self._streaming_last_content:
            return

        try:
            await self._send_streaming_update(msg, WECOM_THINKING_PLACEHOLDER)
        except Exception as e:
            logger.warning(
                "[%s] Failed to prime WeCom streaming reply for req_id=%s: %s",
                self.name or "wecom",
                req_id,
                e,
            )

    async def _consume_sse(self, resp, msg: Optional[ChannelMessage] = None) -> Optional[str]:
        await self._prime_streaming_reply(msg)
        return await super()._consume_sse(resp, msg)

    async def _send_streaming_final(self, msg: ChannelMessage, content: str):
        req_id = msg.reply_context.get("req_id", "")
        if self.mode == "bot" and req_id:
            self._streaming_sent = True
            self._streaming_last_content.pop(req_id, None)
            await self._send_worker_command(
                {
                    "type": "reply",
                    "req_id": req_id,
                    "content": content,
                    "finish": True,
                }
            )
            return

        await super()._send_streaming_final(msg, content)

    def _track_background_task(self, task: asyncio.Task) -> asyncio.Task:
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _start_bot_worker(self):
        node_bin = shutil.which("node")
        if not node_bin:
            self._running = False
            raise RuntimeError("node is required for WeCom bot mode")
        if not self.bot_id or not self.secret:
            self._running = False
            raise RuntimeError("bot_id and secret are required for WeCom bot mode")

        worker_script = Path(__file__).resolve().with_name("wecom_worker").joinpath("worker.mjs")
        if not worker_script.exists():
            self._running = False
            raise RuntimeError(f"WeCom worker script not found: {worker_script}")

        env = os.environ.copy()
        env.update(
            {
                "WECOM_BOT_ID": self.bot_id,
                "WECOM_SECRET": self.secret,
                "WECOM_WS_URL": self.websocket_url,
            }
        )

        self._worker_status = "starting"
        self._worker_process = await asyncio.create_subprocess_exec(
            node_bin,
            str(worker_script),
            cwd=str(worker_script.parent),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._worker_stdout_task = self._track_background_task(
            asyncio.create_task(
                self._read_worker_stdout(),
                name=f"wecom-stdout-{self.name or self.bot_id}",
            )
        )
        self._worker_stderr_task = self._track_background_task(
            asyncio.create_task(
                self._read_worker_stderr(),
                name=f"wecom-stderr-{self.name or self.bot_id}",
            )
        )

        await self._wait_for_worker_ready()

    async def _wait_for_worker_ready(self):
        deadline = time.time() + self._startup_timeout
        grace_deadline = time.time() + min(self._startup_timeout, self._startup_grace_period)
        while time.time() < deadline:
            if self._worker_status == "running":
                return
            if self._worker_status == "failed":
                raise RuntimeError(f"[{self.name or 'wecom'}] WeCom worker failed to start")
            if self._worker_process and self._worker_process.returncode is not None:
                raise RuntimeError(
                    f"[{self.name or 'wecom'}] WeCom worker exited unexpectedly "
                    f"(exitcode={self._worker_process.returncode}); "
                    "run `npm install` in agentclaw/channels/wecom_worker first"
                )
            if time.time() >= grace_deadline and self._worker_process and self._worker_process.returncode is None:
                if self._worker_status == "starting":
                    self._worker_status = "connecting"
                logger.warning(
                    "[%s] WeCom worker still connecting after %.1fs, "
                    "continuing startup asynchronously (status=%s)",
                    self.name or "wecom",
                    self._startup_grace_period,
                    self._worker_status,
                )
                return
            await asyncio.sleep(0.2)

        if self._worker_process and self._worker_process.returncode is None:
            if self._worker_status == "starting":
                self._worker_status = "connecting"
            logger.warning(
                "[%s] WeCom worker startup timed out after %.1fs, "
                "keeping process alive and waiting for async status updates",
                self.name or "wecom",
                self._startup_timeout,
            )
            return

        raise TimeoutError(f"[{self.name or 'wecom'}] WeCom worker startup timeout after {self._startup_timeout}s")

    async def _read_worker_stdout(self):
        process = self._worker_process
        if not process or not process.stdout:
            return

        try:
            while self._running:
                line = await process.stdout.readline()
                if not line:
                    break
                payload = line.decode("utf-8", errors="replace").strip()
                if not payload:
                    continue
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    logger.warning("[%s] Invalid WeCom worker stdout: %s", self.name or "wecom", payload)
                    continue

                event_type = event.get("type", "")
                if event_type == "status":
                    self._handle_worker_status(event)
                elif event_type == "message":
                    await self._handle_worker_message(event)
                elif event_type == "result":
                    if not event.get("ok", True):
                        logger.warning("[%s] WeCom worker command failed: %s", self.name or "wecom", event)
                    elif event.get("op") == "send":
                        logger.info(
                            "[%s] WeCom proactive send acknowledged: chat_id=%s req_id=%s",
                            self.name or "wecom",
                            event.get("chat_id", ""),
                            event.get("req_id", ""),
                        )
                else:
                    logger.debug("[%s] Unknown WeCom worker event: %s", self.name or "wecom", event)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._worker_status = "failed"
            logger.error("[%s] WeCom worker stdout loop crashed: %s", self.name or "wecom", e, exc_info=True)
            raise
        finally:
            if self._running and process.returncode not in (None, 0):
                self._worker_status = "failed"

    async def _read_worker_stderr(self):
        process = self._worker_process
        if not process or not process.stderr:
            return

        try:
            while self._running:
                line = await process.stderr.readline()
                if not line:
                    break
                payload = line.decode("utf-8", errors="replace").rstrip()
                if payload:
                    logger.info("[%s] WeCom worker: %s", self.name or "wecom", payload)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[%s] WeCom worker stderr loop crashed: %s", self.name or "wecom", e, exc_info=True)
            raise

    def _handle_worker_status(self, event: dict):
        stage = event.get("stage", "")
        if stage in {"connected", "authenticated"}:
            self._worker_status = "running"
        elif stage in {"reconnecting", "disconnected"}:
            self._worker_status = "connecting"
        elif stage == "error":
            fatal = bool(event.get("fatal"))
            terminal_name = event.get("name", "") in {"WSAuthFailureError", "WSReconnectExhaustedError"}
            self._worker_status = "failed" if fatal or terminal_name else "connecting"
        elif stage == "kicked":
            self._worker_status = "failed"
        logger.info("[%s] WeCom worker status: %s", self.name or "wecom", event)

    async def _handle_worker_message(self, event: dict):
        msg = self._build_bot_message(event)
        if not msg:
            return
        await self._process_channel_message(msg)

    def _build_bot_message(self, event: dict) -> Optional[ChannelMessage]:
        headers = event.get("headers") or {}
        body = event.get("body") or {}

        message_id = body.get("msgid") or headers.get("req_id") or ""
        if message_id:
            if message_id in self._processed_message_ids:
                logger.debug("[%s] Duplicate WeCom bot message ignored: %s", self.name or "wecom", message_id)
                return None
            self._processed_message_ids.add(message_id)
            if len(self._processed_message_ids) > 1000:
                self._processed_message_ids = set(list(self._processed_message_ids)[-500:])

        text = self._extract_bot_message_text(body)
        if not text:
            logger.debug("[%s] Ignored empty WeCom bot message: %s", self.name or "wecom", body.get("msgtype"))
            return None

        from_user = (body.get("from") or {}).get("userid", "")
        raw_chat_id = body.get("chatid") or from_user
        chat_type = body.get("chattype") or "single"

        return ChannelMessage(
            channel="wecom",
            user_id=from_user,
            chat_id=raw_chat_id,
            message=text,
            message_type="text",
            reply_context={
                "req_id": headers.get("req_id", ""),
                "msgid": body.get("msgid", ""),
                "chat_id": raw_chat_id,
                "chat_type": chat_type,
                "from_user": from_user,
            },
            raw=event,
        )

    @staticmethod
    def _extract_bot_message_text(body: dict) -> str:
        parts: list[str] = []
        msg_type = body.get("msgtype", "")

        if msg_type == "mixed":
            for item in (body.get("mixed") or {}).get("msg_item", []):
                if item.get("msgtype") == "text":
                    content = (item.get("text") or {}).get("content", "")
                    if content:
                        parts.append(content)
        else:
            content = (body.get("text") or {}).get("content", "")
            if content:
                parts.append(content)
            if msg_type == "voice":
                voice_content = (body.get("voice") or {}).get("content", "")
                if voice_content:
                    parts.append(voice_content)

        if not parts:
            quote = body.get("quote") or {}
            quote_type = quote.get("msgtype", "")
            if quote_type == "text":
                content = (quote.get("text") or {}).get("content", "")
                if content:
                    parts.append(content)
            elif quote_type == "voice":
                content = (quote.get("voice") or {}).get("content", "")
                if content:
                    parts.append(content)

        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()

    async def _send_worker_command(self, payload: dict):
        process = self._worker_process
        if not process or process.returncode is not None or not process.stdin:
            raise RuntimeError("WeCom worker is not running")

        data = json.dumps(payload, ensure_ascii=False) + "\n"
        async with self._stdin_lock:
            process.stdin.write(data.encode("utf-8"))
            await process.stdin.drain()

    def _resolve_webhook_url(self) -> str:
        value = (self.webhook_key or "").strip()
        if not value:
            return ""
        if value.startswith("http://") or value.startswith("https://"):
            parsed = urlparse(value)
            query = parse_qs(parsed.query)
            key = (query.get("key") or [""])[0].strip()
            if key:
                self.webhook_key = key
                return f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
            return value
        return f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={value}"

    async def _send_via_webhook(self, content: str):
        url = self._resolve_webhook_url()
        if not url:
            raise RuntimeError("WeCom webhook send failed: missing webhook_key")
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    data = await resp.json()
                    if data.get("errcode") != 0:
                        raise RuntimeError(f"WeCom webhook send failed: {data}")
                    return True
        except Exception as e:
            logger.error("WeCom webhook exception: %s", e)
            raise

    async def _send_app_message(self, to_user: str, content: str):
        await self._ensure_token()

        url = f"{WECOM_API_BASE}/message/send?access_token={self._access_token}"
        payload = {
            "touser": to_user,
            "msgtype": "markdown",
            "agentid": int(self.agent_id) if self.agent_id else 0,
            "markdown": {"content": content},
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    data = await resp.json()
                    if data.get("errcode") != 0:
                        raise RuntimeError(f"WeCom app message send failed: {data}")
                    return True
        except Exception as e:
            logger.error("WeCom app message exception: %s", e)
            raise

    async def _refresh_token(self):
        url = f"{WECOM_API_BASE}/gettoken?corpid={self.corp_id}&corpsecret={self.corp_secret}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    data = await resp.json()
                    if data.get("errcode") == 0:
                        self._access_token = data["access_token"]
                        expire = data.get("expires_in", 7200)
                        self._token_expires_at = time.time() + expire - 300
                        logger.info("WeCom token refreshed, expires in %ss", expire)
                    else:
                        logger.error("WeCom token refresh failed: %s", data)
        except Exception as e:
            logger.error("WeCom token refresh exception: %s", e)

    async def _ensure_token(self):
        if time.time() >= self._token_expires_at:
            await self._refresh_token()

    def _init_crypto(self):
        try:
            from Crypto.Cipher import AES

            self._aes_key_bytes = base64.b64decode(self.aes_key + "=")
            self._aes_iv = self._aes_key_bytes[:16]
            self._aes_cls = AES
            logger.info("WeCom crypto initialized")
        except Exception as e:
            logger.warning("WeCom crypto init failed: %s", e)
            self._aes_key_bytes = b""
            self._aes_iv = b""
            self._aes_cls = None

    def _compute_signature(self, timestamp: str, nonce: str, payload: str) -> str:
        pieces = [self.token, timestamp, nonce]
        if payload:
            pieces.append(payload)
        check_str = "".join(sorted(pieces))
        return hashlib.sha1(check_str.encode("utf-8")).hexdigest()

    @staticmethod
    def _pkcs7_unpad(data: bytes) -> bytes:
        if not data:
            raise ValueError("empty decrypted payload")
        pad = data[-1]
        if pad < 1 or pad > 32:
            raise ValueError("invalid PKCS7 padding")
        return data[:-pad]

    def _decrypt_payload(self, encrypted: str) -> Optional[str]:
        if not self.aes_key:
            logger.warning("WeCom decrypt requested without aes_key")
            return None
        if not getattr(self, "_aes_cls", None):
            self._init_crypto()
        if not getattr(self, "_aes_cls", None):
            return None

        try:
            cipher = self._aes_cls.new(self._aes_key_bytes, self._aes_cls.MODE_CBC, self._aes_iv)
            plain = cipher.decrypt(base64.b64decode(encrypted))
            plain = self._pkcs7_unpad(plain)
            xml_len = int.from_bytes(plain[16:20], "big")
            xml_bytes = plain[20:20 + xml_len]
            receive_id = plain[20 + xml_len:].decode("utf-8")
            if self.corp_id and receive_id and receive_id != self.corp_id:
                logger.warning("WeCom receive_id mismatch: expected %s got %s", self.corp_id, receive_id)
                return None
            return xml_bytes.decode("utf-8")
        except Exception as e:
            logger.warning("WeCom decrypt payload failed: %s", e)
            return None

    @staticmethod
    def _xml_to_dict(xml_str: str) -> dict:
        try:
            root = ET.fromstring(xml_str)
            return {child.tag: child.text for child in root}
        except ET.ParseError as e:
            logger.error("WeCom XML parse error: %s", e)
            return {}

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> Optional[str]:
        computed = self._compute_signature(timestamp, nonce, echostr)
        if computed != msg_signature:
            logger.warning("WeCom URL verification failed")
            return None
        if not self.aes_key:
            return echostr
        return self._decrypt_payload(echostr)

    def parse_xml_message(
        self,
        xml_str: str,
        msg_signature: str = "",
        timestamp: str = "",
        nonce: str = "",
    ) -> Optional[dict]:
        data = self._xml_to_dict(xml_str)
        if not data:
            return {}

        encrypted = data.get("Encrypt", "")
        if not encrypted:
            if self.token:
                if not (msg_signature and timestamp and nonce):
                    logger.warning("WeCom callback missing signature parameters")
                    return None
                computed = self._compute_signature(timestamp, nonce, xml_str)
                if computed != msg_signature:
                    logger.warning("WeCom callback signature verification failed")
                    return None
            return data

        computed = self._compute_signature(timestamp, nonce, encrypted)
        if computed != msg_signature:
            logger.warning("WeCom callback signature verification failed")
            return None

        plain_xml = self._decrypt_payload(encrypted)
        if not plain_xml:
            return None
        return self._xml_to_dict(plain_xml)

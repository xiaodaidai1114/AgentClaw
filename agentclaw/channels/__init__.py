"""
AgentClaw Channel 适配层

将各 IM 平台消息转换为工作流调用，将工作流结果转换为平台消息回复。

一对多模型：同一渠道类型可注册多个实例（不同账号），每个实例绑定一个工作流。

支持平台：
- 飞书 (Feishu / Lark)
- 钉钉 (DingTalk)
- 企业微信 (WeCom)
- QQ
"""

import asyncio
import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import aiohttp

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


# 消息日志回调（server.py 注入，fire-and-forget）
_message_log_callback: Optional[Callable] = None


def set_message_log_callback(callback: Callable):
    """设置消息日志回调函数"""
    global _message_log_callback
    _message_log_callback = callback


@dataclass
class ChannelMessage:
    """统一消息格式"""
    channel: str                          # feishu | dingtalk | wecom | qq
    user_id: str                          # 平台用户 ID
    chat_id: str = ""                     # 群/频道 ID（私聊为空）
    message: str = ""                     # 文本内容
    message_type: str = "text"            # text | image | file | audio
    attachments: List[dict] = field(default_factory=list)
    reply_context: Dict[str, Any] = field(default_factory=dict)  # 平台回复所需上下文
    raw: Dict[str, Any] = field(default_factory=dict)            # 原始消息


class ChannelBase(ABC):
    """
    Channel 适配器基类

    每个实例 = 一个平台账号 + 一个工作流。
    一对多通过注册多个实例实现（如 feishu_sales, feishu_support）。
    """

    channel_type: str = ""

    DEFAULT_WORKFLOW_ID = "__builtin__"

    def __init__(
        self,
        server_base_url: str = "http://127.0.0.1:8000",
        api_key: str = "",
        thread_mode: str = "per_user",  # per_user | per_chat | shared
        workflow_id: str = "",
        user_input_field: str = "user_input",  # 必填，用户消息注入的字段名
        disable_confirm_tool: bool = False,  # 禁用 confirm_action 工具（仅用于不支持按钮回调的渠道）
        **kwargs,
    ):
        self.id = kwargs.pop("channel_id", "")       # 数据库 UUID
        self.name = kwargs.pop("channel_name", "")    # 实例名称
        self.webhook_secret = kwargs.pop("webhook_secret", "")
        self.workflow_id = workflow_id or self.DEFAULT_WORKFLOW_ID
        self.server_base_url = server_base_url.rstrip("/")
        self.api_key = api_key
        self.thread_mode = thread_mode
        self.user_input_field = user_input_field
        self.disable_confirm_tool = disable_confirm_tool
        self._running = False
        self._streaming_sent = False  # 标记流式是否已发送最终内容

    @abstractmethod
    async def start(self):
        """启动 Channel（注册 webhook / 建立长连接）"""

    @abstractmethod
    async def stop(self):
        """停止 Channel"""

    @abstractmethod
    async def on_message(self, raw_event: dict) -> Optional[ChannelMessage]:
        """将平台原始消息转换为统一格式"""

    @abstractmethod
    async def send_reply(self, msg: ChannelMessage, content: str):
        """将工作流结果发送回平台"""

    def build_push_context(self, user_id: str, chat_id: str = "") -> dict:
        """
        构造主动推送所需的 reply_context。
        子类可覆盖以添加平台特定字段。
        """
        return {"user_id": user_id, "chat_id": chat_id}

    def _build_thread_id(self, msg: ChannelMessage) -> str:
        """生成 thread_id，保持会话连续性"""
        if self.thread_mode == "per_chat" and msg.chat_id:
            return f"{self.channel_type}_{msg.chat_id}"
        elif self.thread_mode == "shared":
            return f"{self.channel_type}_shared"
        else:
            # per_user: 每个用户独立上下文
            key = f"{msg.chat_id}_{msg.user_id}" if msg.chat_id else msg.user_id
            return f"{self.channel_type}_{key}"

    async def handle_message(self, raw_event: dict):
        """处理消息的完整流程：解析 → 调用工作流 → 回复 → 记日志"""
        msg = await self.on_message(raw_event)
        if not msg:
            return
        await self._process_channel_message(msg)

    async def _process_channel_message(self, msg: ChannelMessage):
        """处理已解析的 ChannelMessage（内部方法，供子类直接调用）"""
        start_time = time.time()
        result = None
        execution: Dict[str, Any] = {}
        error_msg = ""
        status = "success"

        try:
            thread_id = self._build_thread_id(msg)
            execution = await self._call_workflow_stream(msg, thread_id)
            result = execution.get("answer")

            if result:
                # 流式模式下 _send_streaming_final 已发送，非流式回退到 send_reply
                if not self._streaming_sent:
                    await self.send_reply(msg, result)
            elif getattr(self, '_workflow_cancelled', False):
                status = "cancelled"
                error_msg = "workflow cancelled"
            else:
                status = "error"
                error_msg = "empty workflow response"
        except asyncio.TimeoutError:
            status = "timeout"
            error_msg = "workflow timeout"
            logger.error(f"[{self.channel_type}] handle_message timeout")
        except Exception as e:
            status = "error"
            error_msg = str(e)
            logger.error(f"[{self.channel_type}] handle_message failed: {e}", exc_info=True)
        finally:
            # fire-and-forget 消息日志
            if msg and _message_log_callback and self.id:
                duration_ms = int((time.time() - start_time) * 1000)
                try:
                    from agentclaw.channels.models import ChannelMessageLog
                    log = ChannelMessageLog(
                        channel_id=self.id,
                        channel_name=self.name,
                        user_id=msg.user_id,
                        chat_id=msg.chat_id,
                        message=msg.message,
                        reply=result or "",
                        workflow_id=self.workflow_id,
                        trace_id=execution.get("trace_id", ""),
                        status=status,
                        duration_ms=duration_ms,
                        error=error_msg,
                    )
                    asyncio.create_task(_message_log_callback(log))
                except Exception as log_err:
                    logger.debug(f"Message log callback failed: {log_err}")

    async def _call_workflow_stream(self, msg: ChannelMessage, thread_id: str) -> Dict[str, Any]:
        """
        调用 AgentClaw 工作流 API（SSE streaming 模式）。

        消费 SSE 事件流，收集所有 message 事件的 answer 字段拼成完整回复。
        IM 平台不适合逐 token 推送，所以收集完整回复后一次性发送。
        """
        url = f"{self.server_base_url}/api/workflow/run"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "workflow_id": self.workflow_id,
            "conversation_id": thread_id,
            "user_id": f"{self.channel_type}:{msg.user_id}",
            "response_mode": "streaming",
            "from_channel": True,
            "disable_confirm_tool": self.disable_confirm_tool,
            "inputs": {
                self.user_input_field: msg.message,
            },
        }

        if msg.attachments:
            payload["files"] = msg.attachments

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"[{self.channel_type}] workflow API error {resp.status}: {body}")
                        return {}

                    content_type = resp.headers.get("Content-Type", "")

                    # SSE streaming 响应
                    if "text/event-stream" in content_type:
                        return await self._consume_sse(resp, msg)

                    # Fallback: blocking JSON 响应
                    data = await resp.json()
                    metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
                    return {
                        "answer": (
                            data.get("answer")
                            or data.get("data", {}).get("text")
                            or data.get("data", {}).get("outputs", {}).get("result")
                            or json.dumps(data, ensure_ascii=False)
                        ),
                        "trace_id": metadata.get("trace_id", ""),
                        "usage": metadata.get("usage", {}) if isinstance(metadata, dict) else {},
                    }
        except asyncio.TimeoutError:
            logger.error(f"[{self.channel_type}] workflow API timeout")
            return {}
        except Exception as e:
            logger.error(f"[{self.channel_type}] workflow API call failed: {e}")
            return {}

    async def _consume_sse(self, resp: aiohttp.ClientResponse, msg: Optional[ChannelMessage] = None) -> Dict[str, Any]:
        """消费 SSE 事件流，实时推送到渠道"""
        chunks = []
        self._streaming_sent = False
        self._workflow_cancelled = False
        last_update_time = time.time()
        update_interval = 1.0  # 每秒最多更新一次
        workflow_answer = None
        trace_id = ""
        usage: Dict[str, Any] = {}

        logger.debug(f"[{self.channel_type}] _consume_sse: msg={'present' if msg else 'None'}")

        async for line_bytes in resp.content:
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if not data_str:
                continue
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            event_type = event.get("event", "")

            if event_type == "message":
                answer = event.get("answer", "")
                if answer:
                    chunks.append(answer)

                    # 实时推送（限流：每秒最多一次）
                    if msg:
                        now = time.time()
                        if now - last_update_time >= update_interval:
                            await self._send_streaming_update(msg, "".join(chunks))
                            last_update_time = now
            elif event_type == "message_end":
                metadata = event.get("metadata", {})
                if isinstance(metadata, dict) and isinstance(metadata.get("usage"), dict):
                    usage = metadata["usage"]

            elif event_type in ("message_end", "workflow_finished"):
                # 检测取消/失败状态
                event_data = event.get("data", {})
                event_status = event_data.get("status", "") if isinstance(event_data, dict) else ""
                outputs = event_data.get("outputs", {}) if isinstance(event_data, dict) else {}
                if isinstance(outputs, dict):
                    trace_id = outputs.get("trace_id", "") or trace_id

                if event_status == "cancelled" or (isinstance(outputs, dict) and outputs.get("cancelled")):
                    logger.info(f"[{self.channel_type}] Workflow cancelled, skipping reply")
                    self._workflow_cancelled = True
                    break

                # 发送最终内容
                logger.info(f"[{self.channel_type}] Received {event_type}, msg={'present' if msg else 'None'}")
                if msg:
                    workflow_answer = outputs.get("answer") if isinstance(outputs, dict) else None
                    final_content = workflow_answer or "".join(chunks)
                    logger.info(f"[{self.channel_type}] Sending final content: {final_content[:50]}...")
                    logger.info(f"[{self.channel_type}] About to call _send_streaming_final")
                    try:
                        await self._send_streaming_final(msg, final_content)
                        logger.info(f"[{self.channel_type}] _send_streaming_final completed")
                    except Exception as e:
                        logger.error(f"[{self.channel_type}] Failed to send final content: {e}", exc_info=True)
                else:
                    logger.warning(f"[{self.channel_type}] No msg to send final content")
                break

        return {
            "answer": workflow_answer or ("".join(chunks) if chunks else None),
            "trace_id": trace_id,
            "usage": usage,
        }

    async def _send_streaming_update(self, msg: ChannelMessage, content: str):
        """发送流式更新（子类可覆盖实现）"""
        # 默认不做任何事，子类实现流式更新
        pass

    async def _send_streaming_final(self, msg: ChannelMessage, content: str):
        """发送最终内容（子类可覆盖实现）"""
        self._streaming_sent = True
        try:
            logger.info(f"[{self.channel_type}] _send_streaming_final: calling send_reply")
            await self.send_reply(msg, content)
            logger.info(f"[{self.channel_type}] _send_streaming_final: send_reply completed")
        except Exception as e:
            logger.error(f"[{self.channel_type}] _send_streaming_final failed: {e}", exc_info=True)


class ChannelManager:
    """
    Channel 管理器，负责加载、启动和停止所有 Channel。

    一对多：同一渠道类型可注册多个实例（不同名称），每个实例对应一个账号+工作流。
    例如：feishu_sales (账号A → 销售工作流), feishu_support (账号B → 客服工作流)
    """

    def __init__(self):
        self._channels: Dict[str, ChannelBase] = {}

    def register(self, name: str, channel: ChannelBase):
        self._channels[name] = channel
        logger.info(f"Channel registered: {name} ({channel.channel_type}) → workflow={channel.workflow_id}")

    def unregister(self, name: str) -> bool:
        if name in self._channels:
            del self._channels[name]
            logger.info(f"Channel unregistered: {name}")
            return True
        return False

    def get(self, name: str) -> Optional[ChannelBase]:
        return self._channels.get(name)

    def get_by_type(self, channel_type: str) -> List[ChannelBase]:
        """按类型获取所有匹配的 Channel（一对多场景下可能有多个）"""
        return [ch for ch in self._channels.values() if ch.channel_type == channel_type]

    def list_all(self) -> Dict[str, ChannelBase]:
        return dict(self._channels)

    async def push_message(self, channel_name: str, user_id: str, content: str, chat_id: str = "") -> dict:
        """
        主动推送消息到指定 Channel 的用户。

        供工作流/定时任务调用，实现模型主动发消息。

        Args:
            channel_name: Channel 名称（如 "feishu_sales"）
            user_id: 目标用户 ID
            content: 消息内容
            chat_id: 群 ID（可选）

        Returns:
            是否发送成功
        """
        channel = self.get(channel_name)
        if not channel:
            # 按类型查找（取第一个），向后兼容
            matches = self.get_by_type(channel_name)
            channel = matches[0] if matches else None
        if not channel:
            logger.warning(f"Channel not found: {channel_name}")
            return {"ok": False, "error": f"channel not found: {channel_name}", "code": "not_found"}
        if not user_id and not chat_id:
            return {"ok": False, "error": "user_id or chat_id is required", "code": "invalid_target"}

        msg = ChannelMessage(
            channel=channel.channel_type,
            user_id=user_id,
            chat_id=chat_id,
            reply_context=channel.build_push_context(user_id, chat_id),
        )
        try:
            result = await channel.send_reply(msg, content)
            if result is False:
                return {"ok": False, "error": "send failed", "code": "send_failed"}
            return {"ok": True}
        except Exception as e:
            logger.error(f"push_message failed: {e}")
            return {"ok": False, "error": str(e), "code": "send_failed"}

    async def start_all(self):
        """启动所有 Channel"""
        for name, channel in self._channels.items():
            try:
                await channel.start()
                logger.info(f"Channel started: {name}")
            except Exception as e:
                logger.error(f"Channel start failed: {name}: {e}", exc_info=True)

    async def stop_all(self):
        """停止所有 Channel"""
        for name, channel in self._channels.items():
            try:
                await channel.stop()
                logger.info(f"Channel stopped: {name}")
            except Exception as e:
                logger.error(f"Channel stop failed: {name}: {e}")

    @classmethod
    async def from_store(cls, store, server_base_url: str = "http://127.0.0.1:8000", api_key: str = "") -> "ChannelManager":
        """从数据库 ChannelStore 加载所有已启用的渠道"""
        manager = cls()
        channels, _ = await store.list_channels(enabled=True, limit=1000)

        for record in channels:
            platform_config = _resolve_env_vars(record.config)
            channel = _create_channel(
                ch_type=record.type,
                workflow_id=record.workflow_id,
                server_base_url=server_base_url,
                api_key=api_key,
                thread_mode=record.thread_mode,
                user_input_field=record.user_input_field,
                channel_id=record.id,
                channel_name=record.name,
                **platform_config,
            )
            if channel:
                manager.register(record.name, channel)
            else:
                logger.warning(f"Unknown channel type: {record.type} (name={record.name})")

        return manager

    @classmethod
    def from_config(cls, config_path: str, server_base_url: str = "http://127.0.0.1:8000", api_key: str = "") -> "ChannelManager":
        """
        从配置文件加载所有 Channel。

        一对多示例（channels.json）：
        {
          "channels": [
            {"name": "feishu_sales", "type": "feishu", "workflow_id": "sales_wf",
             "user_input_field": "query", "config": {"app_id": "...", "app_secret": "..."}},
            {"name": "feishu_support", "type": "feishu", "workflow_id": "support_wf",
             "user_input_field": "question", "config": {"app_id": "...", "app_secret": "..."}}
          ]
        }
        """
        manager = cls()
        config_file = Path(config_path)

        if not config_file.exists():
            logger.debug(f"channels.json not found: {config_path}")
            return manager

        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)

        for idx, ch_config in enumerate(config.get("channels", [])):
            if not ch_config.get("enabled", True):
                continue

            ch_type = ch_config.get("type", "")
            ch_name = ch_config.get("name", f"{ch_type}_{idx}")
            workflow_id = ch_config.get("workflow_id", "")
            thread_mode = ch_config.get("thread_mode", "per_user")
            user_input_field = ch_config.get("user_input_field", "user_input")
            platform_config = ch_config.get("config", {})

            # 环境变量替换
            platform_config = _resolve_env_vars(platform_config)

            channel = _create_channel(
                ch_type=ch_type,
                workflow_id=workflow_id,
                server_base_url=server_base_url,
                api_key=api_key,
                thread_mode=thread_mode,
                user_input_field=user_input_field,
                **platform_config,
            )
            if channel:
                manager.register(ch_name, channel)
            else:
                logger.warning(f"Unknown channel type: {ch_type}")

        return manager


def _resolve_env_vars(config: dict) -> dict:
    """递归替换 ${ENV_VAR} 为环境变量值"""
    result = {}
    for key, value in config.items():
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_key = value[2:-1]
            result[key] = os.environ.get(env_key, "")
        elif isinstance(value, dict):
            result[key] = _resolve_env_vars(value)
        else:
            result[key] = value
    return result


def _create_channel(
    ch_type: str,
    server_base_url: str,
    api_key: str,
    thread_mode: str,
    workflow_id: str = "",
    user_input_field: str = "user_input",
    **kwargs,
) -> Optional[ChannelBase]:
    """工厂方法：根据类型创建 Channel 实例"""
    from agentclaw.channels.feishu import FeishuChannel
    from agentclaw.channels.dingtalk import DingTalkChannel
    from agentclaw.channels.wecom import WeComChannel
    from agentclaw.channels.qq import QQChannel

    channel_classes = {
        "feishu": FeishuChannel,
        "dingtalk": DingTalkChannel,
        "wecom": WeComChannel,
        "qq": QQChannel,
    }

    cls = channel_classes.get(ch_type)
    if not cls:
        return None

    return cls(
        server_base_url=server_base_url,
        api_key=api_key,
        thread_mode=thread_mode,
        workflow_id=workflow_id,
        user_input_field=user_input_field,
        **kwargs,
    )

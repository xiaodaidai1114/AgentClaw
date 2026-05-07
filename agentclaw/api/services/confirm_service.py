"""
确认服务 - 管理危险操作的用户确认

流程：
1. 模型调用 confirm_action 工具 → 创建 pending confirmation
2. SSE 推送 confirm_request 事件给前端
3. 前端弹出确认对话框
4. 用户点击确认/拒绝 → 调用 POST /api/confirm/{confirm_id}
5. 工具收到结果，返回给模型
"""

import asyncio
import time
from typing import Dict, Optional
import threading

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class PendingConfirmation:
    """一个待确认的操作"""

    __slots__ = ("confirm_id", "action", "description", "require_sudo", "created_at", "event", "event_loop", "result", "sudo_password")

    def __init__(self, confirm_id: str, action: str, description: str, require_sudo: bool = False):
        self.confirm_id = confirm_id
        self.action = action
        self.description = description
        self.require_sudo = require_sudo
        self.created_at = time.time()
        self.event = asyncio.Event()
        try:
            self.event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self.event_loop = None
        self.result: Optional[bool] = None  # True=approved, False=rejected
        self.sudo_password: Optional[str] = None  # sudo 密码（仅在 require_sudo=True 时使用）


class ConfirmationManager:
    """确认管理器（单例）"""

    _instance: Optional["ConfirmationManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._pending: Dict[str, PendingConfirmation] = {}

    def create(self, confirm_id: str, action: str, description: str, require_sudo: bool = False) -> PendingConfirmation:
        """创建一个待确认操作"""
        confirmation = PendingConfirmation(confirm_id, action, description, require_sudo)
        self._pending[confirm_id] = confirmation
        logger.info(f"创建确认请求: {confirm_id} - {action} (sudo={require_sudo})")
        return confirmation

    def resolve(self, confirm_id: str, approved: bool, sudo_password: Optional[str] = None) -> bool:
        """
        解决一个确认请求

        Args:
            confirm_id: 确认 ID
            approved: 是否批准
            sudo_password: sudo 密码（仅在 require_sudo=True 时需要）

        Returns:
            True 如果找到并解决，False 如果不存在
        """
        confirmation = self._pending.get(confirm_id)
        if not confirmation:
            return False
        if confirmation.result is not None or confirmation.event.is_set():
            return False

        confirmation.result = approved
        if approved and confirmation.require_sudo and sudo_password:
            confirmation.sudo_password = sudo_password
        self._set_event_threadsafe(confirmation)
        logger.info(f"确认请求已解决: {confirm_id} -> {'approved' if approved else 'rejected'}")
        return True

    @staticmethod
    def _set_event_threadsafe(confirmation: PendingConfirmation):
        """Wake the confirmation waiter on the loop that created it."""
        loop = confirmation.event_loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(confirmation.event.set)
        else:
            confirmation.event.set()

    def cleanup(self, confirm_id: str):
        """清理已完成的确认"""
        self._pending.pop(confirm_id, None)

    def get(self, confirm_id: str) -> Optional[PendingConfirmation]:
        """获取待确认操作"""
        return self._pending.get(confirm_id)

    def cleanup_expired(self, max_age: float = 300.0):
        """清理超时的确认（默认 5 分钟）"""
        now = time.time()
        expired = [
            cid
            for cid, c in self._pending.items()
            if now - c.created_at > max_age
        ]
        for cid in expired:
            c = self._pending.pop(cid)
            if not c.event.is_set():
                c.result = False
                self._set_event_threadsafe(c)
        if expired:
            logger.info(f"清理了 {len(expired)} 个超时确认请求")


def get_confirmation_manager() -> ConfirmationManager:
    return ConfirmationManager()

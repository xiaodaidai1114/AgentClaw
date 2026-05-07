"""
飞书扫码设置流程

复用 @larksuite/openclaw-lark-tools 的扫码创建机器人能力。
后端通过子进程运行该 npm 工具，将终端输出（含二维码）流式传给前端。

两种模式：
1. 嵌入式终端（PTY）：后端启动子进程，前端 xterm.js 渲染
2. 引导模式：前端展示命令，用户在自己的终端运行后手动输入凭据
"""

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

# 全局设置会话存储
_setup_sessions: Dict[str, "FeishuSetupSession"] = {}


@dataclass
class FeishuSetupSession:
    """一次飞书扫码设置会话"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"   # pending | running | completed | error
    process: Any = None
    output_buffer: list = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error: str = ""

    # openclaw 临时配置目录（隔离，不影响全局配置）
    _config_dir: Optional[str] = None

    async def start(self) -> str:
        """
        启动 npx @larksuite/openclaw-lark-tools install 子进程。

        返回 session_id。
        """
        # 检查 npx 可用性
        npx_path = shutil.which("npx")
        if not npx_path:
            self.status = "error"
            self.error = "npx not found. Please install Node.js first."
            return self.id

        # 创建临时配置目录
        self._config_dir = os.path.join(tempfile.gettempdir(), f"agentclaw_feishu_setup_{self.id}")
        os.makedirs(self._config_dir, exist_ok=True)

        self.status = "running"

        try:
            env = os.environ.copy()
            # 用临时目录隔离 openclaw 配置
            env["HOME"] = self._config_dir

            self.process = await asyncio.create_subprocess_exec(
                npx_path, "-y", "@larksuite/openclaw-lark-tools", "install",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.PIPE,
                env=env,
                cwd=self._config_dir,
            )

            # 后台读取输出
            asyncio.create_task(self._read_output())

        except Exception as e:
            self.status = "error"
            self.error = str(e)
            logger.error(f"Feishu setup start failed: {e}")

        return self.id

    async def _read_output(self):
        """异步读取子进程输出"""
        try:
            while self.process and self.process.stdout:
                data = await self.process.stdout.read(4096)
                if not data:
                    break
                self.output_buffer.append(data)
        except Exception as e:
            logger.debug(f"Read output error: {e}")
        finally:
            if self.process:
                await self.process.wait()
                if self.process.returncode == 0:
                    self.status = "completed"
                    self._parse_result()
                else:
                    self.status = "error"
                    self.error = f"Process exited with code {self.process.returncode}"

    async def send_input(self, text: str):
        """向子进程发送输入（用户在终端中的交互）"""
        if self.process and self.process.stdin:
            self.process.stdin.write(text.encode())
            await self.process.stdin.drain()

    def get_output(self, offset: int = 0) -> bytes:
        """获取从 offset 开始的输出数据"""
        data = b"".join(self.output_buffer[offset:])
        return data

    def _parse_result(self):
        """解析 openclaw 配置文件获取 app_id/app_secret"""
        if not self._config_dir:
            return

        # 尝试多个可能的配置文件路径
        config_paths = [
            Path(self._config_dir) / ".openclaw" / "openclaw.json",
            Path(self._config_dir) / "openclaw.json",
        ]

        for config_path in config_paths:
            if config_path.exists():
                try:
                    with open(config_path, "r") as f:
                        config = json.load(f)

                    feishu_config = config.get("channels", {}).get("feishu", {})
                    app_id = feishu_config.get("appId", "")
                    app_secret = feishu_config.get("appSecret", "")

                    # appSecret 可能是 SecretInput 格式
                    if isinstance(app_secret, dict):
                        source = app_secret.get("source", "")
                        if source == "env":
                            env_key = app_secret.get("id", "")
                            app_secret = os.environ.get(env_key, "")
                        else:
                            # 可能是加密存储，无法直接读取
                            app_secret = ""

                    if app_id:
                        self.result = {
                            "app_id": app_id,
                            "app_secret": app_secret if isinstance(app_secret, str) else "",
                            "domain": feishu_config.get("domain", "feishu"),
                            "connection_mode": feishu_config.get("connectionMode", "websocket"),
                        }
                        return
                except Exception as e:
                    logger.warning(f"Failed to parse openclaw config: {e}")

        # 如果解析不到，尝试从输出中提取
        all_output = b"".join(self.output_buffer).decode("utf-8", errors="replace")
        # openclaw-lark-tools 可能在输出中显示 appId
        for line in all_output.split("\n"):
            if "appId" in line or "App ID" in line:
                logger.debug(f"Found app_id hint in output: {line.strip()}")

    async def cleanup(self):
        """清理资源"""
        if self.process and self.process.returncode is None:
            try:
                self.process.kill()
                await self.process.wait()
            except Exception:
                pass

        # 清理临时目录
        if self._config_dir and os.path.exists(self._config_dir):
            import shutil as _shutil
            try:
                _shutil.rmtree(self._config_dir, ignore_errors=True)
            except Exception:
                pass


def create_setup_session() -> FeishuSetupSession:
    """创建新的设置会话"""
    session = FeishuSetupSession()
    _setup_sessions[session.id] = session
    return session


def get_setup_session(session_id: str) -> Optional[FeishuSetupSession]:
    """获取设置会话"""
    return _setup_sessions.get(session_id)


async def cleanup_session(session_id: str):
    """清理设置会话"""
    session = _setup_sessions.pop(session_id, None)
    if session:
        await session.cleanup()

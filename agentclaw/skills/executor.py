"""
Skill 脚本执行器 - 隔离环境执行
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from agentclaw.platform_compat import run_subprocess_in_executor

logger = logging.getLogger(__name__)


class SkillEnvironment:
    """Skill 独立执行环境"""

    BASE_DIR = Path.home() / ".agentclaw" / "skill-envs"

    def __init__(self, skill_name: str, requirements_file: Optional[Path] = None):
        """初始化 Skill 环境

        Args:
            skill_name: 技能名称
            requirements_file: requirements.txt 路径
        """
        self.skill_name = skill_name
        self.requirements_file = requirements_file
        self.venv_path = self.BASE_DIR / skill_name
        self._initialized = False

    @property
    def python(self) -> str:
        """获取该环境的 Python 解释器路径"""
        if sys.platform == "win32":
            return str(self.venv_path / "Scripts" / "python.exe")
        return str(self.venv_path / "bin" / "python")

    @property
    def is_initialized(self) -> bool:
        """环境是否已初始化"""
        return self._initialized or self.venv_path.exists()

    def ensure_initialized(self, force: bool = False) -> bool:
        """确保环境已初始化

        Args:
            force: 强制重新初始化（删除现有环境）

        Returns:
            是否成功初始化
        """
        if force and self.venv_path.exists():
            logger.info(f"Force reinitializing environment: {self.skill_name}")
            shutil.rmtree(self.venv_path)
            self._initialized = False

        if self._initialized:
            return True

        if self.venv_path.exists():
            self._initialized = True
            return True

        try:
            self._create_venv()
            self._install_dependencies()
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize environment for {self.skill_name}: {e}")
            return False

    def _create_venv(self):
        """创建虚拟环境（优先使用 uv）"""
        self.venv_path.parent.mkdir(parents=True, exist_ok=True)

        # 优先使用 uv（更快）
        if shutil.which("uv"):
            logger.info(f"Creating venv with uv: {self.venv_path}")
            subprocess.run(
                ["uv", "venv", str(self.venv_path)],
                check=True,
                capture_output=True,
            )
        else:
            logger.info(f"Creating venv with venv: {self.venv_path}")
            subprocess.run(
                [sys.executable, "-m", "venv", str(self.venv_path)],
                check=True,
                capture_output=True,
            )

    def _install_dependencies(self):
        """从 requirements.txt 安装依赖"""
        if not self.requirements_file or not self.requirements_file.exists():
            logger.debug(f"No requirements.txt for {self.skill_name}")
            return

        logger.info(f"Installing dependencies for {self.skill_name}")

        # 优先使用 uv pip
        if shutil.which("uv"):
            cmd = [
                "uv",
                "pip",
                "install",
                "--python",
                self.python,
                "-r",
                str(self.requirements_file),
            ]
        else:
            cmd = [
                self.python,
                "-m",
                "pip",
                "install",
                "-r",
                str(self.requirements_file),
            ]

        subprocess.run(cmd, check=True, capture_output=True)
        logger.info(f"Dependencies installed for {self.skill_name}")
        
        # 执行 post_install 钩子（如果存在）
        self._run_post_install()
    
    def _find_post_install_hook(self) -> Optional[Path]:
        """查找平台兼容的 post_install 钩子。"""
        if not self.requirements_file:
            return None

        hook_dir = self.requirements_file.parent
        if sys.platform == "win32":
            hook_names = [
                "post_install.ps1",
                "post_install.cmd",
                "post_install.bat",
                "post_install.py",
                "post_install.sh",
            ]
        else:
            hook_names = [
                "post_install.sh",
                "post_install.py",
                "post_install.ps1",
                "post_install.cmd",
                "post_install.bat",
            ]

        for name in hook_names:
            candidate = hook_dir / name
            if candidate.exists():
                return candidate.resolve()
        return None

    def _build_post_install_command(self, hook_path: Path) -> Optional[List[str]]:
        """根据钩子后缀构建跨平台执行命令。"""
        suffix = hook_path.suffix.lower()
        if suffix == ".py":
            return [self.python, str(hook_path)]
        if suffix == ".ps1":
            shell = (
                shutil.which("powershell")
                or shutil.which("powershell.exe")
                or shutil.which("pwsh")
                or shutil.which("pwsh.exe")
            )
            if shell:
                return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(hook_path)]
            return None
        if suffix in {".cmd", ".bat"}:
            shell = os.environ.get("COMSPEC") or shutil.which("cmd.exe") or shutil.which("cmd")
            if shell:
                return [shell, "/c", str(hook_path)]
            return None
        if suffix == ".sh":
            shell = shutil.which("bash") or shutil.which("sh")
            if shell:
                return [shell, str(hook_path)]
            return None
        return None

    def _run_post_install(self):
        """执行平台兼容的 post_install 钩子（如果存在）。"""
        hook_path = self._find_post_install_hook()
        if not hook_path:
            return

        cmd = self._build_post_install_command(hook_path)
        if not cmd:
            logger.warning(
                f"Post-install hook found but no compatible runner is available for {self.skill_name}: {hook_path.name}"
            )
            return

        logger.info(f"Running {hook_path.name} for {self.skill_name}")
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                cwd=str(hook_path.parent),
                env={**os.environ, "SKILL_PYTHON": self.python, "SKILL_VENV": str(self.venv_path)},
                timeout=600,  # 10 分钟超时
            )
            if result.stdout:
                logger.debug(f"Post-install output: {result.stdout.decode()}")
            logger.info(f"Post-install completed for {self.skill_name}: {hook_path.name}")
        except subprocess.TimeoutExpired:
            logger.error(f"Post-install timeout for {self.skill_name}")
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode() if e.stderr else "unknown error"
            logger.warning(f"Post-install failed for {self.skill_name} ({hook_path.name}): {stderr}")

    async def execute(
        self,
        script_path: str,
        args: List[str],
        timeout: int = 60,
        cwd: Optional[str] = None,
    ) -> str:
        """在隔离环境中执行脚本

        Args:
            script_path: 脚本路径
            args: 命令行参数
            timeout: 超时时间（秒）
            cwd: 工作目录，默认为脚本所在目录

        Returns:
            脚本输出（stdout）

        Raises:
            RuntimeError: 脚本执行失败或超时
        """
        if not self.ensure_initialized():
            raise RuntimeError(f"Failed to initialize environment for {self.skill_name}")

        # 构建命令
        cmd = [self.python, script_path] + args
        work_dir = cwd or str(Path(script_path).parent)

        logger.debug(f"Executing: {' '.join(cmd)} in {work_dir}")

        if sys.platform == "win32":
            proc = await run_subprocess_in_executor(
                cmd,
                cwd=work_dir,
                timeout=timeout,
            )
            stdout = proc.stdout
            stderr = proc.stderr
            returncode = proc.returncode
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                raise RuntimeError(f"Script execution timeout ({timeout}s): {script_path}")
            returncode = proc.returncode

        if returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Script execution failed: {error_msg}")

        return stdout.decode()

    def reset(self):
        """重置环境（删除并重新创建）"""
        if self.venv_path.exists():
            shutil.rmtree(self.venv_path)
            logger.info(f"Removed environment: {self.venv_path}")
        self._initialized = False


class ScriptExecutor:
    """脚本执行器（管理多个 Skill 环境）"""

    def __init__(self):
        self._envs: Dict[str, SkillEnvironment] = {}

    def register_skill(
        self, skill_name: str, requirements_file: Optional[Path] = None
    ) -> SkillEnvironment:
        """注册 Skill 环境

        Args:
            skill_name: 技能名称
            requirements_file: requirements.txt 路径

        Returns:
            SkillEnvironment 实例
        """
        if skill_name not in self._envs:
            self._envs[skill_name] = SkillEnvironment(skill_name, requirements_file)
            logger.debug(f"Registered skill environment: {skill_name}")
        return self._envs[skill_name]

    def get_env(self, skill_name: str) -> Optional[SkillEnvironment]:
        """获取 Skill 执行环境

        Args:
            skill_name: 技能名称

        Returns:
            SkillEnvironment 实例，不存在返回 None
        """
        return self._envs.get(skill_name)

    async def execute(
        self,
        skill_name: str,
        script_path: str,
        args: List[str],
        timeout: int = 60,
    ) -> str:
        """执行 Skill 脚本

        Args:
            skill_name: 技能名称
            script_path: 脚本路径
            args: 命令行参数
            timeout: 超时时间

        Returns:
            脚本输出

        Raises:
            ValueError: 技能未注册
            RuntimeError: 执行失败
        """
        env = self._envs.get(skill_name)
        if not env:
            raise ValueError(f"Skill not registered: {skill_name}")

        return await env.execute(script_path, args, timeout)

    def reset_env(self, skill_name: str) -> bool:
        """重置指定 Skill 环境

        Args:
            skill_name: 技能名称

        Returns:
            是否成功
        """
        env = self._envs.get(skill_name)
        if env:
            env.reset()
            return True
        return False

    def reset_all(self):
        """重置所有环境"""
        for env in self._envs.values():
            env.reset()
        logger.info("Reset all skill environments")

    def clean_all(self):
        """清理所有 Skill 环境（包括未注册的）"""
        if SkillEnvironment.BASE_DIR.exists():
            shutil.rmtree(SkillEnvironment.BASE_DIR)
            logger.info(f"Cleaned all skill environments: {SkillEnvironment.BASE_DIR}")
        self._envs.clear()

    def list_envs(self) -> List[str]:
        """列出所有已注册的环境"""
        return list(self._envs.keys())

    def list_all_envs(self) -> List[Path]:
        """列出所有已创建的环境（包括未注册的）"""
        if not SkillEnvironment.BASE_DIR.exists():
            return []
        return [d for d in SkillEnvironment.BASE_DIR.iterdir() if d.is_dir()]

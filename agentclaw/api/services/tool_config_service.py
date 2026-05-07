"""
工具配置服务 - 管理 Skill 和 MCP 工具的启用/禁用状态

所有工作流的配置都持久化到文件
"""

from typing import Dict, List, Optional, Set
import threading
import json
from pathlib import Path

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class ToolConfigManager:
    """
    工具配置管理器（单例）

    管理每个工作流的 skill 和 MCP 工具启用/禁用状态。
    配置持久化到文件，重启后自动恢复。
    """
    
    _instance: Optional["ToolConfigManager"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance
    
    def _init(self):
        # {workflow_id: {"disabled_skills": set(), "disabled_tools": set()}}
        self._configs: Dict[str, Dict[str, Set[str]]] = {}

        # 配置目录（所有工作流的配置）
        from agentclaw.config import get_config
        config = get_config()
        self._config_dir = config.project.project_dir / ".agentclaw"
        self._config_dir.mkdir(parents=True, exist_ok=True)

        # 加载所有工作流的持久化配置
        self._load_all_configs()
    
    def _ensure_config(self, workflow_id: str) -> Dict[str, Set[str]]:
        if workflow_id not in self._configs:
            self._configs[workflow_id] = {
                "disabled_skills": set(),
                "disabled_tools": set(),
            }
        return self._configs[workflow_id]
    
    def get_config(self, workflow_id: str) -> Dict[str, List[str]]:
        """获取工作流的工具配置"""
        config = self._ensure_config(workflow_id)
        return {
            "disabled_skills": sorted(config["disabled_skills"]),
            "disabled_tools": sorted(config["disabled_tools"]),
        }
    
    def set_config(
        self,
        workflow_id: str,
        disabled_skills: Optional[List[str]] = None,
        disabled_tools: Optional[List[str]] = None,
    ) -> Dict[str, List[str]]:
        """设置工作流的工具配置"""
        config = self._ensure_config(workflow_id)
        if disabled_skills is not None:
            config["disabled_skills"] = set(disabled_skills)
        if disabled_tools is not None:
            config["disabled_tools"] = set(disabled_tools)
        logger.info(
            f"工作流 {workflow_id} 工具配置更新: "
            f"disabled_skills={sorted(config['disabled_skills'])}, "
            f"disabled_tools={sorted(config['disabled_tools'])}"
        )

        # 持久化到文件
        self._save_config(workflow_id)

        return self.get_config(workflow_id)
    
    def reset_config(self, workflow_id: str) -> Dict[str, List[str]]:
        """重置工作流的工具配置（全部启用）"""
        self._configs.pop(workflow_id, None)

        # 删除配置文件
        config_file = self._get_config_file(workflow_id)
        if config_file.exists():
            config_file.unlink()
            logger.info(f"已删除工作流 {workflow_id} 的配置文件")

        logger.info(f"工作流 {workflow_id} 工具配置已重置")
        return self.get_config(workflow_id)
    
    def is_skill_disabled(self, workflow_id: str, skill_name: str) -> bool:
        """检查某个 skill 是否被禁用"""
        config = self._configs.get(workflow_id)
        if not config:
            return False
        return skill_name in config["disabled_skills"]
    
    def is_tool_disabled(self, workflow_id: str, tool_name: str) -> bool:
        """检查某个工具是否被禁用"""
        config = self._configs.get(workflow_id)
        if not config:
            return False
        return tool_name in config["disabled_tools"]
    
    def get_disabled_skills(self, workflow_id: str) -> Set[str]:
        """获取被禁用的 skill 集合"""
        config = self._configs.get(workflow_id)
        if not config:
            return set()
        return config["disabled_skills"].copy()
    
    def get_disabled_tools(self, workflow_id: str) -> Set[str]:
        """获取被禁用的工具集合"""
        config = self._configs.get(workflow_id)
        if not config:
            return set()
        return config["disabled_tools"].copy()

    def _get_config_file(self, workflow_id: str) -> Path:
        """获取工作流的配置文件路径"""
        # 文件名格式: {workflow_id}_tool_config.json
        safe_id = workflow_id.replace("/", "_").replace("\\", "_")
        return self._config_dir / f"{safe_id}_tool_config.json"

    def _load_all_configs(self) -> None:
        """从文件加载所有工作流的配置"""
        if not self._config_dir.exists():
            logger.debug("配置目录不存在，使用默认配置")
            return

        # 查找所有配置文件
        for config_file in self._config_dir.glob("*_tool_config.json"):
            try:
                workflow_id = config_file.stem.replace("_tool_config", "")
                self._load_config(workflow_id, config_file)
            except Exception as e:
                logger.warning(f"加载配置文件 {config_file} 失败: {e}")

    def _load_config(self, workflow_id: str, config_file: Optional[Path] = None) -> None:
        """从文件加载单个工作流的配置"""
        if config_file is None:
            config_file = self._get_config_file(workflow_id)

        if not config_file.exists():
            return

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            disabled_skills = set(data.get("disabled_skills", []))
            disabled_tools = set(data.get("disabled_tools", []))

            self._configs[workflow_id] = {
                "disabled_skills": disabled_skills,
                "disabled_tools": disabled_tools,
            }

            logger.info(
                f"已加载工作流 {workflow_id} 配置: "
                f"disabled_skills={sorted(disabled_skills)}, "
                f"disabled_tools={sorted(disabled_tools)}"
            )
        except Exception as e:
            logger.warning(f"加载工作流 {workflow_id} 配置失败: {e}")

    def _save_config(self, workflow_id: str) -> None:
        """保存单个工作流的配置到文件"""
        config = self._configs.get(workflow_id)
        if not config:
            return

        try:
            self._config_dir.mkdir(parents=True, exist_ok=True)

            config_file = self._get_config_file(workflow_id)
            data = {
                "disabled_skills": sorted(config["disabled_skills"]),
                "disabled_tools": sorted(config["disabled_tools"]),
            }

            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.debug(f"已保存工作流 {workflow_id} 配置到 {config_file}")
        except Exception as e:
            logger.error(f"保存工作流 {workflow_id} 配置失败: {e}")


def get_tool_config_manager() -> ToolConfigManager:
    """获取工具配置管理器实例"""
    return ToolConfigManager()

"""
提示词服务 - 封装提示词管理业务逻辑
"""

from typing import Optional, List, Dict, Any
import re

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class PromptService:
    """提示词服务"""
    
    def __init__(self, registry=None):
        self._registry = registry
    
    def _get_prompt_manager(self, workflow_id: str):
        """获取工作流的 PromptManager"""
        if not self._registry:
            return None
        
        wf = self._registry.get(workflow_id)
        if not wf:
            return None
        
        return getattr(wf, "_prompt_manager", None)
    
    def list_prompts(self, workflow_id: str) -> List[dict]:
        """获取工作流的所有提示词"""
        pm = self._get_prompt_manager(workflow_id)
        if not pm:
            return []
        
        # 使用异步版本确保数据库已加载
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在事件循环中，尝试触发延迟加载
                if hasattr(pm, '_ensure_db_loaded'):
                    asyncio.create_task(pm._ensure_db_loaded())
        except Exception:
            pass
        
        prompts = pm.list_all()
        
        for p in prompts:
            p["workflow_id"] = workflow_id
            p["variables"] = self._extract_variables(p.get("content", ""))
            # 字段映射：key -> prompt_key
            if "key" in p and "prompt_key" not in p:
                p["prompt_key"] = p.pop("key")
            # 字段映射：default -> default_content
            if "default" in p and "default_content" not in p:
                p["default_content"] = p.pop("default")
            # 字段映射：updated_at -> created_at
            if "updated_at" in p and "created_at" not in p:
                p["created_at"] = p.pop("updated_at")
        
        return prompts
    
    def get_prompt(self, workflow_id: str, prompt_key: str) -> Optional[dict]:
        """获取单个提示词"""
        pm = self._get_prompt_manager(workflow_id)
        if not pm:
            return None
        
        info = pm.get_prompt_info(prompt_key)
        if not info:
            return None
        
        info["workflow_id"] = workflow_id
        info["variables"] = self._extract_variables(info.get("content", ""))
        # 字段映射
        if "key" in info and "prompt_key" not in info:
            info["prompt_key"] = info.pop("key")
        if "default" in info and "default_content" not in info:
            info["default_content"] = info.pop("default")
        if "updated_at" in info and "created_at" not in info:
            info["created_at"] = info.pop("updated_at")
        
        return info
    
    async def update_prompt(
        self,
        workflow_id: str,
        prompt_key: str,
        content: str,
        updated_by: str = "admin",
    ) -> dict:
        """更新提示词"""
        pm = self._get_prompt_manager(workflow_id)
        if not pm:
            raise ValueError(f"工作流 '{workflow_id}' 不存在或未配置 PromptManager")
        
        # 确保热更新已就绪（会尝试连接 Redis）
        if hasattr(pm, 'ensure_hot_reload_ready'):
            await pm.ensure_hot_reload_ready()
        
        # 注意：即使热更新未启用，也可以更新提示词（会保存到数据库）
        # 只是不支持无重启热更新而已
        
        result = pm.update_prompt(prompt_key, content, updated_by)
        result["workflow_id"] = workflow_id
        result["variables"] = self._extract_variables(content)
        # 字段映射
        if "key" in result and "prompt_key" not in result:
            result["prompt_key"] = result.pop("key")
        if "default" in result and "default_content" not in result:
            result["default_content"] = result.pop("default")
        if "updated_at" in result and "created_at" not in result:
            result["created_at"] = result.pop("updated_at")
        
        return result
    
    async def reset_prompt(
        self,
        workflow_id: str,
        prompt_key: str,
        updated_by: str = "admin",
    ) -> dict:
        """重置提示词为默认值"""
        pm = self._get_prompt_manager(workflow_id)
        if not pm:
            raise ValueError(f"工作流 '{workflow_id}' 不存在或未配置 PromptManager")
        
        # 确保热更新已就绪（会尝试连接 Redis）
        if hasattr(pm, 'ensure_hot_reload_ready'):
            await pm.ensure_hot_reload_ready()
        
        # 注意：即使热更新未启用，也可以重置提示词（会保存到数据库）
        
        result = pm.reset_prompt(prompt_key, updated_by)
        result["workflow_id"] = workflow_id
        result["variables"] = self._extract_variables(result.get("content", ""))
        # 字段映射
        if "key" in result and "prompt_key" not in result:
            result["prompt_key"] = result.pop("key")
        if "default" in result and "default_content" not in result:
            result["default_content"] = result.pop("default")
        if "updated_at" in result and "created_at" not in result:
            result["created_at"] = result.pop("updated_at")
        
        return result
    
    async def get_history(
        self,
        workflow_id: str,
        prompt_key: str,
        limit: int = 10,
    ) -> List[dict]:
        """获取提示词历史版本"""
        pm = self._get_prompt_manager(workflow_id)
        if not pm:
            return []
        
        return await pm.get_history(prompt_key, limit)
    
    async def rollback(
        self,
        workflow_id: str,
        prompt_key: str,
        version: int,
        updated_by: str = "admin",
    ) -> dict:
        """回滚到指定版本"""
        pm = self._get_prompt_manager(workflow_id)
        if not pm:
            raise ValueError(f"工作流 '{workflow_id}' 不存在或未配置 PromptManager")
        
        result = await pm.rollback_to_version(prompt_key, version, updated_by)
        result["workflow_id"] = workflow_id
        
        return result
    
    def preview_prompt(
        self,
        workflow_id: str,
        content: str,
        variables: Dict[str, Any],
    ) -> str:
        """预览提示词（变量替换）"""
        pm = self._get_prompt_manager(workflow_id)
        if pm:
            return pm._render_template(content, variables)
        
        result = content
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result
    
    def _extract_variables(self, content: str) -> List[str]:
        """提取变量占位符"""
        pattern = r'\{(\w+)\}'
        return list(set(re.findall(pattern, content)))


def get_prompt_service() -> PromptService:
    """获取提示词服务实例"""
    from agentclaw.api.registry import WorkflowRegistry
    
    return PromptService(registry=WorkflowRegistry)

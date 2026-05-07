"""
模型服务 - 封装模型管理业务逻辑
"""

from typing import Optional

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

NON_CONVERSATION_MODEL_TYPES = {"embedding", "rerank"}


class ModelService:
    """模型服务"""
    
    def __init__(self, llm_manager=None):
        self._llm_manager = llm_manager
    
    def list_models(self) -> dict:
        """获取所有模型列表和降级状态"""
        if not self._llm_manager:
            return {"models": [], "fallback_state": {}}
        
        models = []
        for config in self._llm_manager.get_all_models():
            info = self._llm_manager.get_model_info(config.id)
            if info:
                models.append(info)
        
        fallback_state = self._llm_manager.get_fallback_state()
        
        return {
            "models": models,
            "fallback_state": fallback_state,
        }
    
    def list_available_models(self) -> dict:
        """获取可用模型列表（用于节点模型切换）"""
        if not self._llm_manager:
            return {"models": [], "default_model_id": None}

        models = []
        for config in self._llm_manager.get_all_models():
            model_type = str(config.model_type or "chat").strip().lower()
            if model_type in NON_CONVERSATION_MODEL_TYPES:
                continue
            models.append({
                "id": config.id,
                "provider": config.provider,
                "model": config.model,
                "model_type": config.model_type,
                "supports_vision": getattr(config, "supports_vision", False),
            })

        return {
            "models": models,
            "default_model_id": self._llm_manager.default_id,
        }
    
    def get_model(self, model_id: str) -> Optional[dict]:
        """获取单个模型信息"""
        if not self._llm_manager:
            return None
        
        return self._llm_manager.get_model_info(model_id)
    
    def update_model(self, model_id: str, **params) -> Optional[dict]:
        """更新模型配置"""
        if not self._llm_manager:
            return None
        
        success = self._llm_manager.update_model_config(model_id, **params)
        if not success:
            return None
        
        return self._llm_manager.get_model_info(model_id)
    
    def force_fallback(self, model_id: str, reason: str = "手动触发") -> dict:
        """手动触发降级"""
        if not self._llm_manager:
            return {}
        
        self._llm_manager.force_fallback(reason)
        return self._llm_manager.get_fallback_state()
    
    def force_primary(self, model_id: str) -> dict:
        """恢复主模型"""
        if not self._llm_manager:
            return {}
        
        self._llm_manager.force_primary()
        return self._llm_manager.get_fallback_state()
    
    def get_usage_stats(self) -> dict:
        """获取模型使用统计"""
        if not self._llm_manager:
            return {}
        
        return self._llm_manager.get_usage_stats()


def get_model_service() -> ModelService:
    """获取模型服务实例"""
    llm_manager = None
    
    try:
        from agentclaw.api.registry import WorkflowRegistry
        workflows = WorkflowRegistry.list_all()
        if workflows:
            llm_manager = getattr(workflows[0], "_llm_manager", None)
    except Exception:
        pass
    
    return ModelService(llm_manager=llm_manager)

"""
Admin Token 管理模块

提供：
- Token 生成和验证
- 从环境变量读取或自动生成
"""

from __future__ import annotations
import os
import secrets
from typing import Optional

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class AdminTokenManager:
    """
    Admin Token 管理器
    
    支持：
    - 从环境变量读取 Token（ADMIN_TOKEN）
    - 自动生成随机 Token（格式：ac-admin-{32位随机字符}）
    - Token 验证
    
    Example:
        manager = AdminTokenManager.get_instance()
        
        # 验证 Token
        if manager.verify(token):
            print("Token 有效")
    """
    
    _instance: Optional["AdminTokenManager"] = None
    _token: Optional[str] = None
    
    @classmethod
    def get_instance(cls) -> "AdminTokenManager":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（用于测试）"""
        cls._instance = None
        cls._token = None
    
    def __init__(self):
        if AdminTokenManager._token is None:
            AdminTokenManager._token = self._init_token()
    
    def _init_token(self) -> str:
        """初始化 Token"""
        # 从统一配置读取（会自动加载 .env）
        from agentclaw.config import get_config
        config = get_config()
        token = config.auth.admin_token

        if token:
            logger.info("使用环境变量配置的 Admin Token")
            return token
        
        # 自动生成临时 Token
        random_part = secrets.token_hex(16)
        token = f"ac-admin-{random_part}"
        from agentclaw.api.auth.utils import mask_secret
        
        logger.warning("=" * 60)
        logger.warning("⚠️  未配置 ADMIN_TOKEN 环境变量，已生成临时 Token")
        logger.warning(f"   Token: {mask_secret(token)}")
        logger.warning("   建议在环境变量中配置固定 Token：")
        logger.warning("   export ADMIN_TOKEN=your-secure-token")
        logger.warning("=" * 60)
        
        return token
    
    @property
    def token(self) -> str:
        """获取当前 Token"""
        return AdminTokenManager._token
    
    def verify(self, token: str) -> bool:
        """验证 Token"""
        if not token or not AdminTokenManager._token:
            return False
        return secrets.compare_digest(token, AdminTokenManager._token)


class WorkflowAPIKeyManager:
    """
    工作流 API Key 管理器
    
    支持：
    - 从环境变量读取 API Key（WORKFLOW_API_KEY）
    - 自动生成随机 API Key（格式：sk-{48位随机字符}）
    - API Key 验证
    
    Example:
        manager = WorkflowAPIKeyManager.get_instance()
        
        # 验证 API Key
        if manager.verify(api_key):
            print("API Key 有效")
    """
    
    _instance: Optional["WorkflowAPIKeyManager"] = None
    _api_key: Optional[str] = None
    
    @classmethod
    def get_instance(cls) -> "WorkflowAPIKeyManager":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（用于测试）"""
        cls._instance = None
        cls._api_key = None
    
    def __init__(self):
        if WorkflowAPIKeyManager._api_key is None:
            WorkflowAPIKeyManager._api_key = self._init_api_key()
    
    def _init_api_key(self) -> str:
        """初始化 API Key"""
        # 从统一配置读取（会自动加载 .env）
        from agentclaw.config import get_config
        config = get_config()
        api_key = config.auth.workflow_api_key

        if api_key:
            logger.info("使用环境变量配置的 Workflow API Key")
            return api_key
        
        # 自动生成 API Key 并写入环境变量
        random_part = secrets.token_hex(24)
        api_key = f"sk-{random_part}"
        
        # 写入环境变量，方便后续使用
        os.environ["WORKFLOW_API_KEY"] = api_key
        from agentclaw.api.auth.utils import mask_secret
        
        logger.warning("=" * 60)
        logger.warning("⚠️  未配置 WORKFLOW_API_KEY 环境变量，已生成 API Key")
        logger.warning(f"   API Key: {mask_secret(api_key)}")
        logger.warning("   请在请求头中添加: Authorization: Bearer <workflow-api-key>")
        logger.warning("   建议在环境变量中配置固定 API Key：")
        logger.warning("   export WORKFLOW_API_KEY=sk-your-secure-key")
        logger.warning("=" * 60)
        
        return api_key
    
    @property
    def api_key(self) -> str:
        """获取当前 API Key"""
        return WorkflowAPIKeyManager._api_key
    
    def verify(self, api_key: str) -> bool:
        """验证 API Key"""
        if not api_key or not WorkflowAPIKeyManager._api_key:
            return False
        return secrets.compare_digest(api_key, WorkflowAPIKeyManager._api_key)

"""
API Key 认证模块

提供：
- API Key 生成与验证
- 多种认证方式（Header / Query）
- 权限管理
- 用量限制
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import hashlib
import secrets
import json
from pathlib import Path

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


@dataclass
class APIKey:
    """API Key 配置"""
    key: str
    name: str = "default"
    workflows: List[str] = field(default_factory=lambda: ["*"])
    rate_limit: int = 0
    expires_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    _request_count: int = 0
    _last_reset: datetime = field(default_factory=datetime.now)
    
    def is_valid(self) -> bool:
        if self.expires_at and datetime.now() > self.expires_at:
            return False
        return True
    
    def can_access(self, workflow_id: str) -> bool:
        if not self.is_valid():
            return False
        if "*" in self.workflows:
            return True
        return workflow_id in self.workflows
    
    def check_rate_limit(self) -> bool:
        if self.rate_limit == 0:
            return True
        now = datetime.now()
        if (now - self._last_reset).seconds >= 60:
            self._request_count = 0
            self._last_reset = now
        if self._request_count >= self.rate_limit:
            return False
        self._request_count += 1
        return True
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "workflows": self.workflows,
            "rate_limit": self.rate_limit,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat(),
            "key_prefix": self.key[:8] + "..." if len(self.key) > 8 else self.key,
        }


@dataclass
class AuthConfig:
    """认证配置"""
    enabled: bool = False
    header_name: str = "Authorization"
    header_prefix: str = "Bearer"
    query_param: str = "api_key"
    allow_query: bool = True
    api_keys: Dict[str, APIKey] = field(default_factory=dict)
    storage: str = "memory"
    storage_path: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: dict) -> "AuthConfig":
        config = cls(
            enabled=data.get("enabled", False),
            header_name=data.get("header_name", "Authorization"),
            header_prefix=data.get("header_prefix", "Bearer"),
            query_param=data.get("query_param", "api_key"),
            allow_query=data.get("allow_query", True),
            storage=data.get("storage", "memory"),
            storage_path=data.get("storage_path"),
        )
        for key, key_config in data.get("api_keys", {}).items():
            if isinstance(key_config, dict):
                config.api_keys[key] = APIKey(
                    key=key,
                    name=key_config.get("name", "default"),
                    workflows=key_config.get("workflows", ["*"]),
                    rate_limit=key_config.get("rate_limit", 0),
                )
            else:
                config.api_keys[key] = APIKey(key=key, name=str(key_config))
        return config
    
    @classmethod
    def from_file(cls, path: str) -> "AuthConfig":
        file_path = Path(path)
        if not file_path.exists():
            return cls()
        with open(file_path, "r", encoding="utf-8") as f:
            if path.endswith(".json"):
                data = json.load(f)
            elif path.endswith((".yaml", ".yml")):
                import yaml
                data = yaml.safe_load(f)
            else:
                data = {}
        return cls.from_dict(data.get("auth", data))


@dataclass
class AuthResult:
    """认证结果"""
    valid: bool
    reason: str = ""
    key: Optional[APIKey] = None
    workflow_id: Optional[str] = None
    
    @property
    def error_message(self) -> str:
        messages = {
            "auth_disabled": "",
            "missing_key": "缺少 API Key，请在 Header 中提供 Authorization: Bearer sk-xxx",
            "invalid_key": "无效的 API Key",
            "expired_key": "API Key 已过期",
            "access_denied": f"无权访问工作流: {self.workflow_id}",
            "rate_limited": "请求过于频繁，请稍后重试",
        }
        return messages.get(self.reason, "认证失败")


class APIKeyManager:
    """API Key 管理器"""
    
    def __init__(self, config: Optional[AuthConfig] = None):
        self.config = config or AuthConfig()
        self._keys: Dict[str, APIKey] = dict(self.config.api_keys)
    
    def generate_key(
        self,
        name: str = "default",
        workflows: Optional[List[str]] = None,
        rate_limit: int = 0,
        expires_days: Optional[int] = None,
    ) -> str:
        """生成新的 API Key"""
        random_bytes = secrets.token_bytes(32)
        key_hash = hashlib.sha256(random_bytes).hexdigest()[:32]
        api_key = f"sk-{key_hash}"
        expires_at = None
        if expires_days:
            expires_at = datetime.now() + timedelta(days=expires_days)
        self._keys[api_key] = APIKey(
            key=api_key,
            name=name,
            workflows=workflows or ["*"],
            rate_limit=rate_limit,
            expires_at=expires_at,
        )
        logger.info(f"生成 API Key: {name} ({api_key[:8]}...)")
        return api_key
    
    def validate(self, api_key: str, workflow_id: Optional[str] = None) -> AuthResult:
        """验证 API Key"""
        if not self.config.enabled:
            return AuthResult(valid=True, reason="auth_disabled")
        if not api_key:
            return AuthResult(valid=False, reason="missing_key")
        key_obj = self._keys.get(api_key)
        if not key_obj:
            return AuthResult(valid=False, reason="invalid_key")
        if not key_obj.is_valid():
            return AuthResult(valid=False, reason="expired_key")
        if workflow_id and not key_obj.can_access(workflow_id):
            return AuthResult(valid=False, reason="access_denied", workflow_id=workflow_id)
        if not key_obj.check_rate_limit():
            return AuthResult(valid=False, reason="rate_limited")
        return AuthResult(valid=True, key=key_obj)
    
    def revoke(self, api_key: str) -> bool:
        """撤销 API Key"""
        if api_key in self._keys:
            del self._keys[api_key]
            logger.info(f"撤销 API Key: {api_key[:8]}...")
            return True
        return False
    
    def list_keys(self) -> List[dict]:
        """列出所有 Key"""
        return [key.to_dict() for key in self._keys.values()]
    
    def get_key(self, api_key: str) -> Optional[APIKey]:
        """获取 Key 对象"""
        return self._keys.get(api_key)
    
    def extract_key_from_request(self, headers: dict, query_params: dict) -> Optional[str]:
        """从请求中提取 API Key"""
        auth_header = headers.get(self.config.header_name.lower()) or headers.get(self.config.header_name)
        if auth_header:
            prefix = f"{self.config.header_prefix} "
            if auth_header.startswith(prefix):
                return auth_header[len(prefix):]
            if auth_header.startswith("sk-"):
                return auth_header
        if self.config.allow_query:
            return query_params.get(self.config.query_param)
        return None

"""
WorkflowRegistry - 工作流注册表

管理所有已发布的工作流，支持：
- 工作流注册和查找
- API 路由生成
- 版本管理和灰度发布
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Callable
import threading

from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow

logger = get_logger(__name__)


class WorkflowRegistry:
    """
    工作流注册表（单例）
    
    管理所有已发布的工作流，提供：
    - 注册和查找工作流
    - 生成 API 路由
    - 版本管理和灰度发布
    
    Example:
        # 注册
        WorkflowRegistry.register(workflow)
        
        # 查找
        workflow = WorkflowRegistry.get("customer_service_v1")
        
        # 获取所有
        all_workflows = WorkflowRegistry.list_all()
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance
    
    def _init(self):
        """初始化实例"""
        self._workflows: Dict[str, Workflow] = {}
        self._endpoints: Dict[str, dict] = {}  # {path: endpoint_config}
        self._traffic_split: Dict[str, Dict[str, str]] = {}  # {unified_path: {tag: workflow_id}}
    
    @classmethod
    def register(
        cls,
        workflow: Workflow,
        stream: bool = True,
        endpoints: Optional[List[dict]] = None,
        traffic_split: Optional[Dict[str, str]] = None,
        require_auth: bool = True,
    ) -> None:
        """
        注册工作流
        
        Args:
            workflow: 工作流实例
            stream: 是否启用流式输出（已废弃，保留用于兼容）
            endpoints: 自定义端点配置列表（已废弃）
            traffic_split: 灰度发布配置（已废弃）
            require_auth: 是否需要 API Key 认证
            
        Note:
            旧的路由格式 /api/{workflow_id}/stream 已废弃。
            请使用统一端点 /api/workflow/run，在 body 中指定 workflow_id。
            
        Raises:
            ValueError: 如果 workflow_id 已存在
        """
        instance = cls()
        
        # 校验 workflow_id 是否重复
        if workflow.id in instance._workflows:
            existing = instance._workflows[workflow.id]
            raise ValueError(
                f"Workflow ID '{workflow.id}' already registered. "
                f"Existing: '{existing.name}', New: '{workflow.name}'. "
                f"Each workflow must have a unique ID."
            )
        
        # 注册工作流
        instance._workflows[workflow.id] = workflow
        try:
            from agentclaw.config import get_config
            from agentclaw.api.services.settings_service import apply_saved_workflow_settings
            apply_saved_workflow_settings(workflow, get_config().project.project_dir)
        except Exception as e:
            logger.warning(f"应用工作流本地设置覆盖失败 {workflow.id}: {e}")
        auth_icon = "🔒" if require_auth else "🔓"
        logger.info(f"注册工作流: {workflow.id} ({workflow.name}) {auth_icon}")
        logger.info(f"  使用统一端点: POST /api/workflow/run")
        
        # 不再生成旧的端点，统一使用 /api/workflow/run
        
        # Prompt 管理端点（自动注册）
        instance._endpoints[f"/api/{workflow.id}/_prompts"] = {
            "workflow_id": workflow.id,
            "handler": "list_prompts",
            "methods": ["GET"],
        }
        instance._endpoints[f"/api/{workflow.id}/_prompts/{{key}}"] = {
            "workflow_id": workflow.id,
            "handler": "get_prompt",
            "methods": ["GET"],
        }
        instance._endpoints[f"/api/{workflow.id}/_prompts/{{key}}/update"] = {
            "workflow_id": workflow.id,
            "handler": "update_prompt",
            "methods": ["PUT"],
        }
        instance._endpoints[f"/api/{workflow.id}/_prompts/{{key}}/reset"] = {
            "workflow_id": workflow.id,
            "handler": "reset_prompt",
            "methods": ["POST"],
        }
        
        # 灰度配置
        if traffic_split:
            # 创建统一入口
            base_name = workflow.id.rsplit("_v", 1)[0]
            unified_path = f"/api/{base_name}"
            instance._traffic_split[unified_path] = traffic_split
    
    @classmethod
    def get(cls, workflow_id: str) -> Optional[Workflow]:
        """获取工作流"""
        instance = cls()
        return instance._workflows.get(workflow_id)
    
    @classmethod
    def list_all(cls) -> List[Workflow]:
        """获取所有工作流"""
        instance = cls()
        return list(instance._workflows.values())
    
    @classmethod
    def get_endpoints(cls) -> Dict[str, dict]:
        """获取所有端点配置"""
        instance = cls()
        return instance._endpoints.copy()
    
    @classmethod
    def get_traffic_split(cls) -> Dict[str, Dict[str, str]]:
        """获取灰度配置"""
        instance = cls()
        return instance._traffic_split.copy()
    
    @classmethod
    def unregister(cls, workflow_id: str) -> bool:
        """注销工作流"""
        instance = cls()
        if workflow_id in instance._workflows:
            del instance._workflows[workflow_id]
            
            # 清理端点
            paths_to_remove = [
                path for path, config in instance._endpoints.items()
                if config["workflow_id"] == workflow_id
            ]
            for path in paths_to_remove:
                del instance._endpoints[path]
            
            logger.info(f"注销工作流: {workflow_id}")
            return True
        return False
    
    @classmethod
    def clear(cls) -> None:
        """清空所有注册"""
        instance = cls()
        instance._workflows.clear()
        instance._endpoints.clear()
        instance._traffic_split.clear()
        logger.info("清空工作流注册表")
    
    @classmethod
    def resolve_workflow(
        cls,
        path: str,
        user_tags: Optional[List[str]] = None,
    ) -> Optional[Workflow]:
        """
        根据路径和用户标签解析工作流
        
        支持灰度发布：根据用户标签选择不同版本
        
        Args:
            path: API 路径
            user_tags: 用户标签列表
        
        Returns:
            解析到的工作流实例
        """
        instance = cls()
        
        # 检查灰度配置
        if path in instance._traffic_split:
            split_config = instance._traffic_split[path]
            
            # 根据用户标签匹配
            if user_tags:
                for tag in user_tags:
                    if tag in split_config:
                        workflow_id = split_config[tag]
                        return instance._workflows.get(workflow_id)
            
            # 使用默认版本
            default_id = split_config.get("default")
            if default_id:
                return instance._workflows.get(default_id)
        
        # 直接匹配端点
        if path in instance._endpoints:
            workflow_id = instance._endpoints[path]["workflow_id"]
            return instance._workflows.get(workflow_id)
        
        return None
    
    @classmethod
    def get_workflow_info(cls, workflow_id: str) -> Optional[dict]:
        """获取工作流详细信息"""
        workflow = cls.get(workflow_id)
        if not workflow:
            return None
        
        return {
            "id": workflow.id,
            "name": workflow.name,
            "version": workflow.version,
            "description": workflow.description,
            "auth_required": workflow.auth_required,
            "allowed_roles": workflow.allowed_roles,
            "timeout": workflow.timeout,
            "nodes": list(workflow._nodes.keys()),
        }
    
    @classmethod
    def list_info(cls) -> List[dict]:
        """获取所有工作流的信息"""
        return [
            cls.get_workflow_info(wf.id)
            for wf in cls.list_all()
        ]

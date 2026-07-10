"""
工作流注册模块

在此文件中导入所有工作流，确保它们被注册到 WorkflowRegistry。
添加新工作流时，只需在此文件中添加导入语句即可。
"""

# 导入所有工作流（确保它们被注册）
from .hello_world import workflow as hello_world_workflow

# 导出所有工作流（可选，方便外部访问）
__all__ = [
    "hello_world_workflow",
]
# AgentClaw template import: custom_demo
from .custom_demo.agents.custom_demo import workflow as custom_demo_workflow  # noqa: F401
# AgentClaw template import: router
from .router.agents.router import workflow as router_workflow  # noqa: F401

# Daily AI News agent
try:
    from .daily_ai_news import workflow as daily_ai_news_workflow  # noqa: F401
except ImportError:
    pass

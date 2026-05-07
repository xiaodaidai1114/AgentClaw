"""Register all example workflows for the AgentClaw examples project."""

from agentclaw.examples.mcps.example_tools import toolkit as examples_mcp_toolkit

from .hello_world import workflow as hello_world_workflow
from .intent_router import workflow as intent_router_workflow
from .tool_agent import workflow as tool_agent_workflow
from .human_approval import workflow as human_approval_workflow
from .parallel_analysis import workflow as parallel_analysis_workflow
from .skills_agent import workflow as gif_agent_workflow, workflow_auto as smart_agent_workflow
from .mcp_agent import workflow as mcp_agent_workflow
from .custom_node_report import workflow as custom_node_report_workflow
from .advanced_llm import workflow as advanced_llm_workflow
from .document_analyzer import workflow as document_analyzer_workflow
from .knowledge_rag import workflow as knowledge_rag_workflow

__all__ = [
    "hello_world_workflow",
    "intent_router_workflow",
    "tool_agent_workflow",
    "human_approval_workflow",
    "parallel_analysis_workflow",
    "gif_agent_workflow",
    "smart_agent_workflow",
    "mcp_agent_workflow",
    "custom_node_report_workflow",
    "advanced_llm_workflow",
    "document_analyzer_workflow",
    "knowledge_rag_workflow",
    "examples_mcp_toolkit",
]

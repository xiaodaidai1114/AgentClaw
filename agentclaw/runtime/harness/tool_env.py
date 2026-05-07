"""Tool execution environment used by the agent harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolExecutionEnvironment:
    """Managers and tool name sets needed by legacy tool execution helpers."""

    toolkit: Any = None
    skill_mcp_manager: Any = None
    skill_mcp_tool_names: Any = None
    planning_mcp_manager: Any = None
    planning_mcp_tool_names: Any = None
    download_mcp_manager: Any = None
    download_mcp_tool_names: Any = None
    browser_mcp_manager: Any = None
    browser_mcp_tool_names: Any = None
    search_mcp_manager: Any = None
    search_mcp_tool_names: Any = None
    computer_mcp_manager: Any = None
    computer_mcp_tool_names: Any = None
    coding_mcp_manager: Any = None
    coding_mcp_tool_names: Any = None
    published_mcp_tools: Any = None
    published_mcp_tool_names: Any = None

    def to_kwargs(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "state": state,
            "toolkit": self.toolkit,
            "mcp_manager": self.skill_mcp_manager,
            "mcp_tool_names": self.skill_mcp_tool_names,
            "planning_mcp_manager": self.planning_mcp_manager,
            "planning_mcp_tool_names": self.planning_mcp_tool_names,
            "download_mcp_manager": self.download_mcp_manager,
            "download_mcp_tool_names": self.download_mcp_tool_names,
            "browser_mcp_manager": self.browser_mcp_manager,
            "browser_mcp_tool_names": self.browser_mcp_tool_names,
            "search_mcp_manager": self.search_mcp_manager,
            "search_mcp_tool_names": self.search_mcp_tool_names,
            "computer_mcp_manager": self.computer_mcp_manager,
            "computer_mcp_tool_names": self.computer_mcp_tool_names,
            "coding_mcp_manager": self.coding_mcp_manager,
            "coding_mcp_tool_names": self.coding_mcp_tool_names,
            "published_mcp_tools": self.published_mcp_tools,
            "published_mcp_tool_names": self.published_mcp_tool_names,
        }

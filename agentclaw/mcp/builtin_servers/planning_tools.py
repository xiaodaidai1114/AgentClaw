"""Built-in MCP server: planning-tools."""

from typing import List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

class TodoManager:
    """
    Manages a structured task list with enforced constraints.
    
    Key Design Decisions (from Claude Code):
    1. Max 20 items: Prevents the model from creating endless lists
    2. One in_progress: Forces focus - can only work on ONE thing at a time
    3. Compatibility-first fields: content + status are required; activeForm is optional
    
    The activeForm field:
    - Present tense form of what's happening
    - Shown when status is "in_progress"
    - Example: content="Add tests", activeForm="Adding unit tests..."
    """
    
    def __init__(self):
        self.items = []
    
    def update(self, items: list) -> str:
        """
        Validate and update the todo list.
        
        Validation Rules:
        - Each item must have: content, status
        - Status must be: pending | in_progress | completed
        - Only ONE item can be in_progress at a time
        - Maximum 20 items allowed
        """
        validated = []
        in_progress_count = 0
        
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active_form = str(item.get("activeForm", "")).strip()
            
            if not content:
                raise ValueError(f"Item {i}: content required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status '{status}'")

            # activeForm is optional for compatibility with imperfect model output.
            # If missing, auto-fill a sensible value so TodoWrite does not fail.
            if not active_form:
                if status == "in_progress":
                    active_form = f"Working on: {content}"
                else:
                    active_form = content

            if status == "in_progress":
                in_progress_count += 1
            
            validated.append({
                "content": content,
                "status": status,
                "activeForm": active_form
            })
        
        if len(validated) > 20:
            raise ValueError("Max 20 todos allowed")
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        
        self.items = validated
        return self.render()
    
    def render(self) -> str:
        """
        Render the todo list as human-readable text.
        
        Format:
            [x] Completed task
            [>] In progress task <- Doing something...
            [ ] Pending task
            
            (2/3 completed)
        """
        if not self.items:
            return "No todos."
        
        lines = []
        for item in self.items:
            if item["status"] == "completed":
                lines.append(f"[x] {item['content']}")
            elif item["status"] == "in_progress":
                lines.append(f"[>] {item['content']} <- {item['activeForm']}")
            else:
                lines.append(f"[ ] {item['content']}")
        
        completed = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({completed}/{len(self.items)} completed)")
        
        return "\n".join(lines)
    
    def get_todos(self) -> str:
        """Get current todo list"""
        return self.render()


class PlanningToolsServer:
    """
    Planning Tools MCP Server
    
    Provides task planning and tracking tools:
    - TodoWrite: Update the task list (plan and track progress)
    - GetTodos: Get current task list
    
    Design Philosophy (from Claude Code):
    - "Make Plans Visible" - explicit planning prevents context fade
    - Constraints enable focus (max 20 items, one in_progress)
    
    Usage:
        python -m agentclaw.mcp.builtin_servers planning-tools
    """
    
    def __init__(self):
        self._todo_manager = TodoManager()
        self._server = Server("planning-tools")
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup MCP server handlers"""
        
        @self._server.list_tools()
        async def list_tools() -> List[Tool]:
            return [
                Tool(
                    name="TodoWrite",
                    description="Update the task list. Use to plan and track progress on multi-step tasks. "
                                "Constraints: max 20 items, only one task can be in_progress at a time. "
                                "activeForm is optional (auto-filled if omitted).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "items": {
                                "type": "array",
                                "description": "Complete list of tasks (replaces existing list)",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "content": {
                                            "type": "string",
                                            "description": "Task description"
                                        },
                                        "status": {
                                            "type": "string",
                                            "enum": ["pending", "in_progress", "completed"],
                                            "description": "Task status"
                                        },
                                        "activeForm": {
                                            "type": "string",
                                            "description": "Optional present tense action, e.g. 'Reading files...'"
                                        }
                                    },
                                    "required": ["content", "status"]
                                }
                            }
                        },
                        "required": ["items"]
                    }
                ),
                Tool(
                    name="GetTodos",
                    description="Get the current task list to see progress and what's next.",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                )
            ]
        
        @self._server.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[TextContent]:
            try:
                if name == "TodoWrite":
                    items = arguments.get("items", [])
                    result = self._todo_manager.update(items)
                elif name == "GetTodos":
                    result = self._todo_manager.get_todos()
                else:
                    result = f"Unknown tool: {name}"
                
                return [TextContent(type="text", text=str(result))]
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {e}")]
    
    async def run(self):
        """Run the MCP server"""
        logger.info("[planning-tools] Starting MCP server (stdio)")
        
        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(
                read_stream,
                write_stream,
                self._server.create_initialization_options()
            )

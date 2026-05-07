"""Built-in MCP server: search-tools."""

import os
from typing import List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

class SearchToolsServer:
    """
    Search Tools MCP Server (SearXNG)

    通过 SearXNG 实例提供网络搜索能力，完全免费，无需 API key。

    需要通过环境变量 SEARXNG_BASE_URL 配置 SearXNG 实例地址。
    如果未配置，服务器将不会启动。

    工具：
    - search_web: 网页搜索
    - search_news: 新闻搜索
    - search_images: 图片搜索

    SearXNG 搜索语法：
    - !engine query: 指定搜索引擎（如 !google, !bing, !ddg）
    - :lang query: 指定语言（如 :zh, :en）
    - !!bang query: 使用 DuckDuckGo bangs

    Usage:
        SEARXNG_BASE_URL=http://127.0.0.1:6013 python -m agentclaw.mcp.builtin_servers search-tools
    """

    def __init__(self):
        self.base_url = os.getenv("SEARXNG_BASE_URL", "").rstrip("/")
        self._server = Server("search-tools")
        self._setup_handlers()

    def _setup_handlers(self):
        @self._server.list_tools()
        async def list_tools() -> List[Tool]:
            return [
                Tool(
                    name="search_web",
                    description=(
                        "Search the web using SearXNG (aggregates Google, Bing, DuckDuckGo, etc.). "
                        "Returns titles, URLs, and snippets. Use for finding current information, "
                        "articles, documentation, etc. "
                        "Supports SearXNG syntax: '!google query' for specific engine, ':zh query' for language."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (supports SearXNG syntax like !engine, :lang)"
                            },
                            "language": {
                                "type": "string",
                                "description": "Language code (e.g., 'zh', 'en', 'ja'). Default: 'zh'",
                                "default": "zh"
                            },
                            "time_range": {
                                "type": "string",
                                "enum": ["", "day", "week", "month", "year"],
                                "description": "Time range filter. Empty for all time.",
                                "default": ""
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of results to return (1-20)",
                                "default": 10
                            }
                        },
                        "required": ["query"]
                    }
                ),
                Tool(
                    name="search_news",
                    description=(
                        "Search for news articles using SearXNG. "
                        "Returns recent news with titles, URLs, and snippets. "
                        "Good for finding current events and recent developments."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "News search query"
                            },
                            "language": {
                                "type": "string",
                                "description": "Language code (e.g., 'zh', 'en'). Default: 'zh'",
                                "default": "zh"
                            },
                            "time_range": {
                                "type": "string",
                                "enum": ["", "day", "week", "month", "year"],
                                "description": "Time range filter. Default: 'week' for news.",
                                "default": "week"
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of results (1-20)",
                                "default": 10
                            }
                        },
                        "required": ["query"]
                    }
                ),
                Tool(
                    name="search_images",
                    description=(
                        "Search for images using SearXNG. "
                        "Returns image URLs, thumbnails, and source pages."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Image search query"
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of results (1-20)",
                                "default": 10
                            }
                        },
                        "required": ["query"]
                    }
                ),
            ]

        @self._server.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[TextContent]:
            if not self.base_url:
                return [TextContent(
                    type="text",
                    text="[ERROR] SEARXNG_BASE_URL environment variable not set. "
                         "Please configure SearXNG instance URL."
                )]

            try:
                if name == "search_web":
                    result = await self._search(arguments, category="general")
                elif name == "search_news":
                    result = await self._search(arguments, category="news")
                elif name == "search_images":
                    result = await self._search(arguments, category="images")
                else:
                    result = f"[ERROR] Unknown tool: {name}"
                return [TextContent(type="text", text=result)]
            except Exception as e:
                logger.error(f"[search-tools] Error: {e}")
                return [TextContent(type="text", text=f"[ERROR] Search failed: {e}")]

    async def _search(self, args: dict, category: str) -> str:
        """Execute search via SearXNG API"""
        import urllib.parse

        query = args.get("query", "").strip()
        if not query:
            return "[ERROR] 'query' is required"

        language = args.get("language", "zh")
        time_range = args.get("time_range", "")
        max_results = min(max(int(args.get("max_results", 10)), 1), 20)

        # Build search URL
        params = {
            "q": query,
            "format": "json",
            "language": language,
            "safesearch": "0",
            "categories": category,
        }
        if time_range:
            params["time_range"] = time_range

        url = f"{self.base_url}/search?{urllib.parse.urlencode(params)}"

        # Execute request
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        if not results:
            return f"No results found for: {query}"

        # Format results
        results = results[:max_results]

        if category == "images":
            return self._format_image_results(results, query)
        else:
            return self._format_text_results(results, query, category)

    def _format_text_results(self, results: list, query: str, category: str) -> str:
        """Format text search results"""
        lines = [f"Search results for: {query}", f"Category: {category}", "=" * 50, ""]

        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            url = r.get("url", "")
            content = r.get("content", "")

            # Clean up content
            if content:
                content = content.strip()
                if len(content) > 300:
                    content = content[:300] + "..."

            lines.append(f"{i}. {title}")
            lines.append(f"   URL: {url}")
            if content:
                lines.append(f"   {content}")
            lines.append("")

        lines.append(f"Total: {len(results)} results")
        return "\n".join(lines)

    def _format_image_results(self, results: list, query: str) -> str:
        """Format image search results"""
        lines = [f"Image search results for: {query}", "=" * 50, ""]

        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            img_src = r.get("img_src", "")
            thumbnail = r.get("thumbnail_src", "") or r.get("thumbnail", "")
            source_url = r.get("url", "")

            lines.append(f"{i}. {title}")
            if img_src:
                lines.append(f"   Image: {img_src}")
            if thumbnail and thumbnail != img_src:
                lines.append(f"   Thumbnail: {thumbnail}")
            if source_url:
                lines.append(f"   Source: {source_url}")
            lines.append("")

        lines.append(f"Total: {len(results)} images")
        return "\n".join(lines)

    async def run(self):
        if not self.base_url:
            logger.error("[search-tools] SEARXNG_BASE_URL not set, cannot start server")
            return

        logger.info(f"[search-tools] Starting MCP server (stdio)")
        logger.info(f"[search-tools] SearXNG URL: {self.base_url}")

        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(
                read_stream,
                write_stream,
                self._server.create_initialization_options(),
            )

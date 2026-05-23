# 07 MCP Agent

MCP 工具调用示例：发布本地 MCP 工具，并可结合 mcp.json 中的外部 fetch 工具。

## 使用方式

在 Dashboard 的模板库中导入该模板后，会复制到当前项目的 `agents/mcp_agent/` 目录，并注册 workflow `mcp_agent`。

推荐输入：

```text
请分析这段运维记录并生成 Markdown 报告：凌晨任务失败，出现 timeout 和 permission denied。
```

## 包含内容

- `agents/mcp_agent.py`：workflow 入口文件

- `mcps/example_tools.py`：随模板发布的本地 MCP 工具
- `mcp.json`：外部 fetch MCP server 配置示例

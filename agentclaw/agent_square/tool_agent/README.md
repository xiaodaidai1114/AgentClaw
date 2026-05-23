# 03 Tool Agent

自定义工具调用示例：搜索、计算、天气等工具由 LLM 按需调用。

## 使用方式

在 Dashboard 的模板库中导入该模板后，会复制到当前项目的 `agents/tool_agent/` 目录，并注册 workflow `tool_agent`。

推荐输入：

```text
帮我计算 15 * 7 + 23，再查一下 Tokyo 的天气。
```

## 包含内容

- `agents/tool_agent.py`：workflow 入口文件

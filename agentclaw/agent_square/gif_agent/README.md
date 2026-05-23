# 06A GIF Creator Agent

显式技能注入示例：使用随模板附带的 slack-gif-creator skill 辅助创建 Slack GIF。

## 使用方式

在 Dashboard 的模板库中导入该模板后，会复制到当前项目的 `agents/gif_agent/` 目录，并注册 workflow `gif_agent`。

推荐输入：

```text
How do I create a bouncing ball GIF for Slack emoji?
```

## 包含内容

- `agents/gif_agent.py`：workflow 入口文件

- `skills/slack-gif-creator/`：示例项目 skill，导入后供 workflow 自动发现

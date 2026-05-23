# 09 周报生成器

高级 LLM 配置示例：模型参数、重试、上下文控制、流式周报生成。

## 使用方式

在 Dashboard 的模板库中导入该模板后，会复制到当前项目的 `agents/weekly_report/` 目录，并注册 workflow `weekly_report`。

推荐输入：

```text
完成用户认证模块重构
修复 3 个线上 bug
和前端对接新版 API
Review 了两个 PR
```

## 包含内容

- `agents/weekly_report.py`：workflow 入口文件

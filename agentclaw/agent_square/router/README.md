# 02 Intent Router

意图识别与条件路由示例：把提问、投诉、问候分配给不同处理节点。

## 使用方式

在 Dashboard 的模板库中导入该模板后，会复制到当前项目的 `agents/router/` 目录，并注册 workflow `router`。

推荐输入：

```text
你们的服务让我等太久了，我想反馈一下。
```

## 包含内容

- `agents/router.py`：workflow 入口文件

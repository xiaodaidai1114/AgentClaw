# 04 Human Review

人工审核示例：LLM 起草客服回复，HumanNode 中断等待审核，再根据反馈继续。

## 使用方式

在 Dashboard 的模板库中导入该模板后，会复制到当前项目的 `agents/approval/` 目录，并注册 workflow `approval`。

推荐输入：

```text
我的订单已经等了两周还没到，客服电话也打不通。
```

## 包含内容

- `agents/approval.py`：workflow 入口文件

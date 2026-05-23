# 11 知识库问答

知识库 RAG 示例：检索知识库文档分块，由 LLM 生成带引用来源的回答。

## 使用方式

在 Dashboard 的模板库中导入该模板后，会复制到当前项目的 `agents/kb_rag/` 目录，并注册 workflow `kb_rag`。

推荐输入：

```text
根据知识库资料，介绍项目的核心功能。
```

## 包含内容

- `agents/kb_rag.py`：workflow 入口文件

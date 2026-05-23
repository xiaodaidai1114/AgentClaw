# 10 Document Analyzer

文档处理示例：上传多个文档，DocumentNode 解析后由 LLM 综合分析。

## 使用方式

在 Dashboard 的模板库中导入该模板后，会复制到当前项目的 `agents/doc_analyzer/` 目录，并注册 workflow `doc_analyzer`。

推荐输入：

```text
上传文档后，问题填写：请总结这些文档的主要内容。
```

## 包含内容

- `agents/doc_analyzer.py`：workflow 入口文件

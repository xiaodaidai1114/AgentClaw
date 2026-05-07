# 知识库管理

> 内部 agent/shell 调用使用本机 internal relay。先读取 `<project_dir>/.agentclaw/relay.json` 的 `internal_url` 作为 `{BASE_URL}`，实际 URL 为 `{BASE_URL}/_internal` + 下方文档路径。

## 知识库 CRUD

### 列出知识库

`GET /admin/knowledgebases`

返回:
```json
{
  "knowledgebases": [KnowledgeBaseResponse]
}
```

**KnowledgeBaseResponse 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 知识库 ID |
| `name` | string | 知识库名称 |
| `description` | string | 说明 |
| `embedding_model_id` | string | 嵌入模型 ID |
| `rerank_model_id` | string | 重排序模型 ID |
| `llm_model_id` | string | LLM 模型 ID（用于摘要等） |
| `chunk_size` | int | 分块大小（字符数），默认 1200 |
| `chunk_overlap` | int | 分块重叠（字符数），默认 200 |
| `is_default` | boolean | 是否为默认知识库 |
| `embedding_dim` | int | 向量维度 |
| `retrieval_config` | object | 检索配置（见下文） |
| `metadata` | object | 扩展元数据 |
| `document_count` | int | 文档数量 |
| `chunk_count` | int | 分块数量 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

**retrieval_config 字段:**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `mode` | string | `hybrid` | 检索模式: `hybrid`(混合) / `dense`(向量) / `keyword`(关键词) |
| `score_threshold` | float | 0.72 | 相似度阈值（低于此分数的结果将被过滤） |
| `top_k` | int | 8 | 返回结果数量上限 |

### 创建知识库

`POST /admin/knowledgebases`

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | string | 是 | - | 知识库名称 |
| `description` | string | 否 | `""` | 说明 |
| `embedding_model_id` | string | 否 | `""` | 嵌入模型 ID（空则使用系统默认） |
| `rerank_model_id` | string | 否 | `""` | 重排序模型 ID（空则不使用 Rerank） |
| `llm_model_id` | string | 否 | `""` | LLM 模型 ID |
| `chunk_size` | int | 否 | 1200 | 分块大小（字符数） |
| `chunk_overlap` | int | 否 | 200 | 分块重叠（字符数） |
| `is_default` | boolean | 否 | `false` | 是否为默认知识库 |
| `retrieval_config` | object | 否 | `{}` | 检索配置: `{mode, score_threshold, top_k}` |
| `metadata` | object | 否 | `{}` | 扩展元数据 |

**请求示例:**
```json
{
  "name": "产品文档",
  "description": "公司产品相关文档",
  "chunk_size": 1200,
  "chunk_overlap": 200,
  "rerank_model_id": "rerank-model-1",
  "retrieval_config": {
    "mode": "hybrid",
    "score_threshold": 0.3,
    "top_k": 8
  }
}
```

### 获取知识库

`GET /admin/knowledgebases/{knowledgebase_id}`

返回: `KnowledgeBaseResponse`（字段同上）

### 更新知识库

`PUT /admin/knowledgebases/{knowledgebase_id}`

**请求参数（全部可选）:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | string | 知识库名称 |
| `description` | string | 说明 |
| `embedding_model_id` | string | 嵌入模型 ID |
| `rerank_model_id` | string | 重排序模型 ID |
| `llm_model_id` | string | LLM 模型 ID |
| `chunk_size` | int | 分块大小 |
| `chunk_overlap` | int | 分块重叠 |
| `is_default` | boolean | 是否为默认知识库 |
| `retrieval_config` | object | 检索配置 |
| `metadata` | object | 扩展元数据 |
| `embedding_dim` | int | 向量维度 |

```json
{
  "name": "更新的名称",
  "retrieval_config": {"mode": "dense", "score_threshold": 0.8, "top_k": 5}
}
```

### 删除知识库

`DELETE /admin/knowledgebases/{knowledgebase_id}`

删除知识库及其所有文档和分块。

---

## 文档管理

### 列出文档

`GET /admin/knowledgebases/{kb_id}/documents`

返回:
```json
{
  "documents": [KnowledgeDocumentResponse]
}
```

**KnowledgeDocumentResponse 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 文档 ID |
| `knowledgebase_id` | string | 所属知识库 ID |
| `original_name` | string | 原始文件名 |
| `mime_type` | string | MIME 类型 |
| `size` | int | 文件大小(字节) |
| `status` | string | 处理状态: `pending` / `processing` / `ready` / `error` |
| `chunk_count` | int | 已生成的分块数量 |
| `parser_name` | string | 使用的解析器，默认 `markitdown` |
| `error` | string | 错误信息（仅 error 状态） |
| `metadata` | object | 扩展元数据 |
| `created_at` | datetime | 上传时间 |
| `indexed_at` | datetime | 最后索引时间 |

### 上传文档

`POST /admin/knowledgebases/{kb_id}/documents/upload`

Content-Type: `multipart/form-data`

**表单字段:**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | 要上传的文档文件（PDF、Word、Markdown、TXT 等） |

上传后自动触发解析和索引构建。

### 导入本地文件

`POST /admin/knowledgebases/{kb_id}/documents/import`

从服务器本地文件系统导入文档。

**请求参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_path` | string | 是 | 服务器上的文件绝对路径 |
| `metadata` | object | 否 | 扩展元数据 |

```json
{"file_path": "/path/to/document.pdf"}
```

### 获取文档详情

`GET /admin/knowledgebases/{kb_id}/documents/{doc_id}`

返回: `KnowledgeDocumentResponse`（字段同上）

### 下载文档

`GET /admin/knowledgebases/{kb_id}/documents/{doc_id}/download`

返回原始文件流。

### 重建索引

`POST /admin/knowledgebases/{kb_id}/documents/{doc_id}/reindex`

重新解析文档并重建向量索引。当修改了分块参数或嵌入模型后使用。

### 替换文档

`POST /admin/knowledgebases/{kb_id}/documents/{doc_id}/replace`

Content-Type: `multipart/form-data`，字段: `file`

用新文件替换原文档，自动重新解析和索引。

### 删除文档

`DELETE /admin/knowledgebases/{kb_id}/documents/{doc_id}`

删除文档及其所有分块和向量索引。

---

## 分块管理

### 列出分块

`GET /admin/knowledgebases/{kb_id}/documents/{doc_id}/chunks`

返回:
```json
{
  "chunks": [KnowledgeChunkResponse]
}
```

**KnowledgeChunkResponse 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 分块 ID |
| `knowledgebase_id` | string | 所属知识库 ID |
| `document_id` | string | 所属文档 ID |
| `chunk_index` | int | 分块在文档中的序号 |
| `content` | string | 分块文本内容 |
| `token_count` | int | Token 数量 |
| `metadata` | object | 扩展元数据 |
| `created_at` | datetime | 创建时间 |

### 创建分块

`POST /admin/knowledgebases/{kb_id}/documents/{doc_id}/chunks`

手动创建一个新分块。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `content` | string | 是 | - | 分块文本内容 |
| `chunk_index` | int | 否 | 自动追加 | 分块序号 |
| `metadata` | object | 否 | `{}` | 扩展元数据 |

```json
{"content": "这是手动添加的分块内容。"}
```

### 更新分块

`PUT /admin/knowledgebases/{kb_id}/documents/{doc_id}/chunks/{chunk_id}`

**请求参数（全部可选）:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `content` | string | 更新后的文本内容 |
| `chunk_index` | int | 更新序号 |
| `metadata` | object | 更新元数据 |

```json
{"content": "更新后的分块内容。"}
```

### 删除分块

`DELETE /admin/knowledgebases/{kb_id}/documents/{doc_id}/chunks/{chunk_id}`

---

## 知识库检索

`POST /admin/knowledgebases/{kb_id}/search`

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | 是 | - | 检索问题 |
| `top_k` | int | 否 | 8 | 返回结果数量上限 |
| `mode` | string | 否 | 知识库默认值 | 检索模式: `hybrid` / `dense` / `keyword` |
| `score_threshold` | float | 否 | 知识库默认值 | 相似度阈值 |
| `rerank_model_id` | string | 否 | 知识库默认值 | 重排序模型 ID |
| `prefer_builtin_hybrid` | boolean | 否 | - | 是否优先使用内置混合检索 |

**请求示例:**
```json
{
  "query": "如何申请年假？",
  "top_k": 8,
  "mode": "hybrid",
  "score_threshold": 0.72,
  "rerank_model_id": "rerank-model-1"
}
```

**响应:**
```json
{
  "query": "如何申请年假？",
  "knowledgebase_id": "kb_uuid",
  "strategy": "hybrid",
  "total": 5,
  "hits": [SearchHit]
}
```

**SearchHit 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `chunk_id` | string | 命中的分块 ID |
| `document_id` | string | 所属文档 ID |
| `document_name` | string | 文档名称 |
| `chunk_index` | int | 分块序号 |
| `content` | string | 分块文本内容 |
| `score` | float | 最终得分（经 Rerank 后） |
| `dense_score` | float | 向量检索得分 |
| `keyword_score` | float | 关键词检索得分（BM25） |
| `rerank_score` | float | 重排序得分 |
| `source_path` | string | 文档来源路径 |
| `metadata` | object | 分块元数据 |

---

## 检索日志

### 列出日志

`GET /admin/knowledgebases/{kb_id}/search-logs`

返回:
```json
{
  "logs": [SearchLogResponse]
}
```

**SearchLogResponse 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 日志 ID |
| `knowledgebase_id` | string | 知识库 ID |
| `query` | string | 检索问题 |
| `mode` | string | 检索模式 |
| `strategy` | string | 实际使用的策略 |
| `top_k` | int | Top K 参数 |
| `hit_count` | int | 命中结果数 |
| `latency_ms` | int | 耗时(ms) |
| `hits` | object[] | 命中结果摘要 |
| `created_at` | datetime | 检索时间 |

### 创建日志

`POST /admin/knowledgebases/{kb_id}/search-logs`

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | 是 | - | 检索问题 |
| `mode` | string | 否 | `""` | 检索模式 |
| `strategy` | string | 否 | `""` | 实际使用的策略 |
| `top_k` | int | 否 | 8 | Top K 参数 |
| `hit_count` | int | 否 | 0 | 命中结果数 |
| `latency_ms` | int | 否 | 0 | 耗时(ms) |
| `hits` | object[] | 否 | `[]` | 命中结果摘要 |

### 清空日志

`DELETE /admin/knowledgebases/{kb_id}/search-logs`

清空该知识库的所有检索日志。

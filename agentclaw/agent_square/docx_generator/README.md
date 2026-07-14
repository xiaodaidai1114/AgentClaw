# 📄 Word 文档生成器

基于 AgentClaw 平台的智能 Word 文档生成 Agent。输入主题即可自动生成格式精美的 .docx 文档。

## 功能特点

- **智能文档规划**：AI 自动分析需求，规划文档结构和内容
- **三种风格**：专业（professional）/ 创意（creative）/ 简洁（simple）
- **丰富元素**：支持标题层级、段落、无序列表、有序列表、表格
- **自动排版**：字体、字号、颜色、对齐、页边距自动适配
- **目录与页码**：可选自动生成目录和页码
- **可下载输出**：生成的 .docx 文件保存在 `generated_docs/` 目录

## 输入参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| topic | string | ✅ | - | 文档主题 |
| content | string | ❌ | "" | 详细内容或大纲（可选，AI 自动生成） |
| author | string | ❌ | "" | 文档作者 |
| style | string | ❌ | professional | 文档风格 |
| include_toc | string | ❌ | yes | 是否包含目录 |
| include_page_numbers | string | ❌ | yes | 是否包含页码 |
| filename | string | ❌ | "" | 输出文件名 |

## 使用示例

```python
# 通过 API 调用
POST /api/workflow/run
{
    "workflow_id": "docx_generator",
    "inputs": {
        "topic": "2024年Q2项目周报",
        "author": "张三",
        "style": "professional",
        "include_toc": "yes"
    }
}
```

## 输出

生成的 Word 文档保存在项目 `generated_docs/` 目录下，文件名格式为 `{主题}_{时间戳}.docx`。

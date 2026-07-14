# 🔥 小红书爆款文案生成器 v2

增强版小红书爆款文案生成 Agent，基于 AgentClaw 平台构建。

## 功能特点

- **6 种文案风格**：种草 🌱 / 测评 📊 / 教程 📖 / 情感 💕 / 干货 📚 / 合集 🎁
- **多版本输出**：一次生成 1-3 个不同角度的文案版本
- **爆款分析**：自动评估爆款潜力、标题吸引力、受众匹配度
- **SEO 优化**：内置关键词优化建议，提升搜索曝光
- **专业提示词**：融入小红书爆款公式、用户心理和算法推荐机制

## 输入参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| topic | string | ✅ | - | 文案主题或产品名称 |
| style | string | ❌ | 种草 | 文案风格 |
| target_audience | string | ❌ | - | 目标受众 |
| tone | string | ❌ | - | 语气风格 |
| key_points | string | ❌ | - | 核心卖点（逗号分隔） |
| word_count | string | ❌ | 300-500 | 期望字数范围 |
| num_versions | string | ❌ | 1 | 生成版本数（1/2/3） |
| include_analysis | string | ❌ | yes | 是否附带爆款分析 |
| seo_keywords | string | ❌ | - | SEO关键词（逗号分隔） |

## 使用示例

```python
# 通过 API 调用
POST /api/workflow/run
{
    "workflow_id": "viral_xiaohongshu_writer",
    "inputs": {
        "topic": "适合学生党的平价美白精华",
        "style": "种草",
        "target_audience": "学生党",
        "tone": "真诚",
        "key_points": "平价, 温和不刺激, 有效果",
        "word_count": "300-500",
        "num_versions": "2",
        "include_analysis": "yes",
        "seo_keywords": "学生党护肤, 平价美白"
    }
}
```

## 输出内容

每篇文案包含：
1. 📌 **标题** - 爆款标题
2. 💬 **文案正文** - 带 emoji 分段
3. 🏷️ **推荐标签** - 3-8 个优化标签
4. 📝 **文案说明** - 风格、字数、受众等
5. 📈 **爆款分析** - 评分和优化建议

## 运行方式

```bash
agentclaw up
```

然后通过 AgentClaw 管理后台或 API 调用。

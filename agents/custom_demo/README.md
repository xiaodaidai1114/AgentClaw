# 08 数据报告生成器

自定义节点示例：Python 解析数据，LLM 生成分析，CustomNode 格式化报告。

## 使用方式

在 Dashboard 的模板库中导入该模板后，会复制到当前项目的 `agents/custom_demo/` 目录，并注册 workflow `custom_demo`。

推荐输入：

```text
本月各部门业绩评分：市场部 85，研发部 92，销售部 78，运营部 96。
```

## 包含内容

- `agents/custom_demo.py`：workflow 入口文件

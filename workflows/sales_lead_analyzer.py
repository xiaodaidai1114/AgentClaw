"""
销售线索分析助手 (Sales Lead Analyzer)
======================================
智能分析销售线索质量、优先级和转化潜力，输出结构化评分报告和跟进建议。
支持单条深度分析和批量线索评估两种模式。

工作流架构:
  1. parse_input - 解析用户输入，提取线索数据、分析模式、行业背景等
  2. analyze_leads - LLM 分析线索，输出结构化评分和跟进建议
  3. format_output - 按指定格式输出最终报告
"""

from agentclaw import Workflow, LLMNode

# ── Workflow Definition ──────────────────────────────────────────────────

workflow = Workflow(
    id="sales_lead_analyzer",
    name="销售线索分析助手",
    version="1.0.0",
    description="智能分析销售线索质量、优先级和转化潜力，输出结构化评分报告和跟进建议。支持单条深度分析和批量线索评估。",
    welcome="你好！我是销售线索分析助手。请提供待分析的销售线索数据，我可以进行单条深度分析或批量评估。",
    inputs={
        "leads_data": {
            "type": "string",
            "required": True,
            "description": "待分析的销售线索数据。可以是单条线索的详细描述，也可以是多条线索的结构化文本（支持 CSV/JSON/自然语言格式）"
        },
        "analysis_mode": {
            "type": "string",
            "required": False,
            "default": "deep",
            "description": "分析模式：deep（深度分析单条线索）/ batch（批量评估多条线索）"
        },
        "industry_context": {
            "type": "string",
            "required": False,
            "default": "",
            "description": "行业背景信息，如目标行业、市场趋势等（可选），帮助更精准地评估线索匹配度"
        },
        "scoring_criteria": {
            "type": "string",
            "required": False,
            "default": "",
            "description": "自定义评分标准，如重点关注的评估维度、权重配置等（可选），不传则使用默认评分体系"
        },
        "output_format": {
            "type": "string",
            "required": False,
            "default": "markdown",
            "description": "输出格式：markdown（结构化报告）/ json（结构化数据）/ concise（简洁摘要）"
        }
    },
    timeout=240
)

# ── Node 1: Parse Input ──────────────────────────────────────────────────

parse_prompt = """你是一个销售线索数据解析专家。请解析用户输入的线索数据，提取结构化信息。

## 输入数据
用户提供的线索数据：
{leads_data}

## 分析模式
{analysis_mode}

## 行业背景（如有）
{industry_context}

## 自定义评分标准（如有）
{scoring_criteria}

## 你的任务
1. 判断输入是单条线索还是多条线索
2. 如果用户未明确指定分析模式，根据数据量自动判断：单条用 deep，多条用 batch
3. 提取关键字段：公司名称、联系人、行业、规模、需求描述、预算范围、决策时间线等
4. 输出一个结构化的解析结果，供后续分析节点使用

请以 JSON 格式输出解析结果，包含以下字段：
- detection_mode: 检测到的模式（"deep" 或 "batch"）
- lead_count: 线索数量
- parsed_data: 解析后的结构化数据摘要
- key_fields: 提取到的关键字段列表
- data_quality: 数据质量评估（high/medium/low）
"""

parse_node = LLMNode(
    id="parse_input",
    system_prompt="你是一个专业的销售线索数据解析专家。你擅长从各种格式的输入中提取结构化的线索信息。",
    user_prompt=parse_prompt,
    output_format="text",
    output_key="parsed_result",
    model_params={"temperature": 0.2}
)

# ── Node 2: Analyze Leads ────────────────────────────────────────────────

analyze_prompt = """你是一位资深销售分析师和客户关系管理专家。请根据以下解析后的线索数据进行深度分析。

## 解析后的线索数据
{parsed_result}

## 原始输入数据
{leads_data}

## 分析模式
{analysis_mode}

## 行业背景
{industry_context}

## 自定义评分标准
{scoring_criteria}

## 分析要求

### 如果是深度分析模式 (deep)：
对单条线索进行全面评估，输出以下维度的评分和分析：

1. **线索质量评分（总分 100）**：
   - 需求明确度（0-20）：客户需求是否清晰、具体
   - 预算匹配度（0-20）：预算范围是否与产品/服务匹配
   - 决策权与时间线（0-15）：是否有决策权、购买时间线是否明确
   - 行业匹配度（0-15）：是否在目标行业范围内
   - 联系人质量（0-15）：联系人的职位、影响力、参与度
   - 竞争态势（0-15）：竞争激烈程度、我方优势

2. **线索优先级**：高/中/低，并说明理由

3. **转化潜力评估**：预计转化概率（百分比）和预期周期

4. **关键风险点**：可能影响转化的风险因素

5. **跟进建议**：
   - 最佳跟进时机
   - 建议的沟通策略
   - 推荐的话术方向
   - 需要进一步了解的信息

6. **下一步行动**：具体的行动项和时间建议

### 如果是批量评估模式 (batch)：
对多条线索进行批量评估，输出：

1. **线索概览表**：按优先级排列，包含每条线索的评分、优先级、转化概率
2. **高潜力线索**：Top 3 高潜力线索的详细分析
3. **批量统计**：
   - 线索分布（按行业/规模/地区）
   - 优先级分布
   - 平均评分和转化概率
4. **整体建议**：批量跟进策略和资源分配建议

### 评分标准说明（默认）：
- 90-100: 极高潜力，立即跟进
- 75-89: 高潜力，优先跟进
- 60-74: 中等潜力，正常跟进
- 40-59: 低潜力，培育为主
- 0-39: 低质量线索，考虑放弃或转交

请确保分析结果专业、具体、可操作。避免模糊描述，给出明确的评分和具体的行动建议。
"""

analyze_node = LLMNode(
    id="analyze_leads",
    system_prompt="你是一位资深销售分析师，擅长从多维度评估销售线索质量并给出可操作的跟进建议。你的分析专业、具体、数据驱动。",
    user_prompt=analyze_prompt,
    output_format="text",
    output_key="analysis_result",
    model_params={"temperature": 0.3}
)

# ── Node 3: Format Output ────────────────────────────────────────────────

format_prompt = """你是一位专业的报告撰写专家。请根据分析结果，按指定的输出格式生成最终报告。

## 分析结果
{analysis_result}

## 输出格式要求
{output_format}

## 格式说明
- 如果 output_format 是 "markdown"：生成结构化的 Markdown 报告，包含标题、表格、列表、评分可视化等
- 如果 output_format 是 "json"：生成结构化的 JSON 数据，便于程序化处理
- 如果 output_format 是 "concise"：生成简洁的摘要文本，突出最关键的信息

## 报告要求
1. 报告开头包含线索概况摘要（一句话总结）
2. 评分和优先级突出显示
3. 跟进建议清晰可执行
4. 结尾包含免责声明：本分析基于提供的数据，建议结合人工判断做最终决策
"""

format_node = LLMNode(
    id="format_output",
    system_prompt="你是一位专业的报告撰写专家，擅长将分析结果转化为清晰、美观、可操作的报告。",
    user_prompt=format_prompt,
    output_format="text",
    output_key="output",
    output_to_user=True,
    model_params={"temperature": 0.2}
)

# ── Build Graph ──────────────────────────────────────────────────────────

workflow.add_node(parse_node)
workflow.add_node(analyze_node)
workflow.add_node(format_node)

workflow.add_edge("parse_input", "analyze_leads")
workflow.add_edge("analyze_leads", "format_output")

# ── Publish ──────────────────────────────────────────────────────────────

workflow.publish()

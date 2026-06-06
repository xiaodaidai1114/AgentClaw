# AgentClaw 最佳实践

> 使用声明式配置，让框架自动管理复杂逻辑

---

## 核心原则

1. **声明式优先**：使用 `LLMNode`、`HumanNode` 等声明式节点
2. **自动管理**：会话、消息历史、状态持久化都由框架自动管理
3. **约定优于配置**：合理默认值，减少必要配置

---

## 系统保留字段

框架使用以下系统保留字段（以 `__` 开头和结尾）：

| 字段名 | 说明 |
|--------|------|
| `__messages__` | 对话历史 |
| `__interrupted__` | 中断标记 |
| `__status__` | 状态 |

> ⚠️ 用户定义的 State 字段不应使用 `__` 开头的名称。

---

## 先选择实现模式

AgentClaw 的核心思想是让用户尽快构建出可运行、可追踪、可迭代的智能体。不要一开始就设计一套复杂框架，也不要把所有逻辑塞进一个超大 `LLMNode` 或一个超大 Python 文件。先根据复杂度选择合适的实现模式。

| 你的场景 | 推荐结构 | 先不要用 |
|----------|----------|----------|
| 单轮问答、总结、简单工具调用 | 一个 `Workflow` + 一个或少量 `LLMNode` | 子工作流、模板、复杂状态机 |
| 固定多步骤处理，如分类、分析、生成报告 | `Workflow` + 多个节点 + `StateExtractNode` | 多角色子工作流 |
| 多轮交互，如预约、审批、问卷、游戏主持 | 显式业务 `state` + router + 用户输入解析 | 只靠聊天历史判断流程 |
| 多角色或多专家协作，如评审团、辩论、游戏玩家 | 主 `Workflow` + 子 `Workflow` + `SubWorkflowNode` | 自定义一套脱离 AgentClaw 的 Actor 框架 |
| 大量重复的角色/步骤图结构 | `WorkflowTemplate` 生成普通 `Workflow` | 复制粘贴多份节点 |

一个通用判断：

- **流程简单**：直接写节点。
- **输出要进业务状态**：加 `StateExtractNode`。
- **用户要多轮参与**：显式维护业务 `state`。
- **多个角色要隔离上下文/记忆**：用子 `Workflow`。
- **同样的图结构要创建多份**：用 `WorkflowTemplate`。

---

## 推荐分层

复杂智能体推荐把职责拆成几层，而不是让模型自己“猜”完整流程。

| 层 | 职责 | AgentClaw 对应能力 |
|----|------|-------------------|
| State | 保存事实、阶段、用户选择、业务结果 | workflow state / `register_state_field` |
| Workflow | 控制节点顺序、路由、中断、循环 | `Workflow`、edge、router |
| View | 把完整 state 裁剪成模型可见输入 | 普通函数节点或 `BaseNode` |
| Prompt | 保存稳定规则、角色设定、阶段任务 | `PromptManager`、`{@prompt_key}` |
| Model | 生成自然语言、建议或候选动作 | `LLMNode` |
| Extract | 把自然语言提取成结构化字段 | `StateExtractNode` |
| Apply | 校验动作并写回业务 state | 普通函数节点或 `BaseNode` |
| Sub Workflow | 隔离多角色/多专家的私有状态 | `SubWorkflowNode` |
| Template | 复用重复的图结构 | `WorkflowTemplate` |

推荐流水线：

```text
业务 state
  -> View 节点裁剪输入
  -> LLMNode 使用 prompt 生成结果
  -> StateExtractNode 提取结构化动作
  -> Apply 节点校验并写回 state
  -> Router 决定下一步
```

这条流水线比“一个大 prompt 直接改状态”更稳定，也更容易测试。

---

## 模式一：简单问答型智能体

适合客服问答、文档总结、单轮分析、简单工具调用。用户给输入，模型给输出，不需要复杂状态机。

```python
from agentclaw import Workflow, LLMNode, Input

workflow = Workflow(
    id="simple_assistant",
    name="简单助手",
    inputs=[Input("user_input", str, required=False)],
    user_input="user_input",
)

workflow.add_node(LLMNode(
    id="answer",
    model_id="default",
    system_prompt="{@assistant_rules}",
    user_prompt="{user_input}",
    output_key="answer",
))

workflow.add_edge("__start__", "answer")
workflow.add_edge("answer", "__end__")
workflow.publish()
```

提示词可以放在 YAML 中，便于后续热更新：

```yaml
assistant_rules:
  content: |
    你是一个清晰、可靠的助手。
    回答要简洁，必要时说明不确定性。
```

这个级别不要提前拆子工作流。先把最小可用版本跑起来。

---

## 模式二：多步骤流程型智能体

适合简历筛选、需求分析、报告生成、代码审查、文章改写等固定流程。流程不是一个 LLM 节点，而是多个节点串起来。

```python
from agentclaw import Workflow, LLMNode, StateExtractNode, Input

workflow = Workflow(
    id="resume_screening",
    name="简历筛选助手",
    inputs=[Input("resume_text", str, required=True)],
)

workflow.add_node(LLMNode(
    id="analyze_resume",
    model_id="default",
    system_prompt="{@resume_screening_rules}",
    user_prompt="{resume_text}",
    output_key="resume_analysis_raw",
))

workflow.add_node(StateExtractNode(
    id="extract_resume_score",
    source_key="resume_analysis_raw",
    fields={
        "candidate_name": "候选人姓名",
        "score": "0-100 的匹配分数",
        "risks": "主要风险点列表",
        "recommendation": "建议：pass/interview/reject",
    },
))

@workflow.node(id="render_result")
def render_result(state):
    return {
        "reply": (
            f"候选人：{state.get('candidate_name')}\n"
            f"评分：{state.get('score')}\n"
            f"建议：{state.get('recommendation')}"
        )
    }

workflow.add_edge("__start__", "analyze_resume")
workflow.add_edge("analyze_resume", "extract_resume_score")
workflow.add_edge("extract_resume_score", "render_result")
workflow.add_edge("render_result", "__end__")
workflow.publish()
```

关键原则：

- `LLMNode` 负责分析和生成。
- `StateExtractNode` 负责把文本结果变成字段。
- 普通节点负责业务处理和展示。

不要要求模型“顺便更新状态”。模型输出进入业务逻辑前，先结构化。

---

## 模式三：交互状态机型智能体

适合预约助手、审批流、问卷调查、多轮客服、教学辅导、游戏主持等。它们的共同点是：用户每次输入后，系统要根据当前阶段决定下一步。

多轮智能体不要只靠 `__messages__` 聊天历史硬撑。应该把业务阶段显式放进 state。

```python
from agentclaw import Workflow, Input

workflow = Workflow(
    id="booking_assistant",
    name="预约助手",
    inputs=[
        Input("user_input", str, required=False),
        Input("booking", dict, required=False),
    ],
    user_input="user_input",
)
workflow.register_state_field("booking", dict)


def empty_booking_state():
    return {
        "phase": "ASK_DATE",
        "date": "",
        "time": "",
        "confirmed": False,
    }


@workflow.node(id="load_booking")
def load_booking(state):
    return {"booking": state.get("booking") or empty_booking_state()}


@workflow.node(id="apply_user_input")
def apply_user_input(state):
    booking = state["booking"]
    text = str(state.get("user_input") or "").strip()

    if booking["phase"] == "ASK_DATE" and text:
        booking["date"] = text
        booking["phase"] = "ASK_TIME"
    elif booking["phase"] == "ASK_TIME" and text:
        booking["time"] = text
        booking["phase"] = "ASK_CONFIRM"
    elif booking["phase"] == "ASK_CONFIRM" and text:
        booking["confirmed"] = "确认" in text or "可以" in text
        booking["phase"] = "DONE" if booking["confirmed"] else "ASK_DATE"

    return {"booking": booking}


@workflow.node(id="render_reply")
def render_reply(state):
    booking = state["booking"]
    if booking["phase"] == "ASK_DATE":
        reply = "请告诉我你想预约哪一天。"
    elif booking["phase"] == "ASK_TIME":
        reply = "请告诉我你想预约几点。"
    elif booking["phase"] == "ASK_CONFIRM":
        reply = f"你要预约 {booking['date']} {booking['time']}，确认吗？"
    else:
        reply = "预约已确认。"

    return {
        "reply": reply,
        "booking": booking,
        "session_dir": "state.booking",
    }


workflow.add_edge("__start__", "load_booking")
workflow.add_edge("load_booking", "apply_user_input")
workflow.add_edge("apply_user_input", "render_reply")
workflow.add_edge("render_reply", "__end__")
workflow.publish()
```

如果用户输入很自由，比如“明天下午三点可以吗”，可以把 `apply_user_input` 前面换成 `StateExtractNode`：

```text
用户自然语言
  -> StateExtractNode 提取 date/time/intent
  -> apply_user_input 更新业务 state
```

关键原则：

- state 里保存阶段，例如 `phase`。
- 用户输入先解析成当前阶段能理解的动作。
- router 或普通节点根据 state 推进流程。
- 不向用户展示内部动作名，例如 `join_sheriff_campaign`。

---

## 模式四：多角色/多专家型智能体

适合多专家评审、会议模拟、辩论、多角色游戏、复杂协作。只有当多个角色需要独立上下文、独立记忆或并行决策时，才使用子工作流。

推荐结构：

```text
主 Workflow
  管全局 state、流程推进、用户交互、结果汇总

子 Workflow
  管单个角色/专家如何思考和输出

SubWorkflowNode
  管主子状态映射、实例隔离、结果写回
```

示例：多专家评审。

```python
from agentclaw import Workflow, LLMNode, StateExtractNode, SubWorkflowNode

reviewer = Workflow(
    id="reviewer_actor",
    name="单个评审专家",
    tracing=False,
)
reviewer.register_state_field("request", dict)
reviewer.register_state_field("memory", dict)

reviewer.add_node(LLMNode(
    id="review",
    model_id="reviewer_model",
    system_prompt="{@reviewer_rules}",
    user_prompt="{request}",
    output_key="review_raw",
))

reviewer.add_node(StateExtractNode(
    id="extract_review",
    source_key="review_raw",
    fields={
        "score": "0-100 分",
        "decision": "approve/reject/revise",
        "reason": "理由",
    },
))

reviewer.add_edge("__start__", "review")
reviewer.add_edge("review", "extract_review")
reviewer.add_edge("extract_review", "__end__")
```

主流程调用一个专家实例：

```python
main.add_node(SubWorkflowNode(
    id="call_security_reviewer",
    workflow=reviewer,
    instance_id="security",
    thread_id_strategy="derived",
    readonly_input_map={
        "request": "reviewer_requests.security",
    },
    state_map={
        "memory": "reviewers.security.memory",
    },
    output_map={
        "review_result": "reviewer_outputs.security",
    },
    merge_strategy={
        "reviewers": "deep_merge",
        "reviewer_outputs": "deep_merge",
    },
))
```

关键原则：

- 子工作流是普通 `Workflow`，不是脱离 AgentClaw 的新框架。
- `instance_id` 区分同一个子工作流的不同角色实例。
- `state_map` 保存该角色自己的记忆。
- `readonly_input_map` 给子工作流传入本轮请求。
- `output_map` 把子工作流结果写回主 state。
- 主流程负责判断何时调用谁，不让子流程控制全局状态机。

---

## WorkflowTemplate 只做重复图结构复用

当你发现自己复制了三份以上相似节点结构，就考虑 `WorkflowTemplate`。它的职责是“生成普通 Workflow”，不是替代状态机，也不是隐藏业务流程。

适合：

- 多个专家有相同评审流程。
- 多个玩家有相同行动流程。
- 多个渠道有相同处理步骤。

不适合：

- 主业务状态机。
- 大量业务 if/else。
- 用户交互中断逻辑。

示例：

```python
from agentclaw import WorkflowTemplate, LLMNode, StateExtractNode

expert_template = WorkflowTemplate(
    id="expert_review_template",
    name="专家评审模板",
)

expert_template.add_node(LLMNode(
    id="{expert_id}__review",
    model_id="{model_id}",
    system_prompt="{expert_system_prompt}",
    user_prompt="{review_material}",
    output_key="{expert_id}_review_raw",
))

expert_template.add_node(StateExtractNode(
    id="{expert_id}__extract",
    source_key="{expert_id}_review_raw",
    fields={
        "score": "评分",
        "reason": "理由",
    },
))

expert_template.add_edge("__start__", "{expert_id}__review")
expert_template.add_edge("{expert_id}__review", "{expert_id}__extract")
expert_template.add_edge("{expert_id}__extract", "__end__")

security_reviewer = expert_template.instantiate(
    id="security_reviewer",
    variables={
        "expert_id": "security",
        "model_id": "fast",
        "expert_system_prompt": "{@expert_common_rules}\n\n{@security_expert}",
    },
)
```

注意区分两类变量：

- `{expert_id}`、`{model_id}`、`{expert_system_prompt}` 是模板实例化变量。
- `{review_material}` 是运行时 state 变量，会在 LLMNode 执行时再替换。
- `{@expert_common_rules}` 是 PromptManager 引用。

---

## 提示词拆分

提示词不要散落在很多 `LLMNode` 里。推荐把稳定内容放进 YAML，通过 `{@prompt_key}` 引用。

拆分原则：

| 类型 | 放在哪里 | 示例 |
|------|----------|------|
| 稳定规则 | prompts YAML | 公司政策、游戏规则、审核标准 |
| 角色设定 | prompts YAML | 安全专家、客服、辩手、玩家身份行为 |
| 阶段任务 | prompts YAML | 分类、评审、投票、总结、生成报告 |
| 输出格式要求 | prompts YAML 或 `StateExtractNode` | JSON 字段、评分标准 |
| 当前局势/材料 | state / View 节点 | 用户输入、公开信息、候选目标 |
| 模型选择 | `model_id` / `models.json` | fast、strong、reviewer_model |

示例：

```yaml
support_rules:
  content: |
    你是客服助手。
    不要承诺无法确认的事情。
    遇到退款、投诉、账号安全问题要升级人工。

classify_ticket:
  content: |
    判断用户问题类型。
    只能输出：refund / account / bug / other。

reply_style:
  content: |
    回复要礼貌、简短、可执行。
```

节点里组合提示词：

```python
workflow.add_node(LLMNode(
    id="classify_ticket",
    model_id="default",
    system_prompt="{@support_rules}\n\n{@classify_ticket}",
    user_prompt="{user_input}",
    output_key="classification_raw",
))
```

推荐规则：

- `LLMNode` 里只组合 prompt，不写大段业务知识。
- 可复用知识放 `prompts/*.yaml`。
- 当前业务数据放 state，不写死在 prompt 文件。
- 复杂输出用 `StateExtractNode` 提取，不靠模型每次都完美返回 JSON。

---

## View：不要把完整 state 直接给模型

复杂智能体经常有隐藏信息、内部状态、权限边界。不要把完整 state 直接塞给 `LLMNode`，应该先构建模型可见的 view。

```python
@workflow.node(id="build_review_view")
def build_review_view(state):
    return {
        "review_view": {
            "material": state["material"],
            "criteria": state["criteria"],
            "previous_public_comments": state.get("public_comments", []),
        }
    }

workflow.add_node(LLMNode(
    id="review",
    system_prompt="{@reviewer_rules}",
    user_prompt="{review_view}",
    output_key="review_raw",
))
```

这个模式尤其适合：

- 多角色游戏：不同玩家不能看到全部身份。
- 审批系统：不同角色不能看到所有内部字段。
- 多专家评审：专家只看任务材料和自己的记忆。
- 客服系统：模型不应该看到 API token、内部配置等字段。

---

## 推荐目录结构

简单项目：

```text
agents/
  my_agent.py
prompts/
  my_agent.yaml
models.json
```

复杂项目：

```text
agents/
  my_agent/
    agent.py          # 薄入口，只导出 workflow
    workflow.py       # AgentClaw 图装配
    state.py          # 默认状态、状态查询、状态更新辅助
    views.py          # 构建 LLM 可见输入
    actions.py        # action schema、解析、校验
    prompts.yaml      # 也可以放到项目 prompts/ 目录
models.json
```

复杂模板库应用也推荐类似结构：

```text
agent_square/
  some_app/
    agents/
      some_app.py          # 薄入口，保持模板导入路径稳定
      some_app_workflow.py
      some_app_state.py
      some_app_actions.py
      some_app_views.py
```

入口文件尽量薄，避免后续把状态、prompt、规则、渲染、图装配全部堆在一起。

---

## 复杂智能体的核心原则

可以把复杂智能体记成这几句话：

- 主 `Workflow` 管流程。
- 业务 `state` 管事实。
- View 节点管模型能看到什么。
- `PromptManager` 管稳定知识。
- `LLMNode` 管生成。
- `StateExtractNode` 管结构化。
- Apply 节点管校验和状态写回。
- 子 `Workflow` 管多角色隔离。
- `WorkflowTemplate` 管重复图结构复用。

这套模式能覆盖普通客服、报告生成、审批流、多专家评审、辩论、游戏主持等大多数场景，同时仍然完全基于 AgentClaw 原有框架。

---

## 场景最佳实践

### 1. 简单 LLM 调用

```python
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="你是一个友好的助手"
))
```

### 2. 多轮对话

```python
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="你是一个友好的助手",
    use_context=True,           # 自动加载对话历史（默认）
    max_context_messages=20     # 限制历史条数
))

# 使用 thread_id 实现跨请求会话
result = await workflow.run(
    {"user_input": "你好"},
    thread_id="session_001"     # 状态自动持久化
)
```

### 3. 输出固定内容（开场白等）

```python
from agentclaw import output

@workflow.node("greeting")
async def greeting(state):
    # 临时提示（不保存到上下文）
    await output("处理中，请稍候...")
    return {}

@workflow.node("opening")
async def opening(state):
    # 角色设定/开场白（保存到上下文）
    opening = "喵～你好呀！我是你的小助手喵～"
    await output(opening, save_to_context=True)
    return {}
```


### 4. 流式输出

```python
# 使用 LLMNode（自动流式输出）
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="你是助手",
    stream=True  # 显式开启流式输出
))
```

### 5. Human-in-Loop（等待用户输入）

```python
# 对话场景：保存用户输入到对话历史
workflow.add_node(HumanNode(
    id="await_input",
    feedback_field="user_input",
    save_to_context=True,  # 默认值
))

# 审批场景：不保存到对话历史
workflow.add_node(HumanNode(
    id="approval",
    feedback_field="approved",
    save_to_context=False,
))
```

### 6. 工具调用

```python
from agentclaw import ToolKit

toolkit = ToolKit()

@toolkit.tool
async def search_database(query: str, limit: int = 10) -> str:
    """
    搜索数据库
    
    Args:
        query: 搜索关键词
        limit: 返回数量限制
    """
    return await db.search(query, limit)

workflow.use(toolkit)

workflow.add_node(LLMNode(
    id="agent",
    system_prompt="你是智能助手，可以使用工具完成任务",
    tools=["search_database"],
    tool_choice="auto",
    max_tool_rounds=5,
))
```

### 7. Skills 技能调用

```python
# 指定技能列表
workflow.add_node(LLMNode(
    id="agent",
    system_prompt="你是智能助手",
    skills=["pdf", "webapp-testing"],
))

# 自动匹配相关技能（推荐）
workflow.add_node(LLMNode(
    id="agent",
    system_prompt="你是智能助手",
    skills="*",  # 根据用户输入自动匹配
))
```

### 8. 条件路由

```python
workflow.add_router(
    after="classify",
    routes={
        "question": "handle_question",
        "complaint": "handle_complaint",
        "default": "__end__"
    },
    condition="result.intent"  # 支持嵌套字段
)
```

### 9. 节点间数据传递

```python
workflow.add_node(LLMNode(
    id="analyze",
    system_prompt="分析：{user_input}",  # 自动从 state 读取
    output_key="analysis"                 # 自动写入 state
))

workflow.add_node(LLMNode(
    id="summarize",
    system_prompt="基于分析结果({analysis})生成摘要"
))
```

> ⚠️ **变量转义**：`{variable}` 会被识别为变量并替换。如果需要输出字面量的花括号（如 JSON 格式示例），请使用双花括号 `{{}}` 进行转义：
> ```python
> system_prompt="""返回 JSON 格式：
> {{"intent": "question" | "complaint"}}"""  # {{}} 会被渲染为 {}
> ```

---

## 完整示例：多轮对话

```python
from agentclaw import Workflow, LLMNode, HumanNode, output


def create_chat_workflow() -> Workflow:
    workflow = Workflow(id="chat", name="多轮对话")
    
    # 1. 开场白
    @workflow.node("greeting")
    async def greeting(state):
        await output("你好！我是你的助手，有什么可以帮你的？", save_to_context=True)
        return {}
    
    # 2. 等待用户输入
    workflow.add_node(HumanNode(
        id="await_input",
        feedback_field="user_input",
    ))
    
    # 3. LLM 回复
    workflow.add_node(LLMNode(
        id="reply",
        system_prompt="你是一个友好的助手",
        use_context=True,
        stream=True,
    ))
    
    # 边配置
    workflow.add_edge("greeting", "await_input")
    workflow.add_edge("await_input", "reply")
    workflow.add_edge("reply", "await_input")  # 循环
    
    return workflow
```

---

## 关键配置速查

### LLMNode

| 配置 | 默认值 | 说明 |
|-----|-------|------|
| `use_context` | `True` | 加载对话历史 |
| `save_to_context` | `True` | 保存对话到历史 |
| `max_context_messages` | `None` | 最大历史消息数（默认继承 `MAX_CONTEXT_MESSAGES`） |
| `stream` | `False` | 是否开启流式输出 |
| `output_key` | 节点 ID | 输出存储键 |
| `output_format` | `"text"` | `text` / `json` |
| `tools` | `None` | 工具名称列表 |
| `skills` | `None` | 技能列表或 `"*"` 自动匹配 |
| `max_tool_rounds` | `None` | 最大工具调用轮数（默认继承 `MAX_TOOL_ROUNDS`） |

### HumanNode

| 配置 | 默认值 | 说明 |
|-----|-------|------|
| `feedback_field` | `"feedback"` | 等待用户提供的字段 |
| `save_to_context` | `True` | 保存用户输入到对话历史 |

### output() 函数

```python
from agentclaw import output
from agentclaw.utils.stream import fake_stream

await output("处理完成！")                              # 不保存到上下文
await output("你好！", save_to_context=True)            # 保存到上下文
await output(fake_stream("流式输出内容"), stream=True)  # 模拟流式输出
```

---

## 服务部署

```python
# server.py
import agents  # 导入 agents 模块，自动注册所有工作流

from agentclaw import AgentClawServer

server = AgentClawServer()
server.run()
```

或使用 CLI：

```bash
agentclaw serve
```

框架自动处理：
- Admin Token 自动生成
- 认证中间件自动注册
- Admin Dashboard 自动启用

### 生产环境

```bash
# .env
ADMIN_TOKEN=your-secure-token
WORKFLOW_API_KEY=sk-your-workflow-key
```

生产环境安全建议：

- 固定配置 `ADMIN_TOKEN` 和 `WORKFLOW_API_KEY`，不要依赖每次启动自动生成。
- `WORKFLOW_API_KEY` 是可执行所有工作流的全局执行 Key，不是 Admin Token；工作流级 Key 只有在对应工作流开启发布 API 后才会被接受。调度器、渠道推送、文件列表和 Dashboard 管理接口仍只给 `ADMIN_TOKEN`。
- 对外分享 Agent 时，在工作流配置里显式开启「公开发布」，并设置合适的 `rate_limit`、`public_conversation_limit`、`public_message_limit`；默认保持关闭。
- 内置智能体不能公开分享，避免把内部能力暴露给匿名用户。
- 浏览器里展示上传文件或 Markdown 图片时使用短期签名 URL，不要把裸 `/api/files/{id}` 当永久公开链接。
- 公网反向代理场景只有在代理会清理伪造的 `X-Forwarded-*` 头时，才开启 `AGENTCLAW_TRUST_PROXY_HEADERS=1`。

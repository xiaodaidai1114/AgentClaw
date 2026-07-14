# Phase 1 — Agent Blueprint 系统

> 状态：✅ 已完成
> 交付物：`agentclaw/agent_factory/` 子包（blueprint + serializer）+ 32 个单元测试
> 验收：全部通过，现有流程无回归

---

## 1. 目标

为「一句话生成企业 Agent」建立**统一数据结构**。AgentBlueprint 是用户需求与可运行 Agent 之间的结构化中间态：

```
用户需求 → [Agent Factory] → AgentBlueprint → [Scaffold Generator] → agents/<name>/
```

本 Phase 为纯数据结构，**无运行时副作用，不影响现有 Workflow/Node/API**。

## 2. 设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| Schema 框架 | Pydantic v2 | 项目已全局使用，校验/序列化原生支持 |
| 必填字段 | `name` / `domain` / `role` | Agent 核心身份；其余字段均有默认值，确保 v0.1 可最小化创建 |
| 默认版本 | `"v0.1"` | 对应「实习生雏形」语义 |
| 默认状态 | `"draft"` | 对应 Agent 生命周期起点（Phase 6 Registry 扩展） |
| 状态/类型 | 字符串常量类（非 Enum） | 允许企业自定义扩展值，同时提供受参考取值集 |
| YAML 依赖 | try-import pyyaml（不加直接依赖） | 遵循项目「不直接依赖 pyyaml」约定（见 [skills/parser.py](agentclaw/skills/parser.py) 自研解析器）；pyyaml 作为 langchain/openai 间接依赖通常可用，不可用时 JSON 路径不受影响 |
| 时间戳 | UTC `datetime`，ISO 序列化 | 跨时区一致；Pydantic 自动还原 |
| 中文序列化 | `ensure_ascii=False` | 可读性 |

## 3. 模块结构

```
agentclaw/agent_factory/
├── __init__.py      # 包导出
├── blueprint.py     # Schema 定义
└── serializer.py    # JSON/YAML/dict/文件 序列化
```

### 3.1 Schema（[blueprint.py](agentclaw/agent_factory/blueprint.py)）

| 模型 | 关键字段 | 默认 |
|---|---|---|
| `AgentBlueprint` | name*, display_name, description, domain*, role*, goals[], responsibilities[], inputs[], outputs[], skills[], tools[], knowledge_sources[], memory, workflow[], constraints[], guardrails[], version, status, created_at, updated_at | version=`"v0.1"`, status=`"draft"`, 列表=`[]` |
| `SkillSpec` | name*, description, type, required, source, confidence | confidence=0.0 (0~1) |
| `ToolSpec` | name*, description, type, required, auth_required, permission_level | permission_level=`"read_only"`（Phase 9 预留） |
| `KnowledgeSourceSpec` | name*, type, description | type=`"knowledge_base"` |
| `MemorySpec` | type, persist, description | type=`"workflow"`, persist=True |
| `WorkflowStep` | step_id*, name*, description, input, output, tools[], skills[] | 列表=`[]` |

> `*` = 必填（缺失或空字符串触发 `ValidationError`）

常量类：`AgentStatus`（draft/prototype/trial/production/deprecated/archived）、`SkillSourceType`、`ToolPermissionLevel`（read_only/write_with_approval/write_auto/admin_only）、`AgentDomain`（9 个企业领域）、`DEFAULT_VERSION`。

### 3.2 序列化器（[serializer.py](agentclaw/agent_factory/serializer.py)）

| 函数 | 说明 |
|---|---|
| `to_json(bp, indent=2, ensure_ascii=False)` / `from_json(text)` | JSON，Pydantic 原生 |
| `to_yaml(bp)` / `from_yaml(text)` | YAML，需 pyyaml（`yaml_available()` 探测） |
| `to_dict(bp)` / `from_dict(data)` | 纯 Python 字典 |
| `save(bp, path)` / `load(path)` | 按扩展名自动选择 `.yaml`/`.yml`/`.json`，自动建父目录 |

## 4. 用法示例

```python
from agentclaw.agent_factory import AgentBlueprint, SkillSpec, ToolSpec, WorkflowStep, to_yaml, save

# 1. 创建 Blueprint（最小化，仅需 name/domain/role）
bp = AgentBlueprint(
    name="sales_lead_analysis_agent",
    display_name="销售线索分析助手",
    description="分析销售线索并给出跟进建议",
    domain="sales",
    role="销售线索分析师",
    goals=["识别高价值线索", "给出跟进优先级"],
    skills=[SkillSpec(name="lead_scoring", confidence=0.8, required=True)],
    tools=[ToolSpec(name="crm_query", permission_level="read_only")],
    workflow=[WorkflowStep(step_id="s1", name="评分", tools=["crm_query"])],
    guardrails=["不泄露客户隐私"],
)

# 2. 序列化
print(bp.version)            # "v0.1"
print(to_yaml(bp))           # YAML 字符串（中文不转义）

# 3. 保存到文件（Phase 2 的 Scaffold Generator 会用此结构落地）
save(bp, "agents/sales_lead_analysis_agent/agent.yaml")
```

## 5. 测试（[test_agent_blueprint.py](agentclaw/test/unit/test_agent_blueprint.py)）

32 个测试，覆盖：

- 创建（全字段 / 最小化）、默认值（version/status/timestamps）、`touch()`
- 必填校验（name/domain/role 缺失与空字符串）、子模型校验、confidence 边界
- JSON roundtrip（字段/时间戳保留）、dict roundtrip
- YAML roundtrip（字段/嵌套列表/最小化/空内容报错）—— pyyaml 不可用时自动 skip
- 文件 save/load（yaml/json/yml 扩展名/建父目录/不支持扩展名报错）
- 独立性（不依赖运行时配置）

**运行结果**：`32 passed in 1.27s`

## 6. 与现有系统的关系

- **零侵入**：`agent_factory` 是独立子包，仅依赖 `pydantic`，不 import 任何运行时模块（Workflow/Node/API/Tracing）
- **未改 `agentclaw/__init__.py`**：顶层导入不受影响（验证 `import agentclaw; from agentclaw import AgentClawServer` 正常）
- **现有测试无回归**：`test_env_config.py` / `test_safe_compare.py` / `test_example_agent_square_templates.py` 共 14 测试全部通过

## 7. 后续 Phase 衔接

| Phase | 如何使用本 Phase 成果 |
|---|---|
| Phase 2 Agent Factory | `BlueprintGenerator` 输出 `AgentBlueprint`；`ScaffoldGenerator` 用 `save(bp, "agents/<name>/agent.yaml")` 落地，并用 blueprint 字段生成 `prompt.md` / `workflow.json` |
| Phase 3 企业模板 | 模板加载为 `AgentBlueprint` 部分字段，由用户需求覆盖 |
| Phase 6 Agent Registry | `agent_registry` 表的 `blueprint_path` 指向序列化文件；版本 diff 基于 Blueprint 字段 |
| Phase 7 Versioning | 每版本存一份 `agent.yaml`，changelog 记录 `added_skills`/`removed_skills` |
| Phase 9 Tool Permission | `ToolSpec.permission_level` 已预留，RBAC 启用后强制校验 |

## 8. 回滚

删除 `agentclaw/agent_factory/` 目录即可完全回滚，不影响任何现有功能。

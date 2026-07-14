# Phase 4 — Experience Collector

> 状态：✅ 已完成
> 交付物：`agentclaw/experience/` 子包（5 模块）+ 22 个单元测试
> 验收：22 passed，Phase 1-3 回归 96 passed 无回归

---

## 1. 目标

记录企业 Agent 运行过程（任务/工具调用/回复/人工反馈/失败），聚合为 Trajectory，为 **Phase 5 Skill Evolution Engine** 提供原始数据。

设计原则（Phase 0 审计）：
- **独立模块、不依赖运行时**：本 Phase 是纯数据采集层，不改 Workflow/Node/Tracing 核心
- **JSONL 优先 + 接口可替换**：先用本地 JSONL，`StorageBackend` 抽象预留 PostgreSQL
- **隐私脱敏默认开启**：企业数据写入前过滤 8 类敏感信息
- **复用思路**：事件结构对齐现有三层 trace 表（workflow_logs/node_logs/llm_logs），后续可用 `BaseTracer` 子类零侵入挂载，自动从 trace 生成 experience

## 2. 模块结构

```
agentclaw/experience/
├── __init__.py             # 包导出
├── event_schema.py         # 5 类事件 + Trajectory（Pydantic）
├── privacy_filter.py       # 8 类敏感信息脱敏
├── trajectory_store.py     # JSONLStorage + StorageBackend 抽象 + TrajectoryStore
├── event_logger.py         # EventLogger（构造事件→脱敏→写入）
└── feedback_collector.py   # FeedbackCollector（人工反馈）
```

## 3. 事件 Schema（[event_schema.py](agentclaw/experience/event_schema.py)）

| 事件 | event_type | 关键字段 |
|---|---|---|
| `TaskStartedEvent` | `task_started` | agent_version, user_request |
| `ToolCalledEvent` | `tool_called` | tool_name, tool_input, tool_output, success, latency_ms |
| `AgentRespondedEvent` | `agent_responded` | response, confidence (0-1) |
| `HumanFeedbackEvent` | `human_feedback_received` | rating (1-5), feedback, human_correction |
| `TaskFailedEvent` | `task_failed` | error_type, error_message, failed_step |

所有事件继承 `BaseEvent`（event_type/agent_id/task_id/timestamp）。`Trajectory` 把同 task_id 的事件聚合为一条轨迹（steps/tool_calls/final_answer/human_feedback/human_correction/success/rating）。

`event_from_dict(data)` 按 event_type 反序列化为对应子类，便于从 JSONL 重建。

## 4. 隐私脱敏（[privacy_filter.py](agentclaw/experience/privacy_filter.py)）

默认开启（EventLogger 写入前过滤），覆盖 8 类：

| 类别 | 方式 |
|---|---|
| email / 手机号 / 身份证 / 银行卡 | 正则匹配 → mask_value（保留首尾，中间打码） |
| api_key / token / password / secret | `key=value` 正则 → 值打码 |
| address / phone 等字段 | `sanitize_dict` 敏感 key 整值打码 |

- `sanitize_text(str)`：字符串正则脱敏
- `sanitize_dict(dict)`：字典敏感 key + 递归字符串脱敏
- `has_sensitive_info(str)`：快速检测（诊断/测试用）

## 5. 存储（[trajectory_store.py](agentclaw/experience/trajectory_store.py)）

**JSONL 默认后端**（存储布局，相对项目根或 `AGENTCLAW_DATA_DIR`）：
```
data/experience/events.jsonl        每行一个事件 JSON
data/experience/trajectories.jsonl  每行一个 Trajectory JSON
```

**`StorageBackend` 抽象**（4 个方法：append_event / append_trajectory / list_events / list_trajectories）：实现该接口即可切换到 PostgreSQL 或其他后端，业务代码（EventLogger/TrajectoryStore）不变。

**`TrajectoryStore`**：
- `record_event(event)`：写单个事件
- `finalize_trajectory(task_id, agent_id, ...)`：聚合同 task_id 事件 → Trajectory → 写入存储
- `list_trajectories(agent_id)` / `list_events(task_id)`：查询

## 6. 用法示例

```python
from pathlib import Path
from agentclaw.experience import EventLogger, FeedbackCollector, TrajectoryStore, JSONLStorage

# 初始化（JSONL 存储到 data/experience/）
store = TrajectoryStore(JSONLStorage(Path("data/experience")))
logger = EventLogger(store=store)  # privacy_enabled 默认 True

# 记录一次任务
logger.log_task_started("sales_agent", "task-001",
                        user_request="分析本周销售线索", agent_version="v0.1")
logger.log_tool_called("sales_agent", "task-001", "crm_query",
                       tool_input={"lead_id": 123}, tool_output="...", latency_ms=120)
logger.log_agent_responded("sales_agent", "task-001",
                           response="建议优先跟进 A 公司", confidence=0.8)
traj = logger.finalize("task-001", "sales_agent")

# 收集人工反馈（Skill Evolution 的核心信号）
fc = FeedbackCollector(logger)
fc.submit("sales_agent", "task-001", rating=4,
          human_correction="预算大于 50 万的客户应标记为高价值")

# 反馈会进入下次 finalize 的 Trajectory（或单独 finalize）
```

脱敏效果：`tool_input={"email": "a@b.com"}` 写入前自动变成 `a@b.com → a****om`。

## 7. 测试（[test_experience.py](agentclaw/test/unit/test_experience.py)）

22 个测试，覆盖：

- 5 类事件创建 + JSONL 序列化 + 字段默认值 + confidence 边界
- `event_from_dict` 反序列化 roundtrip
- 脱敏：4 类正则检测/打码 + 非敏感文本不动 + 密钥 key=value + 字典敏感 key + mask_value 保留首尾
- JSONL 存储读写 + task_id/agent_id 过滤
- EventLogger 默认脱敏 / 关闭脱敏保留原文
- Trajectory 聚合（tool_calls 收集、final_answer、success/failure 判定）
- FeedbackCollector：记录 + rating 校验（1-5 或 0）+ 人工修正进入 Trajectory
- `StorageBackend` 抽象不可实例化 + 自定义内存后端可插拔

**运行结果**：`22 passed`；Phase 1-3 回归 `96 passed` 无回归。`import agentclaw` 正常（不破坏顶层包）。

## 8. 后续衔接

| 阶段 | 如何使用本 Phase 成果 |
|---|---|
| Phase 5 Skill Evolution | 从 `trajectories.jsonl` 挖掘重复模式（高频工具组合/重复人工修正/高频失败）→ 生成 Skill Candidate |
| 后续（自动采集） | 实现 `BaseTracer` 子类，零侵入挂载现有三层 trace 表，把 workflow_logs/node_logs/llm_logs 自动转为 Experience 事件（开关 `AGENTCLAW_EXPERIENCE_ENABLED`，默认 off） |
| Phase 9 RBAC | 事件含 agent_id/task_id，未来可加 user_id/tenant_id 隔离 |

## 9. 回滚

删除 `agentclaw/experience/` 目录即完全回滚。本 Phase 为纯新增模块，不影响 Workflow/Node/API/Tracing 任何现有功能。

## 10. 当前范围说明

本 Phase 完成**数据采集层**（Schema + 脱敏 + 存储 + Logger + 测试），尚未：
- 自动挂载到运行时（需 `BaseTracer` 子类，后续阶段）
- 替换为 PostgreSQL（`StorageBackend` 已预留接口，实现 `PGStorage` 即可）

这两个属于"接通"，放到 Skill Evolution 需要数据时再做，避免过早耦合运行时。

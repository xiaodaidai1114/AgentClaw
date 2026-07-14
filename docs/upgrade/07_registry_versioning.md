# Phase 6 — Registry + 版本管理

> 状态：✅ 已完成
> 交付物：`agentclaw/registry/` 子包（3 模块）+ 17 个单元测试（含端到端）
> 验收：17 passed，Phase 1-5 回归 130 passed 无回归

---

## 1. 目标

建立企业 Agent 和 Skill 的**统一注册中心** + 版本管理：
- Agent/Skill 的注册、查询、状态、启禁用、关联
- Agent 版本管理：每次变更（加 Skill / 改 Prompt / 改 Workflow）生成新版本，支持 diff 与回滚

复用：Agent 状态（`blueprint.AgentStatus`）、Skill 状态（`skill_candidate` 的 published/deprecated）。

## 2. 模块结构

```
agentclaw/registry/
├── __init__.py             # 包导出
├── agent_registry.py       # AgentRecord + AgentVersion + AgentRegistry
├── skill_registry.py       # SkillRecord + SkillRegistry
└── version_manager.py      # VersionManager（创建/列表/diff/回滚/标记）
```

存储：JSONL（`data/registry/agents.jsonl` + `skills.jsonl`），相对项目根或 `AGENTCLAW_DATA_DIR`。Registry 只记录元数据 + 版本历史，运行物本身在 `agents/<name>.py` 与 `skills/enterprise/...`。

## 3. AgentRegistry（[agent_registry.py](agentclaw/registry/agent_registry.py)）

**AgentRecord**：agent_id / name / display_name / domain / current_version / status / file_path / blueprint_path / versions[] / 时间戳

**状态**（`AgentStatus`）：`draft`（默认）→ `prototype` → `trial` → `production` → `deprecated` → `archived`

**操作**：
- `register(record)`：注册；新记录自动补一条 `initial_creation` 版本
- `get / exists / list_all(domain, status)`
- `update_status(agent_id, status)`：非法状态报 ValueError
- `remove(agent_id)`

**变更类型常量**：`initial_creation` / `skill_added` / `skill_removed` / `prompt_updated` / `workflow_updated` / `rollback`

## 4. SkillRegistry（[skill_registry.py](agentclaw/registry/skill_registry.py)）

**SkillRecord**：skill_id / name / domain / version / status / path / source_candidate_id / agent_ids[] / 时间戳

**状态**：默认 `published`（注册即启用）；`enable` → published，`disable` → deprecated

**操作**：
- `register / get / exists / list_all(domain, status)`
- `list_by_domain(domain)` / `list_by_agent(agent_id)`
- `enable(skill_id)` / `disable(skill_id)`
- `link_agent(skill_id, agent_id)` / `unlink_agent`（幂等）
- `remove(skill_id)`

## 5. VersionManager（[version_manager.py](agentclaw/registry/version_manager.py)）

| 方法 | 说明 |
|---|---|
| `create_version(agent_id, change_type, added_skills, removed_skills, ...)` | 递增 minor 版本（v0.1→v0.2），追加版本历史，更新 current_version |
| `list_versions(agent_id)` | 按时间序列出版本 |
| `get_version(agent_id, version)` | 取指定版本 |
| `diff(agent_id, v1, v2)` | 比较两版本的 skill 集合差异（added/removed） |
| `rollback(agent_id, to_version)` | 回滚：创建 `change_type=rollback` 的新版本（不删历史，保留可追溯） |
| `mark_production / mark_deprecated / mark_trial` | 标记 agent 状态 |

回滚不物理删除中间版本——保留完整历史，符合企业可审计要求。

## 6. 用法示例（端到端）

```python
from agentclaw.registry import AgentRegistry, SkillRegistry, VersionManager, AgentRecord, SkillRecord
from agentclaw.registry.agent_registry import CHANGE_SKILL_ADDED

agent_reg = AgentRegistry()         # data/registry/agents.jsonl
skill_reg = SkillRegistry()         # data/registry/skills.jsonl
vm = VersionManager(agent_reg)

# 1. 注册 agent（自动 v0.1 initial）
agent_reg.register(AgentRecord(
    agent_id="sales_agent", name="sales", domain="sales",
    file_path="agents/sales.py",
))

# 2. 发布新 skill（来自 Phase 5）并关联 + 版本递增
skill_reg.register(SkillRecord(
    skill_id="high_value", name="high_value", domain="sales",
    source_candidate_id="cand_xxx",
))
skill_reg.link_agent("high_value", "sales_agent")
vm.create_version("sales_agent", change_type=CHANGE_SKILL_ADDED,
                  added_skills=["high_value"], changed_by="skill_evolution")
# current_version: v0.1 → v0.2

# 3. 看版本差异
vm.diff("sales_agent", "v0.1", "v0.2")  # {"added": ["high_value"], "removed": []}

# 4. 回滚 + 标记生产
vm.rollback("sales_agent", "v0.1")      # → v0.3
vm.mark_production("sales_agent")
```

## 7. 测试（[test_registry.py](agentclaw/test/unit/test_registry.py)）

17 个测试，覆盖：

- **AgentRegistry**：注册自动 initial 版本 / domain+status 过滤 / 状态更新 / 非法状态报错 / 删除
- **SkillRegistry**：注册查询 / 按 domain+agent 查询 / enable+disable / link+unlink 幂等 / 不存在报错
- **VersionManager**：版本递增追加 / 列表+get / diff 检测 added skills / 回滚创建新版本 / 回滚缺失版本报错 / 标记生产+废弃
- **端到端**（`test_end_to_end_registry_versioning`）：注册 agent → 发布 skill 并关联 → 版本递增 → diff → 回滚 → 标记生产

**运行结果**：`17 passed`；Phase 1-5 回归 `130 passed` 无回归；`import agentclaw` 正常。

## 8. 后续衔接

| 阶段 | 如何使用本 Phase 成果 |
|---|---|
| Phase 8 Evaluation | 版本发布前跑回归评估，新版低于旧版则阻止自动发布 |
| Phase 11 CLI/API/UI | `list-agents` / `rollback-agent` / Dashboard 注册中心页直接调用 Registry + VersionManager |
| Phase 5 Skill Evolution | 发布 skill 时 `SkillRegistry.register` + `link_agent` + `VersionManager.create_version` 联动 |
| 后续（持久化升级） | JSONL → PostgreSQL（Registry 接口不变，换存储实现） |

## 9. 回滚

删除 `agentclaw/registry/` 目录即完全回滚。本 Phase 为纯新增模块，不依赖运行时，不影响现有功能。

## 10. 当前范围说明

完成**注册中心 + 版本管理核心**。尚未：
- 接入 CLI/API/UI（Phase 11）
- 与 Phase 5 发布流程自动联动（`SkillPublisher.publish` 后调 `SkillRegistry.register`，下一阶段接通）
- 评估门（Phase 8）

这些是"接通"，放到对应 Phase 再做。

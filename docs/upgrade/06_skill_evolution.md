# Phase 5 — Skill Evolution Engine

> 状态：✅ 已完成
> 交付物：`agentclaw/evolution/` 子包（6 模块）+ 17 个单元测试（含端到端）
> 验收：17 passed，Phase 1-4 回归 113 passed 无回归

---

## 1. 目标

从 Phase 4 采集的真实使用轨迹中**挖掘重复模式**，生成 Skill Candidate，经评估与**人工审批**后发布为可复用 Skill——让 Agent 从"实习生"持续成长为企业专属 AI 员工。

核心原则（企业安全）：**AI 只负责挖掘与生成，人决定是否采纳发布**。未审批的 Skill Candidate 永远不能进入生产。

## 2. 完整流程

```
Trajectory（Phase 4 采集）
    │
    ▼
PatternMiner        挖掘重复模式（business_rule / tool_combination / failure）
    │                Pattern
    ▼
SkillExtractor      Pattern → SkillCandidate（触发条件/步骤/规则/示例）
    │                status: candidate
    ▼
SkillEvaluator      评估（confidence + evidence）→ recommendation
    │
    ▼
ApprovalGate        人工审批：candidate → pending_approval → approved / rejected
    │                （只有 approved 可继续）
    ▼
SkillPublisher      发布到 Skill Registry：skills/enterprise/{domain}/{name}/
                     status: published
```

## 3. 模块结构

```
agentclaw/evolution/
├── __init__.py             # 包导出
├── skill_candidate.py      # SkillCandidate Schema + 状态常量 + CandidateStore（JSONL）
├── pattern_miner.py        # Pattern + PatternMiner（n-gram Jaccard 聚类）
├── skill_extractor.py      # Pattern → SkillCandidate
├── skill_evaluator.py      # EvaluationResult + SkillEvaluator
├── approval_gate.py        # ApprovalGate（人工审批门）
└── skill_publisher.py      # SkillPublisher（发布到 registry）
```

## 4. 模式类型（[pattern_miner.py](agentclaw/evolution/pattern_miner.py)）

| 类型 | 说明 | 信号来源 |
|---|---|---|
| `business_rule` | **重复的人工修正**（最有价值） | Trajectory.human_correction 多次相似 |
| `tool_combination` | 高频工具组合 | Trajectory.tool_calls 的工具集合重复 |
| `failure_pattern` | 高频失败步骤 | 失败 Trajectory 的 failed_step 重复 |

聚类用**字符 n-gram Jaccard 相似度**（无需中文分词依赖），贪心聚类，确定性可测试。挖掘阈值：`min_evidence`（默认 3，证据数下限）、`min_similarity`（默认 0.3）。

示例：100 次采购审批中，人工修正多次出现「超过 10 万元需要主管审批」→ 挖掘为 `business_rule` Pattern（evidence_count=42, confidence≈0.87）。

## 5. SkillCandidate 状态流转

```
candidate → pending_approval → approved → published
                          ↘ rejected
approved → deprecated（后续）
```

状态常量见 [skill_candidate.py](agentclaw/evolution/skill_candidate.py)。`CandidateStore` 用 JSONL 存储（按 candidate_id upsert，`candidates.jsonl`）。

## 6. 关键安全闸门（[approval_gate.py](agentclaw/evolution/approval_gate.py) + [skill_publisher.py](agentclaw/evolution/skill_publisher.py)）

- `ApprovalGate.approve()` 只接受 `pending_approval` 状态（否则 ValueError）
- `SkillPublisher.publish()` 只接受 `approved` 状态（否则 ValueError）
- 即：**未审批的 candidate 绝不可能发布**——这是 Skill Evolution 的安全闸门，由测试 `test_publisher_rejects_non_approved` / `test_cannot_approve_non_pending` 锁定

## 7. 发布产物（[skill_publisher.py](agentclaw/evolution/skill_publisher.py)）

发布到 `skills/enterprise/{domain}/{name}/`（与 skill_creator 目录约定一致）：

```
skills/enterprise/sales/high_value/
├── SKILL.md         技能说明（触发条件/步骤/规则）
├── rules.yaml       业务规则
├── examples.json    示例（来自人工修正样本）
└── metadata.yaml    元数据（candidate_id/domain/confidence/source_patterns）
```

## 8. 用法示例（端到端）

```python
from agentclaw.experience import Trajectory
from agentclaw.evolution import (
    PatternMiner, SkillExtractor, ApprovalGate, SkillPublisher, CandidateStore,
)

# 1. 从 Phase 4 的 trajectories.jsonl 读取（这里用内存示例）
trajectories = [...]  # List[Trajectory]，含重复 human_correction

# 2. 挖掘
patterns = PatternMiner(min_evidence=3).mine(trajectories)

# 3. 生成 candidate 并提交审批
store = CandidateStore("data/experience/candidates.jsonl")
gate = ApprovalGate(store)
for p in patterns:
    if p.pattern_type == "business_rule":
        gate.submit_for_approval(SkillExtractor().extract(p))

# 4. 人工审批（在 Dashboard / CLI 触发）
for pending in gate.list_pending():
    gate.approve(pending.candidate_id, approver="skill_reviewer")

# 5. 发布
pub = SkillPublisher("skills/enterprise")
for c in store.list_all(status="approved"):
    pub.publish(c)
```

## 9. 测试（[test_skill_evolution.py](agentclaw/test/unit/test_skill_evolution.py)）

17 个测试，覆盖：

- **PatternMiner**：business_rule（重复修正 + 噪声分离）/ tool_combination / failure / min_evidence 阈值
- **SkillExtractor**：Pattern → Candidate（domain/status/rules/source 正确）/ extract_many
- **SkillEvaluator**：高 confidence → promote；低 → 不 promote
- **ApprovalGate**：submit/approve/reject 完整流程；非 pending 不能 approve；不存在 candidate 报错
- **SkillPublisher**：非 approved 拒绝发布；approved 生成 4 个文件；list_published
- **CandidateStore**：upsert + status 过滤
- **端到端**（`test_end_to_end_evolution`）：5 条重复修正 trajectory → pending candidate → approved → published skill（SKILL.md 含业务规则）

**运行结果**：`17 passed`；Phase 1-4 回归 `113 passed` 无回归；`import agentclaw` 正常。

## 10. 后续衔接

| 阶段 | 如何使用本 Phase 成果 |
|---|---|
| Phase 6 Skill Registry | 发布产物（`skills/enterprise/`）接入统一 Registry 管理；CandidateStore 可升级为 Registry 持久化 |
| 后续（自动挖掘） | 周期性从 `trajectories.jsonl` 跑 PatternMiner，自动生成 candidate 待审批（开关 `AGENTCLAW_EVOLUTION_ENABLED`，默认 off） |
| Phase 7 Versioning | 发布新 skill → Agent 版本 +1（changelog 记录 added_skills） |
| Phase 8 Evaluation | 新 skill 发布前回归评估，不达标的候选不进入 approved |

## 11. 回滚

删除 `agentclaw/evolution/` 目录即完全回滚。本 Phase 为纯新增模块，不依赖运行时（不读 Workflow/Node/Tracing 核心），不影响现有功能。

## 12. 当前范围说明

完成**进化引擎核心**（挖掘/提取/评估/审批/发布）。尚未：
- 自动周期性挖掘（需调度，后续接 scheduler）
- 接入 Dashboard 审批界面（Phase 11 UI）
- 回归评估门（Phase 8 Evaluation）

这些是"接通"，放到对应 Phase 再做，避免过早耦合。

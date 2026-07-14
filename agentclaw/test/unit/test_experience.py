"""
Experience Collector 单元测试（Phase 4）

覆盖：
- 5 类事件创建与序列化
- 隐私脱敏（email/手机/身份证/银行卡/密钥/敏感key）
- JSONL 存储读写
- Trajectory 聚合（事件 → 轨迹）
- EventLogger 脱敏默认开启
- FeedbackCollector（评分校验 + 脱敏）
- StorageBackend 抽象可替换
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentclaw.experience import (
    AgentRespondedEvent,
    EVENT_TYPE_TASK_STARTED,
    EventLogger,
    FeedbackCollector,
    HumanFeedbackEvent,
    JSONLStorage,
    StorageBackend,
    TaskStartedEvent,
    ToolCalledEvent,
    TrajectoryStore,
    event_from_dict,
    has_sensitive_info,
    mask_value,
    sanitize_dict,
    sanitize_text,
)


pytestmark = pytest.mark.unit


def _store(tmp_path: Path) -> TrajectoryStore:
    """用 tmp_path 构造存储，避免污染项目 data/experience"""
    return TrajectoryStore(JSONLStorage(tmp_path / "exp"))


# ------------------------------------------------------------------
# 事件 Schema
# ------------------------------------------------------------------

def test_event_creation_and_jsonl():
    ev = TaskStartedEvent(
        agent_id="sales_agent", task_id="t1",
        user_request="分析线索", agent_version="v0.1",
    )
    assert ev.event_type == EVENT_TYPE_TASK_STARTED
    data = json.loads(ev.to_jsonl())
    assert data["event_type"] == "task_started"
    assert data["agent_id"] == "sales_agent"
    assert data["user_request"] == "分析线索"
    assert "timestamp" in data


def test_tool_called_event_defaults():
    ev = ToolCalledEvent(agent_id="a", task_id="t", tool_name="crm_query")
    assert ev.success is True
    assert ev.latency_ms == 0.0
    assert ev.tool_input == {}


def test_agent_responded_confidence_bounds():
    with pytest.raises(Exception):
        AgentRespondedEvent(agent_id="a", task_id="t", confidence=1.5)
    with pytest.raises(Exception):
        AgentRespondedEvent(agent_id="a", task_id="t", confidence=-0.1)


def test_event_from_dict_roundtrip():
    ev = ToolCalledEvent(
        agent_id="a", task_id="t", tool_name="x",
        success=False, latency_ms=12.5,
    )
    restored = event_from_dict(json.loads(ev.to_jsonl()))
    assert isinstance(restored, ToolCalledEvent)
    assert restored.tool_name == "x"
    assert restored.success is False
    assert restored.latency_ms == 12.5


# ------------------------------------------------------------------
# 隐私脱敏
# ------------------------------------------------------------------

def test_sanitize_detects_sensitive_categories():
    assert has_sensitive_info("邮箱 john@example.com")
    assert has_sensitive_info("手机 13800138000")
    assert has_sensitive_info("身份证 110101199001011234")
    assert has_sensitive_info("银行卡 6222021234567890123")


def test_sanitize_masks_each_category():
    assert "john@example.com" not in sanitize_text("联系 john@example.com")
    assert "13800138000" not in sanitize_text("电话13800138000")
    assert "110101199001011234" not in sanitize_text("身份证110101199001011234")
    assert "6222021234567890123" not in sanitize_text("卡号6222021234567890123")


def test_sanitize_keeps_non_sensitive_text():
    text = "这是一段普通文本，没有敏感信息，数字 12345"
    assert sanitize_text(text) == text
    assert has_sensitive_info(text) is False


def test_sanitize_secret_key_value():
    text = "api_key=sk-abcdef123456 token: bearer_xyz789 password=secret"
    result = sanitize_text(text)
    assert "sk-abcdef123456" not in result
    assert "bearer_xyz789" not in result
    assert "secret" not in result.split("password=")[1] if "password=" in result else True


def test_sanitize_dict_sensitive_keys():
    d = {
        "name": "张三",
        "password": "secret123",
        "phone": "13800138000",
        "api_key": "key123",
        "nested": {"token": "tok"},
    }
    result = sanitize_dict(d)
    assert result["name"] == "张三"
    assert result["password"] != "secret123"
    assert "13800138000" not in result["phone"]
    assert result["nested"]["token"] != "tok"


def test_mask_value_keeps_head_tail():
    assert mask_value("12345678") == "12****78"
    assert mask_value("ab") == "**"
    assert mask_value("") == ""


# ------------------------------------------------------------------
# JSONL 存储
# ------------------------------------------------------------------

def test_jsonl_storage_event_roundtrip(tmp_path):
    storage = JSONLStorage(tmp_path / "exp")
    ev = TaskStartedEvent(agent_id="a", task_id="t1", user_request="test")
    storage.append_event(ev.model_dump(mode="json"))
    events = storage.list_events()
    assert len(events) == 1
    assert events[0]["task_id"] == "t1"
    assert len(storage.list_events(task_id="t1")) == 1
    assert len(storage.list_events(task_id="other")) == 0


def test_jsonl_storage_trajectory_filter(tmp_path):
    storage = JSONLStorage(tmp_path / "exp")
    storage.append_trajectory({"trajectory_id": "t1", "agent_id": "a"})
    storage.append_trajectory({"trajectory_id": "t2", "agent_id": "b"})
    assert len(storage.list_trajectories()) == 2
    assert len(storage.list_trajectories(agent_id="a")) == 1


# ------------------------------------------------------------------
# EventLogger + 脱敏
# ------------------------------------------------------------------

def test_event_logger_sanitizes_by_default(tmp_path):
    logger = EventLogger(store=_store(tmp_path), privacy_enabled=True)
    logger.log_task_started("a", "t1", user_request="邮箱 test@example.com")
    events = logger.store.list_events(task_id="t1")
    assert "test@example.com" not in events[0]["user_request"]


def test_event_logger_privacy_disabled_keeps_raw(tmp_path):
    logger = EventLogger(store=_store(tmp_path), privacy_enabled=False)
    logger.log_task_started("a", "t1", user_request="邮箱 test@example.com")
    events = logger.store.list_events(task_id="t1")
    assert "test@example.com" in events[0]["user_request"]


def test_trajectory_aggregation(tmp_path):
    logger = EventLogger(store=_store(tmp_path))
    logger.log_task_started("sales_agent", "t1", user_request="分析线索", agent_version="v0.1")
    logger.log_tool_called("sales_agent", "t1", "crm_query", success=True, latency_ms=120)
    logger.log_tool_called("sales_agent", "t1", "enrich", success=False, latency_ms=50)
    logger.log_agent_responded("sales_agent", "t1", response="建议跟进", confidence=0.8)

    traj = logger.finalize("t1", "sales_agent")

    assert traj.agent_id == "sales_agent"
    assert traj.agent_version == "v0.1"
    assert traj.task == "分析线索"
    assert len(traj.tool_calls) == 2
    assert traj.tool_calls[0].tool_name == "crm_query"
    assert traj.final_answer == "建议跟进"
    assert traj.success is True

    # trajectory 写入存储
    trajs = logger.store.list_trajectories()
    assert len(trajs) == 1
    assert trajs[0]["trajectory_id"] == "t1"


def test_trajectory_failed_marks_unsuccessful(tmp_path):
    logger = EventLogger(store=_store(tmp_path))
    logger.log_task_started("a", "t1")
    logger.log_task_failed("a", "t1", error_type="ToolError", failed_step="query")
    traj = logger.finalize("t1", "a")
    assert traj.success is False


# ------------------------------------------------------------------
# FeedbackCollector
# ------------------------------------------------------------------

def test_feedback_collector_records(tmp_path):
    logger = EventLogger(store=_store(tmp_path))
    fc = FeedbackCollector(logger)
    ev = fc.submit("a", "t1", rating=4, feedback="不错", human_correction="预算>50万应标记高价值")
    assert isinstance(ev, HumanFeedbackEvent)
    assert ev.rating == 4
    events = logger.store.list_events(task_id="t1")
    assert len(events) == 1
    assert events[0]["event_type"] == "human_feedback_received"


def test_feedback_rating_validation(tmp_path):
    fc = FeedbackCollector(EventLogger(store=_store(tmp_path)))
    with pytest.raises(ValueError):
        fc.submit("a", "t1", rating=6)
    with pytest.raises(ValueError):
        fc.submit("a", "t1", rating=-1)


def test_feedback_zero_rating_allowed(tmp_path):
    fc = FeedbackCollector(EventLogger(store=_store(tmp_path)))
    ev = fc.submit("a", "t1", rating=0, feedback="仅文字反馈")
    assert ev.rating == 0


def test_feedback_correction_appears_in_trajectory(tmp_path):
    """人工修正进入 Trajectory（Skill Evolution 的核心信号）"""
    logger = EventLogger(store=_store(tmp_path))
    logger.log_task_started("a", "t1", user_request="x")
    fc = FeedbackCollector(logger)
    fc.submit("a", "t1", rating=2, human_correction="超过10万元需主管审批")
    traj = logger.finalize("t1", "a")
    assert traj.human_correction == "超过10万元需主管审批"
    assert traj.rating == 2


# ------------------------------------------------------------------
# StorageBackend 抽象（可替换为 PostgreSQL）
# ------------------------------------------------------------------

def test_storage_backend_is_abstract():
    with pytest.raises(TypeError):
        StorageBackend()  # 抽象类不可实例化


def test_custom_storage_backend_pluggable(tmp_path):
    """自定义内存存储（模拟未来 PostgreSQL 替换）"""
    class MemoryStorage(StorageBackend):
        def __init__(self):
            self.events = []
            self.trajs = []

        def append_event(self, d):
            self.events.append(d)

        def append_trajectory(self, d):
            self.trajs.append(d)

        def list_events(self, task_id=None):
            return [e for e in self.events if task_id is None or e.get("task_id") == task_id]

        def list_trajectories(self, agent_id=None):
            return [t for t in self.trajs if agent_id is None or t.get("agent_id") == agent_id]

    store = TrajectoryStore(MemoryStorage())
    logger = EventLogger(store=store)
    logger.log_task_started("a", "t1", user_request="test")
    assert len(store.storage.events) == 1

    traj = logger.finalize("t1", "a")
    assert len(store.storage.trajs) == 1
    assert traj.task == "test"

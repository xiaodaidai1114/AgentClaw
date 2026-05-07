"""
State - 状态管理模块

提供 LangGraph 状态持久化和消息处理功能
"""

from agentclaw.state.checkpointer import (
    setup_checkpointer,
    get_checkpointer,
    close_checkpointer,
    start_keepalive_task,
    stop_keepalive_task,
    get_state_by_thread,
    list_thread_states,
    create_memory_checkpointer,
    save_checkpoint,
)
from agentclaw.state.memory import (
    create_user_message,
    create_ai_message,
    create_system_message,
    get_messages_from_state,
    format_messages_for_llm,
    get_last_user_message,
    get_last_ai_message,
    create_chat_state_type,
    SYSTEM_STATE_FIELDS,
    warn_if_system_field,
    State,
    Field,
)
from agentclaw.state.schema import StateSchema, FieldSchema
from agentclaw.state.serializer import (
    make_serializable,
    safe_json_dumps,
    safe_json_loads,
    SafeJSONEncoder,
)

__all__ = [
    # Checkpointer
    "setup_checkpointer",
    "get_checkpointer",
    "close_checkpointer",
    "start_keepalive_task",
    "stop_keepalive_task",
    "get_state_by_thread",
    "list_thread_states",
    "create_memory_checkpointer",
    "save_checkpoint",
    # Memory helpers
    "create_user_message",
    "create_ai_message",
    "create_system_message",
    "get_messages_from_state",
    "format_messages_for_llm",
    "get_last_user_message",
    "get_last_ai_message",
    "create_chat_state_type",
    # System fields
    "SYSTEM_STATE_FIELDS",
    "warn_if_system_field",
    # State class
    "State",
    "Field",
    # Schema
    "StateSchema",
    "FieldSchema",
    # Serializer
    "make_serializable",
    "safe_json_dumps",
    "safe_json_loads",
    "SafeJSONEncoder",
]

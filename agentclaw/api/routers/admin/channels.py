"""
Channel 管理 Admin API

数据库驱动的渠道 CRUD + 消息日志查询。

- GET    /admin/channels              — 列出所有渠道配置
- POST   /admin/channels              — 新增渠道
- PUT    /admin/channels/{id}         — 更新渠道配置
- DELETE /admin/channels/{id}         — 删除渠道
- POST   /admin/channels/{id}/restart — 重启单个渠道
- GET    /admin/channels/{id}/logs    — 查询渠道消息日志
- GET    /admin/channels/logs         — 全局日志查询
- GET    /admin/channels/logs/stats   — 日志统计
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from pydantic import BaseModel

from agentclaw.channels.models import (
    ChannelCreate,
    ChannelLogListResponse,
    ChannelLogResponse,
    ChannelLogStats,
    ChannelMessageLog,
    ChannelRecord,
    ChannelResponse,
    ChannelUpdate,
)
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/channels", tags=["channels"])

# 全局 ChannelStore 引用，在 server.py 启动时注入
_channel_store = None


def set_channel_store(store):
    global _channel_store
    _channel_store = store


def get_channel_store():
    return _channel_store


def _get_store():
    if not _channel_store:
        raise HTTPException(status_code=503, detail="ChannelStore not initialized")
    return _channel_store


def _get_running_map() -> dict:
    """获取渠道运行状态映射"""
    try:
        from agentclaw.channels.routes import get_channel_manager
        manager = get_channel_manager()
        if manager:
            return {
                name: ch._running
                for name, ch in manager.list_all().items()
            }
    except Exception:
        pass
    return {}


def _get_channel_manager_optional():
    try:
        from agentclaw.channels.routes import get_channel_manager
        return get_channel_manager()
    except Exception:
        return None


async def _apply_channel_runtime(record: ChannelRecord) -> None:
    """将数据库中的渠道配置同步到运行中的实例。"""
    manager = _get_channel_manager_optional()
    if not manager:
        logger.debug("ChannelManager not initialized, skip runtime apply: %s", record.name)
        return

    old_ch = manager.get(record.name)
    if old_ch:
        await old_ch.stop()
        manager.unregister(record.name)

    if not record.enabled:
        logger.info("Channel runtime stopped after config apply: %s", record.name)
        return

    from agentclaw.channels import _create_channel, _resolve_env_vars
    from agentclaw.api.auth.token import WorkflowAPIKeyManager
    from agentclaw.config import get_config

    config = get_config()
    wf_api_key = WorkflowAPIKeyManager.get_instance().api_key
    platform_config = _resolve_env_vars(record.config)

    new_ch = _create_channel(
        ch_type=record.type,
        server_base_url=f"http://127.0.0.1:{config.server.port if hasattr(config, 'server') else 8000}",
        api_key=wf_api_key,
        thread_mode=record.thread_mode,
        workflow_id=record.workflow_id,
        user_input_field=record.user_input_field,
        channel_id=record.id,
        channel_name=record.name,
        **platform_config,
    )
    if not new_ch:
        raise HTTPException(status_code=400, detail=f"Unknown channel type: {record.type}")

    manager.register(record.name, new_ch)
    await new_ch.start()
    logger.info("Channel runtime applied: %s → workflow=%s", record.name, record.workflow_id)


def _channel_to_response(record: ChannelRecord, running_map: dict) -> dict:
    return ChannelResponse(
        id=record.id,
        name=record.name,
        type=record.type,
        workflow_id=record.workflow_id,
        user_input_field=record.user_input_field,
        thread_mode=record.thread_mode,
        enabled=record.enabled,
        config=record.config,
        running=running_map.get(record.name, False),
        created_at=record.created_at,
        updated_at=record.updated_at,
    ).model_dump(mode="json")


def _log_to_response(log: ChannelMessageLog) -> dict:
    """将 ChannelMessageLog 转换为 ChannelLogResponse dict"""
    return ChannelLogResponse(
        id=log.id,
        channel_id=log.channel_id,
        channel_name=log.channel_name,
        user_id=log.user_id,
        chat_id=log.chat_id,
        message=log.message,
        reply=log.reply,
        workflow_id=log.workflow_id,
        trace_id=log.trace_id,
        status=log.status,
        duration_ms=log.duration_ms,
        error=log.error,
        created_at=log.created_at,
    ).model_dump(mode="json")


# ============================================================
# 日志端点（放在参数化路由前，避免路径冲突）
# ============================================================

class ProbeRequest(BaseModel):
    """凭据验证请求"""
    type: str
    config: dict


@router.post("/probe", summary="Probe channel credentials")
async def probe_credentials(req: ProbeRequest):
    """验证渠道凭据是否有效"""
    from agentclaw.channels.probe import probe_channel

    result = await probe_channel(req.type, req.config)
    return {
        "ok": result.ok,
        "bot_name": result.bot_name,
        "bot_id": result.bot_id,
        "error": result.error,
        "extra": result.extra,
    }


@router.post("/feishu/setup", summary="Start Feishu QR setup")
async def start_feishu_setup():
    """启动飞书扫码设置会话（后端运行 openclaw-lark-tools install）"""
    from agentclaw.channels.setup import create_setup_session

    session = create_setup_session()
    await session.start()

    return {
        "session_id": session.id,
        "status": session.status,
        "error": session.error,
    }


@router.get("/feishu/setup/{session_id}", summary="Get Feishu setup status")
async def get_feishu_setup(session_id: str):
    """获取飞书扫码设置会话状态和输出"""
    from agentclaw.channels.setup import get_setup_session

    session = get_setup_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Setup session not found")

    output = session.get_output().decode("utf-8", errors="replace")
    return {
        "session_id": session.id,
        "status": session.status,
        "output": output,
        "result": session.result,
        "error": session.error,
    }


@router.post("/feishu/setup/{session_id}/input", summary="Send input to Feishu setup")
async def send_feishu_setup_input(session_id: str, body: dict):
    """向扫码设置会话发送用户输入"""
    from agentclaw.channels.setup import get_setup_session

    session = get_setup_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Setup session not found")

    text = body.get("input", "")
    await session.send_input(text)
    return {"ok": True}


@router.delete("/feishu/setup/{session_id}", summary="Cleanup Feishu setup")
async def cleanup_feishu_setup(session_id: str):
    """清理飞书扫码设置会话"""
    from agentclaw.channels.setup import cleanup_session

    await cleanup_session(session_id)
    return {"ok": True}


@router.get("/logs", summary="List all channel message logs")
async def list_all_logs(
    channel_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """全局消息日志查询"""
    store = _get_store()
    logs, total = await store.list_message_logs(
        channel_id=channel_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        page=page,
        limit=limit,
    )
    return ChannelLogListResponse(
        logs=[_log_to_response(log) for log in logs],
        total=total,
        page=page,
        limit=limit,
    ).model_dump(mode="json")


@router.get("/logs/stats", summary="Message log statistics")
async def log_stats(
    channel_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
):
    """消息日志统计"""
    store = _get_store()
    stats = await store.get_log_stats(
        channel_id=channel_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
    )
    return ChannelLogStats(**stats).model_dump()


# ============================================================
# 渠道 CRUD
# ============================================================

@router.get("", summary="List all channel configs")
async def list_channels(
    type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """列出所有渠道配置（含运行状态）"""
    store = _get_store()
    channels, total = await store.list_channels(type=type, page=page, limit=limit)
    running_map = _get_running_map()

    return {
        "channels": [_channel_to_response(ch, running_map) for ch in channels],
        "total": total,
    }


@router.post("", summary="Create channel")
async def create_channel(req: ChannelCreate):
    """新增渠道配置"""
    store = _get_store()

    valid_types = {"feishu", "dingtalk", "wecom", "qq"}
    if req.type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type: {req.type}. Must be one of {valid_types}",
        )

    # 检查名称唯一
    existing = await store.get_channel_by_name(req.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Channel already exists: {req.name}")

    record = ChannelRecord(
        name=req.name,
        type=req.type,
        workflow_id=req.workflow_id,
        user_input_field=req.user_input_field,
        thread_mode=req.thread_mode,
        enabled=req.enabled,
        config=req.config,
    )
    await store.create_channel(record)

    logger.info(f"Channel created: {record.name} ({record.type}) id={record.id}")
    running_map = _get_running_map()
    return _channel_to_response(record, running_map)


@router.get("/{channel_id}", summary="Get channel")
async def get_channel(channel_id: str):
    """获取单个渠道配置"""
    store = _get_store()
    record = await store.get_channel(channel_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Channel not found: {channel_id}")

    running_map = _get_running_map()
    return _channel_to_response(record, running_map)


@router.put("/{channel_id}", summary="Update channel")
async def update_channel(channel_id: str, req: ChannelUpdate):
    """更新渠道配置"""
    store = _get_store()

    existing = await store.get_channel(channel_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Channel not found: {channel_id}")

    updates = req.model_dump(exclude_none=True)
    if not updates:
        running_map = _get_running_map()
        return _channel_to_response(existing, running_map)

    # 合并平台配置
    if "config" in updates:
        merged = dict(existing.config)
        merged.update(updates["config"])
        updates["config"] = merged

    updated = await store.update_channel(channel_id, updates)
    await _apply_channel_runtime(updated)

    logger.info(f"Channel updated: {existing.name} (id={channel_id})")
    running_map = _get_running_map()
    return _channel_to_response(updated, running_map)


@router.delete("/{channel_id}", summary="Delete channel")
async def delete_channel(channel_id: str):
    """删除渠道配置并停止实例"""
    store = _get_store()

    record = await store.get_channel(channel_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Channel not found: {channel_id}")

    # 停止运行中的实例
    try:
        from agentclaw.channels.routes import get_channel_manager
        manager = get_channel_manager()
        if manager:
            ch = manager.get(record.name)
            if ch:
                await ch.stop()
                manager.unregister(record.name)
    except Exception as e:
        logger.warning(f"Failed to stop channel {record.name}: {e}")

    await store.delete_channel(channel_id)

    logger.info(f"Channel deleted: {record.name} (id={channel_id})")
    return {"message": f"Channel {record.name} deleted"}


@router.post("/{channel_id}/restart", summary="Restart channel")
async def restart_channel(channel_id: str):
    """重启单个渠道（重新加载配置并启动）"""
    store = _get_store()

    record = await store.get_channel(channel_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Channel not found: {channel_id}")

    if not record.enabled:
        raise HTTPException(status_code=400, detail=f"Channel is disabled: {record.name}")

    try:
        await _apply_channel_runtime(record)
        logger.info(f"Channel restarted: {record.name}")
        return {"message": f"Channel {record.name} restarted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Channel restart failed: {record.name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 单个渠道日志
# ============================================================

@router.get("/{channel_id}/logs", summary="Channel message logs")
async def channel_logs(
    channel_id: str,
    status: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """查询指定渠道的消息日志"""
    store = _get_store()

    record = await store.get_channel(channel_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Channel not found: {channel_id}")

    logs, total = await store.list_message_logs(
        channel_id=channel_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        page=page,
        limit=limit,
    )
    return ChannelLogListResponse(
        logs=[_log_to_response(log) for log in logs],
        total=total,
        page=page,
        limit=limit,
    ).model_dump(mode="json")

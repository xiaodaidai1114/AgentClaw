from typing import Any

from fastapi import APIRouter, Body, Depends

from agentclaw.api.schemas.common import APIError, ErrorCode
from agentclaw.api.services.settings_service import SettingsService, get_settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


def _bad_section(section: str) -> None:
    raise APIError(
        error=f"不支持的配置分组: {section}",
        code=ErrorCode.INVALID_REQUEST,
        status_code=400,
    )


@router.get("/global")
async def get_global_settings(service: SettingsService = Depends(get_settings_service)):
    return service.get_global()


@router.get("/env")
async def get_settings_env_reference(service: SettingsService = Depends(get_settings_service)):
    return service.get_env_reference()


@router.put("/env")
async def update_settings_env(
    payload: dict[str, Any] = Body(default={}),
    service: SettingsService = Depends(get_settings_service),
):
    return service.update_env(payload)


@router.get("/models")
async def get_models_config(service: SettingsService = Depends(get_settings_service)):
    return service.get_models_config()


@router.put("/models")
async def update_models_config(
    payload: dict[str, Any] = Body(default={}),
    service: SettingsService = Depends(get_settings_service),
):
    try:
        return service.update_models_config(payload)
    except ValueError as exc:
        raise APIError(
            error=str(exc),
            code=ErrorCode.INVALID_REQUEST,
            status_code=400,
        )


@router.put("/global")
async def update_global_settings(
    payload: dict[str, Any] = Body(default={}),
    service: SettingsService = Depends(get_settings_service),
):
    return service.update_global(payload)


@router.get("/maintenance")
async def get_maintenance_settings(service: SettingsService = Depends(get_settings_service)):
    return service.get_maintenance()


@router.put("/maintenance")
async def update_maintenance_settings(
    payload: dict[str, Any] = Body(default={}),
    service: SettingsService = Depends(get_settings_service),
):
    return service.update_maintenance(payload)


@router.get("/infra/{section}")
async def get_infra_settings(
    section: str,
    service: SettingsService = Depends(get_settings_service),
):
    if section not in {"database", "redis", "upload", "auth", "scheduler"}:
        _bad_section(section)
    return service.get_infra(section)


@router.put("/infra/{section}")
async def update_infra_settings(
    section: str,
    payload: dict[str, Any] = Body(default={}),
    service: SettingsService = Depends(get_settings_service),
):
    if section not in {"database", "redis", "upload", "auth", "scheduler"}:
        _bad_section(section)
    return service.update_infra(section, payload)


@router.get("/workflows/{workflow_id}")
async def get_workflow_settings(
    workflow_id: str,
    service: SettingsService = Depends(get_settings_service),
):
    try:
        return service.get_workflow(workflow_id)
    except KeyError:
        raise APIError(
            error=f"工作流 '{workflow_id}' 不存在",
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            status_code=404,
        )


@router.put("/workflows/{workflow_id}")
async def update_workflow_settings(
    workflow_id: str,
    payload: dict[str, Any] = Body(default={}),
    service: SettingsService = Depends(get_settings_service),
):
    try:
        return service.update_workflow(workflow_id, payload)
    except KeyError:
        raise APIError(
            error=f"工作流 '{workflow_id}' 不存在",
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            status_code=404,
        )


@router.post("/workflows/{workflow_id}/fields/{field}/reset")
async def reset_workflow_setting_field(
    workflow_id: str,
    field: str,
    service: SettingsService = Depends(get_settings_service),
):
    try:
        return service.reset_workflow_field(workflow_id, field)
    except KeyError:
        raise APIError(
            error=f"工作流 '{workflow_id}' 不存在",
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            status_code=404,
        )
    except ValueError:
        raise APIError(
            error=f"不支持重置工作流字段: {field}",
            code=ErrorCode.INVALID_REQUEST,
            status_code=400,
        )


@router.get("/workflows/{workflow_id}/nodes/{node_id}")
async def get_node_settings(
    workflow_id: str,
    node_id: str,
    service: SettingsService = Depends(get_settings_service),
):
    try:
        return service.get_node(workflow_id, node_id)
    except KeyError:
        raise APIError(
            error=f"节点 '{node_id}' 不存在",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
        )


@router.post("/workflows/{workflow_id}/nodes/{node_id}/fields/{field}/reset")
async def reset_node_setting_field(
    workflow_id: str,
    node_id: str,
    field: str,
    service: SettingsService = Depends(get_settings_service),
):
    try:
        return service.reset_node_field(workflow_id, node_id, field)
    except KeyError:
        raise APIError(
            error=f"节点 '{node_id}' 不存在",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
        )
    except ValueError:
        raise APIError(
            error=f"不支持重置节点字段: {field}",
            code=ErrorCode.INVALID_REQUEST,
            status_code=400,
        )


@router.put("/workflows/{workflow_id}/nodes/{node_id}")
async def update_node_settings(
    workflow_id: str,
    node_id: str,
    payload: dict[str, Any] = Body(default={}),
    service: SettingsService = Depends(get_settings_service),
):
    try:
        return service.update_node(workflow_id, node_id, payload)
    except KeyError:
        raise APIError(
            error=f"节点 '{node_id}' 不存在",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
        )

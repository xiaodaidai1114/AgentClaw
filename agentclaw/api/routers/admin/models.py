"""
模型 API 路由
"""

from fastapi import APIRouter, Depends

from agentclaw.api.schemas import (
    ModelInfo,
    ModelListResponse,
    ModelUpdateRequest,
    ModelFallbackRequest,
    FallbackState,
)
from agentclaw.api.schemas.common import ErrorCode, APIError
from agentclaw.api.schemas.dashboard import (
    AvailableModel,
    AvailableModelsResponse,
)
from agentclaw.api.services import get_model_service, ModelService

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/available", response_model=AvailableModelsResponse, summary="List available models")
async def list_available_models(
    service: ModelService = Depends(get_model_service),
):
    """List available models for node model switching."""
    result = service.list_available_models()
    return AvailableModelsResponse(
        models=[AvailableModel(**m) for m in result["models"]],
        default_model_id=result.get("default_model_id"),
    )


@router.get("", response_model=ModelListResponse, summary="List models")
async def list_models(
    service: ModelService = Depends(get_model_service),
):
    """List all configured models with current fallback state."""
    result = service.list_models()
    
    return ModelListResponse(
        models=[ModelInfo(**m) for m in result["models"]],
        fallback_state=FallbackState(**result["fallback_state"]),
    )


@router.get("/{model_id}", response_model=ModelInfo, summary="Get model")
async def get_model(
    model_id: str,
    service: ModelService = Depends(get_model_service),
):
    """Get a single model's configuration and status."""
    model = service.get_model(model_id)
    if not model:
        raise APIError(
            error=f"模型 '{model_id}' 不存在",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
        )
    return ModelInfo(**model)


@router.put("/{model_id}", response_model=ModelInfo, summary="Update model")
async def update_model(
    model_id: str,
    request: ModelUpdateRequest,
    service: ModelService = Depends(get_model_service),
):
    """Update model configuration (temperature, max_tokens, timeout)."""
    params = request.model_dump(exclude_none=True)
    if not params:
        raise APIError(
            error="没有要更新的参数",
            code=ErrorCode.INVALID_REQUEST,
            status_code=400,
        )
    
    result = service.update_model(model_id, **params)
    if not result:
        raise APIError(
            error=f"模型 '{model_id}' 不存在",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
        )
    
    return ModelInfo(**result)


@router.post("/{model_id}/fallback", response_model=FallbackState, summary="Force fallback")
async def force_fallback(
    model_id: str,
    request: ModelFallbackRequest,
    service: ModelService = Depends(get_model_service),
):
    """Manually trigger model fallback."""
    result = service.force_fallback(model_id, request.reason or "手动触发")
    return FallbackState(**result)


@router.post("/{model_id}/recover", response_model=FallbackState, summary="Recover primary model")
async def recover_primary(
    model_id: str,
    service: ModelService = Depends(get_model_service),
):
    """Recover primary model from fallback state."""
    result = service.force_primary(model_id)
    return FallbackState(**result)

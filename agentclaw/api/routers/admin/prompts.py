"""
提示词 API 路由
"""

from fastapi import APIRouter, Query, Depends

from agentclaw.api.schemas import (
    PromptInfo,
    PromptListResponse,
    PromptUpdateRequest,
    PromptPreviewRequest,
    PromptPreviewResponse,
    PromptHistoryResponse,
    PromptHistory,
    PromptRollbackRequest,
)
from agentclaw.api.schemas.common import ErrorCode, APIError
from agentclaw.api.services import get_prompt_service, PromptService

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("/{workflow_id}", response_model=PromptListResponse, summary="List prompts")
async def list_prompts(
    workflow_id: str,
    service: PromptService = Depends(get_prompt_service),
):
    """List all prompts for a workflow."""
    prompts = service.list_prompts(workflow_id)
    return PromptListResponse(prompts=[PromptInfo(**p) for p in prompts])


@router.get("/{workflow_id}/{prompt_key}", response_model=PromptInfo, summary="Get prompt")
async def get_prompt(
    workflow_id: str,
    prompt_key: str,
    service: PromptService = Depends(get_prompt_service),
):
    """Get a single prompt by key."""
    prompt = service.get_prompt(workflow_id, prompt_key)
    if not prompt:
        raise APIError(
            error=f"提示词 '{prompt_key}' 不存在",
            code=ErrorCode.PROMPT_NOT_FOUND,
            status_code=404,
        )
    return PromptInfo(**prompt)


@router.put("/{workflow_id}/{prompt_key}", response_model=PromptInfo, summary="Update prompt")
async def update_prompt(
    workflow_id: str,
    prompt_key: str,
    request: PromptUpdateRequest,
    service: PromptService = Depends(get_prompt_service),
):
    """Update prompt content. Requires Redis for hot-reload."""
    try:
        result = await service.update_prompt(
            workflow_id,
            prompt_key,
            request.content,
            updated_by="admin",
        )
        return PromptInfo(**result)
    except KeyError as e:
        raise APIError(
            error=str(e),
            code=ErrorCode.PROMPT_NOT_FOUND,
            status_code=404,
        )
    except RuntimeError as e:
        raise APIError(
            error=str(e),
            code=ErrorCode.SERVICE_UNAVAILABLE,
            status_code=503,
        )
    except ValueError as e:
        raise APIError(
            error=str(e),
            code=ErrorCode.VALIDATION_ERROR,
            status_code=400,
        )


@router.post("/{workflow_id}/{prompt_key}/reset", response_model=PromptInfo, summary="Reset prompt")
async def reset_prompt(
    workflow_id: str,
    prompt_key: str,
    service: PromptService = Depends(get_prompt_service),
):
    """Reset prompt to default value. Requires Redis for hot-reload."""
    try:
        result = await service.reset_prompt(
            workflow_id,
            prompt_key,
            updated_by="admin",
        )
        return PromptInfo(**result)
    except KeyError as e:
        raise APIError(
            error=str(e),
            code=ErrorCode.PROMPT_NOT_FOUND,
            status_code=404,
        )
    except RuntimeError as e:
        raise APIError(
            error=str(e),
            code=ErrorCode.SERVICE_UNAVAILABLE,
            status_code=503,
        )
    except ValueError as e:
        raise APIError(
            error=str(e),
            code=ErrorCode.VALIDATION_ERROR,
            status_code=400,
        )


@router.get("/{workflow_id}/{prompt_key}/history", response_model=PromptHistoryResponse, summary="Get prompt history")
async def get_prompt_history(
    workflow_id: str,
    prompt_key: str,
    limit: int = Query(10, ge=1, le=50, description="Number of versions to return"),
    service: PromptService = Depends(get_prompt_service),
):
    """Get prompt version history."""
    history = await service.get_history(workflow_id, prompt_key, limit)
    return PromptHistoryResponse(history=[PromptHistory(**h) for h in history])


@router.post("/{workflow_id}/{prompt_key}/rollback", response_model=PromptInfo, summary="Rollback prompt")
async def rollback_prompt(
    workflow_id: str,
    prompt_key: str,
    request: PromptRollbackRequest,
    service: PromptService = Depends(get_prompt_service),
):
    """Rollback prompt to a specific version."""
    try:
        result = await service.rollback(
            workflow_id,
            prompt_key,
            request.version,
            updated_by="admin",
        )
        return PromptInfo(**result)
    except KeyError as e:
        raise APIError(
            error=str(e),
            code=ErrorCode.PROMPT_NOT_FOUND,
            status_code=404,
        )
    except ValueError as e:
        raise APIError(
            error=str(e),
            code=ErrorCode.VALIDATION_ERROR,
            status_code=400,
        )


@router.post("/{workflow_id}/preview", response_model=PromptPreviewResponse, summary="Preview prompt")
async def preview_prompt(
    workflow_id: str,
    request: PromptPreviewRequest,
    service: PromptService = Depends(get_prompt_service),
):
    """Preview prompt with variable substitution."""
    rendered = service.preview_prompt(
        workflow_id,
        request.content,
        request.variables,
    )
    return PromptPreviewResponse(rendered=rendered)

"""
Workflow execution API router

Handles workflow run (blocking + streaming), confirm actions, and file downloads.
"""

from typing import Any, Dict, Iterable, Optional, Tuple
import base64
import hashlib
import hmac
import json
import os
import secrets
import time as _time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agentclaw.api.auth.dependencies import (
    authenticate_bearer,
    authenticate_workflow_or_admin_bearer,
    authentication_failed_response,
    extract_bearer_token,
    require_admin_auth,
    require_workflow_or_admin_auth,
)
from agentclaw.api.routers.public.access import (
    check_public_rate_limit,
    forbidden_response,
    is_builtin_workflow,
    trust_proxy_headers,
    verify_public_share_token,
    workflow_not_found_response,
)
from agentclaw.api.schemas.common import ErrorCode
from agentclaw.api.schemas.execution import (
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowRunError,
    WorkflowRunMetadata,
    UsageInfo,
    ConfirmActionRequest,
    ConfirmActionResponse,
    ContextCompressRequest,
    ContextCompressResponse,
)
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["execution"])

NON_CONVERSATION_MODEL_TYPES = {"embedding", "rerank"}
PUBLIC_SESSION_COOKIE = "agentclaw_public_session"
PUBLIC_SESSION_HEADER = "x-agentclaw-public-session"
PUBLIC_SESSION_TTL_SECONDS = 2 * 60 * 60
PUBLIC_FILE_INPUT_TYPES = {
    "Image",
    "File",
    "Audio",
    "Files",
    "image",
    "file",
    "audio",
    "files",
    "image-upload",
    "file-upload",
    "audio-upload",
    "files-upload",
}


def _is_builtin_workflow(workflow: Any, workflow_id: str) -> bool:
    """Return true for workflows that must never be exposed via anonymous public links."""
    return is_builtin_workflow(workflow, workflow_id)


def _workflow_not_found_response(workflow_id: str) -> JSONResponse:
    return workflow_not_found_response(workflow_id)


def _request_origin(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto") if trust_proxy_headers() else None
    forwarded_host = request.headers.get("x-forwarded-host") if trust_proxy_headers() else None
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def _is_same_origin_public_page_request(request: Request) -> bool:
    sec_fetch_site = (request.headers.get("sec-fetch-site") or "").lower()
    if sec_fetch_site == "cross-site":
        return False
    if sec_fetch_site and sec_fetch_site not in {"same-origin", "same-site", "none"}:
        return False

    expected_origin = _request_origin(request)
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")

    if not origin and not referer:
        return False

    if origin and origin.rstrip("/") != expected_origin:
        return False

    if referer:
        from urllib.parse import urlsplit

        parsed = urlsplit(referer)
        referer_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if referer_origin != expected_origin:
            return False

    return True


def _public_session_signing_secret() -> bytes:
    secret = os.getenv("AGENTCLAW_PUBLIC_SESSION_SECRET", "").strip()
    if not secret:
        from agentclaw.api.auth.token import AdminTokenManager

        secret = AdminTokenManager.get_instance().token
    return secret.encode("utf-8")


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _sign_public_session_payload(encoded_payload: str) -> str:
    digest = hmac.new(
        _public_session_signing_secret(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _base64url_encode(digest)


def _create_public_session(workflow_id: str) -> Tuple[str, int]:
    expires_at = int(_time.time()) + PUBLIC_SESSION_TTL_SECONDS
    payload = {
        "workflow_id": workflow_id,
        "expires_at": expires_at,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded_payload = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = _sign_public_session_payload(encoded_payload)
    return f"{encoded_payload}.{signature}", expires_at


def _verify_public_session(request: Request, workflow_id: str) -> bool:
    if request.headers.get(PUBLIC_SESSION_HEADER) != "1":
        return False
    token = request.cookies.get(PUBLIC_SESSION_COOKIE)
    if not token:
        return False
    try:
        encoded_payload, signature = token.split(".", 1)
    except ValueError:
        return False

    expected_signature = _sign_public_session_payload(encoded_payload)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    try:
        session = json.loads(_base64url_decode(encoded_payload))
    except Exception:
        return False

    if session.get("workflow_id") != workflow_id:
        return False
    return float(session.get("expires_at", 0)) > _time.time()


def _public_workflow_payload(workflow: Any, workflow_id: str) -> Dict[str, Any]:
    """Build the minimal workflow metadata needed by the anonymous chat page."""
    input_schema = None
    if hasattr(workflow, "get_input_schema"):
        input_schema = workflow.get_input_schema()
    else:
        input_schema = getattr(workflow, "input_schema", None)

    form_config = None
    if hasattr(workflow, "get_form_config"):
        form_config = workflow.get_form_config()
    else:
        form_config = getattr(workflow, "form_config", None)

    user_input_field = None
    if hasattr(workflow, "get_user_input_field"):
        user_input_field = workflow.get_user_input_field()
    else:
        user_input_field = getattr(workflow, "user_input_field", None)

    return {
        "id": getattr(workflow, "id", workflow_id),
        "name": getattr(workflow, "name", workflow_id),
        "description": getattr(workflow, "description", "") or "",
        "welcome": getattr(workflow, "welcome", "") or "",
        "form_config": form_config,
        "input_schema": input_schema,
        "user_input_field": user_input_field,
    }


def _normalize_user_and_inputs(
    *,
    user_value: Any,
    input_data: Dict[str, Any],
    user_input_field: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Normalize top-level `user` and `inputs[user_input_field]` into one consistent payload.

    Returns:
        (normalized_input_data, error_payload)
        - normalized_input_data is None when validation fails.
        - error_payload matches API error body shape: {"error": "...", "code": "..."}.
    """
    normalized = dict(input_data or {})

    if user_value is not None and not isinstance(user_value, str):
        return None, {
            "error": "'user' must be a string when provided",
            "code": ErrorCode.INVALID_REQUEST,
        }

    if isinstance(user_value, str):
        normalized["__user__"] = user_value
        if user_input_field:
            existing_input_value = normalized.get(user_input_field)
            if existing_input_value is None:
                normalized[user_input_field] = user_value
            else:
                if not isinstance(existing_input_value, str):
                    return None, {
                        "error": f"'inputs.{user_input_field}' must be a string when provided",
                        "code": ErrorCode.INVALID_REQUEST,
                    }
                if existing_input_value != user_value:
                    return None, {
                        "error": (
                            f"conflict between top-level 'user' and 'inputs.{user_input_field}'. "
                            "Provide only one value or keep them identical."
                        ),
                        "code": ErrorCode.INVALID_REQUEST,
                    }
    elif user_input_field:
        # Compatibility path where caller sends only inputs.<user_input_field>.
        existing_input_value = normalized.get(user_input_field)
        if existing_input_value is not None and not isinstance(existing_input_value, str):
            return None, {
                "error": f"'inputs.{user_input_field}' must be a string when provided",
                "code": ErrorCode.INVALID_REQUEST,
            }

    return normalized, None


def _workflow_file_field_names(workflow_inputs: Optional[Iterable[Any]]) -> set[str]:
    """Return workflow input names that represent file-like payloads."""
    file_fields: set[str] = set()
    for inp in workflow_inputs or []:
        name = getattr(inp, "name", None)
        type_value = getattr(inp, "type", None)
        if isinstance(inp, dict):
            name = name or inp.get("name")
            type_value = type_value or inp.get("type")
        if not name:
            continue
        type_name = type_value.__name__ if hasattr(type_value, "__name__") else str(type_value or "")
        if type_name in PUBLIC_FILE_INPUT_TYPES:
            file_fields.add(str(name))
    return file_fields


def _looks_like_inline_file_payload(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("data:")
    if isinstance(value, list):
        return any(_looks_like_inline_file_payload(item) for item in value)
    return False


def _public_file_payload_error(
    *,
    input_data: Dict[str, Any],
    workflow_inputs: Optional[Iterable[Any]],
    has_request_files_key: bool,
    request_files: Any,
) -> Optional[Dict[str, Any]]:
    """Reject anonymous public file payloads before they touch storage."""
    if has_request_files_key:
        return {
            "error": "File attachments are not supported for anonymous public workflow runs",
            "code": ErrorCode.INVALID_REQUEST,
        }

    file_fields = _workflow_file_field_names(workflow_inputs)
    for key, value in input_data.items():
        if not value:
            continue
        if key in file_fields or _looks_like_inline_file_payload(value):
            return {
                "error": "File inputs are not supported for anonymous public workflow runs",
                "code": ErrorCode.INVALID_REQUEST,
            }
    return None


@router.get(
    "/workflows",
    summary="List workflows",
    description="List all registered workflows",
    dependencies=[Depends(require_workflow_or_admin_auth)],
)
async def list_workflows():
    """List all registered workflows with basic info."""
    from agentclaw.api.registry import WorkflowRegistry
    return {"workflows": WorkflowRegistry.list_info()}


@router.get(
    "/models",
    summary="List models",
    description="List all registered models",
    dependencies=[Depends(require_workflow_or_admin_auth)],
)
async def list_models():
    """List all registered models from models.json."""
    from agentclaw.api.registry import WorkflowRegistry
    try:
        models = []
        seen = set()
        default_model_id = None
        for workflow in WorkflowRegistry.list_all():
            llm_manager = getattr(workflow, '_llm_manager', None)
            if llm_manager is None:
                continue
            if hasattr(llm_manager, 'llm_manager'):
                llm_manager = llm_manager.llm_manager
            if default_model_id is None:
                default_model_id = getattr(llm_manager, 'default_id', None)
            configs = getattr(llm_manager, '_models_cache', {})
            for model_id in getattr(llm_manager, 'model_ids', []):
                if model_id not in seen:
                    config = configs.get(model_id)
                    model_type = str((config.model_type if config else "chat") or "chat").strip().lower()
                    if model_type in NON_CONVERSATION_MODEL_TYPES:
                        continue
                    seen.add(model_id)
                    models.append({"id": model_id, "name": model_id, "type": model_type})
        return {"models": models, "default_model_id": default_model_id}
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        return {"models": [], "default_model_id": None}


@router.get(
    "/public/workflows/{workflow_id}",
    summary="Get anonymous public workflow metadata",
    description="Return the minimal workflow metadata needed by the public agent page.",
)
async def get_public_workflow(workflow_id: str, request: Request):
    """Get a workflow's anonymous public chat metadata."""
    from agentclaw.api.registry import WorkflowRegistry

    workflow = WorkflowRegistry.get(workflow_id)
    if not workflow:
        return _workflow_not_found_response(workflow_id)
    share_error = verify_public_share_token(workflow, workflow_id, request)
    if share_error:
        return share_error
    return {"workflow": _public_workflow_payload(workflow, workflow_id)}


@router.post(
    "/public/workflows/{workflow_id}/session",
    summary="Open anonymous public workflow page session",
    description="Create a short-lived same-origin browser session for the public agent page.",
)
async def open_public_workflow_session(workflow_id: str, request: Request):
    """Create a page session required by the anonymous public run endpoint."""
    from agentclaw.api.registry import WorkflowRegistry

    workflow = WorkflowRegistry.get(workflow_id)
    if not workflow:
        return _workflow_not_found_response(workflow_id)
    share_error = verify_public_share_token(workflow, workflow_id, request)
    if share_error:
        return share_error
    if not _is_same_origin_public_page_request(request):
        return forbidden_response("Public workflow sessions must be opened from the same-origin public page")

    token, expires_at = _create_public_session(workflow_id)
    response = JSONResponse(content={"ok": True, "expires_at": expires_at})
    response.set_cookie(
        PUBLIC_SESSION_COOKIE,
        token,
        max_age=PUBLIC_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/api",
    )
    return response


@router.post(
    "/workflow/run",
    summary="Run workflow",
    description="Execute a workflow in blocking or streaming mode (Dify-compatible format)",
    responses={
        401: {"description": "Unauthorized - invalid API key"},
        404: {"description": "Workflow not found"},
        500: {"description": "Workflow execution error"},
    },
)
async def run_workflow(request: Request):
    return await _run_workflow_request(request, require_auth=True)


@router.post(
    "/public/workflows/{workflow_id}/run",
    summary="Run anonymous public workflow",
    description="Execute one workflow from the anonymous public agent page.",
    responses={
        404: {"description": "Workflow not found"},
        500: {"description": "Workflow execution error"},
    },
)
async def run_public_workflow(workflow_id: str, request: Request):
    return await _run_workflow_request(
        request,
        require_auth=False,
        forced_workflow_id=workflow_id,
        public_mode=True,
    )


async def _run_workflow_request(
    request: Request,
    *,
    require_auth: bool,
    forced_workflow_id: Optional[str] = None,
    public_mode: bool = False,
):
    """
    Execute a workflow.

    Requires Authorization: Bearer {api_key} header.

    Supports two response modes:
    - **blocking**: Returns complete result as JSON
    - **streaming**: Returns SSE event stream
    """
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.graph.context import WorkflowContext
    from agentclaw.runtime.streaming.context import OutputChannel, _output_channel_var
    import uuid
    import time

    if require_auth and not extract_bearer_token(request):
        return authentication_failed_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON body", "code": ErrorCode.INVALID_JSON},
        )

    workflow_id = forced_workflow_id or body.get("workflow_id")
    if not workflow_id:
        return JSONResponse(
            status_code=400,
            content={"error": "workflow_id is required", "code": ErrorCode.INVALID_REQUEST},
        )

    workflow = WorkflowRegistry.get(workflow_id)
    if not workflow:
        if require_auth:
            try:
                await authenticate_bearer(request)
            except HTTPException:
                return authentication_failed_response()
        return _workflow_not_found_response(workflow_id)
    if public_mode and _is_builtin_workflow(workflow, workflow_id):
        return _workflow_not_found_response(workflow_id)
    if require_auth:
        try:
            await authenticate_workflow_or_admin_bearer(request, workflow=workflow, workflow_id=workflow_id)
        except HTTPException:
            return authentication_failed_response()
    if public_mode:
        share_error = verify_public_share_token(workflow, workflow_id, request, body)
        if share_error:
            return share_error
        if not _is_same_origin_public_page_request(request) or not _verify_public_session(request, workflow_id):
            return forbidden_response("Public workflow run requires a same-origin public page session")
        rate_error = check_public_rate_limit(workflow, workflow_id, request, "run")
        if rate_error:
            return rate_error

    # Parse params
    user_value = body.get("user")

    user_id = None if public_mode else body.get("user_id")
    if user_id is not None and not isinstance(user_id, str):
        return JSONResponse(
            status_code=400,
            content={
                "error": "'user_id' must be a string when provided",
                "code": ErrorCode.INVALID_REQUEST,
            },
        )

    response_mode = body.get("response_mode") or body.get("mode", "blocking")
    thread_id = body.get("conversation_id") or str(uuid.uuid4())
    input_data = body.get("inputs")
    if input_data is None:
        input_data = body.get("input_data")
    if input_data is None:
        input_data = {}
    if not isinstance(input_data, dict):
        return JSONResponse(
            status_code=400,
            content={
                "error": "'inputs' must be an object",
                "code": ErrorCode.INVALID_REQUEST,
            },
        )

    user_input_field = workflow.get_user_input_field()
    normalized_input_data, normalize_error = _normalize_user_and_inputs(
        user_value=user_value,
        input_data=input_data,
        user_input_field=user_input_field,
    )
    if normalize_error:
        return JSONResponse(status_code=400, content=normalize_error)
    input_data = normalized_input_data or {}

    # Process file-type inputs
    from agentclaw.database import process_file_inputs

    input_schema = getattr(workflow, "_input_schema", None)
    workflow_inputs = list(input_schema.inputs.values()) if input_schema else None
    if public_mode:
        public_file_error = _public_file_payload_error(
            input_data=input_data,
            workflow_inputs=workflow_inputs,
            has_request_files_key="files" in body,
            request_files=body.get("files"),
        )
        if public_file_error:
            return JSONResponse(status_code=400, content=public_file_error)

    if not public_mode:
        input_data = await process_file_inputs(
            input_data, workflow_inputs
        )

    # Inject __files__ from request (chat attachments)
    req_files = body.get("files")
    if req_files and isinstance(req_files, list):
        input_data["__files__"] = req_files

    is_stream = response_mode in ("streaming", "stream")

    logger.info(f"API request: workflow={workflow_id}, mode={response_mode}, conversation_id={thread_id}, is_stream={is_stream}")

    context = WorkflowContext(
        thread_id=thread_id,
        user_id=user_id,
        request_stream=is_stream,
        from_channel=False if public_mode else bool(body.get("from_channel")),
        disable_confirm_tool=True if public_mode else bool(body.get("disable_confirm_tool")),
        tool_confirmation_required=False if public_mode else bool(body.get("tool_confirmation_required")),
        tool_confirmation_level="off" if public_mode else str(body.get("tool_confirmation_level") or ("high" if body.get("tool_confirmation_required") else "off")),
    )
    context.workflow_id = workflow_id
    context.user_input_field = user_input_field

    # 从 inputs 中读取 model，作为本次请求的模型选择。
    # 仅影响未显式指定 model_id 的 LLM 节点，避免修改全局 _current_model_id 泄漏到后续请求。
    selected_model = None if public_mode else input_data.get("model")
    if selected_model:
        if hasattr(workflow, '_ensure_components'):
            workflow._ensure_components()
        mgr = getattr(workflow, '_llm_manager', None)
        # 解包 TracedLLMManager，读取底层 LLMManager 配置
        if hasattr(mgr, 'llm_manager'):
            mgr = mgr.llm_manager
        if mgr:
            selected_config = mgr._models_cache.get(selected_model)
            selected_type = str(getattr(selected_config, "model_type", "chat") or "chat").lower()
            if selected_config and selected_type not in NON_CONVERSATION_MODEL_TYPES:
                context.runtime_model_id = selected_model
                logger.info(f"请求级模型选择: {selected_model}")
            elif selected_config:
                logger.warning(f"模型 '{selected_model}' 类型为 {selected_type}，不能用于对话模型切换")
            else:
                logger.warning(f"模型 '{selected_model}' 不在配置中, 可用: {list(mgr._models_cache.keys())}")

    if is_stream:
        return StreamingResponse(
            _stream_workflow(workflow, input_data, context, thread_id),
            media_type="text/event-stream",
        )

    # Blocking mode
    start_time = time.perf_counter()
    task_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    channel = OutputChannel(
        workflow_id=workflow_id,
        thread_id=thread_id,
        stream_mode=False,
    )
    channel.task_id = task_id
    channel.message_id = message_id

    try:
        _output_channel_var.set(channel)

        result = await workflow.run(
            inputs=input_data,
            context=context,
            thread_id=thread_id if thread_id else None,
        )

        state = result.get("state", {})
        metadata = result.get("metadata", {})

        answer = channel.get_answer()
        if not answer:
            messages = state.get("__messages__") or []
            new_messages = messages[channel._pre_run_msg_count :]
            for msg in reversed(new_messages):
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    answer = msg.get("content", "")
                    break

        is_interrupted = state.get("__interrupted__", False)
        status = state.get("__status__", "completed")
        confirmation = channel.confirmation_requests[-1] if channel.confirmation_requests else None
        confirmation_payload = None
        if confirmation:
            status = "confirmation_required"
            confirmation_payload = {
                "confirm_id": confirmation.get("confirm_id"),
                "action": confirmation.get("action"),
                "description": confirmation.get("description", ""),
                "require_sudo": bool(confirmation.get("require_sudo")),
                "api": f"/api/confirm/{confirmation.get('confirm_id')}",
                "method": "POST",
                "request": {"approved": True, "sudo_password": "<required-if-require_sudo>" if confirmation.get("require_sudo") else None},
            }
        latency = time.perf_counter() - start_time
        usage = channel.get_usage()

        return JSONResponse(
            content=WorkflowRunResponse(
                event="message",
                task_id=task_id,
                id=message_id,
                message_id=message_id,
                conversation_id=thread_id or metadata.get("thread_id"),
                mode="workflow",
                answer=answer or "",
                metadata=WorkflowRunMetadata(
                    usage=UsageInfo(
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                        latency=latency,
                    ),
                    trace_id=metadata.get("trace_id"),
                    interrupted=is_interrupted,
                    status=status,
                    confirmation_required=bool(confirmation_payload),
                    confirmation=confirmation_payload,
                ),
                created_at=int(time.time()),
            ).model_dump()
        )

    except Exception as e:
        import traceback

        error_detail = traceback.format_exc()
        logger.error(f"Workflow execution failed: {e}\n{error_detail}")
        return JSONResponse(
            status_code=500,
            content=WorkflowRunError(
                task_id=task_id,
                message_id=message_id,
                code=ErrorCode.WORKFLOW_EXECUTION_ERROR,
                message=str(e),
            ).model_dump(),
        )
    finally:
        _output_channel_var.set(None)


@router.post(
    "/confirm/{confirm_id}",
    response_model=ConfirmActionResponse,
    summary="Confirm action",
    description="Approve or reject a dangerous operation requested by the agent",
    responses={404: {"description": "Confirmation not found or already resolved"}},
    dependencies=[Depends(require_admin_auth)],
)
async def confirm_action(confirm_id: str, req: ConfirmActionRequest):
    """
    Confirm or reject a dangerous operation.

    The frontend receives a `confirm_request` SSE event, then calls this
    endpoint when the user approves or rejects.

    If require_sudo=true, the frontend should include sudo_password in the request.
    """
    from agentclaw.api.services.confirm_service import get_confirmation_manager

    manager = get_confirmation_manager()

    # 获取确认对象以检查是否需要 sudo
    confirmation = manager.get(confirm_id)
    if not confirmation:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"Confirmation '{confirm_id}' not found or already resolved"
            },
        )

    require_sudo = confirmation.require_sudo
    sudo_received = bool(req.sudo_password) if require_sudo else False

    if manager.resolve(confirm_id, req.approved, req.sudo_password):
        return ConfirmActionResponse(
            success=True,
            confirm_id=confirm_id,
            approved=req.approved,
            require_sudo=require_sudo,
            sudo_received=sudo_received,
            status="resolved",
            message="approved" if req.approved else "rejected",
        )
    else:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"Confirmation '{confirm_id}' not found or already resolved"
            },
        )


@router.get(
    "/download/{token}",
    summary="Download file",
    description="Download a file via temporary token (generated by download-tools MCP server)",
    responses={
        404: {"description": "File not found or link expired"},
        503: {"description": "Redis not available"},
    },
)
async def download_file(token: str):
    """
    Temporary file download endpoint.

    The download MCP server stores files in Redis and generates tokens.
    The frontend downloads files via this endpoint.
    """
    import base64

    from agentclaw.database import get_database

    db = get_database()
    if not db or not db.is_redis_available():
        return JSONResponse(status_code=503, content={"error": "Redis not available"})

    try:
        client = await db.get_redis_client()
        if not client:
            return JSONResponse(status_code=503, content={"error": "Redis client unavailable"})

        key = f"download:{token}"
        data = await client.hgetall(key)
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": f"Redis error: {e}"})

    if not data:
        return JSONResponse(
            status_code=404, content={"error": "File not found or link expired"}
        )

    content_b64 = data.get("content")
    filename = data.get("filename", "file")
    content_type = data.get("content_type", "application/octet-stream")

    try:
        content = base64.b64decode(content_b64)
    except Exception:
        return JSONResponse(
            status_code=500, content={"error": "Failed to decode file content"}
        )

    from agentclaw.api.files.response import file_response_headers
    from starlette.responses import Response

    return Response(
        content=content,
        media_type=content_type,
        headers=file_response_headers(filename, content_type),
    )


@router.post(
    "/workflow/compress",
    summary="Compress context",
    description="Compress conversation context for a workflow session",
    responses={
        401: {"description": "Unauthorized - invalid API key"},
        404: {"description": "Workflow or conversation not found"},
        500: {"description": "Compression error"},
    },
)
async def compress_context(request: Request):
    """
    Compress conversation context.

    Loads messages from the checkpoint for the given workflow_id + conversation_id,
    runs context compression, and saves the compressed messages back.

    Requires Authorization: Bearer {api_key} header.
    """
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.runtime.context_compressor import ContextCompressor

    try:
        await authenticate_bearer(request)
    except HTTPException:
        return authentication_failed_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON body", "code": ErrorCode.INVALID_JSON},
        )

    workflow_id = body.get("workflow_id")
    if not workflow_id:
        return JSONResponse(
            status_code=400,
            content={"error": "workflow_id is required", "code": ErrorCode.INVALID_REQUEST},
        )

    conversation_id = body.get("conversation_id")
    if not conversation_id:
        return JSONResponse(
            status_code=400,
            content={"error": "conversation_id is required", "code": ErrorCode.INVALID_REQUEST},
        )

    workflow = WorkflowRegistry.get(workflow_id)
    if not workflow:
        return JSONResponse(
            status_code=404,
            content={"error": f"Workflow '{workflow_id}' not found", "code": ErrorCode.WORKFLOW_NOT_FOUND},
        )

    # Ensure checkpointer is ready
    await workflow._ensure_checkpointer()
    if not workflow._checkpointer:
        return JSONResponse(
            status_code=500,
            content={"error": "Checkpointer not available", "code": ErrorCode.OPERATION_FAILED},
        )

    # Get compiled graph and load state
    try:
        compiled_graph = workflow._compile_to_langgraph()
        if not compiled_graph:
            return JSONResponse(
                status_code=500,
                content={"error": "Failed to compile workflow graph", "code": ErrorCode.OPERATION_FAILED},
            )

        config = {"configurable": {"thread_id": conversation_id}}
        snapshot = await compiled_graph.aget_state(config)

        if not snapshot or not snapshot.values:
            return JSONResponse(
                status_code=404,
                content={
                    "error": f"No conversation state found for conversation_id '{conversation_id}'",
                    "code": ErrorCode.NOT_FOUND,
                },
            )

        messages = list(snapshot.values.get("__messages__") or [])
        if not messages:
            return JSONResponse(
                content=ContextCompressResponse(
                    success=True,
                    workflow_id=workflow_id,
                    conversation_id=conversation_id,
                    compressed=False,
                ).model_dump()
            )

        # Run compression
        if hasattr(workflow, '_ensure_components'):
            workflow._ensure_components()
        llm_manager = getattr(workflow, '_llm_manager', None)

        compressor = ContextCompressor()
        compressed_msgs, info = await compressor.compress(messages, llm_manager=llm_manager)

        if not info.get("compressed"):
            return JSONResponse(
                content=ContextCompressResponse(
                    success=True,
                    workflow_id=workflow_id,
                    conversation_id=conversation_id,
                    compressed=False,
                ).model_dump()
            )

        # Save compressed messages back to checkpoint
        # Use RemoveMessage(id=REMOVE_ALL_MESSAGES) to clear old messages first,
        # since add_messages reducer appends by default instead of replacing.
        from langchain_core.messages import RemoveMessage
        from langgraph.graph.message import REMOVE_ALL_MESSAGES

        await compiled_graph.aupdate_state(
            config,
            {"__messages__": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *compressed_msgs]},
        )
        logger.info(f"Context compressed: workflow={workflow_id}, conversation={conversation_id}, {info}")

        # Extract summary text from compressed messages
        summary_text = ""
        for msg in compressed_msgs:
            if msg.get("is_summary"):
                summary_text = msg.get("content", "")
                break

        memory_result = None
        try:
            from agentclaw.config import get_config
            from agentclaw.memory import append_context_summary_to_workflow_memory

            memory_text = await compressor.generate_memory_update(summary_text, llm_manager=llm_manager)
            if memory_text.strip():
                memory_result = append_context_summary_to_workflow_memory(
                    get_config().project.project_dir,
                    workflow_id,
                    memory_text,
                )
                logger.info(
                    "Context compression memory updated: workflow=%s, path=%s",
                    workflow_id,
                    memory_result.get("path"),
                )
        except Exception as e:
            logger.warning(f"Failed to update workflow memory after compression: {e}")

        # Sync compressed state to database conversation (best-effort)
        try:
            from agentclaw.api.services.conversation_service import get_conversation_service
            import time as _time

            service = get_conversation_service()
            conv = await service.get_conversation(workflow_id, conversation_id)
            if conv and conv.get("messages"):
                db_messages = conv["messages"]

                # Mark all existing messages as compressed_out
                for msg in db_messages:
                    msg["compressed_out"] = True

                # Append summary message
                db_messages.append({
                    "role": "assistant",
                    "content": summary_text,
                    "timestamp": int(_time.time() * 1000),
                    "is_summary": True,
                    "original_message_count": info.get("compressed_message_count", 0),
                })

                await service.update_conversation(
                    workflow_id, conversation_id, messages=db_messages
                )
                logger.info(f"Conversation messages synced after compression: {conversation_id}")
        except Exception as e:
            logger.warning(f"Failed to sync conversation messages after compression: {e}")

        return JSONResponse(
            content=ContextCompressResponse(
                success=True,
                workflow_id=workflow_id,
                conversation_id=conversation_id,
                compressed=True,
                original_count=info.get("original_count", 0),
                compressed_count=info.get("compressed_count", 0),
                compressed_message_count=info.get("compressed_message_count", 0),
                summary_length=info.get("summary_length", 0),
                summary=summary_text,
                has_system=info.get("has_system", False),
                has_welcome=info.get("has_welcome", False),
                used_llm=info.get("used_llm", False),
                context_tokens=info.get("context_tokens", 0),
                memory_updated=bool(memory_result and memory_result.get("changed")),
                memory_path=str(memory_result.get("path", "")) if memory_result else "",
            ).model_dump()
        )

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        logger.error(f"Context compression failed: {e}\n{error_detail}")
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Context compression failed: {e}",
                "code": ErrorCode.OPERATION_FAILED,
            },
        )


async def _stream_workflow(workflow, data: dict, context, thread_id: Optional[str] = None):
    """
    Stream workflow execution (Dify-format SSE).

    Event stream:
    - workflow_started
    - node_started / node_finished (per node)
    - message (LLM streaming tokens)
    - message_end
    - tool_call (tool invocations)
    - confirm_request (dangerous operation confirmation)
    - workflow_finished
    - error
    """
    from agentclaw.runtime.streaming.context import OutputChannel, _output_channel_var
    from agentclaw.runtime.sse import sse_format
    from agentclaw.exceptions import WorkflowCancelledError
    from agentclaw.api.server import TaskManager
    import asyncio
    import uuid

    task_id = str(uuid.uuid4())
    task_manager = TaskManager.get_instance()

    logger.info(f"Starting streaming workflow: workflow_id={workflow.id}, task_id={task_id}, thread_id={thread_id}")

    channel = OutputChannel(
        workflow_id=workflow.id,
        thread_id=thread_id or "",
        task_id=task_id,
        stream_mode=True,
    )

    logger.debug(f"OutputChannel created: stream_mode=True, task_id={task_id}")

    async with channel:
        await channel.push_workflow_started()
        _output_channel_var.set(channel)

        async def run_workflow():
            try:
                logger.info(f"Workflow execution started: {workflow.id}")
                result = await workflow.run(
                    inputs=data,
                    context=context,
                    stream=False,
                    thread_id=thread_id if thread_id else None,
                )

                logger.info(f"Workflow execution completed: {workflow.id}")
                logger.debug(f"Workflow result metadata: {result.get('metadata', {})}")

                state = result.get("state", {})
                metadata = result.get("metadata", {})

                answer = channel.get_answer()
                if not answer:
                    messages = state.get("__messages__") or []
                    new_messages = messages[channel._pre_run_msg_count :]
                    for msg in reversed(new_messages):
                        if isinstance(msg, dict) and msg.get("role") == "assistant":
                            answer = msg.get("content", "")
                            break

                is_interrupted = state.get("__interrupted__", False)
                outputs = {
                    "answer": answer,
                    "conversation_id": thread_id,
                    "trace_id": metadata.get("trace_id"),
                    "interrupted": is_interrupted,
                }
                # 转发中断元信息（含 approval_mode 等）
                interrupt_info = state.get("__interrupt_info__")
                if interrupt_info and isinstance(interrupt_info, dict):
                    outputs["interrupt_info"] = interrupt_info
                next_input_info = state.get("next_input_info")
                if next_input_info and isinstance(next_input_info, dict):
                    outputs["next_input_info"] = next_input_info
                await channel.push_workflow_finished(
                    status="interrupted" if is_interrupted else "succeeded",
                    outputs=outputs,
                )

            except WorkflowCancelledError as e:
                logger.info(f"Workflow cancelled: {e}")
                try:
                    await channel.push_workflow_finished(
                        status="cancelled",
                        error=str(e),
                        outputs={"cancelled": True},
                    )
                except Exception:
                    pass

            except asyncio.CancelledError:
                logger.info(f"Workflow task cancelled: {task_id}")
                try:
                    await channel.push_workflow_finished(
                        status="cancelled",
                        error="User cancelled",
                        outputs={"cancelled": True},
                    )
                except Exception:
                    pass

            except Exception as e:
                import traceback

                error_msg = f"{e}\n{traceback.format_exc()}"
                logger.error(f"Workflow execution failed: {error_msg}")
                await channel._push_error(str(e))
                await channel.push_workflow_finished(status="failed", error=str(e))
            finally:
                try:
                    await channel.finish()
                except Exception:
                    pass
                await task_manager.unregister(task_id)

        task = asyncio.create_task(run_workflow())

        await task_manager.register(
            task_id=task_id,
            task=task,
            cancel_token=context.cancel_token if context else None,
            workflow_id=workflow.id,
            thread_id=thread_id,
        )

        try:
            # 使用超时轮询，以便在 task 被取消时能及时退出
            while True:
                if task.done():
                    # task 已结束，排空剩余事件后退出
                    while not channel.queue.empty():
                        event = channel.queue.get_nowait()
                        if event is None:
                            break
                        yield sse_format(event)
                    break
                try:
                    event = await asyncio.wait_for(channel.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if event is None:
                    break
                event_type = event.get("event", "unknown")
                logger.debug(f"SSE event: type={event_type}, task_id={task_id}")
                if event_type == "message_end":
                    logger.info(f"SSE message_end event: metadata={event.get('metadata', {})}")
                yield sse_format(event)
        finally:
            if not task.done():
                task.cancel()
                try:
                    await asyncio.shield(task)
                except (asyncio.CancelledError, Exception):
                    pass
            await task_manager.unregister(task_id)


@router.post(
    "/workflow/truncate",
    summary="Truncate conversation messages",
    description="Truncate conversation __messages__ to a specified count (for edit-and-retry)",
    dependencies=[Depends(require_admin_auth)],
)
async def truncate_messages(request: Request):
    """
    截断会话消息到指定数量，用于编辑重发场景。

    找到第 keep_count 条用户消息对应的位置，保留该消息之前的所有 __messages__。
    keep_count=0 表示清空所有消息（回退到开场白）。
    """
    from agentclaw.api.registry import WorkflowRegistry

    body = await request.json()
    workflow_id = body.get("workflow_id")
    conversation_id = body.get("conversation_id")
    keep_count = body.get("keep_count", 0)

    if not workflow_id or not conversation_id:
        return JSONResponse(
            status_code=400,
            content={"error": "workflow_id and conversation_id are required"},
        )

    workflow = WorkflowRegistry.get(workflow_id)
    if not workflow:
        return JSONResponse(
            status_code=404,
            content={"error": f"Workflow '{workflow_id}' not found"},
        )

    await workflow._ensure_checkpointer()
    if not workflow._checkpointer:
        return JSONResponse(
            status_code=500,
            content={"error": "Checkpointer not available"},
        )

    try:
        compiled_graph = workflow._compile_to_langgraph()
        if not compiled_graph:
            return JSONResponse(
                status_code=500,
                content={"error": "Failed to compile workflow graph"},
            )

        config = {"configurable": {"thread_id": conversation_id}}
        snapshot = await compiled_graph.aget_state(config)

        if not snapshot or not snapshot.values:
            return JSONResponse(
                status_code=404,
                content={"error": f"No conversation state found for '{conversation_id}'"},
            )

        messages = list(snapshot.values.get("__messages__") or [])

        if keep_count <= 0:
            truncated = []
        else:
            # 找到第 keep_count 条用户消息的位置，保留其之前的所有消息
            user_msg_count = 0
            cut_index = 0
            for i, msg in enumerate(messages):
                role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "type", "")
                if role in ("user", "human"):
                    user_msg_count += 1
                    if user_msg_count >= keep_count:
                        cut_index = i
                        break
            else:
                return JSONResponse(content={"success": True, "truncated": False, "message_count": len(messages)})

            truncated = messages[:cut_index]

        from langchain_core.messages import RemoveMessage
        from langgraph.graph.message import REMOVE_ALL_MESSAGES

        await compiled_graph.aupdate_state(
            config,
            {"__messages__": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *truncated]},
        )

        logger.info(f"Messages truncated: workflow={workflow_id}, conversation={conversation_id}, "
                     f"original={len(messages)}, remaining={len(truncated)}, keep_count={keep_count}")

        return JSONResponse(content={"success": True, "truncated": True, "message_count": len(truncated)})

    except Exception as e:
        logger.error(f"Truncate messages failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

"""Public multi-user room routes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agentclaw.api.routers.public.access import (
    check_public_rate_limit,
    forbidden_response,
    verify_public_share_token,
    workflow_not_found_response,
)
from agentclaw.api.routers.public.execution import (
    _normalize_user_and_inputs,
    _public_input_size_error,
    _public_request_body_error,
)
from agentclaw.api.routers.public.session import (
    PUBLIC_SESSION_COOKIE,
    PUBLIC_SESSION_TTL_SECONDS,
    create_public_session,
    ensure_public_user_id,
    is_same_origin_public_page_request,
    public_cookie_secure,
    public_owner_id_from_request,
    public_runtime_thread_id,
    set_public_user_cookie,
    verify_public_session_cookie,
    verify_public_page_session,
)
from agentclaw.api.schemas.common import ErrorCode
from agentclaw.api.schemas.public_room import (
    PublicRoomChatSendRequest,
    PublicRoomCreateRequest,
    PublicRoomJoinRequest,
    PublicRoomTypingRequest,
)
from agentclaw.api.services.public_room_chat_service import get_public_room_chat_service
from agentclaw.api.services.public_room_service import (
    PUBLIC_ROOM_BUSY,
    PUBLIC_ROOM_INFRA_ERROR,
    PublicRoomAccessError,
    PublicRoomBusyError,
    PublicRoomInfraError,
    get_public_room_service,
    public_room_owner_id,
)
from agentclaw.runtime.sse import sse_format


router = APIRouter(tags=["public-rooms"])


def public_room_chat_list_rate_limit() -> str:
    return os.getenv("AGENTCLAW_PUBLIC_ROOM_CHAT_LIST_RATE_LIMIT", "120/min").strip()


def public_room_chat_send_rate_limit() -> str:
    return os.getenv("AGENTCLAW_PUBLIC_ROOM_CHAT_SEND_RATE_LIMIT", "30/min").strip()


def _service_error_response(error: Exception) -> JSONResponse:
    if isinstance(error, PublicRoomInfraError):
        return JSONResponse(
            status_code=503,
            content={"error": str(error), "code": PUBLIC_ROOM_INFRA_ERROR},
        )
    if isinstance(error, PublicRoomBusyError):
        return JSONResponse(
            status_code=409,
            content={
                "error": "Public room is busy",
                "code": PUBLIC_ROOM_BUSY,
                "running_nickname": error.running_nickname,
            },
        )
    if isinstance(error, PublicRoomAccessError):
        return forbidden_response(str(error))
    if isinstance(error, ValueError):
        return JSONResponse(
            status_code=400,
            content={"error": str(error), "code": ErrorCode.INVALID_REQUEST},
        )
    return JSONResponse(status_code=500, content={"error": str(error), "code": ErrorCode.UNKNOWN_ERROR})


def _get_workflow(workflow_id: str) -> Any:
    from agentclaw.api.registry import WorkflowRegistry

    return WorkflowRegistry.get(workflow_id)


def _public_room_stream_event(room_id: str, event: dict[str, Any], *, participant: dict[str, Any] | None = None) -> dict[str, Any] | None:
    event_type = str(event.get("event") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    base = {
        "room_id": room_id,
        "task_id": event.get("task_id"),
        "run_id": event.get("workflow_run_id") or data.get("id"),
        "message_id": event.get("message_id") or event.get("id"),
    }
    if event_type == "workflow_started":
        return {
            **base,
            "event": "agent_run_started",
            "running_nickname": (participant or {}).get("nickname") or "",
        }
    if event_type == "node_started":
        node_id = str(data.get("node_id") or data.get("node") or "").strip()
        if not node_id:
            return None
        return {
            **base,
            "event": "agent_node_started",
            "node_id": node_id,
            "title": str(data.get("title") or node_id),
            "node_type": str(data.get("node_type") or data.get("type") or "unknown"),
            "parallel_group_id": data.get("parallel_group_id"),
        }
    if event_type == "node_finished":
        node_id = str(data.get("node_id") or data.get("node") or "").strip()
        if not node_id:
            return None
        return {
            **base,
            "event": "agent_node_finished",
            "node_id": node_id,
            "status": str(data.get("status") or "succeeded"),
            "elapsed_time": data.get("elapsed_time"),
            "parallel_group_id": data.get("parallel_group_id"),
            "error": str(data.get("error") or "") if data.get("error") else "",
        }
    if event_type == "message":
        delta = str(event.get("answer") or event.get("content") or "")
        if not delta:
            return None
        return {
            **base,
            "event": "agent_message_delta",
            "delta": delta,
        }
    if event_type == "workflow_finished":
        return {
            **base,
            "event": "agent_run_finished",
            "status": data.get("status") or "succeeded",
        }
    if event_type == "error":
        return {
            **base,
            "event": "agent_run_failed",
            "error": str(event.get("message") or data.get("error") or "Workflow execution failed"),
        }
    return None


def _public_workflow_payload(workflow: Any, workflow_id: str) -> dict[str, Any]:
    from agentclaw.api.routers.public.execution import _public_workflow_payload as payload

    return payload(workflow, workflow_id)


def _require_public_page_owner(request: Request, workflow_id: str) -> tuple[str, JSONResponse | None]:
    if not verify_public_page_session(request, workflow_id):
        return "", forbidden_response("Public room access requires a same-origin public page session")
    owner_id = public_owner_id_from_request(request)
    if not owner_id:
        return "", forbidden_response("Public room access requires an anonymous public user")
    return owner_id, None


def _require_public_event_owner(request: Request, workflow_id: str) -> tuple[str, JSONResponse | None]:
    if not is_same_origin_public_page_request(request) or not verify_public_session_cookie(request, workflow_id):
        return "", forbidden_response("Public room event stream requires a same-origin public page session")
    owner_id = public_owner_id_from_request(request)
    if not owner_id:
        return "", forbidden_response("Public room event stream requires an anonymous public user")
    return owner_id, None


async def _room_and_member_or_error(room_id: str, request: Request):
    service = get_public_room_service()
    try:
        room = await service.get_room(room_id)
        if not room:
            return None, None, JSONResponse(status_code=404, content={"error": "Public room not found", "code": ErrorCode.NOT_FOUND})
        owner_id, owner_error = _require_public_page_owner(request, room["workflow_id"])
        if owner_error:
            return None, None, owner_error
        participant = await service.require_member(room_id, owner_id)
        return room, participant, None
    except Exception as exc:
        return None, None, _service_error_response(exc)


async def _room_and_event_member_or_error(room_id: str, request: Request):
    service = get_public_room_service()
    try:
        room = await service.get_room(room_id)
        if not room:
            return None, None, JSONResponse(status_code=404, content={"error": "Public room not found", "code": ErrorCode.NOT_FOUND})
        owner_id, owner_error = _require_public_event_owner(request, room["workflow_id"])
        if owner_error:
            return None, None, owner_error
        participant = await service.require_member(room_id, owner_id)
        return room, participant, None
    except Exception as exc:
        return None, None, _service_error_response(exc)


@router.post("/public/workflows/{workflow_id}/rooms", summary="Create a public multi-user room")
async def create_public_room(workflow_id: str, request: Request, req: PublicRoomCreateRequest):
    workflow = _get_workflow(workflow_id)
    if not workflow:
        return workflow_not_found_response(workflow_id)
    share_error = verify_public_share_token(workflow, workflow_id, request, allow_square_public=True)
    if share_error:
        return share_error
    owner_id, owner_error = _require_public_page_owner(request, workflow_id)
    if owner_error:
        return owner_error
    rate_error = check_public_rate_limit(workflow, workflow_id, request, "room-create")
    if rate_error:
        return rate_error
    try:
        result = await get_public_room_service().create_room(workflow_id, owner_id, req.nickname)
        return result
    except Exception as exc:
        return _service_error_response(exc)


@router.post("/public/rooms/{room_id}/session", summary="Open a public room page session")
async def open_public_room_session(room_id: str, request: Request):
    service = get_public_room_service()
    try:
        if not is_same_origin_public_page_request(request):
            return forbidden_response("Public room sessions must be opened from the same-origin public page")
        room = await service.get_room(room_id)
        if not room:
            return JSONResponse(status_code=404, content={"error": "Public room not found", "code": ErrorCode.NOT_FOUND})
        room_token = request.headers.get("x-agentclaw-room-token", "")
        if not await service.verify_room_token(room_id, room_token):
            return forbidden_response("Public room token is required")
        workflow = _get_workflow(room["workflow_id"])
        if not workflow:
            return workflow_not_found_response(room["workflow_id"])

        public_user_id, _new_user = ensure_public_user_id(request)
        token, expires_at = create_public_session(room["workflow_id"])
        response = JSONResponse(content={"ok": True, "expires_at": expires_at})
        response.set_cookie(
            PUBLIC_SESSION_COOKIE,
            token,
            max_age=PUBLIC_SESSION_TTL_SECONDS,
            httponly=True,
            samesite="strict",
            secure=public_cookie_secure(request),
            path="/api",
        )
        set_public_user_cookie(response, request, public_user_id)
        return response
    except Exception as exc:
        return _service_error_response(exc)


@router.get("/public/rooms/{room_id}/bootstrap", summary="Bootstrap a public room")
async def bootstrap_public_room(room_id: str, request: Request):
    service = get_public_room_service()
    try:
        room = await service.get_room(room_id)
        if not room:
            return JSONResponse(status_code=404, content={"error": "Public room not found", "code": ErrorCode.NOT_FOUND})
        if not verify_public_page_session(request, room["workflow_id"]):
            return forbidden_response("Public room access requires a same-origin public page session")
        room_token = request.headers.get("x-agentclaw-room-token", "")
        if not await service.verify_room_token(room_id, room_token):
            return forbidden_response("Public room token is required")
        owner_id = public_owner_id_from_request(request)
        joined = False
        if owner_id:
            try:
                await service.require_member(room_id, owner_id)
                joined = True
            except PublicRoomAccessError:
                joined = False
        workflow = _get_workflow(room["workflow_id"])
        if not workflow:
            return workflow_not_found_response(room["workflow_id"])
        return {
            "workflow": _public_workflow_payload(workflow, room["workflow_id"]),
            "room": service.public_room_payload(room),
            "joined": joined,
        }
    except Exception as exc:
        return _service_error_response(exc)


@router.post("/public/rooms/{room_id}/join", summary="Join a public room")
async def join_public_room(room_id: str, request: Request, req: PublicRoomJoinRequest):
    service = get_public_room_service()
    try:
        room = await service.get_room(room_id)
        if not room:
            return JSONResponse(status_code=404, content={"error": "Public room not found", "code": ErrorCode.NOT_FOUND})
        owner_id, owner_error = _require_public_page_owner(request, room["workflow_id"])
        if owner_error:
            return owner_error
        room_token = request.headers.get("x-agentclaw-room-token", "")
        if not await service.verify_room_token(room_id, room_token):
            return forbidden_response("Public room token is required")
        await service.join_room(room_id, owner_id, req.nickname)
        return await service.get_state(room_id, owner_id, since_version=None)
    except Exception as exc:
        return _service_error_response(exc)


@router.get("/public/rooms/{room_id}/state", summary="Get public room state")
async def get_public_room_state(room_id: str, request: Request, since_version: int | None = None):
    service = get_public_room_service()
    try:
        room, participant, access_error = await _room_and_member_or_error(room_id, request)
        if access_error:
            return access_error
        return await service.get_state(room_id, participant["owner_id"], since_version=since_version)
    except Exception as exc:
        return _service_error_response(exc)


@router.get("/public/rooms/{room_id}/events", summary="Stream public room events")
async def stream_public_room_events(room_id: str, request: Request):
    service = get_public_room_service()
    try:
        room, participant, access_error = await _room_and_event_member_or_error(room_id, request)
        if access_error:
            return access_error

        async def event_stream():
            await service.touch_member(room_id, participant["owner_id"])
            async for event in service.iter_room_events(room_id):
                if await request.is_disconnected():
                    break
                yield sse_format(event)

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    except Exception as exc:
        return _service_error_response(exc)


@router.post("/public/rooms/{room_id}/typing", summary="Update public room typing status")
async def set_public_room_typing(room_id: str, request: Request, req: PublicRoomTypingRequest):
    service = get_public_room_service()
    try:
        room, participant, access_error = await _room_and_member_or_error(room_id, request)
        if access_error:
            return access_error
        await service.set_typing(room_id, participant["owner_id"], req.typing)
        return {"ok": True}
    except Exception as exc:
        return _service_error_response(exc)


@router.get("/public/rooms/{room_id}/chat", summary="List public room player chat messages")
async def list_public_room_chat(room_id: str, request: Request, after_id: str = "", limit: int = 100):
    try:
        room, participant, access_error = await _room_and_member_or_error(room_id, request)
        if access_error:
            return access_error
        workflow = _get_workflow(room["workflow_id"])
        if not workflow:
            return workflow_not_found_response(room["workflow_id"])
        rate_error = check_public_rate_limit(
            workflow,
            room["workflow_id"],
            request,
            "room-chat-list",
            public_room_chat_list_rate_limit(),
        )
        if rate_error:
            return rate_error
        messages = await get_public_room_chat_service().list_messages(room_id, after_id=after_id, limit=limit)
        return {"messages": messages}
    except Exception as exc:
        return _service_error_response(exc)


@router.post("/public/rooms/{room_id}/chat", summary="Send a public room player chat message")
async def send_public_room_chat(room_id: str, request: Request, req: PublicRoomChatSendRequest):
    try:
        room, participant, access_error = await _room_and_member_or_error(room_id, request)
        if access_error:
            return access_error
        workflow = _get_workflow(room["workflow_id"])
        if not workflow:
            return workflow_not_found_response(room["workflow_id"])
        rate_error = check_public_rate_limit(
            workflow,
            room["workflow_id"],
            request,
            "room-chat-send",
            public_room_chat_send_rate_limit(),
        )
        if rate_error:
            return rate_error
        return await get_public_room_chat_service().send_message(
            room_id,
            participant["owner_id"],
            participant["nickname"],
            req.content,
        )
    except Exception as exc:
        return _service_error_response(exc)


@router.post("/public/rooms/{room_id}/run", summary="Run workflow in a public room")
async def run_public_room(room_id: str, request: Request):
    import asyncio
    import time
    import uuid

    from agentclaw.api.schemas.execution import (
        UsageInfo,
        WorkflowRunMetadata,
        WorkflowRunResponse,
    )
    from agentclaw.graph.context import WorkflowContext
    from agentclaw.runtime.streaming.context import OutputChannel, _output_channel_var

    service = get_public_room_service()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body", "code": ErrorCode.INVALID_JSON})
    body_error = _public_request_body_error(body)
    if body_error:
        return JSONResponse(status_code=413, content=body_error)
    try:
        room, participant, access_error = await _room_and_member_or_error(room_id, request)
        if access_error:
            return access_error
        workflow = _get_workflow(room["workflow_id"])
        if not workflow:
            return workflow_not_found_response(room["workflow_id"])
        rate_error = check_public_rate_limit(workflow, room["workflow_id"], request, "room-run")
        if rate_error:
            return rate_error

        user_value = body.get("user")
        input_data = body.get("inputs")
        if input_data is None:
            input_data = body.get("input_data")
        if input_data is None:
            input_data = {}
        if not isinstance(input_data, dict):
            return JSONResponse(status_code=400, content={"error": "'inputs' must be an object", "code": ErrorCode.INVALID_REQUEST})
        user_input_field = workflow.get_user_input_field()
        input_data, normalize_error = _normalize_user_and_inputs(
            user_value=user_value,
            input_data=input_data,
            user_input_field=user_input_field,
        )
        if normalize_error:
            return JSONResponse(status_code=400, content=normalize_error)
        input_data = input_data or {}
        input_data["__public_room__"] = {
            "room_id": room_id,
            "nickname": participant["nickname"],
        }
        size_error = _public_input_size_error(user_value=user_value, input_data=input_data)
        if size_error:
            return JSONResponse(status_code=413, content=size_error)
        if "files" in body:
            return JSONResponse(status_code=400, content={"error": "File attachments are not supported for anonymous public workflow runs", "code": ErrorCode.INVALID_REQUEST})

        await service.acquire_run_lock(room_id, participant["owner_id"], participant["nickname"])
        await service.set_typing(room_id, participant["owner_id"], False)
        user_text = str(user_value or input_data.get(user_input_field) or "")
        if user_text:
            await service.append_user_message(room_id, participant["owner_id"], user_text)

        runtime_thread_id = public_runtime_thread_id(
            room["workflow_id"],
            public_room_owner_id(room_id),
            room["conversation_id"],
        )
        context = WorkflowContext(
            thread_id=runtime_thread_id,
            user_id=None,
            request_stream=True,
            from_channel=False,
            public_mode=True,
            disable_confirm_tool=True,
            tool_confirmation_required=False,
            tool_confirmation_level="off",
        )
        context.workflow_id = room["workflow_id"]
        context.user_input_field = user_input_field
        start_time = time.perf_counter()
        task_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        channel = OutputChannel(
            workflow_id=room["workflow_id"],
            thread_id=runtime_thread_id,
            stream_mode=True,
        )
        channel.task_id = task_id
        channel.message_id = message_id
        try:
            async def run_workflow():
                token = _output_channel_var.set(channel)
                try:
                    await channel.push_workflow_started()
                    return await workflow.run(inputs=input_data, context=context, thread_id=runtime_thread_id)
                finally:
                    try:
                        await channel.finish()
                    finally:
                        _output_channel_var.reset(token)

            workflow_task = asyncio.create_task(run_workflow())
            result = None
            safe_node_steps: list[dict[str, Any]] = []
            safe_node_step_index: dict[str, int] = {}

            def remember_safe_node_step(room_event: dict[str, Any] | None) -> None:
                if not room_event:
                    return
                event_name = room_event.get("event")
                node_id = str(room_event.get("node_id") or "").strip()
                if not node_id:
                    return
                if event_name == "agent_node_started":
                    if node_id in safe_node_step_index:
                        safe_node_steps[safe_node_step_index[node_id]]["status"] = "running"
                        return
                    node_type = str(room_event.get("node_type") or "unknown")
                    safe_node_step_index[node_id] = len(safe_node_steps)
                    safe_node_steps.append(
                        {
                            "id": node_id,
                            "name": str(room_event.get("title") or node_id),
                            "type": node_type,
                            "typeLabel": node_type,
                            "status": "running",
                            "elapsed_time": None,
                            "parallelGroupId": room_event.get("parallel_group_id"),
                        }
                    )
                    return
                if event_name == "agent_node_finished":
                    if node_id not in safe_node_step_index:
                        safe_node_step_index[node_id] = len(safe_node_steps)
                        safe_node_steps.append(
                            {
                                "id": node_id,
                                "name": node_id,
                                "type": "unknown",
                                "typeLabel": "unknown",
                                "status": "running",
                                "elapsed_time": None,
                                "parallelGroupId": room_event.get("parallel_group_id"),
                            }
                        )
                    step = safe_node_steps[safe_node_step_index[node_id]]
                    step["status"] = str(room_event.get("status") or "succeeded")
                    step["elapsed_time"] = room_event.get("elapsed_time")
                    step["parallelGroupId"] = room_event.get("parallel_group_id") or step.get("parallelGroupId")

            while True:
                if workflow_task.done():
                    while not channel.queue.empty():
                        event = channel.queue.get_nowait()
                        if event is None:
                            break
                        room_event = _public_room_stream_event(room_id, event, participant=participant)
                        remember_safe_node_step(room_event)
                        if room_event:
                            await service.publish_room_event(room_id, room_event)
                    result = await workflow_task
                    break
                try:
                    event = await asyncio.wait_for(channel.queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if event is None:
                    if workflow_task.done():
                        while not channel.queue.empty():
                            event = channel.queue.get_nowait()
                            if event is None:
                                break
                            room_event = _public_room_stream_event(room_id, event, participant=participant)
                            remember_safe_node_step(room_event)
                            if room_event:
                                await service.publish_room_event(room_id, room_event)
                        result = await workflow_task
                        break
                    continue
                room_event = _public_room_stream_event(room_id, event, participant=participant)
                remember_safe_node_step(room_event)
                if room_event:
                    await service.publish_room_event(room_id, room_event)

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
            await service.append_assistant_message(room_id, answer or "", node_steps=safe_node_steps)
            usage = channel.get_usage()
            await service.publish_room_event(
                room_id,
                {
                    "event": "agent_run_finished",
                    "task_id": task_id,
                    "message_id": message_id,
                    "status": state.get("__status__", "completed"),
                },
            )
            return JSONResponse(
                content=WorkflowRunResponse(
                    event="message",
                    task_id=task_id,
                    id=message_id,
                    message_id=message_id,
                    conversation_id=room["conversation_id"],
                    mode="workflow",
                    answer=answer or "",
                    metadata=WorkflowRunMetadata(
                        usage=UsageInfo(
                            prompt_tokens=usage.get("prompt_tokens", 0),
                            completion_tokens=usage.get("completion_tokens", 0),
                            total_tokens=usage.get("total_tokens", 0),
                            latency=time.perf_counter() - start_time,
                        ),
                        trace_id=metadata.get("trace_id"),
                        interrupted=bool(state.get("__interrupted__", False)),
                        status=state.get("__status__", "completed"),
                    ),
                    created_at=int(time.time()),
                ).model_dump()
            )
        except Exception as exc:
            await service.append_assistant_message(room_id, str(exc), status="failed", reason="workflow_error")
            await service.publish_room_event(
                room_id,
                {
                    "event": "agent_run_failed",
                    "task_id": task_id,
                    "message_id": message_id,
                    "error": str(exc),
                },
            )
            raise
        finally:
            await service.release_run_lock(room_id, participant["owner_id"])
    except Exception as exc:
        return _service_error_response(exc)

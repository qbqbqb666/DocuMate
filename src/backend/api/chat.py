import json
from collections.abc import Iterable, Iterator
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from src.backend.api.schemas import (
    ApprovalDecisionRequest,
    ApprovalEventResponse,
    ApprovalResponse,
    CreateThreadRequest,
    CreateThreadResponse,
    CreateTurnRequest,
    ErrorDetail,
    ModelChunkEventResponse,
    StatusEventResponse,
    TurnResultResponse,
)
from src.backend.services.conversation import (
    ApprovalStreamEvent,
    ConversationCoordinator,
    ErrorStreamEvent,
    ModelChunkEvent,
    StatusStreamEvent,
    TurnResult,
    TurnResultStreamEvent,
    TurnStreamEvent,
)
from src.backend.api.workspace import get_app_config
from src.backend.services.app_config import AppConfigService


LOCAL_USER_ID = "local-user"

router = APIRouter(tags=["chat"])


def get_coordinator(request: Request) -> ConversationCoordinator:
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is None:
        raise RuntimeError("ConversationCoordinator 尚未初始化")
    return coordinator


@router.post(
    "/threads",
    response_model=CreateThreadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_thread(
    body: CreateThreadRequest,
    coordinator: ConversationCoordinator = Depends(get_coordinator),
    app_config: AppConfigService = Depends(get_app_config),
) -> CreateThreadResponse:
    workspace_path, _ = _project_context(body.project_id, body.workspace_path, app_config)
    thread_id = coordinator.create_thread(
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
    )
    if body.project_id is not None:
        coordinator.history.set_thread_project(
            thread_id=thread_id,
            user_id=LOCAL_USER_ID,
            workspace_path=workspace_path,
            project_id=body.project_id,
        )
    return CreateThreadResponse(thread_id=thread_id)


@router.post(
    "/threads/{thread_id}/turns",
    response_model=TurnResultResponse,
)
def run_turn(
    thread_id: str,
    body: CreateTurnRequest,
    coordinator: ConversationCoordinator = Depends(get_coordinator),
    app_config: AppConfigService = Depends(get_app_config),
) -> TurnResultResponse:
    workspace_path, accessible_paths = _project_context(body.project_id, body.workspace_path, app_config)
    result = coordinator.run_turn(
        thread_id=thread_id,
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
        content=body.content,
        referenced_attachment_ids=body.referenced_attachment_ids,
        permission=body.permission,
        provider=body.provider,
        model_name=body.model_name,
        **({"accessible_paths": accessible_paths} if body.project_id else {}),
    )
    return turn_result_response(result)


@router.post(
    "/threads/{thread_id}/turns/stream",
    responses={
        200: {
            "description": "SSE 流式事件",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
def stream_turn(
    thread_id: str,
    body: CreateTurnRequest,
    coordinator: ConversationCoordinator = Depends(get_coordinator),
    app_config: AppConfigService = Depends(get_app_config),
) -> StreamingResponse:
    workspace_path, accessible_paths = _project_context(body.project_id, body.workspace_path, app_config)
    events = coordinator.stream_turn(
        thread_id=thread_id,
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
        content=body.content,
        referenced_attachment_ids=body.referenced_attachment_ids,
        permission=body.permission,
        provider=body.provider,
        model_name=body.model_name,
        **({"run_id": body.run_id} if body.run_id else {}),
        **({"accessible_paths": accessible_paths} if body.project_id else {}),
    )
    return _streaming_response(events)


@router.post(
    "/threads/{thread_id}/approvals/{approval_id}",
    response_model=TurnResultResponse,
)
def resume_turn(
    thread_id: str,
    approval_id: str,
    body: ApprovalDecisionRequest,
    coordinator: ConversationCoordinator = Depends(get_coordinator),
    app_config: AppConfigService = Depends(get_app_config),
) -> TurnResultResponse:
    workspace_path, accessible_paths = _project_context(body.project_id, body.workspace_path, app_config)
    result = coordinator.resume_turn(
        thread_id=thread_id,
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
        approval_id=approval_id,
        tool_call_id=body.tool_call_id,
        decision=body.decision,
        **({"accessible_paths": accessible_paths} if body.project_id else {}),
    )
    return turn_result_response(result)


@router.post(
    "/threads/{thread_id}/approvals/{approval_id}/stream",
    responses={
        200: {
            "description": "SSE 流式审批恢复事件",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
def stream_resume_turn(
    thread_id: str,
    approval_id: str,
    body: ApprovalDecisionRequest,
    coordinator: ConversationCoordinator = Depends(get_coordinator),
    app_config: AppConfigService = Depends(get_app_config),
) -> StreamingResponse:
    workspace_path, accessible_paths = _project_context(body.project_id, body.workspace_path, app_config)
    events = coordinator.stream_resume_turn(
        thread_id=thread_id,
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
        approval_id=approval_id,
        tool_call_id=body.tool_call_id,
        decision=body.decision,
        **({"run_id": body.run_id} if body.run_id else {}),
        **({"accessible_paths": accessible_paths} if body.project_id else {}),
    )
    return _streaming_response(events)


@router.post("/threads/{thread_id}/runs/{run_id}/cancel")
def cancel_run(
    thread_id: str,
    run_id: str,
    coordinator: ConversationCoordinator = Depends(get_coordinator),
) -> dict[str, bool | str]:
    return {
        "thread_id": thread_id,
        "run_id": run_id,
        "cancelled": coordinator.cancel_run(thread_id, run_id),
    }


def _project_context(
    project_id: str | None,
    workspace_path: str,
    app_config: AppConfigService,
) -> tuple[str, tuple[str, ...]]:
    if not project_id:
        return workspace_path, (workspace_path,)
    project = app_config.project(project_id)
    return project["primary_path"], tuple(project["folder_paths"])


def turn_result_response(result: TurnResult) -> TurnResultResponse:
    approval = result.approval_request
    return TurnResultResponse.model_validate(
        {
            "thread_id": result.thread_id,
            "turn_number": result.turn_number,
            "input_message_id": result.input_message_id,
            "status": result.status,
            "final_message_id": result.final_message_id,
            "approval": (
                {
                    "approval_id": approval.approval_id,
                    "tool_call_id": approval.tool_call_id,
                    "name": approval.name,
                    "args": approval.args,
                    "reason": approval.reason,
                    "paths": list(approval.paths),
                }
                if approval is not None
                else None
            ),
            "finalization": result.finalization,
            "execution": result.execution_summary,
        }
    )


def _streaming_response(events: Iterable[TurnStreamEvent]) -> StreamingResponse:
    return StreamingResponse(
        stream_sse(events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def stream_sse(events: Iterable[TurnStreamEvent]) -> Iterator[str]:
    emitted_error = False
    try:
        for event in events:
            if isinstance(event, ErrorStreamEvent):
                emitted_error = True
            yield encode_stream_event(event)
    except Exception as error:
        if not emitted_error:
            yield encode_sse(
                "error",
                ErrorDetail(
                    code="stream_error",
                    error_type=type(error).__name__,
                    message=str(error) or "流式处理失败",
                ),
            )


def encode_stream_event(event: TurnStreamEvent) -> str:
    if isinstance(event, StatusStreamEvent):
        return encode_sse(
            "status",
            StatusEventResponse(
                stage=event.stage,
                message=event.message,
                tool_call_id=event.tool_call_id,
                tool_name=event.tool_name,
            ),
        )
    if isinstance(event, ModelChunkEvent):
        return encode_sse("model_chunk", _model_chunk_response(event))
    if isinstance(event, ApprovalStreamEvent):
        approval = event.approval_request
        return encode_sse(
            "approval",
            ApprovalEventResponse(
                approval=ApprovalResponse(
                    approval_id=approval.approval_id,
                    tool_call_id=approval.tool_call_id,
                    name=approval.name,
                    args=approval.args,
                    reason=approval.reason,
                    paths=list(approval.paths),
                ),
                turn=turn_result_response(event.result),
            ),
        )
    if isinstance(event, TurnResultStreamEvent):
        return encode_sse("result", turn_result_response(event.result))
    if isinstance(event, ErrorStreamEvent):
        return encode_sse(
            "error",
            ErrorDetail(
                code="stream_error",
                error_type=event.error_type,
                message=event.message,
            ),
        )
    raise TypeError(f"不支持的流式事件：{type(event).__name__}")


def encode_sse(event_name: str, payload: Any) -> str:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json", exclude_none=True)
    data = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return f"event: {event_name}\ndata: {data}\n\n"


def _model_chunk_response(event: ModelChunkEvent) -> ModelChunkEventResponse:
    chunk = event.chunk
    metadata = event.metadata
    node = metadata.get("langgraph_node")
    return ModelChunkEventResponse(
        text=_chunk_text(getattr(chunk, "content", "")),
        message_id=_optional_string(getattr(chunk, "id", None)),
        node=node if isinstance(node, str) else None,
    )


def _chunk_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        else:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None

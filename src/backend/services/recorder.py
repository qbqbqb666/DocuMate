import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    ToolMessage,
    message_to_dict,
)

from src.backend.services.event_log import EventLogService, EventType, event_log


@dataclass(frozen=True)
class OperationHandle:
    """关联一项操作的开始事件、结束事件和耗时。"""

    operation_id: str
    started_at: float
    execution: "ExecutionMetadata | None" = None


class ExecutionMetadata(TypedDict, total=False):
    """可写入业务事件的最小 LangGraph 执行元数据。"""

    run_id: str
    task_id: str
    checkpoint_id: str
    node_attempt: int


def extract_execution_metadata(runtime: Any) -> ExecutionMetadata | None:
    """从 Runtime 统一提取可追踪字段；缺失时安全省略。"""
    info = getattr(runtime, "execution_info", None) if runtime is not None else None
    if info is None:
        return None
    execution: ExecutionMetadata = {}
    for field in ("run_id", "task_id", "checkpoint_id"):
        value = getattr(info, field, None)
        if isinstance(value, str) and value:
            execution[field] = value  # type: ignore[literal-required]
    node_attempt = getattr(info, "node_attempt", None)
    if isinstance(node_attempt, int) and not isinstance(node_attempt, bool):
        execution["node_attempt"] = node_attempt
    return execution or None


class RunRecorder:
    """把当前 thread/turn 的运行事实转换成标准 JSONL 事件。"""

    def __init__(
        self,
        *,
        thread_id: str,
        turn_number: int,
        event_log_service: EventLogService = event_log,
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.thread_id = thread_id
        self.turn_number = turn_number
        self.event_log = event_log_service
        self._timer = timer

    def turn_started(
        self,
        input_message_id: str,
        *,
        provider: str | None = None,
        model_name: str | None = None,
        permission: str | None = None,
    ) -> OperationHandle:
        started_at = self._timer()
        payload = {"input_message_id": input_message_id}
        if provider is not None:
            payload["provider"] = provider
        if model_name is not None:
            payload["model_name"] = model_name
        if permission is not None:
            payload["permission"] = permission
        self._append(
            EventType.TURN_STARTED,
            payload,
        )
        return OperationHandle(str(self.turn_number), started_at)

    def turn_succeeded(
        self,
        handle: OperationHandle | None,
        *,
        final_message_id: str,
        duration_ms: float | None = None,
    ) -> None:
        self._append(
            EventType.TURN_FINISHED,
            {
                "status": "success",
                "duration_ms": (
                    duration_ms
                    if duration_ms is not None
                    else self._duration_ms(handle)
                ),
                "final_message_id": final_message_id,
            },
        )

    def turn_failed(
        self,
        handle: OperationHandle | None,
        error: BaseException,
        *,
        duration_ms: float | None = None,
    ) -> None:
        self._append(
            EventType.TURN_FINISHED,
            {
                "status": "error",
                "duration_ms": (
                    duration_ms
                    if duration_ms is not None
                    else self._duration_ms(handle)
                ),
                "error": _serialize_error(error),
            },
        )

    def message_created(
        self,
        message: AnyMessage,
        *,
        attachment_ids: Sequence[str] | None = None,
    ) -> AnyMessage:
        """记录核心消息；缺少 ID 时返回带新 ID 的消息副本。"""
        normalized = message
        if not message.id:
            normalized = message.model_copy(update={"id": str(uuid4())})

        payload: dict[str, Any] = {
            "message_id": normalized.id,
            "role": _message_role(normalized),
            "content": _message_content_text(normalized),
        }
        if isinstance(normalized, HumanMessage) and attachment_ids:
            payload["attachment_ids"] = list(attachment_ids)
        elif isinstance(normalized, AIMessage) and normalized.tool_calls:
            payload["tool_calls"] = _jsonable(normalized.tool_calls)
        elif isinstance(normalized, ToolMessage):
            payload["tool_call_id"] = normalized.tool_call_id

        self._append(EventType.MESSAGE, payload)
        return normalized

    def attachment_added(
        self,
        *,
        attachment_id: str,
        message_id: str,
        name: str,
        mime_type: str,
        path: str,
        size: int,
        base64_data: str,
    ) -> None:
        self._append(
            EventType.ATTACHMENT_ADDED,
            {
                "attachment_id": attachment_id,
                "message_id": message_id,
                "name": name,
                "mime_type": mime_type,
                "path": path,
                "size": size,
                "base64_data": base64_data,
            },
        )

    def artifact_recorded(
        self,
        *,
        artifact_id: str,
        name: str,
        mime_type: str,
        url: str,
        operation: str,
        tool_call_id: str,
    ) -> None:
        self._append(
            EventType.ARTIFACT_RECORDED,
            {
                "artifact_id": artifact_id,
                "name": name,
                "mime_type": mime_type,
                "url": url,
                "operation": operation,
                "tool_call_id": tool_call_id,
            },
        )

    def model_started(
        self,
        *,
        provider: str,
        model: str,
        messages: Sequence[AnyMessage],
        tools: Sequence[Mapping[str, Any]],
        parameters: Mapping[str, Any],
        request_id: str | None = None,
        execution: ExecutionMetadata | None = None,
    ) -> OperationHandle:
        normalized_request_id = request_id or str(uuid4())
        started_at = self._timer()
        payload = {
            "request_id": normalized_request_id,
            "provider": provider,
            "model": model,
            "messages": [message_to_dict(message) for message in messages],
            "tools": _jsonable(list(tools)),
            "parameters": _jsonable(dict(parameters)),
        }
        _add_execution(payload, execution)
        self._append(
            EventType.MODEL_REQUEST,
            payload,
        )
        return OperationHandle(normalized_request_id, started_at, execution)

    def model_succeeded(
        self,
        handle: OperationHandle,
        *,
        response: AnyMessage,
        usage: Mapping[str, Any] | None = None,
    ) -> None:
        payload = {
            "request_id": handle.operation_id,
            "status": "success",
            "duration_ms": self._duration_ms(handle),
            "response": message_to_dict(response),
            "usage": _jsonable(dict(usage or {})),
        }
        _add_execution(payload, handle.execution)
        self._append(
            EventType.MODEL_RESULT,
            payload,
        )

    def model_failed(
        self,
        handle: OperationHandle,
        error: BaseException,
    ) -> None:
        payload = {
            "request_id": handle.operation_id,
            "status": "error",
            "duration_ms": self._duration_ms(handle),
            "error": _serialize_error(error),
        }
        _add_execution(payload, handle.execution)
        self._append(
            EventType.MODEL_RESULT,
            payload,
        )

    def tool_started(
        self,
        *,
        tool_call_id: str,
        name: str,
        args: Mapping[str, Any],
        execution: ExecutionMetadata | None = None,
    ) -> OperationHandle:
        started_at = self._timer()
        payload = {
            "tool_call_id": tool_call_id,
            "name": name,
            "args": _jsonable(dict(args)),
        }
        _add_execution(payload, execution)
        self._append(
            EventType.TOOL_STARTED,
            payload,
        )
        return OperationHandle(tool_call_id, started_at, execution)

    def tool_succeeded(
        self,
        handle: OperationHandle,
        *,
        name: str,
        result: Any,
    ) -> None:
        payload = {
            "tool_call_id": handle.operation_id,
            "name": name,
            "status": "success",
            "duration_ms": self._duration_ms(handle),
            "result": _jsonable(result),
        }
        _add_execution(payload, handle.execution)
        self._append(
            EventType.TOOL_RESULT,
            payload,
        )

    def tool_failed(
        self,
        handle: OperationHandle,
        *,
        name: str,
        error: BaseException,
    ) -> None:
        payload = {
            "tool_call_id": handle.operation_id,
            "name": name,
            "status": "error",
            "duration_ms": self._duration_ms(handle),
            "error": _serialize_error(error),
        }
        _add_execution(payload, handle.execution)
        self._append(
            EventType.TOOL_RESULT,
            payload,
        )

    def approval_requested(
        self,
        *,
        approval_id: str,
        tool_call_id: str,
        name: str,
        args: Mapping[str, Any],
    ) -> None:
        self._append(
            EventType.APPROVAL_REQUESTED,
            {
                "approval_id": approval_id,
                "tool_call_id": tool_call_id,
                "name": name,
                "args": _jsonable(dict(args)),
            },
        )

    def approval_decided(
        self,
        *,
        approval_id: str,
        tool_call_id: str,
        decision: str,
    ) -> None:
        self._append(
            EventType.APPROVAL_DECIDED,
            {
                "approval_id": approval_id,
                "tool_call_id": tool_call_id,
                "decision": decision,
            },
        )

    def context_compacted(
        self,
        *,
        summary_message: HumanMessage,
        summarized_message_ids: Sequence[str],
        preserved_message_ids: Sequence[str],
        execution: ExecutionMetadata | None = None,
    ) -> HumanMessage:
        """记录 Lifecycle Context 摘要对持久 State 的替换。"""
        normalized = summary_message
        if not summary_message.id:
            normalized = summary_message.model_copy(update={"id": str(uuid4())})
        payload = {
            "summary_message_id": normalized.id,
            "summary_content": _message_content_text(normalized),
            "summarized_message_ids": list(summarized_message_ids),
            "preserved_message_ids": list(preserved_message_ids),
        }
        _add_execution(payload, execution)
        self._append(
            EventType.CONTEXT_COMPACTED,
            payload,
        )
        return normalized

    def _duration_ms(self, handle: OperationHandle | None) -> float:
        if handle is None:
            raise ValueError("缺少操作起始时间")
        return max(0.0, (self._timer() - handle.started_at) * 1000)

    def _append(
        self,
        event_type: EventType,
        payload: Mapping[str, Any],
    ) -> None:
        self.event_log.append(
            thread_id=self.thread_id,
            turn_number=self.turn_number,
            event_type=event_type,
            payload=payload,
        )


def _message_role(message: AnyMessage) -> str:
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    raise TypeError(f"不支持记录的消息类型：{type(message).__name__}")


def _add_execution(
    payload: dict[str, Any],
    execution: ExecutionMetadata | None,
) -> None:
    if execution:
        payload["execution"] = dict(execution)


def _message_content_text(message: AnyMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return json.dumps(
        _jsonable(message.content),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _serialize_error(error: BaseException) -> dict[str, str]:
    return {
        "type": type(error).__name__,
        "message": str(error),
    }


def _jsonable(value: Any) -> Any:
    """转为 JSON 可序列化基础类型，并拒绝隐式字符串化未知对象。"""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_jsonable(item) for item in value]
    raise TypeError(f"值不能安全序列化为 JSON：{type(value).__name__}")

import json
import os
import threading
from base64 import b64decode
from binascii import Error as BinasciiError
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

from src.backend.paths import DATA_DIRECTORY


SCHEMA_VERSION = "0.2"
SUPPORTED_SCHEMA_VERSIONS = {"0.1", SCHEMA_VERSION}
EVENT_LOG_ROOT = DATA_DIRECTORY / "sessions"
COMMON_FIELDS = {
    "schema_version",
    "sequence",
    "event_type",
    "thread_id",
    "turn_number",
    "timestamp",
    "payload",
}


class EventType(StrEnum):
    """DocuMate 当前支持的事件类型。"""

    THREAD_CREATED = "thread_created"
    TURN_STARTED = "turn_started"
    ATTACHMENT_ADDED = "attachment_added"
    ARTIFACT_RECORDED = "artifact_recorded"
    MESSAGE = "message"
    MODEL_REQUEST = "model_request"
    MODEL_RESULT = "model_result"
    TOOL_STARTED = "tool_started"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    CONTEXT_COMPACTED = "context_compacted"
    TURN_FINISHED = "turn_finished"


class EventLogError(Exception):
    """事件日志错误基类。"""


class EventLogValidationError(EventLogError, ValueError):
    """事件字段不符合当前兼容结构。"""


class EventLogNotFoundError(EventLogError, FileNotFoundError):
    """找不到 thread 对应的事件日志。"""


class DuplicateEventLogError(EventLogError):
    """同一 thread 找到多个事件日志。"""


class CorruptEventLogError(EventLogError):
    """事件日志损坏或包含不完整记录。"""


PAYLOAD_FIELDS = {
    EventType.THREAD_CREATED: (
        {"user_id", "workspace_path"},
        set(),
    ),
    EventType.TURN_STARTED: (
        {"input_message_id"},
        {"provider", "model_name", "permission"},
    ),
    EventType.ATTACHMENT_ADDED: (
        {
            "attachment_id",
            "message_id",
            "name",
            "mime_type",
            "path",
            "size",
            "base64_data",
        },
        set(),
    ),
    EventType.ARTIFACT_RECORDED: (
        {
            "artifact_id",
            "name",
            "mime_type",
            "url",
            "operation",
            "tool_call_id",
        },
        set(),
    ),
    EventType.MESSAGE: (
        {"message_id", "role", "content"},
        {"attachment_ids", "tool_calls", "tool_call_id"},
    ),
    EventType.MODEL_REQUEST: (
        {"request_id", "provider", "model", "messages", "tools", "parameters"},
        {"execution"},
    ),
    EventType.MODEL_RESULT: (
        {"request_id", "status", "duration_ms"},
        {"response", "usage", "error", "execution"},
    ),
    EventType.TOOL_STARTED: (
        {"tool_call_id", "name", "args"},
        {"execution"},
    ),
    EventType.TOOL_RESULT: (
        {"tool_call_id", "name", "status", "duration_ms"},
        {"result", "error", "execution"},
    ),
    EventType.APPROVAL_REQUESTED: (
        {"approval_id", "tool_call_id", "name", "args"},
        set(),
    ),
    EventType.APPROVAL_DECIDED: (
        {"approval_id", "tool_call_id", "decision"},
        set(),
    ),
    EventType.CONTEXT_COMPACTED: (
        {
            "summary_message_id",
            "summary_content",
            "summarized_message_ids",
            "preserved_message_ids",
        },
        {"execution"},
    ),
    EventType.TURN_FINISHED: (
        {"status", "duration_ms"},
        {"final_message_id", "error"},
    ),
}


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _lock_for(thread_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(thread_id, threading.RLock())


def _validate_thread_id(thread_id: str) -> None:
    try:
        valid = isinstance(thread_id, str) and str(UUID(thread_id)) == thread_id
    except ValueError:
        valid = False
    if not valid:
        raise EventLogValidationError(
            "thread_id 必须是小写、带连字符的标准 UUID"
        )


def _validate_turn_number(
    event_type: EventType,
    turn_number: int | None,
) -> None:
    if event_type is EventType.THREAD_CREATED:
        if turn_number is not None:
            raise EventLogValidationError(
                "thread_created 的 turn_number 必须为 null"
            )
        return
    if (
        isinstance(turn_number, bool)
        or not isinstance(turn_number, int)
        or turn_number < 1
    ):
        raise EventLogValidationError("turn_number 必须是大于 0 的整数")


def _validate_status_payload(
    payload: Mapping[str, Any],
    success_field: str,
) -> None:
    status = payload["status"]
    if status not in {"success", "error"}:
        raise EventLogValidationError("status 必须是 success 或 error")
    if status == "success" and success_field not in payload:
        raise EventLogValidationError(
            f"status=success 时必须包含 {success_field}"
        )
    if status == "error" and "error" not in payload:
        raise EventLogValidationError("status=error 时必须包含 error")
    if status == "success" and "error" in payload:
        raise EventLogValidationError("status=success 时不能包含 error")
    if status == "error" and success_field in payload:
        raise EventLogValidationError(
            f"status=error 时不能包含 {success_field}"
        )


def _validate_payload(
    event_type: EventType,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise EventLogValidationError("payload 必须是对象")
    result = dict(payload)
    required, optional = PAYLOAD_FIELDS[event_type]
    missing = required - result.keys()
    unknown = result.keys() - required - optional
    if missing:
        raise EventLogValidationError(
            f"{event_type.value} 缺少字段：{sorted(missing)}"
        )
    if unknown:
        raise EventLogValidationError(
            f"{event_type.value} 包含未知字段：{sorted(unknown)}"
        )

    if "execution" in result:
        _validate_execution(result["execution"])

    if event_type is EventType.TURN_STARTED:
        optional_strings = ("provider", "model_name", "permission")
        if any(
            field in result
            and (
                not isinstance(result[field], str)
                or not result[field].strip()
            )
            for field in optional_strings
        ):
            raise EventLogValidationError(
                "provider、model_name 和 permission 必须是非空字符串"
            )
    elif event_type is EventType.ATTACHMENT_ADDED:
        if isinstance(result["size"], bool) or not isinstance(result["size"], int):
            raise EventLogValidationError("size 必须是整数")
        if not isinstance(result["base64_data"], str) or not result["base64_data"]:
            raise EventLogValidationError("base64_data 必须是非空字符串")
        try:
            b64decode(result["base64_data"], validate=True)
        except (BinasciiError, ValueError) as exc:
            raise EventLogValidationError("base64_data 不是有效 Base64") from exc
    elif event_type is EventType.ARTIFACT_RECORDED:
        if result["operation"] not in {"created", "modified"}:
            raise EventLogValidationError(
                "operation 必须是 created 或 modified"
            )
    elif event_type is EventType.MESSAGE:
        role = result["role"]
        if role not in {"user", "assistant", "tool"}:
            raise EventLogValidationError("role 必须是 user、assistant 或 tool")
        if role == "tool" and "tool_call_id" not in result:
            raise EventLogValidationError("tool 消息必须包含 tool_call_id")
        if role == "user" and ({"tool_calls", "tool_call_id"} & result.keys()):
            raise EventLogValidationError("user 消息不能包含工具调用字段")
        if role == "assistant" and ({"attachment_ids", "tool_call_id"} & result.keys()):
            raise EventLogValidationError("assistant 消息包含不适用字段")
        if role == "tool" and ({"attachment_ids", "tool_calls"} & result.keys()):
            raise EventLogValidationError("tool 消息包含不适用字段")
    elif event_type is EventType.MODEL_REQUEST:
        if not isinstance(result["messages"], list) or not isinstance(
            result["tools"], list
        ):
            raise EventLogValidationError("messages 和 tools 必须是数组")
        if not isinstance(result["parameters"], Mapping):
            raise EventLogValidationError("parameters 必须是对象")
    elif event_type is EventType.MODEL_RESULT:
        _validate_status_payload(result, "response")
    elif event_type is EventType.TOOL_RESULT:
        _validate_status_payload(result, "result")
    elif event_type is EventType.APPROVAL_REQUESTED:
        if not isinstance(result["args"], Mapping):
            raise EventLogValidationError("args 必须是对象")
    elif event_type is EventType.APPROVAL_DECIDED:
        if result["decision"] not in {"allow", "deny"}:
            raise EventLogValidationError("decision 必须是 allow 或 deny")
    elif event_type is EventType.CONTEXT_COMPACTED:
        for field in ("summarized_message_ids", "preserved_message_ids"):
            value = result[field]
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise EventLogValidationError(f"{field} 必须是字符串数组")
    elif event_type is EventType.TURN_FINISHED:
        _validate_status_payload(result, "final_message_id")

    try:
        json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise EventLogValidationError("payload 必须能够序列化为 JSON") from exc
    return result


def _validate_execution(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise EventLogValidationError("execution 必须是对象")
    allowed = {"run_id", "task_id", "checkpoint_id", "node_attempt"}
    unknown = value.keys() - allowed
    if unknown:
        raise EventLogValidationError(
            f"execution 包含未知字段：{sorted(unknown)}"
        )
    for field in ("run_id", "task_id", "checkpoint_id"):
        if field in value and (
            not isinstance(value[field], str) or not value[field]
        ):
            raise EventLogValidationError(f"execution.{field} 必须是非空字符串")
    if "node_attempt" in value and (
        isinstance(value["node_attempt"], bool)
        or not isinstance(value["node_attempt"], int)
        or value["node_attempt"] < 1
    ):
        raise EventLogValidationError("execution.node_attempt 必须是大于 0 的整数")


def _format_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EventLogValidationError("时间必须包含时区")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_line(
    raw_line: bytes,
    path: Path,
    line_number: int,
) -> dict[str, Any]:
    if not raw_line.endswith(b"\n"):
        raise CorruptEventLogError(f"日志尾行不完整：{path}")
    try:
        event = json.loads(raw_line)
        event_type = EventType(event["event_type"])
        if (
            set(event) != COMMON_FIELDS
            or event["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS
        ):
            raise ValueError
        if (
            isinstance(event["sequence"], bool)
            or not isinstance(event["sequence"], int)
        ):
            raise ValueError
        if (
            not isinstance(event["timestamp"], str)
            or not event["timestamp"].endswith("Z")
        ):
            raise ValueError
        datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        _validate_thread_id(event["thread_id"])
        _validate_turn_number(event_type, event["turn_number"])
        _validate_payload(event_type, event["payload"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CorruptEventLogError(
            f"日志第 {line_number} 行不符合支持的 schema：{path}"
        ) from exc
    return event


class EventLogService:
    """按 thread 创建、追加和流式读取 JSONL 事件日志。"""

    def __init__(
        self,
        root: Path = EVENT_LOG_ROOT,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.root = Path(root)
        self._clock = clock

    def now(self) -> datetime:
        """返回服务使用的当前 UTC 时间，便于跨恢复计算轮次耗时。"""
        return self._clock().astimezone(timezone.utc)

    def create_thread_log(
        self,
        *,
        thread_id: str,
        user_id: str,
        workspace_path: str,
    ) -> Path:
        _validate_thread_id(thread_id)
        with _lock_for(thread_id):
            if self.find_thread_log(thread_id) is not None:
                raise DuplicateEventLogError(f"thread 日志已存在：{thread_id}")
            created_at = self.now()
            directory = self.root / created_at.strftime("%Y/%m/%d")
            directory.mkdir(parents=True, exist_ok=True)
            milliseconds = created_at.microsecond // 1000
            time_name = f"{created_at:%Y%m%dT%H%M%S}{milliseconds:03d}Z"
            path = directory / f"rollout-{time_name}-{thread_id}.jsonl"
            event = self._build_event(
                sequence=1,
                event_type=EventType.THREAD_CREATED,
                thread_id=thread_id,
                turn_number=None,
                payload={"user_id": user_id, "workspace_path": workspace_path},
                timestamp=created_at,
            )
            self._write(path, event, "xb")
            return path

    def find_thread_log(self, thread_id: str) -> Path | None:
        _validate_thread_id(thread_id)
        if not self.root.exists():
            return None
        matches = list(self.root.rglob(f"*-{thread_id}.jsonl"))
        if len(matches) > 1:
            raise DuplicateEventLogError(f"thread 存在多个日志：{thread_id}")
        return matches[0] if matches else None

    def iter_thread_ids(self) -> Iterator[str]:
        """按稳定顺序列出 sessions 中的 thread，并检测重复日志。"""
        if not self.root.exists():
            return
        found: dict[str, Path] = {}
        for path in sorted(self.root.rglob("*.jsonl")):
            thread_id = path.stem[-36:]
            try:
                _validate_thread_id(thread_id)
            except EventLogValidationError as exc:
                raise CorruptEventLogError(
                    f"日志文件名缺少有效 thread_id：{path}"
                ) from exc
            previous = found.get(thread_id)
            if previous is not None:
                raise DuplicateEventLogError(
                    f"thread 存在多个日志：{thread_id}（{previous}、{path}）"
                )
            found[thread_id] = path
        yield from sorted(found)

    def append(
        self,
        *,
        thread_id: str,
        turn_number: int,
        event_type: EventType,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        _validate_thread_id(thread_id)
        try:
            normalized_type = EventType(event_type)
        except ValueError as exc:
            raise EventLogValidationError(f"未知 event_type：{event_type}") from exc
        if normalized_type is EventType.THREAD_CREATED:
            raise EventLogValidationError("thread_created 只能在创建文件时写入")
        _validate_turn_number(normalized_type, turn_number)

        with _lock_for(thread_id):
            path = self.find_thread_log(thread_id)
            if path is None:
                raise EventLogNotFoundError(f"找不到 thread 日志：{thread_id}")
            last_event = self._last_event(path)
            event = self._build_event(
                sequence=last_event["sequence"] + 1,
                event_type=normalized_type,
                thread_id=thread_id,
                turn_number=turn_number,
                payload=payload,
                timestamp=self._clock(),
            )
            self._write(path, event, "ab")
            return event

    def iter_events(
        self,
        thread_id: str,
        *,
        after_sequence: int = 0,
    ) -> Iterator[dict[str, Any]]:
        _validate_thread_id(thread_id)
        if (
            isinstance(after_sequence, bool)
            or not isinstance(after_sequence, int)
            or after_sequence < 0
        ):
            raise EventLogValidationError("after_sequence 必须是非负整数")
        path = self.find_thread_log(thread_id)
        if path is None:
            raise EventLogNotFoundError(f"找不到 thread 日志：{thread_id}")

        with _lock_for(thread_id), path.open("rb") as file:
            for expected, raw_line in enumerate(file, start=1):
                event = _parse_line(raw_line, path, expected)
                if event["thread_id"] != thread_id or event["sequence"] != expected:
                    raise CorruptEventLogError(
                        f"thread_id 或 sequence 不连续：{path}，第 {expected} 行"
                    )
                if expected > after_sequence:
                    yield event

    def find_attachment_event(
        self,
        thread_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        """根据 attachment_id 查找唯一的原始附件事件。"""
        matched: dict[str, Any] | None = None
        for event in self.iter_events(thread_id):
            if (
                event["event_type"] == EventType.ATTACHMENT_ADDED.value
                and event["payload"]["attachment_id"] == attachment_id
            ):
                if matched is not None:
                    raise CorruptEventLogError(
                        f"attachment_id 存在重复事件：{attachment_id}"
                    )
                matched = event
        return matched

    def _build_event(
        self,
        *,
        sequence: int,
        event_type: EventType,
        thread_id: str,
        turn_number: int | None,
        payload: Mapping[str, Any],
        timestamp: datetime,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "sequence": sequence,
            "event_type": event_type.value,
            "thread_id": thread_id,
            "turn_number": turn_number,
            "timestamp": _format_timestamp(timestamp),
            "payload": _validate_payload(event_type, payload),
        }

    @staticmethod
    def _write(path: Path, event: Mapping[str, Any], mode: str) -> None:
        data = (
            json.dumps(
                event,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        try:
            with path.open(mode) as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
        except FileExistsError as exc:
            raise DuplicateEventLogError(f"日志文件已存在：{path}") from exc

    @staticmethod
    def _last_event(path: Path) -> dict[str, Any]:
        last_line = b""
        with path.open("rb") as file:
            for last_line in file:
                pass
        if not last_line:
            raise CorruptEventLogError(f"日志文件为空：{path}")
        return _parse_line(last_line, path, -1)


event_log = EventLogService()

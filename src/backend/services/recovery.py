import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5

from langchain_core.messages import ToolMessage

from src.backend.services.event_log import EventLogService, EventType
from src.backend.services.recorder import RunRecorder
from src.backend.services.state_rebuilder import restore_checkpoint_from_event_log


class RunInterruptedError(RuntimeError):
    """上一次进程退出导致轮次无法继续。"""


@dataclass(frozen=True)
class ThreadRecoveryResult:
    thread_id: str
    repaired_turns: tuple[int, ...] = ()
    preserved_approval_turn: int | None = None

    @property
    def changed(self) -> bool:
        return bool(self.repaired_turns)


class ConversationRecoveryService:
    """把崩溃遗留的未闭环 turn 修复为可重放的失败轮次。"""

    def __init__(self, *, graph: Any, event_log_service: EventLogService) -> None:
        self.graph = graph
        self.event_log = event_log_service

    def recover_thread(self, thread_id: str) -> ThreadRecoveryResult:
        events = list(self.event_log.iter_events(thread_id))
        started = {
            event["turn_number"]
            for event in events
            if event["event_type"] == EventType.TURN_STARTED.value
        }
        finished = {
            event["turn_number"]
            for event in events
            if event["event_type"] == EventType.TURN_FINISHED.value
        }
        running = sorted(started - finished)
        if not running:
            return ThreadRecoveryResult(thread_id)

        preserved = self._valid_pending_approval_turn(thread_id, events, running)
        repaired: list[int] = []
        for turn_number in running:
            if turn_number == preserved:
                continue
            self._repair_turn(thread_id, turn_number, events)
            repaired.append(turn_number)
            events = list(self.event_log.iter_events(thread_id))

        if repaired:
            restore_checkpoint_from_event_log(
                self.graph,
                thread_id,
                event_log_service=self.event_log,
            )
        return ThreadRecoveryResult(
            thread_id=thread_id,
            repaired_turns=tuple(repaired),
            preserved_approval_turn=preserved,
        )

    def _valid_pending_approval_turn(
        self,
        thread_id: str,
        events: list[dict[str, Any]],
        running: list[int],
    ) -> int | None:
        if len(running) != 1:
            return None
        turn_number = running[0]
        turn_events = [
            event for event in events if event["turn_number"] == turn_number
        ]
        decisions = {
            (event["payload"]["approval_id"], event["payload"]["tool_call_id"])
            for event in turn_events
            if event["event_type"] == EventType.APPROVAL_DECIDED.value
        }
        pending = [
            event["payload"]
            for event in turn_events
            if event["event_type"] == EventType.APPROVAL_REQUESTED.value
            and (
                event["payload"]["approval_id"],
                event["payload"]["tool_call_id"],
            ) not in decisions
        ]
        if len(pending) != 1:
            return None
        try:
            snapshot = self.graph.get_state(
                {"configurable": {"thread_id": thread_id}}
            )
            interrupts = tuple(getattr(snapshot, "interrupts", ()))
        except Exception:
            return None
        if len(interrupts) != 1:
            return None
        interrupt = interrupts[0]
        value = getattr(interrupt, "value", None)
        expected = pending[0]
        if (
            getattr(interrupt, "id", None) == expected["approval_id"]
            and isinstance(value, dict)
            and value.get("type") == "tool_approval"
            and value.get("tool_call_id") == expected["tool_call_id"]
        ):
            return turn_number
        return None

    def _repair_turn(
        self,
        thread_id: str,
        turn_number: int,
        events: list[dict[str, Any]],
    ) -> None:
        turn_events = [
            event for event in events if event["turn_number"] == turn_number
        ]
        recorder = RunRecorder(
            thread_id=thread_id,
            turn_number=turn_number,
            event_log_service=self.event_log,
        )
        error = RunInterruptedError("应用退出导致本轮未正常完成")

        self._close_model_requests(thread_id, turn_number, turn_events, error)
        unresolved_approvals = self._close_approvals(recorder, turn_events)
        self._close_tool_calls(
            recorder,
            turn_events,
            unresolved_approvals=unresolved_approvals,
        )

        started_event = next(
            event
            for event in turn_events
            if event["event_type"] == EventType.TURN_STARTED.value
        )
        recorder.turn_failed(
            None,
            error,
            duration_ms=_elapsed_ms(
                started_event["timestamp"],
                self.event_log.now(),
            ),
        )

    def _close_model_requests(
        self,
        thread_id: str,
        turn_number: int,
        events: list[dict[str, Any]],
        error: RunInterruptedError,
    ) -> None:
        completed = {
            event["payload"]["request_id"]
            for event in events
            if event["event_type"] == EventType.MODEL_RESULT.value
        }
        for event in events:
            if event["event_type"] != EventType.MODEL_REQUEST.value:
                continue
            payload = event["payload"]
            if payload["request_id"] in completed:
                continue
            result: dict[str, Any] = {
                "request_id": payload["request_id"],
                "status": "error",
                "duration_ms": _elapsed_ms(event["timestamp"], self.event_log.now()),
                "error": _serialized_interruption(error),
            }
            if "execution" in payload:
                result["execution"] = payload["execution"]
            self.event_log.append(
                thread_id=thread_id,
                turn_number=turn_number,
                event_type=EventType.MODEL_RESULT,
                payload=result,
            )

    @staticmethod
    def _close_approvals(
        recorder: RunRecorder,
        events: list[dict[str, Any]],
    ) -> set[str]:
        decided = {
            (event["payload"]["approval_id"], event["payload"]["tool_call_id"])
            for event in events
            if event["event_type"] == EventType.APPROVAL_DECIDED.value
        }
        unresolved_tool_calls: set[str] = set()
        for event in events:
            if event["event_type"] != EventType.APPROVAL_REQUESTED.value:
                continue
            payload = event["payload"]
            key = (payload["approval_id"], payload["tool_call_id"])
            if key in decided:
                continue
            recorder.approval_decided(
                approval_id=payload["approval_id"],
                tool_call_id=payload["tool_call_id"],
                decision="deny",
            )
            unresolved_tool_calls.add(payload["tool_call_id"])
        return unresolved_tool_calls

    def _close_tool_calls(
        self,
        recorder: RunRecorder,
        events: list[dict[str, Any]],
        *,
        unresolved_approvals: set[str],
    ) -> None:
        calls: dict[str, dict[str, Any]] = {}
        for event in events:
            if event["event_type"] != EventType.MESSAGE.value:
                continue
            for call in event["payload"].get("tool_calls", []):
                if isinstance(call, dict) and isinstance(call.get("id"), str):
                    calls[call["id"]] = call

        starts = {
            event["payload"]["tool_call_id"]: event
            for event in events
            if event["event_type"] == EventType.TOOL_STARTED.value
        }
        results = {
            event["payload"]["tool_call_id"]: event["payload"]
            for event in events
            if event["event_type"] == EventType.TOOL_RESULT.value
        }
        messages = {
            event["payload"]["tool_call_id"]
            for event in events
            if event["event_type"] == EventType.MESSAGE.value
            and event["payload"]["role"] == "tool"
        }

        for tool_call_id, call in calls.items():
            if tool_call_id in messages:
                continue
            name = str(call.get("name") or "unknown_tool")
            result = results.get(tool_call_id)
            if result is None and tool_call_id not in unresolved_approvals:
                start = starts.get(tool_call_id)
                if start is None:
                    handle = recorder.tool_started(
                        tool_call_id=tool_call_id,
                        name=name,
                        args=call.get("args") if isinstance(call.get("args"), dict) else {},
                    )
                else:
                    handle = None
                failure = RunInterruptedError(
                    "工具执行期间应用退出，执行结果未知"
                )
                if handle is not None:
                    recorder.tool_failed(handle, name=name, error=failure)
                else:
                    payload: dict[str, Any] = {
                        "tool_call_id": tool_call_id,
                        "name": name,
                        "status": "error",
                        "duration_ms": _elapsed_ms(
                            start["timestamp"], self.event_log.now()
                        ),
                        "error": _serialized_interruption(failure),
                    }
                    execution = start["payload"].get("execution")
                    if execution:
                        payload["execution"] = execution
                    self.event_log.append(
                        thread_id=recorder.thread_id,
                        turn_number=recorder.turn_number,
                        event_type=EventType.TOOL_RESULT,
                        payload=payload,
                    )
                result = payload if handle is None else {
                    "status": "error",
                    "error": _serialized_interruption(failure),
                }

            content = _tool_message_content(
                tool_call_id,
                name,
                result,
                approval_interrupted=tool_call_id in unresolved_approvals,
            )
            recorder.message_created(
                ToolMessage(
                    id=_recovery_message_id(
                        recorder.thread_id,
                        recorder.turn_number,
                        tool_call_id,
                    ),
                    tool_call_id=tool_call_id,
                    status="error" if not result or result["status"] == "error" else "success",
                    content=content,
                )
            )


def _tool_message_content(
    tool_call_id: str,
    name: str,
    result: dict[str, Any] | None,
    *,
    approval_interrupted: bool,
) -> str:
    if result and result["status"] == "success":
        payload = {
            "ok": True,
            "status": "success",
            "tool_call_id": tool_call_id,
            "tool": name,
            "data": result.get("result"),
            "error": None,
        }
    else:
        error = (
            result.get("error")
            if result
            else {
                "type": "RunInterruptedError",
                "message": (
                    "应用退出时仍在等待批准，本次工具调用未执行"
                    if approval_interrupted
                    else "工具执行期间应用退出，执行结果未知"
                ),
            }
        )
        payload = {
            "ok": False,
            "status": "error",
            "tool_call_id": tool_call_id,
            "tool": name,
            "data": None,
            "error": {
                "code": "run_interrupted",
                "message": error.get("message", "应用退出导致工具调用中断"),
                "retryable": True,
            },
        }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _recovery_message_id(thread_id: str, turn_number: int, tool_call_id: str) -> str:
    return str(uuid5(UUID(thread_id), f"recovery:{turn_number}:{tool_call_id}"))


def _serialized_interruption(error: RunInterruptedError) -> dict[str, str]:
    return {"type": type(error).__name__, "message": str(error)}


def _elapsed_ms(started_at: str, ended_at: datetime) -> float:
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    ended = ended_at.astimezone(timezone.utc)
    return max(0.0, (ended - started).total_seconds() * 1000)

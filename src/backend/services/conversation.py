import base64
import json
import mimetypes
import threading
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.types import Command, Interrupt

from src.backend.agent.context import AgentContext, ModelProvider, PermissionMode
from src.backend.agent.state import FinalizationResult
from src.backend.services.event_log import EventLogService, EventType, event_log
from src.backend.services.history import HistoryService
from src.backend.services.recorder import RunRecorder
from src.backend.services.recovery import (
    ConversationRecoveryService,
    ThreadRecoveryResult,
)
from src.backend.services.state_rebuilder import restore_checkpoint_from_event_log
from src.backend.services.cancellation import (
    RunCancelledError,
    RunRegistry,
)


@dataclass(frozen=True)
class ImageInput:
    """一张由外部本地路径提交的图片。"""

    path: str
    name: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class ApprovalRequest:
    """一个正在等待用户决定的工具或项目外路径调用。"""

    approval_id: str
    tool_call_id: str
    name: str
    args: dict[str, Any]
    reason: Literal["mutation", "external_path"] = "mutation"
    paths: tuple[dict[str, str], ...] = ()


class ModelExecutionSummary(TypedDict):
    calls: int
    succeeded: int
    failed: int
    duration_ms: float
    input_tokens: int
    output_tokens: int
    total_tokens: int


class ToolExecutionSummary(TypedDict):
    total: int
    succeeded: int
    failed: int
    denied: int
    rounds: int
    limit_reached: bool
    duration_ms: float


class ApprovalExecutionSummary(TypedDict):
    requested: int
    allowed: int
    denied: int


class TurnExecutionSummary(TypedDict):
    duration_ms: float
    model: ModelExecutionSummary
    tools: ToolExecutionSummary
    approvals: ApprovalExecutionSummary


@dataclass(frozen=True)
class TurnResult:
    """一轮调用完成后返回的稳定标识和 State。"""

    thread_id: str
    turn_number: int
    input_message_id: str
    status: Literal["completed", "awaiting_approval"]
    final_message_id: str | None
    approval_request: ApprovalRequest | None
    state: dict[str, Any]
    finalization: FinalizationResult | None = None
    execution_summary: TurnExecutionSummary | None = None


@dataclass(frozen=True)
class ModelChunkEvent:
    """模型真正生成的一个消息 chunk。"""

    chunk: Any
    metadata: dict[str, Any]
    type: Literal["model_chunk"] = "model_chunk"


@dataclass(frozen=True)
class StatusStreamEvent:
    """程序产生的实时阶段状态。"""

    stage: Literal["context", "model", "approval", "tool", "summary"]
    message: str
    tool_call_id: str | None = None
    tool_name: str | None = None
    type: Literal["status"] = "status"


@dataclass(frozen=True)
class ToolStreamEvent:
    """工具的真实执行状态，与助手正文分开传输。"""

    tool_call_id: str
    name: str
    args: dict[str, Any]
    status: Literal["running", "success", "error", "denied"]
    result: Any = None
    type: Literal["tool"] = "tool"


@dataclass(frozen=True)
class ApprovalStreamEvent:
    """当前 turn 因工具审批暂停。"""

    approval_request: ApprovalRequest
    result: TurnResult
    type: Literal["approval"] = "approval"


@dataclass(frozen=True)
class TurnResultStreamEvent:
    """当前 turn 的最终结果。"""

    result: TurnResult
    type: Literal["result"] = "result"


@dataclass(frozen=True)
class ErrorStreamEvent:
    """当前流的结构化错误通知。"""

    error_type: str
    message: str
    type: Literal["error"] = "error"


TurnStreamEvent = (
    ModelChunkEvent
    | StatusStreamEvent
    | ToolStreamEvent
    | ApprovalStreamEvent
    | TurnResultStreamEvent
    | ErrorStreamEvent
)


class ConversationError(RuntimeError):
    """对话协调错误。"""


class ConversationCoordinator:
    """
    协调 JSONL 事件源、LangGraph checkpoint 和 History 投影。

    JSONL 先记录运行事实，Graph 只接收轻量 State，History 在每轮结束
    或异常后从 JSONL 增量补齐。
    """

    def __init__(
        self,
        *,
        graph: Any,
        history_service: HistoryService,
        event_log_service: EventLogService = event_log,
        run_registry: RunRegistry | None = None,
    ) -> None:
        self.graph = graph
        self.history = history_service
        self.event_log = event_log_service
        self.runs = run_registry or RunRegistry()
        self.recovery = ConversationRecoveryService(
            graph=graph,
            event_log_service=event_log_service,
        )

    def cancel_run(self, thread_id: str, run_id: str) -> bool:
        return self.runs.cancel(thread_id, run_id)

    def cancel_all(self) -> int:
        return self.runs.cancel_all()

    def recover_unfinished_turns(self) -> tuple[ThreadRecoveryResult, ...]:
        """启动阶段修复所有崩溃遗留轮次，并同步 History 投影。"""
        results: list[ThreadRecoveryResult] = []
        for thread_id in self.event_log.iter_thread_ids():
            with _lock_for(thread_id):
                result = self.recovery.recover_thread(thread_id)
                if result.changed:
                    self.history.sync_thread(thread_id)
                results.append(result)
        return tuple(results)

    def _recover_thread_before_new_turn(self, thread_id: str) -> None:
        result = self.recovery.recover_thread(thread_id)
        if result.changed:
            self.history.sync_thread(thread_id)

    def create_thread(self, *, user_id: str, workspace_path: str) -> str:
        thread_id = str(uuid4())
        normalized_workspace = str(Path(workspace_path).expanduser().resolve())
        self.event_log.create_thread_log(
            thread_id=thread_id,
            user_id=user_id,
            workspace_path=normalized_workspace,
        )
        self.history.sync_thread(thread_id)
        return thread_id

    def run_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        workspace_path: str,
        accessible_paths: Sequence[str] = (),
        content: str,
        images: Sequence[ImageInput] = (),
        referenced_attachment_ids: Sequence[str] = (),
        permission: PermissionMode = PermissionMode.REQUEST_APPROVAL,
        provider: ModelProvider = ModelProvider.SILICONFLOW,
        model_name: str = "Qwen/Qwen3.5-4B",
    ) -> TurnResult:
        with _lock_for(thread_id):
            self._recover_thread_before_new_turn(thread_id)
            permission = _normalize_permission(permission)
            provider = _normalize_provider(provider)
            if not isinstance(model_name, str) or not model_name.strip():
                raise ConversationError("model_name 必须是非空字符串")
            events = list(self.event_log.iter_events(thread_id))
            normalized_workspace = str(Path(workspace_path).expanduser().resolve())
            _validate_thread_identity(events, user_id, normalized_workspace)
            _ensure_no_running_turn(events)
            self._restore_missing_checkpoint(thread_id, events)

            turn_number = max(
                (event["turn_number"] or 0 for event in events),
                default=0,
            ) + 1
            input_message_id = str(uuid4())
            prepared_images = [
                _prepare_image(image, input_message_id) for image in images
            ]
            known_attachment_ids = {
                event["payload"]["attachment_id"]
                for event in events
                if event["event_type"] == EventType.ATTACHMENT_ADDED.value
            }
            unknown = set(referenced_attachment_ids) - known_attachment_ids
            if unknown:
                raise ConversationError(
                    f"引用了不存在的附件：{sorted(unknown)}"
                )
            selected_attachment_ids = list(dict.fromkeys([
                *referenced_attachment_ids,
                *(image["attachment_id"] for image in prepared_images),
            ]))

            recorder = RunRecorder(
                thread_id=thread_id,
                turn_number=turn_number,
                event_log_service=self.event_log,
            )
            turn_handle = recorder.turn_started(
                input_message_id,
                provider=provider.value,
                model_name=model_name,
                permission=permission.value,
            )
            for image in prepared_images:
                recorder.attachment_added(
                    attachment_id=image["attachment_id"],
                    message_id=input_message_id,
                    name=image["name"],
                    mime_type=image["mime_type"],
                    path=image["url"],
                    size=image["size"],
                    base64_data=image["base64_data"],
                )
            user_message = recorder.message_created(
                HumanMessage(id=input_message_id, content=content),
                attachment_ids=selected_attachment_ids,
            )
            state_attachments = {
                image["attachment_id"]: {
                    key: value
                    for key, value in image.items()
                    if key != "base64_data"
                }
                for image in prepared_images
            }
            graph_input = {
                "messages": [user_message],
                "attachments": state_attachments,
                "prepare": {
                    "turn_number": turn_number,
                    "input_message_id": input_message_id,
                    "selected_attachment_ids": selected_attachment_ids,
                },
                "tool_execution_plan": None,
                "tool_loop": {
                    "round_count": 0,
                    "failure_counts": {},
                    "force_final_response": False,
                    "total_calls": 0,
                    "succeeded_calls": 0,
                    "failed_calls": 0,
                    "denied_calls": 0,
                    "tool_call_ids": [],
                },
                "finalization": None,
            }
            context = AgentContext(
                user_id=user_id,
                workspace_path=normalized_workspace,
                accessible_paths=_normalize_accessible_paths(normalized_workspace, accessible_paths),
                permission=permission,
                provider=provider,
                model_name=model_name,
                recorder=recorder,
            )
            config = {
                "configurable": {"thread_id": thread_id},
                "run_id": uuid4(),
            }

            try:
                state = self.graph.invoke(graph_input, config, context=context)
                interrupt_value = _single_interrupt(state)
                if interrupt_value is not None:
                    approval = _approval_request(interrupt_value)
                    recorder.approval_requested(
                        approval_id=approval.approval_id,
                        tool_call_id=approval.tool_call_id,
                        name=approval.name,
                        args=approval.args,
                    )
                    return TurnResult(
                        thread_id=thread_id,
                        turn_number=turn_number,
                        input_message_id=input_message_id,
                        status="awaiting_approval",
                        final_message_id=None,
                        approval_request=approval,
                        state=state,
                    )

                final_message = _final_ai_message(state)
                recorder.turn_succeeded(turn_handle, final_message_id=final_message.id)
                finalization = _finalization_from_state(state)
                execution_summary = _turn_execution_summary(
                    list(self.event_log.iter_events(thread_id)),
                    turn_number,
                    finalization,
                )
            except BaseException as error:
                recorder.turn_failed(turn_handle, error)
                raise
            finally:
                self.history.sync_thread(thread_id)

            return TurnResult(
                thread_id=thread_id,
                turn_number=turn_number,
                input_message_id=input_message_id,
                status="completed",
                final_message_id=final_message.id,
                approval_request=None,
                state=state,
                finalization=finalization,
                execution_summary=execution_summary,
            )

    def stream_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        workspace_path: str,
        accessible_paths: Sequence[str] = (),
        content: str,
        images: Sequence[ImageInput] = (),
        referenced_attachment_ids: Sequence[str] = (),
        permission: PermissionMode = PermissionMode.REQUEST_APPROVAL,
        provider: ModelProvider = ModelProvider.SILICONFLOW,
        model_name: str = "Qwen/Qwen3.5-4B",
        run_id: str | None = None,
    ) -> Generator[TurnStreamEvent, None, None]:
        """流式执行新 turn，同时输出模型 chunk 和程序状态。"""
        with _lock_for(thread_id):
            self._recover_thread_before_new_turn(thread_id)
            permission = _normalize_permission(permission)
            provider = _normalize_provider(provider)
            if not isinstance(model_name, str) or not model_name.strip():
                raise ConversationError("model_name 必须是非空字符串")
            events = list(self.event_log.iter_events(thread_id))
            normalized_workspace = str(Path(workspace_path).expanduser().resolve())
            _validate_thread_identity(events, user_id, normalized_workspace)
            _ensure_no_running_turn(events)
            self._restore_missing_checkpoint(thread_id, events)

            turn_number = max(
                (event["turn_number"] or 0 for event in events),
                default=0,
            ) + 1
            input_message_id = str(uuid4())
            prepared_images = [
                _prepare_image(image, input_message_id) for image in images
            ]
            known_attachment_ids = {
                event["payload"]["attachment_id"]
                for event in events
                if event["event_type"] == EventType.ATTACHMENT_ADDED.value
            }
            unknown = set(referenced_attachment_ids) - known_attachment_ids
            if unknown:
                raise ConversationError(
                    f"引用了不存在的附件：{sorted(unknown)}"
                )
            selected_attachment_ids = list(dict.fromkeys([
                *referenced_attachment_ids,
                *(image["attachment_id"] for image in prepared_images),
            ]))

            recorder = RunRecorder(
                thread_id=thread_id,
                turn_number=turn_number,
                event_log_service=self.event_log,
            )
            turn_handle = recorder.turn_started(
                input_message_id,
                provider=provider.value,
                model_name=model_name,
                permission=permission.value,
            )
            for image in prepared_images:
                recorder.attachment_added(
                    attachment_id=image["attachment_id"],
                    message_id=input_message_id,
                    name=image["name"],
                    mime_type=image["mime_type"],
                    path=image["url"],
                    size=image["size"],
                    base64_data=image["base64_data"],
                )
            user_message = recorder.message_created(
                HumanMessage(id=input_message_id, content=content),
                attachment_ids=selected_attachment_ids,
            )
            state_attachments = {
                image["attachment_id"]: {
                    key: value
                    for key, value in image.items()
                    if key != "base64_data"
                }
                for image in prepared_images
            }
            graph_input = {
                "messages": [user_message],
                "attachments": state_attachments,
                "prepare": {
                    "turn_number": turn_number,
                    "input_message_id": input_message_id,
                    "selected_attachment_ids": selected_attachment_ids,
                },
                "tool_execution_plan": None,
                "tool_loop": {
                    "round_count": 0,
                    "failure_counts": {},
                    "force_final_response": False,
                    "total_calls": 0,
                    "succeeded_calls": 0,
                    "failed_calls": 0,
                    "denied_calls": 0,
                    "tool_call_ids": [],
                },
                "finalization": None,
            }
            active_run_id = run_id or str(uuid4())
            cancellation = self.runs.begin(thread_id, active_run_id)
            context = AgentContext(
                user_id=user_id,
                workspace_path=normalized_workspace,
                accessible_paths=_normalize_accessible_paths(normalized_workspace, accessible_paths),
                permission=permission,
                provider=provider,
                model_name=model_name,
                recorder=recorder,
                cancellation=cancellation,
            )
            config = {
                "configurable": {"thread_id": thread_id},
                "run_id": active_run_id,
            }

            turn_recorded = False
            try:
                yield from self._stream_graph(graph_input, config, context)
                state = _state_after_stream(self.graph, config)
                interrupt_value = _single_interrupt(state)
                if interrupt_value is not None:
                    approval = _approval_request(interrupt_value)
                    recorder.approval_requested(
                        approval_id=approval.approval_id,
                        tool_call_id=approval.tool_call_id,
                        name=approval.name,
                        args=approval.args,
                    )
                    result = TurnResult(
                        thread_id=thread_id,
                        turn_number=turn_number,
                        input_message_id=input_message_id,
                        status="awaiting_approval",
                        final_message_id=None,
                        approval_request=approval,
                        state=state,
                    )
                    yield ApprovalStreamEvent(approval, result)
                    return

                final_message = _final_ai_message(state)
                recorder.turn_succeeded(turn_handle, final_message_id=final_message.id)
                turn_recorded = True
                finalization = _finalization_from_state(state)
                execution_summary = _turn_execution_summary(
                    list(self.event_log.iter_events(thread_id)),
                    turn_number,
                    finalization,
                )
                yield TurnResultStreamEvent(
                    TurnResult(
                        thread_id=thread_id,
                        turn_number=turn_number,
                        input_message_id=input_message_id,
                        status="completed",
                        final_message_id=final_message.id,
                        approval_request=None,
                        state=state,
                        finalization=finalization,
                        execution_summary=execution_summary,
                    )
                )
            except GeneratorExit:
                cancellation.cancel()
                if not turn_recorded:
                    recorder.turn_failed(turn_handle, RunCancelledError("任务已停止"))
                raise
            except RunCancelledError as error:
                recorder.turn_failed(turn_handle, error)
                turn_recorded = True
                yield ErrorStreamEvent(type(error).__name__, str(error))
                raise
            except Exception as error:
                recorder.turn_failed(turn_handle, error)
                yield ErrorStreamEvent(type(error).__name__, str(error))
                raise
            finally:
                self.runs.finish(thread_id, active_run_id)
                self.history.sync_thread(thread_id)

    def resume_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        workspace_path: str,
        accessible_paths: Sequence[str] = (),
        approval_id: str,
        tool_call_id: str,
        decision: Literal["allow", "deny"],
    ) -> TurnResult:
        """使用用户对当前 interrupt 的决定恢复同一轮 Graph。"""
        if decision not in {"allow", "deny"}:
            raise ConversationError("审批决定必须是 allow 或 deny")

        with _lock_for(thread_id):
            events = list(self.event_log.iter_events(thread_id))
            normalized_workspace = str(Path(workspace_path).expanduser().resolve())
            _validate_thread_identity(events, user_id, normalized_workspace)
            turn_number = _single_running_turn(events)
            started = next(
                event
                for event in events
                if event["event_type"] == EventType.TURN_STARTED.value
                and event["turn_number"] == turn_number
            )
            input_message_id = started["payload"]["input_message_id"]
            permission, provider, model_name = _turn_runtime_configuration(started)
            config = {
                "configurable": {"thread_id": thread_id},
                "run_id": uuid4(),
            }
            snapshot = self.graph.get_state(config)
            active_interrupts = tuple(getattr(snapshot, "interrupts", ()))
            if len(active_interrupts) != 1:
                raise ConversationError("thread 当前不是唯一工具审批等待状态")
            active = active_interrupts[0]
            approval = _approval_request(active)
            if approval.approval_id != approval_id:
                raise ConversationError("审批 ID 已过期或与当前请求不匹配")
            if approval.tool_call_id != tool_call_id:
                raise ConversationError("审批结果与当前工具调用不匹配")

            recorder = RunRecorder(
                thread_id=thread_id,
                turn_number=turn_number,
                event_log_service=self.event_log,
            )
            recorder.approval_decided(
                approval_id=approval_id,
                tool_call_id=tool_call_id,
                decision=decision,
            )
            context = AgentContext(
                user_id=user_id,
                workspace_path=normalized_workspace,
                accessible_paths=_normalize_accessible_paths(normalized_workspace, accessible_paths),
                permission=permission,
                provider=provider,
                model_name=model_name,
                recorder=recorder,
            )

            try:
                state = self.graph.invoke(
                    Command(
                        resume={
                            "tool_call_id": tool_call_id,
                            "decision": decision,
                        }
                    ),
                    config,
                    context=context,
                )
                interrupt_value = _single_interrupt(state)
                if interrupt_value is not None:
                    next_approval = _approval_request(interrupt_value)
                    recorder.approval_requested(
                        approval_id=next_approval.approval_id,
                        tool_call_id=next_approval.tool_call_id,
                        name=next_approval.name,
                        args=next_approval.args,
                    )
                    return TurnResult(
                        thread_id=thread_id,
                        turn_number=turn_number,
                        input_message_id=input_message_id,
                        status="awaiting_approval",
                        final_message_id=None,
                        approval_request=next_approval,
                        state=state,
                    )

                final_message = _final_ai_message(state)
                recorder.turn_succeeded(
                    None,
                    final_message_id=final_message.id,
                    duration_ms=_elapsed_turn_ms(
                        started["timestamp"],
                        self.event_log.now(),
                    ),
                )
                finalization = _finalization_from_state(state)
                execution_summary = _turn_execution_summary(
                    list(self.event_log.iter_events(thread_id)),
                    turn_number,
                    finalization,
                )
            except Exception as error:
                recorder.turn_failed(
                    None,
                    error,
                    duration_ms=_elapsed_turn_ms(
                        started["timestamp"],
                        self.event_log.now(),
                    ),
                )
                raise
            finally:
                self.history.sync_thread(thread_id)

            return TurnResult(
                thread_id=thread_id,
                turn_number=turn_number,
                input_message_id=input_message_id,
                status="completed",
                final_message_id=final_message.id,
                approval_request=None,
                state=state,
                finalization=finalization,
                execution_summary=execution_summary,
            )

    def stream_resume_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        workspace_path: str,
        accessible_paths: Sequence[str] = (),
        approval_id: str,
        tool_call_id: str,
        decision: Literal["allow", "deny"],
        run_id: str | None = None,
    ) -> Generator[TurnStreamEvent, None, None]:
        """流式恢复同一 turn 的工具审批 interrupt。"""
        if decision not in {"allow", "deny"}:
            raise ConversationError("审批决定必须是 allow 或 deny")

        with _lock_for(thread_id):
            events = list(self.event_log.iter_events(thread_id))
            normalized_workspace = str(Path(workspace_path).expanduser().resolve())
            _validate_thread_identity(events, user_id, normalized_workspace)
            turn_number = _single_running_turn(events)
            started = next(
                event
                for event in events
                if event["event_type"] == EventType.TURN_STARTED.value
                and event["turn_number"] == turn_number
            )
            input_message_id = started["payload"]["input_message_id"]
            permission, provider, model_name = _turn_runtime_configuration(started)
            config = {
                "configurable": {"thread_id": thread_id},
                "run_id": uuid4(),
            }
            snapshot = self.graph.get_state(config)
            active_interrupts = tuple(getattr(snapshot, "interrupts", ()))
            if len(active_interrupts) != 1:
                raise ConversationError("thread 当前不是唯一工具审批等待状态")
            approval = _approval_request(active_interrupts[0])
            if approval.approval_id != approval_id:
                raise ConversationError("审批 ID 已过期或与当前请求不匹配")
            if approval.tool_call_id != tool_call_id:
                raise ConversationError("审批结果与当前工具调用不匹配")

            recorder = RunRecorder(
                thread_id=thread_id,
                turn_number=turn_number,
                event_log_service=self.event_log,
            )
            recorder.approval_decided(
                approval_id=approval_id,
                tool_call_id=tool_call_id,
                decision=decision,
            )
            active_run_id = run_id or str(uuid4())
            cancellation = self.runs.begin(thread_id, active_run_id)
            context = AgentContext(
                user_id=user_id,
                workspace_path=normalized_workspace,
                accessible_paths=_normalize_accessible_paths(normalized_workspace, accessible_paths),
                permission=permission,
                provider=provider,
                model_name=model_name,
                recorder=recorder,
                cancellation=cancellation,
            )

            config["run_id"] = active_run_id

            turn_recorded = False
            try:
                yield from self._stream_graph(
                    Command(
                        resume={
                            "tool_call_id": tool_call_id,
                            "decision": decision,
                        }
                    ),
                    config,
                    context,
                )
                state = _state_after_stream(self.graph, config)
                interrupt_value = _single_interrupt(state)
                if interrupt_value is not None:
                    next_approval = _approval_request(interrupt_value)
                    recorder.approval_requested(
                        approval_id=next_approval.approval_id,
                        tool_call_id=next_approval.tool_call_id,
                        name=next_approval.name,
                        args=next_approval.args,
                    )
                    result = TurnResult(
                        thread_id=thread_id,
                        turn_number=turn_number,
                        input_message_id=input_message_id,
                        status="awaiting_approval",
                        final_message_id=None,
                        approval_request=next_approval,
                        state=state,
                    )
                    yield ApprovalStreamEvent(next_approval, result)
                    return

                final_message = _final_ai_message(state)
                recorder.turn_succeeded(
                    None,
                    final_message_id=final_message.id,
                    duration_ms=_elapsed_turn_ms(
                        started["timestamp"],
                        self.event_log.now(),
                    ),
                )
                turn_recorded = True
                finalization = _finalization_from_state(state)
                execution_summary = _turn_execution_summary(
                    list(self.event_log.iter_events(thread_id)),
                    turn_number,
                    finalization,
                )
                yield TurnResultStreamEvent(
                    TurnResult(
                        thread_id=thread_id,
                        turn_number=turn_number,
                        input_message_id=input_message_id,
                        status="completed",
                        final_message_id=final_message.id,
                        approval_request=None,
                        state=state,
                        finalization=finalization,
                        execution_summary=execution_summary,
                    )
                )
            except GeneratorExit:
                cancellation.cancel()
                if not turn_recorded:
                    recorder.turn_failed(
                        None,
                        RunCancelledError("任务已停止"),
                        duration_ms=_elapsed_turn_ms(
                            started["timestamp"],
                            self.event_log.now(),
                        ),
                    )
                raise
            except BaseException as error:
                recorder.turn_failed(
                    None,
                    error,
                    duration_ms=_elapsed_turn_ms(
                        started["timestamp"],
                        self.event_log.now(),
                    ),
                )
                turn_recorded = True
                yield ErrorStreamEvent(type(error).__name__, str(error))
                raise
            finally:
                self.runs.finish(thread_id, active_run_id)
                self.history.sync_thread(thread_id)

    def _stream_graph(
        self,
        graph_input: Any,
        config: dict[str, Any],
        context: AgentContext,
    ) -> Generator[TurnStreamEvent, None, None]:
        stream = self.graph.stream(
            graph_input,
            config,
            context=context,
            stream_mode=["messages", "custom", "values"],
        )
        try:
            for mode, data in stream:
                context.cancellation.raise_if_cancelled()
                if mode == "messages":
                    chunk, metadata = data
                    if (
                        isinstance(chunk, (AIMessage, AIMessageChunk))
                        and metadata.get("langgraph_node") == "model"
                    ):
                        yield ModelChunkEvent(chunk=chunk, metadata=dict(metadata))
                elif mode == "custom":
                    if isinstance(data, dict) and data.get("type") == "tool":
                        yield ToolStreamEvent(
                            tool_call_id=data["tool_call_id"],
                            name=data["name"],
                            args=data["args"],
                            status=data["status"],
                            result=data.get("result"),
                        )
                    else:
                        yield _status_stream_event(data)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()

    def _restore_missing_checkpoint(
        self,
        thread_id: str,
        events: list[dict[str, Any]],
    ) -> None:
        if not any(
            event["event_type"] == EventType.MESSAGE.value for event in events
        ):
            return
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = self.graph.get_state(config)
        if not snapshot.values:
            restore_checkpoint_from_event_log(
                self.graph,
                thread_id,
                event_log_service=self.event_log,
            )


def create_conversation_coordinator() -> ConversationCoordinator:
    """使用项目默认 Graph、JSONL 和 History DB 创建协调器。"""
    from src.backend.agent.graph import graph
    from src.backend.services.history import create_history_service

    return ConversationCoordinator(
        graph=graph,
        history_service=create_history_service(),
        event_log_service=event_log,
    )


def _status_stream_event(value: Any) -> StatusStreamEvent:
    if not isinstance(value, dict) or value.get("type") != "status":
        raise ConversationError("收到了不可识别的 custom stream 事件")
    stage = value.get("stage")
    if stage not in {"context", "model", "approval", "tool", "summary"}:
        raise ConversationError("状态事件的 stage 无效")
    message = value.get("message")
    tool_call_id = value.get("tool_call_id")
    tool_name = value.get("tool_name")
    if not isinstance(message, str) or not message:
        raise ConversationError("状态事件的 message 必须是非空字符串")
    if tool_call_id is not None and not isinstance(tool_call_id, str):
        raise ConversationError("状态事件的 tool_call_id 无效")
    if tool_name is not None and not isinstance(tool_name, str):
        raise ConversationError("状态事件的 tool_name 无效")
    return StatusStreamEvent(
        stage=stage,
        message=message,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
    )


def _state_after_stream(graph: Any, config: dict[str, Any]) -> dict[str, Any]:
    """从 checkpoint 读取流结束时的完整 State 和 interrupt。"""
    snapshot = graph.get_state(config)
    state = dict(snapshot.values)
    interrupts = tuple(getattr(snapshot, "interrupts", ()))
    if interrupts:
        state["__interrupt__"] = list(interrupts)
    return state


def _prepare_image(image: ImageInput, message_id: str) -> dict[str, Any]:
    path = Path(image.path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"图片文件不存在：{path}")
    mime_type = image.mime_type or mimetypes.guess_type(path.name)[0]
    if not mime_type or not mime_type.startswith("image/"):
        raise ConversationError(f"附件不是可识别的图片：{path}")
    data = path.read_bytes()
    return {
        "attachment_id": str(uuid4()),
        "message_id": message_id,
        "name": image.name or path.name,
        "mime_type": mime_type,
        "url": str(path),
        "size": len(data),
        "base64_data": base64.b64encode(data).decode("ascii"),
    }


def _validate_thread_identity(
    events: list[dict[str, Any]],
    user_id: str,
    workspace_path: str,
) -> None:
    created = events[0]["payload"]
    if created["user_id"] != user_id:
        raise ConversationError("thread 不属于当前 user_id")
    if str(Path(created["workspace_path"]).expanduser().resolve()) != workspace_path:
        raise ConversationError("thread 的 workspace_path 与当前调用不一致")


def _normalize_accessible_paths(
    workspace_path: str,
    accessible_paths: Sequence[str],
) -> tuple[str, ...]:
    roots = [workspace_path]
    roots.extend(str(Path(item).expanduser().resolve()) for item in accessible_paths)
    return tuple(dict.fromkeys(roots))


def _ensure_no_running_turn(events: list[dict[str, Any]]) -> None:
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
    running = started - finished
    if running:
        raise ConversationError(f"thread 存在未收尾轮次：{sorted(running)}")


def _single_running_turn(events: list[dict[str, Any]]) -> int:
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
    running = started - finished
    if len(running) != 1:
        raise ConversationError("thread 不存在唯一未完成轮次")
    return next(iter(running))


def _single_interrupt(state: dict[str, Any]) -> Interrupt | None:
    interrupts = state.get("__interrupt__", [])
    if not interrupts:
        return None
    if len(interrupts) != 1:
        raise ConversationError("当前只支持一次处理一个工具审批")
    return interrupts[0]


def _approval_request(value: Interrupt) -> ApprovalRequest:
    payload = value.value
    if not isinstance(payload, dict) or payload.get("type") != "tool_approval":
        raise ConversationError("当前 interrupt 不是可识别的工具审批")
    tool_call_id = payload.get("tool_call_id")
    name = payload.get("name")
    args = payload.get("args")
    reason = payload.get("reason", "mutation")
    paths = payload.get("paths", [])
    if not isinstance(tool_call_id, str) or not isinstance(name, str):
        raise ConversationError("工具审批请求缺少标识字段")
    if not isinstance(args, dict):
        raise ConversationError("工具审批参数必须是对象")
    if reason not in {"mutation", "external_path"}:
        raise ConversationError("工具审批原因无效")
    if not isinstance(paths, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("argument"), str)
        or not isinstance(item.get("path"), str)
        or item.get("access") not in {"read", "write", "delete"}
        for item in paths
    ):
        raise ConversationError("工具审批路径信息无效")
    return ApprovalRequest(
        approval_id=value.id,
        tool_call_id=tool_call_id,
        name=name,
        args=dict(args),
        reason=reason,
        paths=tuple(dict(item) for item in paths),
    )


def _final_ai_message(state: dict[str, Any]) -> AIMessage:
    message = next(
        (
            message
            for message in reversed(state["messages"])
            if isinstance(message, AIMessage) and message.id
        ),
        None,
    )
    if message is None:
        raise ConversationError("本轮没有产生带 ID 的最终 AIMessage")
    return message


def _finalization_from_state(state: dict[str, Any]) -> FinalizationResult:
    """读取 finalize 节点结果，并兼容未实现该字段的旧 Graph。"""
    prepared = state.get("finalization")
    if isinstance(prepared, dict):
        return prepared  # type: ignore[return-value]

    final_message = _final_ai_message(state)
    tool_loop = state.get("tool_loop") or {}
    tool_call_ids = set(tool_loop.get("tool_call_ids", []))
    artifact_ids = [
        artifact_id
        for artifact_id, artifact in state.get("artifacts", {}).items()
        if artifact.get("tool_call_id") in tool_call_ids
    ]
    content = final_message.content
    return {
        "status": "completed",
        "message": {
            "message_id": final_message.id,
            "role": "assistant",
            "content": (
                content
                if isinstance(content, str)
                else json.dumps(
                    content,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            ),
        },
        "tools": {
            "total": int(tool_loop.get("total_calls", 0)),
            "succeeded": int(tool_loop.get("succeeded_calls", 0)),
            "failed": int(tool_loop.get("failed_calls", 0)),
            "denied": int(tool_loop.get("denied_calls", 0)),
            "rounds": int(tool_loop.get("round_count", 0)),
            "limit_reached": bool(
                tool_loop.get("force_final_response", False)
            ),
        },
        "artifact_ids": artifact_ids,
    }


def _turn_execution_summary(
    events: list[dict[str, Any]],
    turn_number: int,
    finalization: FinalizationResult,
) -> TurnExecutionSummary:
    """从 JSONL 运行事实聚合一个完整 turn 的耗时和用量。"""
    turn_events = [
        event for event in events
        if event.get("turn_number") == turn_number
    ]
    model_results = [
        event["payload"]
        for event in turn_events
        if event["event_type"] == EventType.MODEL_RESULT.value
    ]
    tool_results = [
        event["payload"]
        for event in turn_events
        if event["event_type"] == EventType.TOOL_RESULT.value
    ]
    approval_requests = [
        event for event in turn_events
        if event["event_type"] == EventType.APPROVAL_REQUESTED.value
    ]
    approval_decisions = [
        event["payload"]
        for event in turn_events
        if event["event_type"] == EventType.APPROVAL_DECIDED.value
    ]
    finished = next(
        (
            event["payload"]
            for event in reversed(turn_events)
            if event["event_type"] == EventType.TURN_FINISHED.value
        ),
        {},
    )

    input_tokens = output_tokens = total_tokens = 0
    for result in model_results:
        usage = result.get("usage") or {}
        input_tokens += _usage_count(usage, "input_tokens", "prompt_tokens")
        output_tokens += _usage_count(usage, "output_tokens", "completion_tokens")
        total_tokens += _usage_count(usage, "total_tokens", "total_tokens")

    tools = finalization["tools"]
    return {
        "duration_ms": float(finished.get("duration_ms", 0.0)),
        "model": {
            "calls": len(model_results),
            "succeeded": sum(
                result.get("status") == "success" for result in model_results
            ),
            "failed": sum(
                result.get("status") == "error" for result in model_results
            ),
            "duration_ms": sum(
                float(result.get("duration_ms", 0.0))
                for result in model_results
            ),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        },
        "tools": {
            **tools,
            "duration_ms": sum(
                float(result.get("duration_ms", 0.0))
                for result in tool_results
            ),
        },
        "approvals": {
            "requested": len(approval_requests),
            "allowed": sum(
                decision.get("decision") == "allow"
                for decision in approval_decisions
            ),
            "denied": sum(
                decision.get("decision") == "deny"
                for decision in approval_decisions
            ),
        },
    }


def _usage_count(
    usage: dict[str, Any],
    primary: str,
    fallback: str,
) -> int:
    value = usage.get(primary, usage.get(fallback, 0))
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _elapsed_turn_ms(started_at: str, finished_at: datetime) -> float:
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return max(0.0, (finished_at - started).total_seconds() * 1000)


def _normalize_permission(value: PermissionMode | str) -> PermissionMode:
    try:
        return PermissionMode(value)
    except ValueError as error:
        raise ConversationError(f"不支持的权限模式：{value}") from error


def _normalize_provider(value: ModelProvider | str) -> ModelProvider:
    try:
        return ModelProvider(value)
    except ValueError as error:
        raise ConversationError(f"不支持的模型供应商：{value}") from error


def _turn_runtime_configuration(
    turn_started: dict[str, Any],
) -> tuple[PermissionMode, ModelProvider, str]:
    payload = turn_started["payload"]
    permission = _normalize_permission(
        payload.get("permission", PermissionMode.REQUEST_APPROVAL.value)
    )
    provider = _normalize_provider(
        payload.get("provider", ModelProvider.SILICONFLOW.value)
    )
    model_name = payload.get("model_name", "Qwen/Qwen3.5-4B")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ConversationError("turn_started 中的 model_name 无效")
    return permission, provider, model_name


_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _lock_for(thread_id: str) -> threading.RLock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(thread_id, threading.RLock())

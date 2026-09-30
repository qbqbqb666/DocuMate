from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from src.backend.agent.state import AgentState
from src.backend.services.event_log import EventLogService, EventType, event_log


def rebuild_state_from_event_log(
    thread_id: str,
    *,
    event_log_service: EventLogService = event_log,
) -> AgentState:
    """从 JSONL 事件源重建一份不含 Base64 的 AgentState。"""
    messages: list[AnyMessage] = []
    attachments: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}
    latest_input_message_id: str | None = None
    latest_turn_number = 0
    attachment_ids_by_message: dict[str, list[str]] = {}

    for event in event_log_service.iter_events(thread_id):
        event_type = EventType(event["event_type"])
        payload = event["payload"]
        if event_type is EventType.TURN_STARTED:
            latest_turn_number = event["turn_number"]
            latest_input_message_id = payload["input_message_id"]
        elif event_type is EventType.ATTACHMENT_ADDED:
            attachment_id = payload["attachment_id"]
            attachments[attachment_id] = {
                "attachment_id": attachment_id,
                "message_id": payload["message_id"],
                "name": payload["name"],
                "mime_type": payload["mime_type"],
                "url": payload["path"],
                "size": payload["size"],
            }
        elif event_type is EventType.ARTIFACT_RECORDED:
            artifact_id = payload["artifact_id"]
            artifacts[artifact_id] = dict(payload)
        elif event_type is EventType.MESSAGE:
            message = _message_from_payload(payload)
            _upsert_message(messages, message)
            if payload["role"] == "user":
                attachment_ids_by_message[payload["message_id"]] = list(
                    payload.get("attachment_ids", [])
                )
        elif event_type is EventType.CONTEXT_COMPACTED:
            by_id = {message.id: message for message in messages if message.id}
            preserved = [
                by_id[message_id]
                for message_id in payload["preserved_message_ids"]
                if message_id in by_id
            ]
            messages = [
                HumanMessage(
                    id=payload["summary_message_id"],
                    content=payload["summary_content"],
                    additional_kwargs={"lc_source": "summarization"},
                ),
                *preserved,
            ]

    prepare = None
    if latest_input_message_id is not None:
        prepare = {
            "turn_number": latest_turn_number,
            "input_message_id": latest_input_message_id,
            "selected_attachment_ids": attachment_ids_by_message.get(
                latest_input_message_id,
                [],
            ),
        }
    return {
        "messages": messages,
        "attachments": attachments,
        "artifacts": artifacts,
        "prepare": prepare,
        "tool_execution_plan": None,
        "tool_loop": None,
        "finalization": None,
    }


def restore_checkpoint_from_event_log(
    graph: Any,
    thread_id: str,
    *,
    event_log_service: EventLogService = event_log,
) -> AgentState:
    """将 JSONL 重建结果写回给定 Graph 的 checkpointer。"""
    state = rebuild_state_from_event_log(
        thread_id,
        event_log_service=event_log_service,
    )
    graph.update_state(
        {"configurable": {"thread_id": thread_id}},
        state,
        as_node="finalize",
    )
    return state


def _message_from_payload(payload: dict[str, Any]) -> AnyMessage:
    common = {"id": payload["message_id"], "content": payload["content"]}
    if payload["role"] == "user":
        return HumanMessage(**common)
    if payload["role"] == "assistant":
        return AIMessage(tool_calls=payload.get("tool_calls", []), **common)
    return ToolMessage(tool_call_id=payload["tool_call_id"], **common)


def _upsert_message(messages: list[AnyMessage], message: AnyMessage) -> None:
    for index, existing in enumerate(messages):
        if existing.id == message.id:
            messages[index] = message
            return
    messages.append(message)

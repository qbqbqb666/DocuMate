import json
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from src.backend.main import create_app
from src.backend.services.conversation import (
    ApprovalRequest,
    ApprovalStreamEvent,
    ErrorStreamEvent,
    ModelChunkEvent,
    StatusStreamEvent,
    TurnResult,
    TurnResultStreamEvent,
)


WORKSPACE = "/tmp/documate-api-workspace"


def result(*, awaiting_approval: bool = False) -> TurnResult:
    approval = (
        ApprovalRequest(
            approval_id="approval-1",
            tool_call_id="tool-1",
            name="write_text_file",
            args={"relative_path": "笔记.txt", "content": "你好"},
        )
        if awaiting_approval
        else None
    )
    return TurnResult(
        thread_id="thread-1",
        turn_number=1,
        input_message_id="input-1",
        status="awaiting_approval" if awaiting_approval else "completed",
        final_message_id=None if awaiting_approval else "assistant-1",
        approval_request=approval,
        state={"private": "must-not-leak"},
        finalization=None,
        execution_summary=None,
    )


class FakeHistory:
    def close(self) -> None:
        pass


class StreamingCoordinator:
    def __init__(self, events: list[Any] | None = None) -> None:
        self.history = FakeHistory()
        self.events = events or []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.raise_during_stream: Exception | None = None

    def stream_turn(self, **kwargs: Any):
        self.calls.append(("stream_turn", kwargs))
        return self._events()

    def stream_resume_turn(self, **kwargs: Any):
        self.calls.append(("stream_resume_turn", kwargs))
        return self._events()

    def cancel_run(self, thread_id: str, run_id: str) -> bool:
        self.calls.append(("cancel_run", {"thread_id": thread_id, "run_id": run_id}))
        return True

    def _events(self):
        yield from self.events
        if self.raise_during_stream is not None:
            raise self.raise_during_stream


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    parsed: list[tuple[str, dict[str, Any]]] = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        name = next(line[6:].strip() for line in lines if line.startswith("event:"))
        data = next(line[5:].strip() for line in lines if line.startswith("data:"))
        parsed.append((name, json.loads(data)))
    return parsed


def test_stream_serializes_all_public_event_types() -> None:
    pending = result(awaiting_approval=True)
    completed = result()
    coordinator = StreamingCoordinator(
        [
            StatusStreamEvent(stage="model", message="正在生成回答"),
            ModelChunkEvent(
                chunk=AIMessageChunk(
                    id="assistant-1",
                    content=[
                        {"type": "text", "text": "你好"},
                        {"type": "text", "text": "，世界"},
                    ],
                ),
                metadata={"langgraph_node": "model", "private": object()},
            ),
            ApprovalStreamEvent(pending.approval_request, pending),
            TurnResultStreamEvent(completed),
            ErrorStreamEvent("ExampleError", "测试错误"),
        ]
    )

    with TestClient(create_app(coordinator)) as client:
        response = client.post(
            "/api/threads/thread-1/turns/stream",
            json={"workspace_path": WORKSPACE, "content": "请处理"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = parse_sse(response.text)
    assert [name for name, _ in events] == [
        "status",
        "model_chunk",
        "approval",
        "result",
        "error",
    ]
    assert events[1][1] == {
        "text": "你好，世界",
        "message_id": "assistant-1",
        "node": "model",
    }
    assert events[2][1]["approval"]["approval_id"] == "approval-1"
    assert "state" not in events[2][1]["turn"]
    assert "state" not in events[3][1]
    assert events[4][1]["error_type"] == "ExampleError"


def test_stream_maps_request_and_resume_request() -> None:
    coordinator = StreamingCoordinator()
    with TestClient(create_app(coordinator)) as client:
        turn = client.post(
            "/api/threads/thread-1/turns/stream",
            json={
                "workspace_path": WORKSPACE,
                "content": "hello",
                "provider": "deepseek",
                "model_name": "deepseek-flash",
            },
        )
        resume = client.post(
            "/api/threads/thread-1/approvals/approval-1/stream",
            json={
                "workspace_path": WORKSPACE,
                "tool_call_id": "tool-1",
                "decision": "allow",
            },
        )

    assert turn.status_code == 200
    assert resume.status_code == 200
    assert coordinator.calls[0] == (
        "stream_turn",
        {
            "thread_id": "thread-1",
            "user_id": "local-user",
            "workspace_path": WORKSPACE,
            "content": "hello",
            "referenced_attachment_ids": [],
            "permission": "request_approval",
            "provider": "deepseek",
            "model_name": "deepseek-flash",
        },
    )
    assert coordinator.calls[1] == (
        "stream_resume_turn",
        {
            "thread_id": "thread-1",
            "user_id": "local-user",
            "workspace_path": WORKSPACE,
            "approval_id": "approval-1",
            "tool_call_id": "tool-1",
            "decision": "allow",
        },
    )


def test_unreported_stream_exception_becomes_error_event() -> None:
    coordinator = StreamingCoordinator(
        [StatusStreamEvent(stage="model", message="已开始")]
    )
    coordinator.raise_during_stream = RuntimeError("模型连接失败")

    with TestClient(create_app(coordinator)) as client:
        response = client.post(
            "/api/threads/thread-1/turns/stream",
            json={"workspace_path": WORKSPACE, "content": "hello"},
        )

    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["status", "error"]
    assert events[-1][1] == {
        "code": "stream_error",
        "message": "模型连接失败",
        "error_type": "RuntimeError",
    }


def test_existing_error_event_is_not_duplicated_when_coordinator_reraises() -> None:
    coordinator = StreamingCoordinator(
        [ErrorStreamEvent("RuntimeError", "已结构化的错误")]
    )
    coordinator.raise_during_stream = RuntimeError("已结构化的错误")

    with TestClient(create_app(coordinator)) as client:
        response = client.post(
            "/api/threads/thread-1/turns/stream",
            json={"workspace_path": WORKSPACE, "content": "hello"},
        )

    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["error"]


def test_cancel_endpoint_targets_one_run() -> None:
    coordinator = StreamingCoordinator()
    with TestClient(create_app(coordinator)) as client:
        response = client.post("/api/threads/thread-1/runs/run-1/cancel")

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "thread-1",
        "run_id": "run-1",
        "cancelled": True,
    }
    assert coordinator.calls == [
        ("cancel_run", {"thread_id": "thread-1", "run_id": "run-1"})
    ]

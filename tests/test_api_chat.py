from typing import Any

from fastapi.testclient import TestClient

from src.backend.main import create_app
from src.backend.services.conversation import (
    ApprovalRequest,
    ConversationError,
    TurnResult,
)
from src.backend.services.event_log import EventLogNotFoundError


WORKSPACE = "/tmp/documate-api-workspace"


def completed_result() -> TurnResult:
    return TurnResult(
        thread_id="thread-1",
        turn_number=1,
        input_message_id="input-1",
        status="completed",
        final_message_id="assistant-1",
        approval_request=None,
        state={"private": "must-not-leak"},
        finalization={
            "status": "completed",
            "message": {
                "message_id": "assistant-1",
                "role": "assistant",
                "content": "已完成",
            },
            "tools": {
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "denied": 0,
                "rounds": 0,
                "limit_reached": False,
            },
            "artifact_ids": [],
        },
        execution_summary=None,
    )


def approval_result() -> TurnResult:
    approval = ApprovalRequest(
        approval_id="approval-1",
        tool_call_id="tool-1",
        name="write_text_file",
        args={"relative_path": "notes.txt"},
    )
    return TurnResult(
        thread_id="thread-1",
        turn_number=1,
        input_message_id="input-1",
        status="awaiting_approval",
        final_message_id=None,
        approval_request=approval,
        state={"private": "must-not-leak"},
    )


class FakeHistory:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeCoordinator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.history = FakeHistory()
        self.result = completed_result()
        self.error: Exception | None = None

    def _call(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        return self.result

    def create_thread(self, **kwargs: Any) -> str:
        self._call("create_thread", kwargs)
        return "thread-1"

    def run_turn(self, **kwargs: Any) -> TurnResult:
        return self._call("run_turn", kwargs)

    def resume_turn(self, **kwargs: Any) -> TurnResult:
        return self._call("resume_turn", kwargs)

    def stream_turn(self, **kwargs: Any):
        self.calls.append(("stream_turn", kwargs))
        return iter(())

    def stream_resume_turn(self, **kwargs: Any):
        self.calls.append(("stream_resume_turn", kwargs))
        return iter(())


def test_health_and_create_thread_route() -> None:
    coordinator = FakeCoordinator()
    with TestClient(create_app(coordinator)) as client:
        health = client.get("/api/health")
        response = client.post(
            "/api/threads",
            json={"workspace_path": WORKSPACE},
        )

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "documate-backend"}
    assert response.status_code == 201
    assert response.json() == {"thread_id": "thread-1"}
    assert coordinator.calls == [
        (
            "create_thread",
            {"user_id": "local-user", "workspace_path": WORKSPACE},
        )
    ]
    assert coordinator.history.closed is False


def test_run_turn_maps_request_and_hides_internal_state() -> None:
    coordinator = FakeCoordinator()
    with TestClient(create_app(coordinator)) as client:
        response = client.post(
            "/api/threads/thread-1/turns",
            json={
                "workspace_path": WORKSPACE,
                "content": "总结项目",
                "referenced_attachment_ids": ["attachment-1", "attachment-1"],
                "permission": "full_access",
                "provider": "deepseek",
                "model_name": "deepseek-flash",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["finalization"]["message"]["content"] == "已完成"
    assert "state" not in payload
    name, arguments = coordinator.calls[0]
    assert name == "run_turn"
    assert arguments == {
        "thread_id": "thread-1",
        "user_id": "local-user",
        "workspace_path": WORKSPACE,
        "content": "总结项目",
        "referenced_attachment_ids": ["attachment-1"],
        "permission": "full_access",
        "provider": "deepseek",
        "model_name": "deepseek-flash",
    }


def test_resume_turn_maps_approval_identity() -> None:
    coordinator = FakeCoordinator()
    coordinator.result = approval_result()
    with TestClient(create_app(coordinator)) as client:
        response = client.post(
            "/api/threads/thread-1/approvals/approval-1",
            json={
                "workspace_path": WORKSPACE,
                "tool_call_id": "tool-1",
                "decision": "deny",
            },
        )

    assert response.status_code == 200
    assert response.json()["approval"]["approval_id"] == "approval-1"
    assert coordinator.calls == [
        (
            "resume_turn",
            {
                "thread_id": "thread-1",
                "user_id": "local-user",
                "workspace_path": WORKSPACE,
                "approval_id": "approval-1",
                "tool_call_id": "tool-1",
                "decision": "deny",
            },
        )
    ]


def test_request_validation_rejects_invalid_values_before_coordinator() -> None:
    coordinator = FakeCoordinator()
    invalid_bodies = [
        {
            "workspace_path": WORKSPACE,
            "content": "   ",
        },
        {
            "workspace_path": WORKSPACE,
            "content": "hello",
            "provider": "unknown",
        },
        {
            "workspace_path": WORKSPACE,
            "content": "hello",
            "permission": "unsafe",
        },
    ]

    with TestClient(create_app(coordinator)) as client:
        responses = [
            client.post("/api/threads/thread-1/turns", json=body)
            for body in invalid_bodies
        ]
        invalid_decision = client.post(
            "/api/threads/thread-1/approvals/approval-1",
            json={
                "workspace_path": WORKSPACE,
                "tool_call_id": "tool-1",
                "decision": "allow_once",
            },
        )

    assert all(response.status_code == 422 for response in responses)
    assert invalid_decision.status_code == 422
    assert all(
        response.json()["error"]["code"] == "validation_error"
        for response in [*responses, invalid_decision]
    )
    assert coordinator.calls == []


def test_conversation_and_not_found_errors_have_stable_http_shape() -> None:
    coordinator = FakeCoordinator()
    with TestClient(create_app(coordinator)) as client:
        coordinator.error = ConversationError("thread 已有未完成的 turn")
        conflict = client.post(
            "/api/threads/thread-1/turns",
            json={"workspace_path": WORKSPACE, "content": "hello"},
        )

        coordinator.error = EventLogNotFoundError("找不到 thread JSONL：thread-2")
        missing = client.post(
            "/api/threads/thread-2/turns",
            json={"workspace_path": WORKSPACE, "content": "hello"},
        )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conversation_conflict"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "thread_not_found"


def test_workspace_identity_error_is_forbidden() -> None:
    coordinator = FakeCoordinator()
    coordinator.error = ConversationError("thread workspace_path 不匹配")
    with TestClient(create_app(coordinator)) as client:
        response = client.post(
            "/api/threads/thread-1/turns",
            json={"workspace_path": WORKSPACE, "content": "hello"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "conversation_forbidden"

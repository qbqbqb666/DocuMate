from typing import Any

from fastapi.testclient import TestClient

from src.backend.main import create_app
from src.backend.services.history import HistoryNotFoundError


WORKSPACE = "/tmp/documate-api-workspace"


class FakeHistory:
    def list_threads(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{
            "thread_id": "thread-1",
            "created_at": "2026-09-21T10:00:00Z",
            "updated_at": "2026-09-21T10:01:00Z",
            "last_turn_number": 1,
            "message_count": 2,
            "preview": "hello",
            "last_turn_status": "success",
        }]

    def get_thread(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs["thread_id"] == "missing":
            raise HistoryNotFoundError("找不到 thread：missing")
        return {
            "thread_id": kwargs["thread_id"],
            "created_at": "2026-09-21T10:00:00Z",
            "updated_at": "2026-09-21T10:01:00Z",
            "last_turn_number": 1,
            "pending_approval": None,
        }

    def list_messages(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{
            "message_id": "message-1",
            "turn_number": 1,
            "role": "user",
            "content": "hello",
            "tool_calls": None,
            "tool_call_id": None,
            "created_at": "2026-09-21T10:00:00Z",
        }]

    def list_artifacts(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{
            "artifact_id": "artifact-1",
            "turn_number": 1,
            "name": "report.docx",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "url": "/workspace/report.docx",
            "operation": "created",
            "tool_call_id": "tool-1",
            "created_at": "2026-09-21T10:00:00Z",
            "updated_at": "2026-09-21T10:00:00Z",
        }]

    def close(self) -> None:
        pass


class FakeCoordinator:
    def __init__(self) -> None:
        self.history = FakeHistory()


def test_thread_query_routes() -> None:
    with TestClient(create_app(FakeCoordinator())) as client:
        threads = client.get("/api/threads", params={"workspace_path": WORKSPACE})
        detail = client.get(
            "/api/threads/thread-1",
            params={"workspace_path": WORKSPACE},
        )
        messages = client.get(
            "/api/threads/thread-1/messages",
            params={"workspace_path": WORKSPACE},
        )
        artifacts = client.get(
            "/api/threads/thread-1/artifacts",
            params={"workspace_path": WORKSPACE},
        )

    assert threads.status_code == 200
    assert threads.json()[0]["thread_id"] == "thread-1"
    assert detail.status_code == 200
    assert messages.json()["messages"][0]["content"] == "hello"
    assert artifacts.json()["artifacts"][0]["name"] == "report.docx"


def test_thread_query_requires_workspace_and_returns_stable_not_found() -> None:
    with TestClient(create_app(FakeCoordinator())) as client:
        invalid = client.get("/api/threads")
        missing = client.get(
            "/api/threads/missing",
            params={"workspace_path": WORKSPACE},
        )

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "thread_not_found"

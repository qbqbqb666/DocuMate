import io
import tempfile
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient

from src.backend.main import create_app
from src.backend.services.app_config import AppConfigService


class FakeHistory:
    def close(self) -> None:
        pass

    def get_artifact(self, **kwargs):
        return self.artifact


class FakeCoordinator:
    def __init__(self) -> None:
        self.history = FakeHistory()


def docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def test_document_upload_list_detail_search_and_duplicate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        config = AppConfigService(root / "app_config.json")
        config.switch_workspace(str(workspace))

        with TestClient(create_app(FakeCoordinator(), config)) as client:
            uploaded = client.post(
                "/api/documents/upload",
                files={
                    "file": (
                        "notes.docx",
                        docx_bytes("数据库课程总结"),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
            document_id = uploaded.json()["id"]
            listed = client.get("/api/documents")
            detail = client.get(f"/api/documents/{document_id}")
            searched = client.post(
                "/api/search",
                json={"query": "课程", "top_k": 5},
            )
            duplicate = client.post(
                "/api/documents/upload",
                files={"file": ("notes.docx", docx_bytes("重复"))},
            )

        assert uploaded.status_code == 201
        assert uploaded.json()["used_ocr"] is False
        assert listed.json()[0]["filename"] == "notes.docx"
        assert detail.json()["text"] == "数据库课程总结"
        assert searched.json()["hits"][0]["doc_id"] == document_id
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "file_exists"


def test_artifact_download_rejects_path_outside_workspace() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        config = AppConfigService(root / "app_config.json")
        config.switch_workspace(str(workspace))
        coordinator = FakeCoordinator()
        coordinator.history.artifact = {
            "artifact_id": "artifact-1",
            "name": "outside.txt",
            "mime_type": "text/plain",
            "url": str(root / "outside.txt"),
        }

        with TestClient(create_app(coordinator, config)) as client:
            response = client.get("/api/artifacts/artifact-1/download")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


def test_corrupt_document_returns_unified_validation_error() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        config = AppConfigService(root / "app_config.json")
        config.switch_workspace(str(workspace))

        with TestClient(create_app(FakeCoordinator(), config)) as client:
            response = client.post(
                "/api/documents/upload",
                files={"file": ("broken.docx", b"not-a-docx")},
            )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"
        assert response.json()["error"]["message"] == "无法读取文档：broken.docx"
        assert not (workspace / ".documate" / "documents" / "broken.docx").exists()

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from src.backend.main import create_app
from src.backend.services.app_config import AppConfigService


class FakeHistory:
    def close(self) -> None:
        pass

    def workspace_stats(self, **_kwargs):
        return {"thread_count": 3, "total_tokens": 2048}


class FakeCoordinator:
    history = FakeHistory()


def test_workspace_switch_recent_and_settings_round_trip() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        config = AppConfigService(root / "app_config.json")

        with TestClient(create_app(FakeCoordinator(), config)) as client:
            initial = client.get("/api/workspace")
            switched = client.post(
                "/api/workspace/switch",
                json={"path": str(workspace)},
            )
            recent = client.get("/api/workspace/recent")
            settings = client.get("/api/settings")
            updated = client.patch(
                "/api/settings",
                json={"trust_agent": True},
            )

        assert initial.status_code == 200
        assert initial.json()["is_user_set"] is False
        assert switched.status_code == 200
        assert switched.json()["info"]["path"] == str(workspace.resolve())
        assert recent.json() == [{
            "path": str(workspace.resolve()),
            "name": "workspace",
            "exists": True,
            "is_current": True,
        }]
        assert settings.json()["trust_agent"] is False
        assert updated.json()["trust_agent"] is True


def test_model_options_and_workspace_stats() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        config = AppConfigService(root / "app_config.json")
        config.switch_workspace(str(workspace))

        with TestClient(create_app(FakeCoordinator(), config)) as client:
            models = client.get("/api/settings/models")
            stats = client.get("/api/stats")

        assert models.status_code == 200
        assert [
            (item["provider"], item["model_name"], item["display_name"])
            for item in models.json()
        ] == [
            ("siliconflow", "Qwen/Qwen3.5-4B", "Qwen 3.5 4B"),
            ("deepseek", "deepseek-flash", "DeepSeek V4.1 Flash"),
            ("deepseek", "deepseek-v4-pro", "DeepSeek V4 Pro"),
        ]
        assert stats.status_code == 200
        assert stats.json() == {
            "document_count": 0,
            "thread_count": 3,
            "total_tokens": 2048,
        }


def test_workspace_and_model_validation_errors_are_stable() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = AppConfigService(root / "app_config.json")
        with TestClient(create_app(FakeCoordinator(), config)) as client:
            missing = client.post(
                "/api/workspace/switch",
                json={"path": str(root / "missing")},
            )
            invalid_model = client.patch(
                "/api/settings",
                json={"provider": "deepseek", "model_name": "not-registered"},
            )

        assert missing.status_code == 422
        assert missing.json()["error"]["code"] == "invalid_request"
        assert invalid_model.status_code == 422
        assert invalid_model.json()["error"]["code"] == "invalid_request"


def test_projects_support_multiple_folders_and_activation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        primary = root / "primary"
        reference = root / "reference"
        primary.mkdir()
        reference.mkdir()
        config = AppConfigService(root / "app_config.json")

        with TestClient(create_app(FakeCoordinator(), config)) as client:
            created = client.post("/api/projects", json={
                "name": "论文项目",
                "folder_paths": [str(primary), str(reference)],
            })
            listed = client.get("/api/projects")
            activated = client.post(
                f"/api/projects/{created.json()['id']}/activate"
            )

        assert created.status_code == 201
        assert created.json()["primary_path"] == str(primary.resolve())
        assert created.json()["folder_paths"] == [
            str(primary.resolve()), str(reference.resolve())
        ]
        assert listed.json()[0]["name"] == "论文项目"
        assert activated.json()["is_active"] is True

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from src.backend.config import BackendConfig
from src.backend.main import create_app
from src.backend.services.app_config import AppConfigService
from src.backend.services.document_library import DocumentLibrary
from src.backend.services.runtime import AppRuntime


class CountingHistory:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeCoordinator:
    def __init__(self) -> None:
        self.history = CountingHistory()
        self.recovery_calls = 0

    def recover_unfinished_turns(self):
        self.recovery_calls += 1
        return ()


def test_lifespan_reuses_resources_and_reports_ready() -> None:
    with tempfile.TemporaryDirectory() as directory:
        coordinator = FakeCoordinator()
        config = AppConfigService(Path(directory) / "app_config.json")
        documents = DocumentLibrary()
        app = create_app(coordinator, config, documents)

        with TestClient(app) as client:
            first = client.get("/api/ready")
            second = client.get("/api/ready")

            assert first.status_code == 200
            assert first.json()["status"] == "ready"
            assert second.status_code == 200
            assert app.state.runtime.coordinator is coordinator
            assert app.state.runtime.app_config is config
            assert app.state.runtime.document_library is documents
            assert app.state.ready is True
            assert coordinator.recovery_calls == 1

        assert app.state.ready is False
        assert app.state.runtime.closed is True
        # 由测试代码注入的资源仍由注入方管理。
        assert coordinator.history.close_calls == 0


def test_runtime_closes_owned_history_once() -> None:
    with tempfile.TemporaryDirectory() as directory:
        coordinator = FakeCoordinator()
        runtime = AppRuntime(
            coordinator=coordinator,
            app_config=AppConfigService(Path(directory) / "app_config.json"),
            document_library=DocumentLibrary(),
            owns_coordinator=True,
        )

        runtime.start()
        runtime.close()
        runtime.close()

        assert runtime.ready is False
        assert runtime.closed is True
        assert coordinator.history.close_calls == 1


def test_ready_returns_503_without_lifespan() -> None:
    client = TestClient(create_app(FakeCoordinator()))
    try:
        response = client.get("/api/ready")
    finally:
        client.close()

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_cors_allows_configured_origin_and_rejects_other_origin() -> None:
    config = BackendConfig(cors_origins=("http://frontend.test",))
    app = create_app(FakeCoordinator(), backend_config=config)

    with TestClient(app) as client:
        allowed = client.options(
            "/api/health",
            headers={
                "Origin": "http://frontend.test",
                "Access-Control-Request-Method": "GET",
            },
        )
        rejected = client.get(
            "/api/health",
            headers={"Origin": "http://other.test"},
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://frontend.test"
    assert "access-control-allow-origin" not in rejected.headers

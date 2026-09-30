import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from src.backend.main import create_app
from src.backend.services.api_keys import ApiKeyService
from src.backend.services.remote_session import RemoteSessionService


class FakeHistory:
    def close(self) -> None:
        pass


class FakeCoordinator:
    history = FakeHistory()


class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/api/user/me" or self.headers.get("Authorization") != "Bearer remote-token":
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps({"username": "remote_user"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def test_remote_token_unlocks_only_local_api_key_routes() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), AuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = RemoteSessionService(f"http://127.0.0.1:{server.server_port}")
            app = create_app(
                FakeCoordinator(),
                api_keys=ApiKeyService(root / ".env", validator=lambda *_: None),
                remote_session=remote,
            )
            with TestClient(app) as client:
                pushed = client.post(
                    "/__internal/set-token",
                    json={"access_token": "remote-token", "username": "remote_user"},
                )
                assert pushed.status_code == 200
                headers = {"Authorization": "Bearer remote-token"}
                assert client.get("/api/user/api-keys", headers=headers).status_code == 200
                saved = client.put(
                    "/api/user/api-keys/siliconflow",
                    headers=headers,
                    json={"api_key": "sf-test-1234"},
                )
                assert saved.json() == {
                    "provider": "siliconflow",
                    "configured": True,
                    "last4": "1234",
                }
                assert "sf-test-1234" in (root / ".env").read_text(encoding="utf-8")
                assert client.delete(
                    "/api/user/api-keys/siliconflow", headers=headers
                ).status_code == 204
                assert "sf-test-1234" not in (root / ".env").read_text(encoding="utf-8")
                assert client.post(
                    "/api/auth/login",
                    json={"email": "old@example.com", "password": "secret123"},
                ).status_code == 404
                assert client.delete("/__internal/set-token").status_code == 204
                assert client.get("/api/user/api-keys", headers=headers).status_code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

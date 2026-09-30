from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import create_session_factory
from app.main import create_app
from app.security import TokenSigner


def client(tmp_path: Path) -> TestClient:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    private_path.write_bytes(private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    public_path.write_bytes(private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'auth.sqlite3'}",
        jwt_private_key_path=str(private_path),
        jwt_public_key_path=str(public_path),
    )
    return TestClient(create_app(
        settings,
        create_session_factory(settings.database_url),
        TokenSigner(str(private_path), str(public_path), settings.jwt_issuer),
    ))


def test_register_login_refresh_logout_and_me(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        too_short = api.post("/api/auth/register", json={"username": "short", "password": "123456"})
        assert too_short.status_code == 422

        registered = api.post(
            "/api/auth/register", json={"username": "Test_User", "password": "secret123"}
        )
        assert registered.status_code == 200
        body = registered.json()
        assert body["user"]["username"] == "test_user"
        assert api.post(
            "/api/auth/register", json={"username": "test_user", "password": "secret123"}
        ).status_code == 409
        assert api.post(
            "/api/auth/login", json={"username": "test_user", "password": "wrongxx"}
        ).status_code == 401

        logged_in = api.post(
            "/api/auth/login", json={"username": "test_user", "password": "secret123"}
        ).json()
        me = api.get(
            "/api/user/me", headers={"Authorization": f"Bearer {logged_in['access_token']}"}
        )
        assert me.status_code == 200

        refreshed = api.post(
            "/api/auth/refresh", json={"refresh_token": logged_in["refresh_token"]}
        )
        assert refreshed.status_code == 200
        assert api.post(
            "/api/auth/refresh", json={"refresh_token": logged_in["refresh_token"]}
        ).status_code == 401

        new_refresh = refreshed.json()["refresh_token"]
        assert api.post("/api/auth/logout", json={"refresh_token": new_refresh}).status_code == 204
        assert api.post(
            "/api/auth/refresh", json={"refresh_token": new_refresh}
        ).status_code == 401

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import COOKIE, create_app


@pytest.fixture
def api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as db:
        db.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, status TEXT, seen_welcome BOOLEAN, created_at TIMESTAMP)"))
        db.execute(text("CREATE TABLE refresh_sessions (id INTEGER PRIMARY KEY, user_id INTEGER, token_hash TEXT, created_at TIMESTAMP, expires_at TIMESTAMP, revoked_at TIMESTAMP)"))
        for number in range(1, 24):
            db.execute(text("INSERT INTO users VALUES (:id, :name, 'SECRET-HASH', 'active', 0, '2026-01-01 00:00:00')"), {"id": number, "name": f"user{number}"})
        db.execute(text("INSERT INTO users VALUES (24, '<script>alert(1)</script>', 'SECRET-HASH', 'disabled', 1, '2026-01-01 00:00:00')"))
        db.execute(text("INSERT INTO users VALUES (25, '100%_user', 'SECRET-HASH', 'active', 1, '2026-01-01 00:00:00')"))
        db.execute(text("INSERT INTO refresh_sessions VALUES (1, 1, 'SECRET-TOKEN', '2026-01-01', '2099-01-01', NULL), (2, 2, 'SECRET-TOKEN-2', '2026-01-01', '2000-01-01', NULL), (3, 3, 'SECRET-TOKEN-3', '2026-01-01', '2099-01-01', '2026-01-02')"))
    with TestClient(create_app(engine, "qbqb", "qbqb", "test-key")) as client:
        yield client
    engine.dispose()


def login(api):
    assert api.post("/api/login", json={"username": "qbqb", "password": "qbqb"}).status_code == 200


def test_unauthenticated_and_invalid_login(api):
    assert api.get("/").status_code == 200
    assert api.get("/api/dashboard").status_code == 401
    assert api.post("/api/login", json={"username": "qbqb", "password": "wrong"}).status_code == 401
    assert api.get("/api/dashboard").status_code == 401
    assert api.get("/openapi.json").status_code == 404


def test_login_summary_and_no_secret_fields(api):
    result = api.post("/api/login", json={"username": "qbqb", "password": "qbqb"})
    assert "HttpOnly" in result.headers["set-cookie"]
    assert "SameSite=strict" in result.headers["set-cookie"]
    response = api.get("/api/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["stats"] == {"total_users":25,"active_users":24,"today_users":0,"total_sessions":3,"valid_sessions":1}
    assert len(data["users"]["items"]) == 20
    assert [item["state"] for item in data["sessions"]["items"]] == ["revoked", "expired", "valid"]
    for forbidden in ["password_hash", "token_hash", "SECRET-HASH", "SECRET-TOKEN"]:
        assert forbidden not in response.text


def test_search_pagination_and_bound_sql(api):
    login(api)
    assert len(api.get("/api/dashboard?user_page=2").json()["users"]["items"]) == 5
    assert api.get("/api/dashboard?q=USER23").json()["users"]["total"] == 1
    assert api.get("/api/dashboard", params={"q": "%_"}).json()["users"]["total"] == 1
    assert api.get("/api/dashboard", params={"q": "' OR 1=1 --"}).json()["users"]["total"] == 0
    for params in [{"user_page":0},{"page_size":101},{"session_page":-1}]:
        assert api.get("/api/dashboard", params=params).status_code == 422


def test_logout_tampered_expired_cookie(api):
    login(api)
    token = api.cookies.get(COOKIE)
    api.cookies.clear()
    assert api.get("/api/dashboard", headers={"Cookie": COOKIE + "=" + token[:-1] + "z"}).status_code == 401
    expired = "1." + token.split(".",1)[1]
    assert api.get("/api/dashboard", headers={"Cookie": COOKIE + "=" + expired}).status_code == 401
    login(api)
    assert api.post("/api/logout").status_code == 200
    assert api.get("/api/dashboard").status_code == 401


def test_no_write_routes_and_security_headers(api):
    login(api)
    for method in ["post", "put", "patch", "delete"]:
        assert getattr(api,method)("/api/dashboard").status_code == 405
    response = api.get("/api/dashboard")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert api.post("/api/logout", headers={"Origin":"https://other.example"}).status_code == 403


def test_login_rate_limit(api):
    for _ in range(5):
        assert api.post("/api/login", json={"username":"qbqb", "password":"wrong"}).status_code == 401
    assert api.post("/api/login", json={"username":"qbqb", "password":"wrong"}).status_code == 429


def test_credentials_change_invalidates_cookie(api):
    login(api)
    token = api.cookies.get(COOKIE)
    # Authentication is rejected before any database access.
    with TestClient(create_app(object(), "qbqb", "new-password", "test-key")) as changed:
        assert changed.get("/api/dashboard", headers={"Cookie": COOKIE + "=" + token}).status_code == 401


def test_signed_expired_cookie(api):
    import hashlib
    import hmac
    key = hmac.new(b"test-key", b"qbqb\0qbqb", hashlib.sha256).digest()
    value = str(int(time.time()) - 1) + ".nonce"
    signature = hmac.new(key, value.encode(), hashlib.sha256).hexdigest()
    assert api.get("/api/dashboard", headers={"Cookie": COOKIE+"="+value+"."+signature}).status_code == 401


def test_password_hash_requires_login_and_same_origin(api):
    payload = {"password":"new-password123"}
    assert api.post("/api/password-hash", json=payload).status_code == 401
    login(api)
    assert api.post("/api/password-hash", json=payload, headers={"Origin":"https://other.example"}).status_code == 403
    assert api.get("/api/password-hash").status_code == 405


def test_password_hash_compatible_randomized_and_no_db_changes(api):
    from argon2 import PasswordHasher
    login(api)
    before = api.get("/api/dashboard").json()
    password = "应用密码 abc123"
    first = api.post("/api/password-hash",json={"password":password})
    second = api.post("/api/password-hash",json={"password":password})
    assert first.status_code == second.status_code == 200
    encoded = first.json()["password_hash"]
    assert encoded.startswith("$argon2id$v=19$m=65536,t=3,p=2$")
    assert PasswordHasher(time_cost=3,memory_cost=65536,parallelism=2).verify(encoded,password)
    assert encoded != second.json()["password_hash"]
    assert password not in first.text
    assert first.headers["Cache-Control"] == "no-store"
    after = api.get("/api/dashboard").json()
    assert before["users"] == after["users"]
    assert before["sessions"] == after["sessions"]
    assert before["stats"] == after["stats"]


def test_password_hash_validation_does_not_echo_plaintext(api):
    login(api)
    for password in ["short", "x"*129]:
        response = api.post("/api/password-hash",json={"password":password})
        assert response.status_code == 400
        assert password not in response.text


def test_hash_function_never_opens_database():
    with TestClient(create_app(object(),"qbqb","qbqb","test-key")) as api:
        login(api)
        assert api.post("/api/password-hash",json={"password":"new-password123"}).status_code == 200


def test_only_one_hash_computation_at_a_time(api, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import app
    from types import SimpleNamespace
    login(api)
    entered, release = threading.Event(), threading.Event()
    def compute(value):
        entered.set()
        assert release.wait(5)
        return "test-hash"
    monkeypatch.setattr(app,"PASSWORDS",SimpleNamespace(hash=compute))
    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(api.post,"/api/password-hash",json={"password":"new-password123"})
        try:
            assert entered.wait(5)
            assert api.post("/api/password-hash",json={"password":"new-password123"}).status_code == 429
        finally:
            release.set()
        assert pending.result().status_code == 200

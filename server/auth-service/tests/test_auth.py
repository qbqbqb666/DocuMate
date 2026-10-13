from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import os
import secrets
import smtplib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.engine import make_url

from app.config import Settings
from app.database import AuthRateBucket, EmailChallenge, RefreshSession, User, create_session_factory
from app.email_auth import SMTPMailer, limit, utcnow
from app.main import create_app
from app.security import TokenSigner, hash_password


class TestMailer:
    __test__ = False

    def __init__(self):
        self.messages = []
        self.fail = False

    def send(self, email, code, purpose):
        if self.fail:
            raise HTTPException(503, "邮件暂时无法发送，请稍后重试")
        self.messages.append((email, code, purpose))


@pytest.fixture
def service(tmp_path):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path, public_path = tmp_path / "private.pem", tmp_path / "public.pem"
    private_path.write_bytes(private.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public_path.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo))
    database_url = os.getenv("DOCUMATE_TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'auth.sqlite3'}")
    admin = None
    schema = None
    if database_url.startswith("postgresql"):
        if make_url(database_url).database != "documate_email_test":
            raise RuntimeError("PostgreSQL tests only run against documate_email_test")
        admin = create_engine(database_url)
        schema = "test_" + secrets.token_hex(8)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        database_url = make_url(database_url).update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    settings = Settings(database_url=database_url,
        jwt_private_key_path=str(private_path), jwt_public_key_path=str(public_path),
        smtp_host="smtp.example.com", smtp_username="sender@example.com", smtp_password="test-only-secret",
        smtp_from="sender@example.com", email_code_secret="test-only-hmac-secret-" * 3)
    sessions = create_session_factory(settings.database_url, initialize=True)
    mailer = TestMailer()
    app = create_app(settings, sessions, TokenSigner(str(private_path), str(public_path), settings.jwt_issuer), mailer)
    with TestClient(app) as api:
        yield api, sessions, mailer, settings, app
    sessions.kw["bind"].dispose()
    if admin is not None:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def payload(email="person@example.com", **kwargs):
    return {"email": email, "password": "secret123", **kwargs}


def send(service, purpose="register", email="person@example.com", password="secret123"):
    api, _, mailer, _, _ = service
    result = api.post("/api/auth/email-code", json=payload(email, purpose=purpose, password=password))
    assert result.status_code == 200, result.text
    return payload(email, code=mailer.messages[-1][1], verification_id=result.json()["verification_id"])


def registered(service):
    credentials = send(service)
    response = service[0].post("/api/auth/register", json=credentials)
    assert response.status_code == 200, response.text
    return credentials, response.json()


def expire_limits(service):
    with service[1]() as db:
        db.execute(update(AuthRateBucket).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()


def test_registration_login_refresh_logout(service):
    api, sessions, mailer, config, _ = service
    credentials, auth = registered(service)
    assert auth["user"]["email"] == "person@example.com"
    assert auth["user"]["email_verified"] is True
    with sessions() as db:
        user = db.scalar(select(User))
        challenge = db.get(EmailChallenge, credentials["verification_id"])
        assert user.password_hash.startswith("$argon2id$")
        assert credentials["code"] != challenge.code_hash
        assert auth["refresh_token"] != db.scalar(select(RefreshSession)).token_hash
    assert api.post("/api/auth/login", json=credentials).status_code == 400
    assert api.post("/api/auth/login", json={"email": credentials["email"], "password": "secret123"}).status_code == 200
    assert api.post("/api/auth/login", json={"username": auth["user"]["username"], "password": "secret123"}).status_code == 401
    expire_limits(service)
    login = send(service, "login")
    result = api.post("/api/auth/login", json=login)
    assert result.status_code == 200
    assert api.post("/api/auth/login", json=login).status_code == 400
    auth = result.json()
    assert api.get("/api/user/me", headers={"Authorization": "Bearer " + auth["access_token"]}).status_code == 200
    refreshed = api.post("/api/auth/refresh", json={"refresh_token": auth["refresh_token"]})
    assert refreshed.status_code == 200
    assert api.post("/api/auth/refresh", json={"refresh_token": auth["refresh_token"]}).status_code == 401
    new_refresh = refreshed.json()["refresh_token"]
    assert api.post("/api/auth/logout", json={"refresh_token": new_refresh}).status_code == 204
    assert api.post("/api/auth/logout", json={"refresh_token": new_refresh}).status_code == 204
    assert api.post("/api/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401


@pytest.mark.parametrize("change", [{"email": "bad"}, {"password": "1"}, {"code": "x"},
                                     {"verification_id": "x"}, {"extra": "unexpected"}])
def test_invalid_input_does_not_echo_secrets(service, change):
    body = payload(code="123456", verification_id="a" * 32)
    body.update(change)
    result = service[0].post("/api/auth/register", json=body)
    assert result.status_code == 422
    assert "secret123" not in result.text
    assert "123456" not in result.text


def test_expired_code(service):
    body = send(service)
    with service[1]() as db:
        db.get(EmailChallenge, body["verification_id"]).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert service[0].post("/api/auth/register", json=body).status_code == 400


def test_five_wrong_attempts_exhaust_code(service):
    body = send(service)
    wrong = "000000" if body["code"] != "000000" else "999999"
    for _ in range(5):
        assert service[0].post("/api/auth/register", json={**body, "code": wrong}).status_code == 400
    assert service[0].post("/api/auth/register", json=body).status_code == 400
    with service[1]() as db:
        assert db.get(EmailChallenge, body["verification_id"]).attempts == 5


def test_email_and_purpose_are_bound(service):
    body = send(service)
    assert service[0].post("/api/auth/register", json={**body, "email": "other@example.com"}).status_code == 400
    assert service[0].post("/api/auth/reset-password", json=body).status_code == 400
    assert service[0].post("/api/auth/register", json=body).status_code == 200


def test_resend_invalidates_old_code(service):
    old = send(service)
    expire_limits(service)
    new = send(service)
    assert service[0].post("/api/auth/register", json=old).status_code == 400
    assert service[0].post("/api/auth/register", json=new).status_code == 200


def test_send_interval_shared_across_purposes_and_email_case(service):
    send(service)
    result = service[0].post("/api/auth/email-code", json=payload("PERSON@example.com", purpose="reset"))
    assert result.status_code == 429
    assert result.headers["retry-after"] == "60"
    assert len(service[2].messages) == 1


@pytest.mark.parametrize("key,maximum,seconds", [
    ("send:email:hour:a", 5, 3600), ("send:email:day:a", 20, 86400),
    ("send:ip:hour:a", 20, 3600), ("send:ip:day:a", 100, 86400),
])
def test_rate_boundaries_and_reset(service, key, maximum, seconds):
    with service[1]() as db:
        for _ in range(maximum):
            limit(db, key, maximum, seconds)
        with pytest.raises(HTTPException) as error:
            limit(db, key, maximum, seconds)
        assert error.value.status_code == 429
        db.execute(update(AuthRateBucket).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
        limit(db, key, maximum, seconds)


def test_smtp_failure_invalidates_code(service):
    service[2].fail = True
    result = service[0].post("/api/auth/email-code", json=payload(purpose="register"))
    assert result.status_code == 503
    with service[1]() as db:
        record = db.scalar(select(EmailChallenge))
        assert record.delivered is False and record.consumed_at is not None
    assert "验证码已发送" not in result.text
    service[2].fail = False
    assert service[0].post("/api/auth/email-code", json=payload(purpose="register")).status_code == 200


def test_unknown_reset_is_opaque_and_duplicate_registration_is_explicit(service):
    api, _, mailer, _, _ = service
    unknown = api.post("/api/auth/email-code", json=payload("unknown@example.com", purpose="reset"))
    assert unknown.status_code == 200 and mailer.messages == []
    registered(service)
    expire_limits(service)
    count = len(mailer.messages)
    existing = api.post("/api/auth/email-code", json=payload(purpose="register"))
    assert existing.status_code == 409 and len(mailer.messages) == count
    assert existing.json()["detail"] == "该邮箱已注册，请直接登录"


def test_wrong_password_sends_nothing_and_is_limited(service):
    registered(service)
    api, _, mailer, _, _ = service
    expire_limits(service)
    count = len(mailer.messages)
    for _ in range(10):
        assert api.post("/api/auth/email-code", json=payload(purpose="login", password="wrong123")).status_code == 401
    assert api.post("/api/auth/email-code", json=payload(purpose="login")).status_code == 429
    assert len(mailer.messages) == count


def test_reset_revokes_all_refresh_and_invalidates_old_login_codes(service):
    api = service[0]
    _, auth = registered(service)
    expire_limits(service)
    login = send(service, "login")
    expire_limits(service)
    reset = send(service, "reset")
    result = api.post("/api/auth/reset-password", json={**reset, "password": "newsecret"})
    assert result.status_code == 204
    assert api.post("/api/auth/refresh", json={"refresh_token": auth["refresh_token"]}).status_code == 401
    assert api.get("/api/user/me", headers={"Authorization": "Bearer " + auth["access_token"]}).status_code == 401
    assert api.post("/api/auth/login", json={**login, "password": "newsecret"}).status_code == 400
    assert api.post("/api/auth/reset-password", json=reset).status_code == 400
    expire_limits(service)
    fresh = send(service, "login", password="newsecret")
    assert api.post("/api/auth/login", json={**fresh, "password": "newsecret"}).status_code == 200


def test_disabled_user_cannot_refresh_or_get_login_code(service):
    _, auth = registered(service)
    with service[1]() as db:
        db.get(User, auth["user"]["id"]).status = "suspended"
        db.commit()
    assert service[0].post("/api/auth/refresh", json={"refresh_token": auth["refresh_token"]}).status_code == 401
    assert service[0].post("/api/auth/email-code", json=payload(purpose="login")).status_code == 401


def test_legacy_account_not_migrated_or_deleted(service):
    with service[1]() as db:
        db.add(User(username="legacy_user", password_hash=hash_password("oldsecret")))
        db.commit()
    result = service[0].post("/api/auth/login", json={"username": "legacy_user", "password": "oldsecret"})
    assert result.status_code == 200 and result.json()["user"]["email"] is None


def test_concurrent_code_consumption_and_refresh(service):
    api, _, _, _, app = service
    body = send(service)
    def register_once(_):
        with TestClient(app) as client:
            return client.post("/api/auth/register", json=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register_once, range(2)))
    assert sorted(result.status_code for result in results) == [200, 400]
    auth = next(result.json() for result in results if result.status_code == 200)
    def refresh_once(_):
        with TestClient(app) as client:
            return client.post("/api/auth/refresh", json={"refresh_token": auth["refresh_token"]}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(refresh_once, range(2))) == [200, 401]


def test_unconfigured_mail_rejects_requests(service):
    config = replace(service[3], smtp_password="")
    with TestClient(create_app(config, service[1])) as api:
        assert api.get("/health").json()["email_ready"] is False
        assert api.post("/api/auth/email-code", json=payload(purpose="register")).status_code == 503


@pytest.mark.parametrize("tls", ["ssl", "starttls"])
def test_real_smtp_adapter_uses_tls_and_submits_message(service, monkeypatch, tls):
    events = []
    class SMTP:
        def __init__(self, host, port, **kwargs):
            events.append((host, port, kwargs))
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self, **kwargs): events.append("starttls")
        def login(self, username, password): events.append((username, password))
        def send_message(self, message):
            events.append(message)
            return {}
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTP)
    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    SMTPMailer(replace(service[3], smtp_tls=tls)).send("person@example.com", "012345", "login")
    assert "012345" in events[-1].get_content()
    assert events[-1]["To"] == "person@example.com"
    assert ("starttls" in events) == (tls == "starttls")


def test_smtp_errors_are_sanitized(service, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"test-only-secret")
    monkeypatch.setattr(smtplib, "SMTP_SSL", fail)
    with pytest.raises(HTTPException) as error:
        SMTPMailer(service[3]).send("person@example.com", "012345", "login")
    assert "test-only-secret" not in str(error.value.detail)
    assert "test-only-secret" not in repr(service[3])
    assert "stage=connect type=SMTPAuthenticationError smtp_code=535" in caplog.text
    assert "test-only-secret" not in caplog.text
    assert "person@example.com" not in caplog.text
    assert "012345" not in caplog.text


@pytest.mark.parametrize('smtp_code,response,expected', [
    (550, b'User not found: person@example.com', 400),
    (550, b'Rejected by policy', 503),
    (450, b'Mailbox temporarily unavailable', 503),
])
def test_smtp_recipient_errors_are_specific_and_sanitized(service, monkeypatch, caplog, smtp_code, response, expected):
    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def send_message(self, message):
            raise smtplib.SMTPRecipientsRefused({'person@example.com': (smtp_code, response)})
    monkeypatch.setattr(smtplib, 'SMTP_SSL', SMTP)
    with pytest.raises(HTTPException) as error:
        SMTPMailer(service[3]).send('person@example.com', '012345', 'register')
    assert error.value.status_code == expected
    assert 'person@example.com' not in caplog.text
    assert '012345' not in caplog.text
    if expected == 400:
        assert error.value.detail == '该邮箱不存在，请检查邮箱地址'


def test_password_login_does_not_require_smtp_or_send_mail(service):
    api, sessions, mailer, config, _ = service
    registered(service)
    count = len(mailer.messages)
    with TestClient(create_app(replace(config, smtp_password=''), sessions)) as client:
        assert client.post('/api/auth/login', json=payload()).status_code == 200
        assert client.post('/api/auth/login', json=payload(password='wrong123')).status_code == 401
        assert client.post('/api/auth/login', json=payload('unknown@example.com')).status_code == 401
    assert len(mailer.messages) == count


def test_smtp_quit_failure_after_acceptance_does_not_report_send_failure(service, monkeypatch):
    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): raise smtplib.SMTPServerDisconnected('test shutdown')
        def login(self, *args): pass
        def send_message(self, message): return {}
    monkeypatch.setattr(smtplib, 'SMTP_SSL', SMTP)
    SMTPMailer(service[3]).send('person@example.com', '012345', 'register')


def test_successful_send_starts_cooldown_at_acceptance(service, monkeypatch):
    clock = [utcnow()]
    monkeypatch.setattr('app.email_auth.utcnow', lambda: clock[0])
    def delayed_send(email, code, purpose):
        clock[0] += timedelta(seconds=30)
        service[2].messages.append((email, code, purpose))
    service[2].send = delayed_send
    result = service[0].post('/api/auth/email-code', json=payload(purpose='register'))
    assert result.status_code == 200
    repeat = service[0].post('/api/auth/email-code', json=payload(purpose='register'))
    assert repeat.status_code == 429
    assert int(repeat.headers['retry-after']) == 60

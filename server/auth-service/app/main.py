import secrets
from datetime import timedelta
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings
from .database import RefreshSession, User, create_session_factory
from .email_auth import CODE_ERROR, SMTPMailer, consume_code, limit, send_code, utcnow
from .schemas import (AuthResponse, Credentials, EmailCredentials, EmailPasswordCredentials, RefreshRequest,
                      SendEmailCode, UserResponse)
from .security import (TokenSigner, hash_password, new_refresh_token,
                       refresh_token_hash, verify_password)


def create_app(settings: Settings | None = None, session_factory=None,
               signer: TokenSigner | None = None, mailer=None) -> FastAPI:
    config = settings or Settings.from_env()
    sessions = session_factory or create_session_factory(config.database_url)
    tokens = signer or TokenSigner(config.jwt_private_key_path, config.jwt_public_key_path, config.jwt_issuer)
    email_sender = mailer or SMTPMailer(config)
    app = FastAPI(title="DocuMate Auth Service", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # Do not echo submitted passwords or codes in validation responses.
        return JSONResponse(status_code=422, content={"detail": "请检查邮箱、密码和验证码格式"})

    def database():
        with sessions() as session:
            yield session

    def current_user(authorization: Annotated[str | None, Header()] = None,
                     db: Session = Depends(database)) -> User:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "登录已失效，请重新登录")
        try:
            payload = tokens.decode(authorization[7:].strip())
            user = db.get(User, int(str(payload["sub"])))
        except (jwt.PyJWTError, KeyError, ValueError):
            user = None
        if user is None or user.status != "active" or payload.get("ver", 0) != user.auth_version:
            raise HTTPException(401, "登录已失效，请重新登录")
        return user

    def user_payload(user: User) -> UserResponse:
        return UserResponse(id=user.id, username=user.username, email=user.email,
                            email_verified=user.email_verified_at is not None,
                            display_name=user.email or user.username, has_api_key=True,
                            sf_api_key_last4=None, api_key_provider=None, seen_welcome=user.seen_welcome,
                            status=user.status, created_at=user.created_at)

    def auth_payload(db: Session, user: User) -> AuthResponse:
        refresh = new_refresh_token()
        db.add(RefreshSession(user_id=user.id, token_hash=refresh_token_hash(refresh),
                              expires_at=utcnow() + timedelta(days=config.refresh_token_days)))
        result = AuthResponse(access_token=tokens.access_token(
            user.id, user.username, config.access_token_minutes, user.auth_version),
            refresh_token=refresh, expires_in=config.access_token_minutes * 60, user=user_payload(user))
        db.commit()
        return result

    def ip_address(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def request_limit(db: Session, request: Request, action: str) -> None:
        limit(db, f"request:{action}:{ip_address(request)}", 30, 300)

    def password_limit(db: Session, request: Request, identifier: str) -> None:
        limit(db, f"password:ip:{ip_address(request)}", 50, 300)
        limit(db, f"password:account:{identifier}", 10, 300)

    def email_available() -> None:
        if not config.email_ready:
            raise HTTPException(503, "邮箱认证服务尚未配置完成")

    def email_user(db: Session, email: str, password: str | None) -> User:
        user = db.scalar(select(User).where(User.email == email).with_for_update())
        if (user is None or user.status != "active" or user.email_verified_at is None
                or password is None or not verify_password(user.password_hash, password)):
            raise HTTPException(401, "邮箱或密码错误")
        return user

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "documate-auth", "email_ready": config.email_ready}

    @app.get("/.well-known/jwks.json")
    def jwks() -> dict:
        return tokens.jwks()

    @app.post("/api/auth/email-code")
    def email_code(payload: SendEmailCode, request: Request, db: Session = Depends(database)) -> dict:
        email_available()
        request_limit(db, request, "email_send")
        user = None
        if payload.purpose == "login":
            password_limit(db, request, str(payload.email))
            user = email_user(db, str(payload.email), payload.password)
        limit(db, f"send:email:hour:{payload.email}", 5, 3600)
        limit(db, f"send:email:day:{payload.email}", 20, 86400)
        limit(db, f"send:ip:hour:{ip_address(request)}", 20, 3600)
        limit(db, f"send:ip:day:{ip_address(request)}", 100, 86400)
        user = db.scalar(select(User).where(User.email == payload.email))
        if payload.purpose == "register" and user is not None:
            raise HTTPException(409, "该邮箱已注册，请直接登录")
        if payload.purpose == "login":
            user = email_user(db, str(payload.email), payload.password)
        eligible = user is None if payload.purpose == "register" else (
            user is not None and user.status == "active" and user.email_verified_at is not None)
        return send_code(db, config, email_sender, str(payload.email), payload.purpose, user, eligible)

    @app.post("/api/auth/register", response_model=AuthResponse)
    def register(payload: EmailCredentials, request: Request, db: Session = Depends(database)) -> AuthResponse:
        email_available()
        request_limit(db, request, "register")
        consume_code(db, config, str(payload.email), "register", payload.verification_id, payload.code)
        user = User(username="e_" + secrets.token_hex(15), email=str(payload.email),
                    email_verified_at=utcnow(), password_hash=hash_password(payload.password))
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "该邮箱已注册，请直接登录") from None
        return auth_payload(db, user)

    @app.post("/api/auth/login", response_model=AuthResponse)
    def login(payload: EmailCredentials | EmailPasswordCredentials | Credentials, request: Request,
              db: Session = Depends(database)) -> AuthResponse:
        identifier = payload.username if isinstance(payload, Credentials) else str(payload.email)
        password_limit(db, request, identifier)
        if isinstance(payload, Credentials):
            user = db.scalar(select(User).where(User.username == identifier, User.email.is_(None)).with_for_update())
            if user is None or user.status != "active" or not verify_password(user.password_hash, payload.password):
                raise HTTPException(401, "账号或密码错误")
        else:
            user = email_user(db, identifier, payload.password)
            if isinstance(payload, EmailCredentials):
                record = consume_code(db, config, identifier, "login", payload.verification_id, payload.code)
                if record.user_id != user.id or record.auth_version != user.auth_version:
                    raise HTTPException(400, CODE_ERROR)
        return auth_payload(db, user)

    @app.post("/api/auth/reset-password", status_code=status.HTTP_204_NO_CONTENT)
    def reset_password(payload: EmailCredentials, request: Request, db: Session = Depends(database)) -> None:
        email_available()
        request_limit(db, request, "reset")
        user = db.scalar(select(User).where(User.email == payload.email).with_for_update())
        record = consume_code(db, config, str(payload.email), "reset", payload.verification_id, payload.code)
        if (user is None or user.status != "active" or user.email_verified_at is None
                or record.user_id != user.id or record.auth_version != user.auth_version):
            raise HTTPException(400, CODE_ERROR)
        user.password_hash = hash_password(payload.password)
        user.auth_version += 1
        db.execute(update(RefreshSession).where(RefreshSession.user_id == user.id,
                   RefreshSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
        db.commit()

    @app.post("/api/auth/refresh", response_model=AuthResponse)
    def refresh(payload: RefreshRequest, db: Session = Depends(database)) -> AuthResponse:
        record = db.scalar(select(RefreshSession).where(
            RefreshSession.token_hash == refresh_token_hash(payload.refresh_token)))
        now = utcnow()
        if record is None:
            raise HTTPException(401, "刷新令牌已失效，请重新登录")
        user = db.scalar(select(User).where(User.id == record.user_id).with_for_update())
        if user is None or user.status != "active":
            raise HTTPException(401, "登录已失效，请重新登录")
        changed = db.execute(update(RefreshSession).where(
            RefreshSession.id == record.id, RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now).values(revoked_at=now).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise HTTPException(401, "刷新令牌已失效，请重新登录")
        return auth_payload(db, user)

    @app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(payload: RefreshRequest, db: Session = Depends(database)) -> None:
        db.execute(update(RefreshSession).where(
            RefreshSession.token_hash == refresh_token_hash(payload.refresh_token),
            RefreshSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
        db.commit()

    @app.get("/api/user/me", response_model=UserResponse)
    def me(user: User = Depends(current_user)) -> UserResponse:
        return user_payload(user)

    @app.post("/api/user/seen-welcome", response_model=UserResponse)
    def seen_welcome(user: User = Depends(current_user), db: Session = Depends(database)) -> UserResponse:
        user.seen_welcome = True
        db.commit()
        return user_payload(user)

    return app

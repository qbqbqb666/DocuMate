import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings
from .database import RefreshSession, User, create_session_factory
from .schemas import AuthResponse, Credentials, RefreshRequest, UserResponse
from .security import (
    TokenSigner,
    hash_password,
    new_refresh_token,
    refresh_token_hash,
    verify_password,
)


class LoginRateLimiter:
    def __init__(self, attempts: int = 10, window_seconds: int = 300) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._entries: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            recent = [item for item in self._entries.get(key, []) if now - item < self.window_seconds]
            if len(recent) >= self.attempts:
                raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试")
            recent.append(now)
            self._entries[key] = recent

    def clear(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)


def create_app(
    settings: Settings | None = None,
    session_factory=None,
    signer: TokenSigner | None = None,
) -> FastAPI:
    config = settings or Settings.from_env()
    sessions = session_factory or create_session_factory(config.database_url)
    tokens = signer or TokenSigner(
        config.jwt_private_key_path, config.jwt_public_key_path, config.jwt_issuer
    )
    limiter = LoginRateLimiter()
    app = FastAPI(title="DocuMate Auth Service", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def database() -> Session:
        with sessions() as session:
            yield session

    def current_user(
        authorization: Annotated[str | None, Header()] = None,
        db: Session = Depends(database),
    ) -> User:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
        try:
            payload = tokens.decode(authorization[7:].strip())
            user = db.get(User, int(str(payload["sub"])))
        except (jwt.PyJWTError, KeyError, ValueError):
            user = None
        if user is None or user.status != "active":
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
        return user

    def user_payload(user: User) -> UserResponse:
        return UserResponse(
            id=user.id,
            username=user.username,
            display_name=user.username,
            has_api_key=True,
            sf_api_key_last4=None,
            api_key_provider=None,
            seen_welcome=user.seen_welcome,
            status=user.status,
            created_at=user.created_at,
        )

    def auth_payload(db: Session, user: User) -> AuthResponse:
        refresh = new_refresh_token()
        db.add(RefreshSession(
            user_id=user.id,
            token_hash=refresh_token_hash(refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=config.refresh_token_days),
        ))
        db.commit()
        return AuthResponse(
            access_token=tokens.access_token(
                user.id, user.username, config.access_token_minutes
            ),
            refresh_token=refresh,
            expires_in=config.access_token_minutes * 60,
            user=user_payload(user),
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "documate-auth"}

    @app.get("/.well-known/jwks.json")
    def jwks() -> dict[str, object]:
        return tokens.jwks()

    @app.post("/api/auth/register", response_model=AuthResponse)
    def register(payload: Credentials, db: Session = Depends(database)) -> AuthResponse:
        user = User(username=payload.username, password_hash=hash_password(payload.password))
        db.add(user)
        try:
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise HTTPException(status_code=409, detail="该账号已存在，请直接登录") from error
        db.refresh(user)
        return auth_payload(db, user)

    @app.post("/api/auth/login", response_model=AuthResponse)
    def login(payload: Credentials, request: Request, db: Session = Depends(database)) -> AuthResponse:
        key = f"{request.client.host if request.client else 'unknown'}:{payload.username}"
        limiter.check(key)
        user = db.scalar(select(User).where(User.username == payload.username))
        if user is None or user.status != "active" or not verify_password(user.password_hash, payload.password):
            raise HTTPException(status_code=401, detail="账号或密码错误")
        limiter.clear(key)
        return auth_payload(db, user)

    @app.post("/api/auth/refresh", response_model=AuthResponse)
    def refresh(payload: RefreshRequest, db: Session = Depends(database)) -> AuthResponse:
        session = db.scalar(select(RefreshSession).where(
            RefreshSession.token_hash == refresh_token_hash(payload.refresh_token)
        ))
        now = datetime.now(timezone.utc)
        expires_at = session.expires_at.replace(tzinfo=timezone.utc) if session and session.expires_at.tzinfo is None else (session.expires_at if session else now)
        if session is None or session.revoked_at is not None or expires_at <= now:
            raise HTTPException(status_code=401, detail="刷新令牌已失效，请重新登录")
        session.revoked_at = now
        db.commit()
        return auth_payload(db, session.user)

    @app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(payload: RefreshRequest, db: Session = Depends(database)) -> None:
        session = db.scalar(select(RefreshSession).where(
            RefreshSession.token_hash == refresh_token_hash(payload.refresh_token)
        ))
        if session is not None and session.revoked_at is None:
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()

    @app.get("/api/user/me", response_model=UserResponse)
    def me(user: User = Depends(current_user)) -> UserResponse:
        return user_payload(user)

    @app.post("/api/user/seen-welcome", response_model=UserResponse)
    def seen_welcome(
        user: User = Depends(current_user), db: Session = Depends(database)
    ) -> UserResponse:
        user.seen_welcome = True
        db.commit()
        return user_payload(user)

    return app

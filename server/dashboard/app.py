import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from argon2 import PasswordHasher
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import create_engine, text


COOKIE = "documate_dashboard"
SESSION_SECONDS = 8 * 60 * 60
STATIC = Path(__file__).parent / "static"
PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class HashRequest(BaseModel):
    password: SecretStr


def create_app(engine=None, username=None, password=None, secret=None) -> FastAPI:
    db = engine if engine is not None else create_engine(
        os.environ["DASHBOARD_DATABASE_URL"], pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
    )
    admin = username if username is not None else os.environ["DASHBOARD_USERNAME"]
    credential = password if password is not None else os.environ["DASHBOARD_PASSWORD"]
    signing_key = secret if secret is not None else os.environ["DASHBOARD_SESSION_SECRET"]
    # Changing either credential invalidates cookies from the previous configuration.
    key = hmac.new(signing_key.encode(), (admin + "\0" + credential).encode(), hashlib.sha256).digest()
    attempts = OrderedDict()
    lock = threading.Lock()
    hash_lock = threading.Lock()
    app = FastAPI(title="DocuMate Read-only Dashboard", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    def signed(value: str) -> str:
        return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()

    def require_login(request: Request):
        token = request.cookies.get(COOKIE, "")
        try:
            expiry, nonce, signature = token.split(".")
            valid = hmac.compare_digest(signature, signed(expiry + "." + nonce))
            valid = valid and time.time() < int(expiry) <= time.time() + SESSION_SECONDS
        except (ValueError, OverflowError):
            valid = False
        if not valid:
            raise HTTPException(401, "请先登录看板")

    def same_origin(request: Request):
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if origin and origin != expected:
            raise HTTPException(403, "不接受跨站请求")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/dashboard.css")
    def css():
        return FileResponse(STATIC / "dashboard.css")

    @app.get("/dashboard.js")
    def javascript():
        return FileResponse(STATIC / "dashboard.js")

    @app.post("/api/login", dependencies=[Depends(same_origin)])
    def login(payload: Credentials, request: Request, response: Response):
        address = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with lock:
            recent = [stamp for stamp in attempts.get(address, []) if stamp > now - 60]
            if len(recent) >= 5:
                raise HTTPException(429, "尝试过于频繁，请一分钟后再试")
            recent.append(now)
            attempts[address] = recent
            attempts.move_to_end(address)
            if len(attempts) > 10000:
                attempts.popitem(last=False)
        user_ok = hmac.compare_digest(payload.username.encode(), admin.encode())
        password_ok = hmac.compare_digest(payload.password.encode(), credential.encode())
        if not (user_ok and password_ok):
            raise HTTPException(401, "账号或密码错误")
        with lock:
            attempts.pop(address, None)
        value = str(int(time.time()) + SESSION_SECONDS) + "." + secrets.token_hex(16)
        response.set_cookie(COOKIE, value + "." + signed(value), max_age=SESSION_SECONDS,
                            httponly=True, samesite="strict", secure=request.url.scheme == "https")
        return {"username": admin}

    @app.post("/api/logout", dependencies=[Depends(same_origin)])
    def logout(response: Response):
        response.delete_cookie(COOKIE, httponly=True, samesite="strict")
        return {"ok": True}

    @app.post("/api/password-hash", dependencies=[Depends(require_login), Depends(same_origin)])
    def password_hash(payload: HashRequest):
        value = payload.password.get_secret_value()
        if not 6 <= len(value) <= 128:
            raise HTTPException(400, "密码长度应为 6 至 128 个字符")
        if not hash_lock.acquire(blocking=False):
            raise HTTPException(429, "正在生成哈希，请稍后重试")
        try:
            return {"password_hash": PASSWORDS.hash(value), "algorithm": "argon2id"}
        finally:
            hash_lock.release()

    @app.get("/api/dashboard", dependencies=[Depends(require_login)])
    def dashboard(q: str = Query("", max_length=128), user_page: int = Query(1, ge=1),
                  session_page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
        now = datetime.now(timezone.utc)
        search = q.strip().lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
        params = {"now": now, "today": now.astimezone(timezone(timedelta(hours=8))).replace(
            hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc),
            "search": "%" + search + "%", "limit": page_size,
            "user_offset": (user_page - 1) * page_size,
            "session_offset": (session_page - 1) * page_size}
        user_filter = "LOWER(username) LIKE :search ESCAPE '!'"
        session_filter = "LOWER(u.username) LIKE :search ESCAPE '!'"
        try:
            with db.connect() as connection, connection.begin():
                if db.dialect.name == "postgresql":
                    connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                def row(sql):
                    return dict(connection.execute(text(sql), params).mappings().one())
                def rows(sql):
                    return [dict(item) for item in connection.execute(text(sql), params).mappings()]
                user_stats = row("""SELECT COUNT(*) AS total_users,
                    COALESCE(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END), 0) AS active_users,
                    COALESCE(SUM(CASE WHEN created_at >= :today THEN 1 ELSE 0 END), 0) AS today_users FROM users""")
                session_stats = row("""SELECT COUNT(*) AS total_sessions,
                    COALESCE(SUM(CASE WHEN revoked_at IS NULL AND expires_at > :now THEN 1 ELSE 0 END), 0)
                    AS valid_sessions FROM refresh_sessions""")
                users_total = row("SELECT COUNT(*) AS count FROM users WHERE " + user_filter)["count"]
                sessions_total = row("SELECT COUNT(*) AS count FROM refresh_sessions s JOIN users u ON u.id = s.user_id WHERE " + session_filter)["count"]
                users = rows("SELECT id, username, status, seen_welcome, created_at FROM users WHERE "
                             + user_filter + " ORDER BY id DESC LIMIT :limit OFFSET :user_offset")
                sessions = rows("""SELECT s.id, u.username, s.created_at, s.expires_at, s.revoked_at,
                    CASE WHEN s.revoked_at IS NOT NULL THEN 'revoked'
                         WHEN s.expires_at <= :now THEN 'expired' ELSE 'valid' END AS state
                    FROM refresh_sessions s JOIN users u ON u.id = s.user_id WHERE """
                    + session_filter + " ORDER BY s.id DESC LIMIT :limit OFFSET :session_offset")
        except Exception:
            # Connection URLs and driver errors can contain credentials; never return them.
            raise HTTPException(503, "数据库暂时无法读取，请稍后刷新") from None
        return {"updated_at": now, "username": admin, "stats": {**user_stats, **session_stats},
                "users": {"items": users, "total": users_total, "page": user_page},
                "sessions": {"items": sessions, "total": sessions_total, "page": session_page},
                "page_size": page_size}

    return app

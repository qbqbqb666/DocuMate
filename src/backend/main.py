from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.backend.api.api_keys import router as api_keys_router
from src.backend.api.chat import router as chat_router
from src.backend.api.documents import router as documents_router
from src.backend.api.workspace_files import router as workspace_files_router
from src.backend.api.schemas import ErrorDetail, ErrorResponse, InternalTokenRequest
from src.backend.api.settings import router as settings_router
from src.backend.api.projects import router as projects_router
from src.backend.api.stats import router as stats_router
from src.backend.api.threads import router as threads_router
from src.backend.api.workspace import router as workspace_router
from src.backend.config import BackendConfig
from src.backend.services.conversation import (
    ConversationCoordinator,
    ConversationError,
)
from src.backend.services.event_log import EventLogNotFoundError
from src.backend.services.history import HistoryNotFoundError
from src.backend.services.app_config import AppConfigService
from src.backend.services.document_library import DocumentLibrary
from src.backend.services.api_keys import ApiKeyService
from src.backend.services.runtime import AppRuntime
from src.backend.services.remote_session import RemoteSessionError, RemoteSessionService


logger = logging.getLogger("uvicorn.error")


def create_app(
    coordinator: ConversationCoordinator | Any | None = None,
    app_config: AppConfigService | None = None,
    document_library: DocumentLibrary | None = None,
    backend_config: BackendConfig | None = None,
    api_keys: ApiKeyService | None = None,
    remote_session: RemoteSessionService | None = None,
) -> FastAPI:
    server_config = backend_config or BackendConfig.from_env()
    api_key_service = api_keys or ApiKeyService()
    remote_session_service = remote_session or RemoteSessionService(
        os.getenv("DOCUMATE_AUTH_SERVICE_URL")
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("DocuMate 后端开始启动")
        app.state.ready = False
        runtime = AppRuntime.create(
            coordinator=coordinator,
            app_config=app_config,
            document_library=document_library,
        )
        app.state.runtime = runtime
        # 保留直接别名，让现有 API 依赖函数继续简单明确。
        app.state.coordinator = runtime.coordinator
        app.state.app_config = runtime.app_config
        app.state.document_library = runtime.document_library
        app.state.api_keys = api_key_service
        app.state.remote_session = remote_session_service
        try:
            runtime.start()
            app.state.ready = True
            logger.info("DocuMate 后端已就绪")
            yield
        finally:
            logger.info("DocuMate 后端开始关闭")
            app.state.ready = False
            runtime.close()
            logger.info("DocuMate 后端资源已释放")

    app = FastAPI(
        title="DocuMate API",
        version="0.7.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(server_config.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_keys_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(threads_router, prefix="/api")
    app.include_router(workspace_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(projects_router, prefix="/api")
    app.include_router(stats_router, prefix="/api")
    app.include_router(documents_router, prefix="/api")
    app.include_router(workspace_files_router, prefix="/api")

    @app.post("/__internal/set-token", tags=["internal"])
    def set_remote_token(payload: InternalTokenRequest) -> dict[str, str]:
        try:
            username = remote_session_service.set_token(payload.access_token, payload.username)
        except RemoteSessionError as error:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
        return {"status": "ok", "username": username}

    @app.delete("/__internal/set-token", status_code=status.HTTP_204_NO_CONTENT, tags=["internal"])
    def clear_remote_token() -> None:
        remote_session_service.clear()

    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "documate-backend"}

    @app.get("/api/ready", tags=["system"])
    def ready(request: Request, response: Response) -> dict[str, str]:
        runtime = getattr(request.app.state, "runtime", None)
        is_ready = bool(
            getattr(request.app.state, "ready", False)
            and runtime is not None
            and runtime.ready
            and not runtime.closed
        )
        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ready" if is_ready else "not_ready",
            "service": "documate-backend",
        }

    @app.exception_handler(EventLogNotFoundError)
    async def event_log_not_found_handler(
        _: Request,
        error: EventLogNotFoundError,
    ) -> JSONResponse:
        return _error_response(
            status.HTTP_404_NOT_FOUND,
            "thread_not_found",
            str(error),
            error,
        )

    @app.exception_handler(HistoryNotFoundError)
    async def history_not_found_handler(
        _: Request,
        error: HistoryNotFoundError,
    ) -> JSONResponse:
        return _error_response(
            status.HTTP_404_NOT_FOUND,
            "thread_not_found",
            str(error),
            error,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        body = ErrorResponse(
            error=ErrorDetail(
                code="validation_error",
                message="请求参数校验失败",
                error_type=type(error).__name__,
                details=[
                    {
                        key: value
                        for key, value in item.items()
                        if key in {"type", "loc", "msg"}
                    }
                    for item in error.errors()
                ],
            )
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=body.model_dump(mode="json", exclude_none=True),
        )

    @app.exception_handler(ConversationError)
    async def conversation_error_handler(
        _: Request,
        error: ConversationError,
    ) -> JSONResponse:
        message = str(error)
        forbidden = "user_id 不匹配" in message or "workspace_path 不匹配" in message
        return _error_response(
            status.HTTP_403_FORBIDDEN if forbidden else status.HTTP_409_CONFLICT,
            "conversation_forbidden" if forbidden else "conversation_conflict",
            message,
            error,
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(
        _: Request,
        error: ValueError,
    ) -> JSONResponse:
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_request",
            str(error),
            error,
        )

    @app.exception_handler(FileNotFoundError)
    async def file_not_found_handler(
        _: Request,
        error: FileNotFoundError,
    ) -> JSONResponse:
        return _error_response(
            status.HTTP_404_NOT_FOUND,
            "file_not_found",
            str(error),
            error,
        )

    @app.exception_handler(FileExistsError)
    async def file_exists_handler(
        _: Request,
        error: FileExistsError,
    ) -> JSONResponse:
        return _error_response(
            status.HTTP_409_CONFLICT,
            "file_exists",
            str(error),
            error,
        )

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(
        _: Request,
        error: RuntimeError,
    ) -> JSONResponse:
        message = str(error)
        configuration_error = message.startswith("缺少环境变量 ")
        return _error_response(
            (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if configuration_error
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            "model_configuration_error" if configuration_error else "internal_error",
            message if configuration_error else "后端内部错误",
            error,
        )

    return app


def _error_response(
    status_code: int,
    code: str,
    message: str,
    error: Exception,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            error_type=type(error).__name__,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", exclude_none=True),
    )


app = create_app()

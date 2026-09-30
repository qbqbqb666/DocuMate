import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from dotenv import load_dotenv


DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "null",
)


@dataclass(frozen=True)
class BackendConfig:
    """后端进程级配置。"""

    host: str = "127.0.0.1"
    port: int = 8765
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    log_level: str = "info"

    @classmethod
    def from_env(cls) -> "BackendConfig":
        load_dotenv()
        host = os.getenv("DOCUMATE_BACKEND_HOST", "127.0.0.1").strip()
        raw_port = os.getenv("DOCUMATE_BACKEND_PORT", "8765").strip()
        raw_origins = os.getenv("DOCUMATE_CORS_ORIGINS")
        log_level = os.getenv("DOCUMATE_LOG_LEVEL", "info").strip().lower()

        if not host:
            raise ValueError("DOCUMATE_BACKEND_HOST 不能为空")
        try:
            port = int(raw_port)
        except ValueError as error:
            raise ValueError("DOCUMATE_BACKEND_PORT 必须是整数") from error
        if not 1 <= port <= 65535:
            raise ValueError("DOCUMATE_BACKEND_PORT 必须在 1 到 65535 之间")

        origins = (
            tuple(dict.fromkeys(
                item.strip().rstrip("/")
                for item in raw_origins.split(",")
                if item.strip()
            ))
            if raw_origins is not None
            else DEFAULT_CORS_ORIGINS
        )
        if not origins:
            raise ValueError("DOCUMATE_CORS_ORIGINS 至少要包含一个来源")
        for origin in origins:
            _validate_origin(origin)
        if log_level not in {"critical", "error", "warning", "info", "debug", "trace"}:
            raise ValueError("DOCUMATE_LOG_LEVEL 无效")
        return cls(host=host, port=port, cors_origins=origins, log_level=log_level)


def _validate_origin(origin: str) -> None:
    # Electron 打包版从 file:// 加载，Chromium 将其 Origin 序列化为 null。
    if origin == "null":
        return
    if origin == "*":
        raise ValueError("CORS 启用凭据时不允许使用通配符 *")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"CORS 来源无效：{origin}")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(f"CORS 来源不能包含路径、查询或片段：{origin}")

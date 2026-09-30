import uvicorn

from src.backend.config import BackendConfig
from src.backend.main import app
from src.backend.services.parent_watchdog import start_parent_watchdog


def main() -> None:
    config = BackendConfig.from_env()
    start_parent_watchdog()
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level,
    )


if __name__ == "__main__":
    main()

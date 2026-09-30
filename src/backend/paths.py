import os
from pathlib import Path


SOURCE_BACKEND_ROOT = Path(__file__).resolve().parent


def data_directory() -> Path:
    configured = os.getenv("DOCUMATE_DATA_DIR")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else SOURCE_BACKEND_ROOT / "data"
    )


def default_workspace() -> Path:
    configured = os.getenv("DOCUMATE_DEFAULT_WORKSPACE")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else SOURCE_BACKEND_ROOT.parents[1]
    )


def app_environment_path() -> Path:
    configured = os.getenv("DOCUMATE_APP_ENV")
    if configured:
        return Path(configured).expanduser().resolve()
    data_root = os.getenv("DOCUMATE_DATA_DIR")
    if data_root:
        return Path(data_root).expanduser().resolve().parent / ".env"
    return SOURCE_BACKEND_ROOT.parents[1] / ".env"


DATA_DIRECTORY = data_directory()
DEFAULT_WORKSPACE = default_workspace()
APP_ENV_PATH = app_environment_path()

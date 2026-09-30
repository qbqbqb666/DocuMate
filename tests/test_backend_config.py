import pytest

from src.backend.config import BackendConfig


CONFIG_ENV_KEYS = (
    "DOCUMATE_BACKEND_HOST",
    "DOCUMATE_BACKEND_PORT",
    "DOCUMATE_CORS_ORIGINS",
    "DOCUMATE_LOG_LEVEL",
)


def test_backend_config_reads_and_normalizes_environment(monkeypatch) -> None:
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DOCUMATE_BACKEND_HOST", "0.0.0.0")
    monkeypatch.setenv("DOCUMATE_BACKEND_PORT", "9000")
    monkeypatch.setenv(
        "DOCUMATE_CORS_ORIGINS",
        "http://localhost:3000/, https://example.com, http://localhost:3000",
    )
    monkeypatch.setenv("DOCUMATE_LOG_LEVEL", "DEBUG")

    config = BackendConfig.from_env()

    assert config.host == "0.0.0.0"
    assert config.port == 9000
    assert config.cors_origins == (
        "http://localhost:3000",
        "https://example.com",
    )
    assert config.log_level == "debug"


def test_backend_config_accepts_electron_file_origin(monkeypatch) -> None:
    monkeypatch.setenv("DOCUMATE_CORS_ORIGINS", "null")
    assert BackendConfig.from_env().cors_origins == ("null",)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("DOCUMATE_BACKEND_PORT", "abc", "必须是整数"),
        ("DOCUMATE_BACKEND_PORT", "70000", "1 到 65535"),
        ("DOCUMATE_CORS_ORIGINS", "*", "通配符"),
        ("DOCUMATE_CORS_ORIGINS", "localhost:5173", "CORS 来源无效"),
        ("DOCUMATE_LOG_LEVEL", "verbose", "DOCUMATE_LOG_LEVEL 无效"),
    ],
)
def test_backend_config_rejects_invalid_environment(
    monkeypatch,
    key: str,
    value: str,
    message: str,
) -> None:
    for env_key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.setenv(key, value)

    with pytest.raises(ValueError, match=message):
        BackendConfig.from_env()

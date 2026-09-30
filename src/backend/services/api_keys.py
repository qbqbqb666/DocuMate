import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import httpx
from dotenv import dotenv_values, load_dotenv, set_key, unset_key

from src.backend.paths import APP_ENV_PATH


ApiKeyProvider = Literal["siliconflow", "deepseek"]

PROVIDER_CONFIG = {
    "siliconflow": {
        "key_name": "SILICONFLOW_API_KEY",
        "base_name": "SILICONFLOW_BASE_URL",
        "base_url": "https://api.siliconflow.cn/v1",
        "required_models": {"Qwen/Qwen3.5-4B"},
    },
    "deepseek": {
        "key_name": "DEEPSEEK_API_KEY",
        "base_name": "DEEPSEEK_BASE_URL",
        "base_url": "https://api.deepseek.com/v1",
        "required_models": {"deepseek-flash", "deepseek-v4-pro"},
    },
}


class ApiKeyValidationError(ValueError):
    pass


class ApiKeyService:
    """Persist and hot-reload provider credentials for the desktop app."""

    def __init__(
        self,
        path: Path = APP_ENV_PATH,
        validator: Callable[[ApiKeyProvider, str, str], None] | None = None,
    ) -> None:
        self.path = Path(path)
        self._validator = validator or self._validate_remote
        self._lock = threading.RLock()
        self._initialize_file()

    def statuses(self) -> list[dict[str, object]]:
        with self._lock:
            values = dotenv_values(self.path)
            return [self._status(provider, values) for provider in PROVIDER_CONFIG]

    def save(self, provider: ApiKeyProvider, api_key: str) -> dict[str, object]:
        clean_key = api_key.strip()
        if not clean_key:
            raise ValueError("API Key 不能为空")
        config = PROVIDER_CONFIG[provider]
        base_url = str(os.getenv(str(config["base_name"])) or config["base_url"])
        self._validator(provider, clean_key, base_url)
        with self._lock:
            set_key(str(self.path), str(config["key_name"]), clean_key, quote_mode="always")
            os.chmod(self.path, 0o600)
            os.environ[str(config["key_name"])] = clean_key
            os.environ[str(config["base_name"])] = base_url
            self._clear_model_cache()
            return self._status(provider, dotenv_values(self.path))

    def delete(self, provider: ApiKeyProvider) -> None:
        config = PROVIDER_CONFIG[provider]
        with self._lock:
            unset_key(str(self.path), str(config["key_name"]), quote_mode="always")
            os.chmod(self.path, 0o600)
            os.environ.pop(str(config["key_name"]), None)
            self._clear_model_cache()

    def _initialize_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("# DocuMate local AI provider configuration\n", encoding="utf-8")
        os.chmod(self.path, 0o600)
        values = dotenv_values(self.path)
        for config in PROVIDER_CONFIG.values():
            base_name = str(config["base_name"])
            key_name = str(config["key_name"])
            if not values.get(base_name):
                set_key(str(self.path), base_name, str(config["base_url"]), quote_mode="never")
            if key_name not in values:
                set_key(str(self.path), key_name, "", quote_mode="always")
        load_dotenv(self.path, override=True)

    @staticmethod
    def _status(provider: ApiKeyProvider, values: dict | object) -> dict[str, object]:
        config = PROVIDER_CONFIG[provider]
        data = values if isinstance(values, dict) else dict(values)
        api_key = str(data.get(str(config["key_name"])) or "")
        return {
            "provider": provider,
            "configured": bool(api_key),
            "last4": api_key[-4:] if api_key else None,
        }

    @staticmethod
    def _validate_remote(provider: ApiKeyProvider, api_key: str, base_url: str) -> None:
        try:
            response = httpx.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15.0,
            )
        except httpx.HTTPError as error:
            raise ApiKeyValidationError(f"无法连接 {provider} 服务，请检查网络后重试") from error
        if response.status_code in {401, 403}:
            raise ApiKeyValidationError("API Key 验证失败，请检查后重新填写")
        if response.is_error:
            raise ApiKeyValidationError(f"{provider} 服务验证失败（HTTP {response.status_code}）")
        try:
            available = {item["id"] for item in response.json().get("data", [])}
        except (ValueError, TypeError, KeyError) as error:
            raise ApiKeyValidationError(f"{provider} 返回了无法识别的模型列表") from error
        required = PROVIDER_CONFIG[provider]["required_models"]
        if not set(required).issubset(available):
            raise ApiKeyValidationError(f"当前 {provider} Key 无法访问 DocuMate 所需模型")

    @staticmethod
    def _clear_model_cache() -> None:
        from src.backend.agent.model_resolver import model_resolver

        model_resolver.clear_cache()

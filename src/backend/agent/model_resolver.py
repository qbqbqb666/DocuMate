import threading
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models.chat_models import BaseChatModel

from src.backend.agent.context import (
    ModelProvider,
    create_summarization_middleware,
)
from src.backend.agent.tools import ALL_TOOLS
from src.backend.services.llm import MODEL_MAX_INPUT_TOKENS, create_model


@dataclass(frozen=True)
class ModelSpec:
    """一个可选模型及其上下文上限。"""

    provider: ModelProvider
    model_name: str
    max_input_tokens: int


@dataclass(frozen=True)
class ResolvedModel:
    """节点共用的模型、工具绑定模型和摘要器。"""

    provider: ModelProvider
    model_name: str
    model: BaseChatModel
    model_with_tools: Any
    summarizer: SummarizationMiddleware


MODEL_SPECS: dict[tuple[ModelProvider, str], ModelSpec] = {
    (ModelProvider(provider), model_name): ModelSpec(
        provider=ModelProvider(provider),
        model_name=model_name,
        max_input_tokens=max_input_tokens,
    )
    for (provider, model_name), max_input_tokens
    in MODEL_MAX_INPUT_TOKENS.items()
}


class UnsupportedModelError(ValueError):
    """供应商和模型名称未在注册表中登记。"""


class ModelResolver:
    """按 provider/model_name 惰性创建并缓存模型运行组合。"""

    def __init__(self) -> None:
        self._cache: dict[tuple[ModelProvider, str], ResolvedModel] = {}
        self._lock = threading.RLock()

    def resolve(
        self,
        provider: ModelProvider,
        model_name: str,
    ) -> ResolvedModel:
        try:
            normalized_provider = ModelProvider(provider)
        except ValueError as error:
            raise UnsupportedModelError(f"不支持的模型供应商：{provider}") from error
        key = (normalized_provider, model_name)
        spec = MODEL_SPECS.get(key)
        if spec is None:
            raise UnsupportedModelError(
                f"尚未注册模型：{normalized_provider.value}/{model_name}"
            )

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            model = create_model(
                spec.provider.value,
                spec.model_name,
                max_input_tokens=spec.max_input_tokens,
            )
            resolved = ResolvedModel(
                provider=spec.provider,
                model_name=spec.model_name,
                model=model,
                model_with_tools=model.bind_tools(ALL_TOOLS),
                summarizer=create_summarization_middleware(model),
            )
            self._cache[key] = resolved
            return resolved

    def clear_cache(self) -> None:
        """在凭据更换后丢弃已创建的模型客户端。"""
        with self._lock:
            self._cache.clear()


model_resolver = ModelResolver()

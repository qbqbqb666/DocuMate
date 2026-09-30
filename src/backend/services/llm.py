import os

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

from src.backend.paths import APP_ENV_PATH


load_dotenv(APP_ENV_PATH, override=False)


MODEL_MAX_INPUT_TOKENS = {
    ("siliconflow", "Qwen/Qwen3.5-4B"): 262_144,
    ("deepseek", "deepseek-flash"): 1_048_576,
    ("deepseek", "deepseek-v4-pro"): 1_048_576,
}

MODEL_DISPLAY_NAMES = {
    ("siliconflow", "Qwen/Qwen3.5-4B"): "Qwen 3.5 4B",
    ("deepseek", "deepseek-flash"): "DeepSeek V4.1 Flash",
    ("deepseek", "deepseek-v4-pro"): "DeepSeek V4 Pro",
}


def create_deepseek_model(
    model_name: str = "deepseek-flash",
    *,
    max_input_tokens: int | None = None,
):
    """创建通过 DeepSeek 官方 API 调用的聊天模型。"""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

    if not api_key:
        raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY")

    resolved_max_input_tokens = _resolve_max_input_tokens(
        model_name,
        max_input_tokens,
        _provider_models("deepseek"),
    )
    return init_chat_model(
        model=model_name,
        model_provider="deepseek",
        api_key=api_key,
        base_url=base_url,
        profile={"max_input_tokens": resolved_max_input_tokens},
        temperature=0,
        max_retries=2,
    )


def create_siliconflow_model(
    model_name: str = "Qwen/Qwen3.5-4B",
    *,
    max_input_tokens: int | None = None,
):
    """创建通过 SiliconFlow OpenAI 兼容 API 调用的聊天模型。"""
    api_key = os.getenv("SILICONFLOW_API_KEY")
    base_url = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")

    if not api_key:
        raise RuntimeError("缺少环境变量 SILICONFLOW_API_KEY")

    resolved_max_input_tokens = _resolve_max_input_tokens(
        model_name,
        max_input_tokens,
        _provider_models("siliconflow"),
    )

    return init_chat_model(
        model=model_name,
        model_provider="openai",
        api_key=api_key,
        base_url=base_url,
        # SiliconFlow 使用 OpenAI 兼容层，LangChain 无法自动识别其模型
        # Profile，因此在工厂层补入上下文上限。Context Engineering 后续
        # 统一从 model.profile 动态读取，不再绑定某个模型的固定 Token 数。
        profile={"max_input_tokens": resolved_max_input_tokens},
        temperature=0,
        max_retries=2,
        # Agent 工具调用需要模型尽快输出结构化 tool_calls。Qwen3 的
        # 默认思考模式可能只消耗推理 token 后返回空正文，因此关闭思考。
        extra_body={"enable_thinking": False},
    )


def create_model(
    provider: str,
    model_name: str,
    *,
    max_input_tokens: int,
):
    """根据 DocuMate 逻辑供应商创建聊天模型。"""
    if provider == "siliconflow":
        return create_siliconflow_model(
            model_name,
            max_input_tokens=max_input_tokens,
        )
    if provider == "deepseek":
        return create_deepseek_model(
            model_name,
            max_input_tokens=max_input_tokens,
        )
    raise ValueError(f"不支持的模型供应商：{provider}")


def _resolve_max_input_tokens(
    model_name: str,
    explicit_value: int | None,
    registered_values: dict[str, int],
) -> int:
    value = explicit_value
    if value is None:
        value = registered_values.get(model_name)
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ValueError(
            f"缺少模型 {model_name!r} 的 max_input_tokens；"
            "请在模型注册表中登记，或创建模型时显式传入"
        )
    return value


def _provider_models(provider: str) -> dict[str, int]:
    return {
        model_name: max_input_tokens
        for (registered_provider, model_name), max_input_tokens
        in MODEL_MAX_INPUT_TOKENS.items()
        if registered_provider == provider
    }

from fastapi import APIRouter, Depends

from src.backend.api.schemas import (
    AppSettingsResponse,
    ModelOptionResponse,
    UpdateSettingsRequest,
)
from src.backend.api.workspace import get_app_config
from src.backend.services.app_config import AppConfigService
from src.backend.services.llm import MODEL_DISPLAY_NAMES, MODEL_MAX_INPUT_TOKENS


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettingsResponse)
def get_settings(
    service: AppConfigService = Depends(get_app_config),
) -> dict:
    return service.settings()


@router.patch("", response_model=AppSettingsResponse)
def update_settings(
    body: UpdateSettingsRequest,
    service: AppConfigService = Depends(get_app_config),
) -> dict:
    return service.update_settings(body.model_dump(exclude_none=True))


@router.get("/models", response_model=list[ModelOptionResponse])
def list_models() -> list[dict]:
    return [
        {
            "provider": provider,
            "model_name": model_name,
            "display_name": MODEL_DISPLAY_NAMES[(provider, model_name)],
            "max_input_tokens": max_input_tokens,
        }
        for (provider, model_name), max_input_tokens
        in MODEL_MAX_INPUT_TOKENS.items()
    ]

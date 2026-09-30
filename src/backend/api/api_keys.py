from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from src.backend.api.schemas import ApiKeyStatusResponse, SaveApiKeyRequest
from src.backend.services.api_keys import ApiKeyService
from src.backend.services.remote_session import RemoteSessionService


router = APIRouter(tags=["api-keys"])


def get_api_keys(request: Request) -> ApiKeyService:
    service = getattr(request.app.state, "api_keys", None)
    if service is None:
        raise RuntimeError("ApiKeyService 尚未初始化")
    return service


def get_remote_session(request: Request) -> RemoteSessionService:
    service = getattr(request.app.state, "remote_session", None)
    if service is None:
        raise RuntimeError("RemoteSessionService 尚未初始化")
    return service


def require_remote_user(
    authorization: str | None,
    remote: RemoteSessionService,
) -> None:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    if not remote.authorize(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已失效，请重新登录",
        )


@router.get("/user/api-keys", response_model=list[ApiKeyStatusResponse])
def api_key_statuses(
    authorization: str | None = Header(default=None),
    remote: RemoteSessionService = Depends(get_remote_session),
    api_keys: ApiKeyService = Depends(get_api_keys),
) -> list[dict[str, object]]:
    require_remote_user(authorization, remote)
    return api_keys.statuses()


@router.put("/user/api-keys/{provider}", response_model=ApiKeyStatusResponse)
def save_api_key(
    provider: Literal["siliconflow", "deepseek"],
    payload: SaveApiKeyRequest,
    authorization: str | None = Header(default=None),
    remote: RemoteSessionService = Depends(get_remote_session),
    api_keys: ApiKeyService = Depends(get_api_keys),
) -> dict[str, object]:
    require_remote_user(authorization, remote)
    return api_keys.save(provider, payload.api_key)


@router.delete("/user/api-keys/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(
    provider: Literal["siliconflow", "deepseek"],
    authorization: str | None = Header(default=None),
    remote: RemoteSessionService = Depends(get_remote_session),
    api_keys: ApiKeyService = Depends(get_api_keys),
) -> None:
    require_remote_user(authorization, remote)
    api_keys.delete(provider)


from fastapi import APIRouter, Depends, Request

from src.backend.api.schemas import (
    RecentWorkspaceResponse,
    SwitchWorkspaceRequest,
    SwitchWorkspaceResponse,
    WorkspaceInfoResponse,
)
from src.backend.services.app_config import AppConfigService


router = APIRouter(prefix="/workspace", tags=["workspace"])


def get_app_config(request: Request) -> AppConfigService:
    service = getattr(request.app.state, "app_config", None)
    if service is None:
        raise RuntimeError("AppConfigService 尚未初始化")
    return service


@router.get("", response_model=WorkspaceInfoResponse)
def get_workspace(
    service: AppConfigService = Depends(get_app_config),
) -> dict:
    return service.workspace_info()


@router.get("/recent", response_model=list[RecentWorkspaceResponse])
def get_recent_workspaces(
    service: AppConfigService = Depends(get_app_config),
) -> list[dict]:
    return service.recent_workspaces()


@router.post("/switch", response_model=SwitchWorkspaceResponse)
def switch_workspace(
    body: SwitchWorkspaceRequest,
    service: AppConfigService = Depends(get_app_config),
) -> SwitchWorkspaceResponse:
    return SwitchWorkspaceResponse(
        info=WorkspaceInfoResponse.model_validate(service.switch_workspace(body.path))
    )

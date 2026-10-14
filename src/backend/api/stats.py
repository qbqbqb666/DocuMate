from fastapi import APIRouter, Depends

from src.backend.api.chat import LOCAL_USER_ID, get_coordinator
from src.backend.api.workspace_files import roots
from src.backend.api.schemas import WorkspaceStatsResponse
from src.backend.api.workspace import get_app_config
from src.backend.services.app_config import AppConfigService
from src.backend.services.conversation import ConversationCoordinator


router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=WorkspaceStatsResponse)
def workspace_stats(
    coordinator: ConversationCoordinator = Depends(get_coordinator),
    config: AppConfigService = Depends(get_app_config),
) -> WorkspaceStatsResponse:
    workspace_path = config.workspace_info()["path"]
    history = coordinator.history.workspace_stats(
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
    )
    return WorkspaceStatsResponse(
        document_count=roots(config)["total_files"],
        thread_count=history["thread_count"],
        total_tokens=history["total_tokens"],
    )

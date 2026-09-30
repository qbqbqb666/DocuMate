from fastapi import APIRouter, Depends, Query, Response, status

from src.backend.api.chat import LOCAL_USER_ID, get_coordinator
from src.backend.api.schemas import (
    ArtifactListResponse,
    MessageListResponse,
    ThreadDetailResponse,
    ThreadSummaryResponse,
    RenameThreadRequest,
)
from src.backend.services.conversation import ConversationCoordinator


router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("", response_model=list[ThreadSummaryResponse])
def list_threads(
    workspace_path: str = Query(min_length=1),
    project_id: str | None = Query(default=None),
    coordinator: ConversationCoordinator = Depends(get_coordinator),
) -> list[dict]:
    return coordinator.history.list_threads(
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
        project_id=project_id,
    )


@router.get("/{thread_id}", response_model=ThreadDetailResponse)
def get_thread(
    thread_id: str,
    workspace_path: str = Query(min_length=1),
    coordinator: ConversationCoordinator = Depends(get_coordinator),
) -> dict:
    return coordinator.history.get_thread(
        thread_id=thread_id,
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
    )


@router.get("/{thread_id}/messages", response_model=MessageListResponse)
def list_messages(
    thread_id: str,
    workspace_path: str = Query(min_length=1),
    coordinator: ConversationCoordinator = Depends(get_coordinator),
) -> MessageListResponse:
    messages = coordinator.history.list_messages(
        thread_id=thread_id,
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
    )
    return MessageListResponse.model_validate({"messages": messages})


@router.get("/{thread_id}/artifacts", response_model=ArtifactListResponse)
def list_artifacts(
    thread_id: str,
    workspace_path: str = Query(min_length=1),
    coordinator: ConversationCoordinator = Depends(get_coordinator),
) -> ArtifactListResponse:
    artifacts = coordinator.history.list_artifacts(
        thread_id=thread_id,
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
    )
    return ArtifactListResponse.model_validate({"artifacts": artifacts})


@router.patch("/{thread_id}")
def rename_thread(
    thread_id: str,
    body: RenameThreadRequest,
    workspace_path: str = Query(min_length=1),
    coordinator: ConversationCoordinator = Depends(get_coordinator),
) -> dict:
    return coordinator.history.rename_thread(
        thread_id=thread_id,
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
        title=body.title,
    )


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(
    thread_id: str,
    workspace_path: str = Query(min_length=1),
    coordinator: ConversationCoordinator = Depends(get_coordinator),
) -> Response:
    coordinator.history.delete_thread(
        thread_id=thread_id,
        user_id=LOCAL_USER_ID,
        workspace_path=workspace_path,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

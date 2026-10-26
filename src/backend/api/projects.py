from fastapi import APIRouter, Depends, status

from src.backend.api.schemas import CreateProjectRequest, ProjectResponse
from src.backend.api.workspace import get_app_config
from src.backend.api.workspace_files import get_index
from src.backend.services.retrieval import RetrievalService
from src.backend.services.app_config import AppConfigService


router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    service: AppConfigService = Depends(get_app_config),
) -> list[dict]:
    return service.projects()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    body: CreateProjectRequest,
    service: AppConfigService = Depends(get_app_config),
) -> dict:
    return service.create_project(body.name, body.folder_paths)


@router.post("/{project_id}/activate", response_model=ProjectResponse)
def activate_project(
    project_id: str,
    service: AppConfigService = Depends(get_app_config),
) -> dict:
    return service.activate_project(project_id)


@router.delete("/{project_id}")
def remove_project(project_id: str, service: AppConfigService = Depends(get_app_config), index: RetrievalService = Depends(get_index)) -> dict:
    service.remove_project(project_id)
    index.retain_path = service.document_retained
    index.visible_path = service.search_visible
    index.prune_removed()
    return {"removed": True}

from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse

from src.backend.api.chat import LOCAL_USER_ID, get_coordinator
from src.backend.api.schemas import (
    DocumentDetailResponse,
    DocumentResponse,
    SearchRequest,
    SearchResponse,
)
from src.backend.api.workspace import get_app_config
from src.backend.services.app_config import AppConfigService
from src.backend.services.conversation import ConversationCoordinator
from src.backend.services.document_library import DocumentLibrary, MAX_UPLOAD_BYTES


router = APIRouter(tags=["documents"])


def get_document_library(request: Request) -> DocumentLibrary:
    service = getattr(request.app.state, "document_library", None)
    if service is None:
        raise RuntimeError("DocumentLibrary 尚未初始化")
    return service


def _workspace(config: AppConfigService) -> str:
    return config.workspace_info()["path"]


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    library: DocumentLibrary = Depends(get_document_library),
    config: AppConfigService = Depends(get_app_config),
) -> list[dict]:
    return library.list_documents(_workspace(config))


@router.post("/documents/upload", response_model=DocumentDetailResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    library: DocumentLibrary = Depends(get_document_library),
    config: AppConfigService = Depends(get_app_config),
) -> dict:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    return library.upload(
        _workspace(config),
        filename=file.filename or "",
        content=content,
    )


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    document_id: str,
    library: DocumentLibrary = Depends(get_document_library),
    config: AppConfigService = Depends(get_app_config),
) -> dict:
    return library.detail(_workspace(config), document_id)


@router.post("/search", response_model=SearchResponse)
def search_documents(
    body: SearchRequest,
    library: DocumentLibrary = Depends(get_document_library),
    config: AppConfigService = Depends(get_app_config),
) -> SearchResponse:
    hits = library.search(_workspace(config), query=body.query, limit=body.top_k)
    return SearchResponse.model_validate({"hits": hits})


@router.get("/artifacts/{artifact_id}/download", response_class=FileResponse)
def download_artifact(
    artifact_id: str,
    coordinator: ConversationCoordinator = Depends(get_coordinator),
    config: AppConfigService = Depends(get_app_config),
) -> FileResponse:
    workspace = Path(_workspace(config)).resolve()
    artifact = coordinator.history.get_artifact(
        artifact_id=artifact_id,
        user_id=LOCAL_USER_ID,
        workspace_path=str(workspace),
    )
    requested = Path(artifact["url"]).expanduser()
    path = requested.resolve() if requested.is_absolute() else (workspace / requested).resolve()
    if path != workspace and not path.is_relative_to(workspace):
        raise ValueError("artifact 路径超出当前工作区")
    if not path.is_file():
        raise FileNotFoundError(f"artifact 文件不存在：{artifact_id}")
    return FileResponse(path, media_type=artifact["mime_type"], filename=artifact["name"])

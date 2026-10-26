"""浏览和登记当前项目原文件；保留原位置，由后台维护检索索引。"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from src.backend.api.workspace import get_app_config
from src.backend.services.app_config import AppConfigService
from src.backend.services.document_library import MAX_PREVIEW_CHARS, MAX_UPLOAD_BYTES
from src.backend.services.document_parser import SUPPORTED_SUFFIXES, parse_document
from src.backend.services.workspace import EXCLUDED_SEARCH_DIRECTORIES
from src.backend.services.retrieval import RetrievalService, get_retrieval_service

router = APIRouter(prefix="/workspace-files", tags=["workspace-files"])


def project_roots(config: AppConfigService) -> list[Path]:
    sources = config.workspace_sources()
    roots = list(dict.fromkeys(Path(source["path"]) for source in sources
        if not Path(source["path"]).exists() or config.source_exists(source)))
    legacy = [root / ".documate" / "documents" for root in roots if root.is_dir()]
    return roots + [path for path in legacy if path.is_dir() and path.resolve() == path and path not in roots]


def get_index(request: Request) -> RetrievalService:
    service = request.app.state.runtime.retrieval or get_retrieval_service()
    config = get_app_config(request)
    service.retain_path = config.document_retained
    service.visible_path = config.search_visible
    return service


class DocumentSource(BaseModel):
    group_path: str | None = None
    path: str
    kind: Literal["file", "directory"]


class RegisterDocuments(BaseModel):
    workspace_path: str
    project_id: str | None = None
    sources: list[DocumentSource] = Field(min_length=1, max_length=20_000)


class CandidateRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=20_000)
    recursive: bool = False


def scan_files(paths: list[Path]) -> set[Path]:
    files: set[Path] = set()
    for root in paths:
        if root.is_file() and visible(root) and root.suffix.lower() in SUPPORTED_SUFFIXES:
            files.add(root)
        elif root.is_dir():
            def fail(error: OSError) -> None:
                raise error
            for folder, directories, filenames in os.walk(root, onerror=fail, followlinks=False):
                directories[:] = [d for d in directories if visible(Path(folder) / d)]
                files.update(Path(folder) / name for name in filenames
                    if visible(Path(folder) / name) and Path(name).suffix.lower() in SUPPORTED_SUFFIXES)
                if len(files) > 20_000:
                    raise ValueError("资料超过 20000 份，请选择较小的文件夹")
    return files


@router.post("/candidates")
def candidates(body: CandidateRequest) -> dict:
    paths = []
    for value in body.paths:
        path = Path(value)
        if (not path.is_absolute() or path.resolve() != path or not path.exists()
                or any(part.startswith(".") or part in EXCLUDED_SEARCH_DIRECTORIES for part in path.parts[1:])
                or not visible(path)):
            raise ValueError("请选择存在的普通文件或文件夹，不支持隐藏目录或符号链接")
        if body.recursive and not path.is_dir():
            raise ValueError("请选择文件夹")
        if not body.recursive and (not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES):
            raise ValueError("支持 PDF、DOCX、XLSX、TXT 和 Markdown")
        paths.append(path)
    files = scan_files(paths) if body.recursive else set(paths)
    return {"files": [entry(path) for path in sorted(files)], "total": len(files)}


@router.post("/register")
def register_documents(body: RegisterDocuments, config: AppConfigService = Depends(get_app_config), service: RetrievalService = Depends(get_index)) -> dict:
    sources = config.register_documents(body.workspace_path, body.project_id, [source.model_dump() for source in body.sources])
    service.request_index([source["path"] for source in sources if not Path(source["path"]).exists() or config.source_exists(source)])
    return {"registered": len(body.sources)}


class RemoveDocument(BaseModel):
    workspace_path: str
    project_id: str | None = None
    path: str | None = None
    paths: list[str] | None = Field(default=None, min_length=1, max_length=20_000)


@router.post("/remove")
def remove_document(body: RemoveDocument, config: AppConfigService = Depends(get_app_config), service: RetrievalService = Depends(get_index)) -> dict:
    config.remove_documents(body.workspace_path, body.project_id, body.paths or ([body.path] if body.path else []))
    service.retain_path = config.document_retained
    service.visible_path = config.search_visible
    service.prune_removed()
    return {"removed": True}


@router.post("/enter-workspace")
def enter_workspace(body: CandidateRequest, config: AppConfigService = Depends(get_app_config), service: RetrievalService = Depends(get_index)) -> dict:
    if len(body.paths) != 1:
        raise ValueError("请选择一个文件")
    path = scoped_path(config, body.paths[0])
    if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("请选择支持的资料文件")
    project = config.project_for_document(str(path))
    config.activate_project(project["id"])
    service.request_index([path])
    return {"project": project, "file": entry(path), "index": service.index_status([path])["files"][0]}


@router.post("/refresh")
def refresh_index(config: AppConfigService = Depends(get_app_config), service: RetrievalService = Depends(get_index)) -> dict:
    service.request_index(config.index_paths())
    return {"queued": True}


@router.get("/index-status")
def index_status(config: AppConfigService = Depends(get_app_config), service: RetrievalService = Depends(get_index)) -> dict:
    paths = project_roots(config)
    missing = [Path(source["path"]) for source in config.workspace_sources()
               if not config.source_exists(source)]
    return service.index_status([path for path in [*scan_files(paths), *missing] if config.document_visible(path)])


def visible(path: Path) -> bool:
    return not path.name.startswith(".") and path.name not in EXCLUDED_SEARCH_DIRECTORIES and not path.is_symlink()


def scoped_path(config: AppConfigService, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError("文件路径无效")
    roots = project_roots(config)
    if not config.document_visible(path, directory=path.is_dir()):
        raise ValueError("资料已从当前项目移除")
    if not any(path == root or path.is_relative_to(root) for root in roots):
        raise ValueError("文件路径超出当前项目")
    if path.resolve() != path or path.is_symlink():
        raise ValueError("不支持符号链接路径")
    if not path.exists():
        raise FileNotFoundError("原文件已移除或路径不存在")
    root = max((r for r in roots if path == r or path.is_relative_to(r)), key=lambda r: len(r.parts))
    if any(not visible(root.joinpath(*path.relative_to(root).parts[:i + 1])) for i in range(len(path.relative_to(root).parts))):
        raise ValueError("此目录不在文件区浏览范围")
    return path


def entry(path: Path) -> dict:
    info = path.stat()
    return {"id": str(path), "filename": path.name, "saved_path": str(path),
            "kind": "directory" if path.is_dir() else "file",
            "doc_type": path.suffix.lower().lstrip("."), "size_bytes": info.st_size,
            "uploaded_at": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
            "previewable": path.suffix.lower() in SUPPORTED_SUFFIXES}


@router.get("")
def roots(config: AppConfigService = Depends(get_app_config)) -> dict:
    paths = project_roots(config)
    files = {path for path in scan_files(paths) if config.document_visible(path)}
    sources = {source["path"]: source["kind"] for source in config.workspace_sources()}
    groups = {source["path"]: source.get("group_path") for source in config.workspace_sources() if source.get("group_path")}
    entries = []
    for path in dict.fromkeys([*paths, *(Path(value) for value in sources)]):
        if not config.document_visible(path, directory=sources.get(str(path)) == "directory" or path.is_dir()):
            continue
        if path.exists() and (str(path) not in sources or config.source_exists({"path": str(path), "kind": sources[str(path)]})):
            item = entry(path)
        else:
            item = {"id": str(path), "filename": path.name, "saved_path": str(path),
                    "kind": sources.get(str(path), "directory"), "doc_type": path.suffix.lstrip("."),
                    "size_bytes": 0, "uploaded_at": "", "previewable": False, "missing": True}
        if path.parts[-2:] == (".documate", "documents"):
            item["filename"] = f"旧版导入资料 · {path.parent.parent.name}"
        if str(path) in groups:
            item["group_path"] = groups[str(path)]
        entries.append(item)
    return {"roots": entries, "total_files": len(files)}


@router.get("/children")
def children(path: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200), config: AppConfigService = Depends(get_app_config)) -> dict:
    directory = scoped_path(config, path)
    if not directory.is_dir():
        raise ValueError("请选择文件夹")
    items = sorted((p for p in directory.iterdir() if visible(p) and config.document_visible(p, directory=p.is_dir()) and (p.is_dir() or p.is_file())), key=lambda p: (not p.is_dir(), p.name.casefold()))
    return {"entries": [entry(p) for p in items[offset:offset + limit]], "total": len(items)}


@router.get("/preview")
def preview(path: str, known_version: str | None = None, config: AppConfigService = Depends(get_app_config)) -> dict:
    source = scoped_path(config, path)
    if not source.is_file() or source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("支持预览 PDF、DOCX、XLSX、TXT 和 Markdown")
    if source.stat().st_size > MAX_UPLOAD_BYTES:
        raise ValueError("文件超过 50 MB，暂不支持预览")
    before = source.stat()
    version = f"{before.st_dev}:{before.st_ino}:{before.st_size}:{before.st_mtime_ns}:{before.st_ctime_ns}"
    if known_version == version:
        return {"unchanged": True, "version": version}
    try:
        text = "\n".join(block.text for block in parse_document(source))
    except Exception as error:
        raise ValueError(f"无法解析原文件：{source.name}") from error
    after = source.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("文件正在保存，请稍后重新预览")
    return {**entry(source), "text": text[:MAX_PREVIEW_CHARS], "char_count": len(text), "truncated": len(text) > MAX_PREVIEW_CHARS, "version": version}

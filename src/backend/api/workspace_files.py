"""按需浏览当前项目原文件；不复制文件，也不触发向量计算。"""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from src.backend.api.workspace import get_app_config
from src.backend.services.app_config import AppConfigService
from src.backend.services.document_library import MAX_PREVIEW_CHARS, MAX_UPLOAD_BYTES
from src.backend.services.document_parser import SUPPORTED_SUFFIXES, parse_document
from src.backend.services.workspace import EXCLUDED_SEARCH_DIRECTORIES

router = APIRouter(prefix="/workspace-files", tags=["workspace-files"])


def project_roots(config: AppConfigService) -> list[Path]:
    workspace = Path(config.workspace_info()["path"])
    project = next((p for p in config.projects() if p["is_active"] and p["primary_path"] == str(workspace)), None)
    roots = list(dict.fromkeys(Path(p) for p in (project["folder_paths"] if project else [str(workspace)])))
    legacy = [root / ".documate" / "documents" for root in roots]
    return roots + [path for path in legacy if path.is_dir() and path.resolve() == path and path not in roots]


def visible(path: Path) -> bool:
    return not path.name.startswith(".") and path.name not in EXCLUDED_SEARCH_DIRECTORIES and not path.is_symlink()


def scoped_path(config: AppConfigService, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError("文件路径无效")
    roots = project_roots(config)
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
    files: set[Path] = set()
    def fail(error: OSError) -> None:
        raise error
    for root in paths:
        if not root.is_dir():
            raise FileNotFoundError(f"项目文件夹不存在：{root}")
        for folder, directories, filenames in os.walk(root, onerror=fail):
            directories[:] = [d for d in directories if visible(Path(folder) / d)]
            files.update(Path(folder) / name for name in filenames if visible(Path(folder) / name) and Path(name).suffix.lower() in SUPPORTED_SUFFIXES)
    entries = [entry(p) for p in paths]
    for item in entries:
        if Path(item["id"]).parts[-2:] == (".documate", "documents"):
            item["filename"] = f"旧版导入资料 · {Path(item['id']).parent.parent.name}"
    return {"roots": entries, "total_files": len(files)}


@router.get("/children")
def children(path: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200), config: AppConfigService = Depends(get_app_config)) -> dict:
    directory = scoped_path(config, path)
    if not directory.is_dir():
        raise ValueError("请选择文件夹")
    items = sorted((p for p in directory.iterdir() if visible(p) and (p.is_dir() or p.is_file())), key=lambda p: (not p.is_dir(), p.name.casefold()))
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

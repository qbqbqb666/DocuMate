import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.backend.services.llm import MODEL_MAX_INPUT_TOKENS
from src.backend.paths import DATA_DIRECTORY, DEFAULT_WORKSPACE


APP_CONFIG_PATH = DATA_DIRECTORY / "app_config.json"


class AppConfigService:
    """本地单用户的工作区和 Agent 偏好。"""

    def __init__(self, path: Path = APP_CONFIG_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def workspace_info(self) -> dict[str, Any]:
        data = self._read()
        configured = data.get("workspace_path")
        workspace = Path(configured).resolve() if configured else DEFAULT_WORKSPACE.resolve()
        return {
            "path": str(workspace),
            "is_user_set": configured is not None,
            "is_dev_default": configured is None,
            "documents_dir": str(workspace / ".documate" / "documents"),
            "generated_dir": str(workspace / ".documate" / "generated"),
            "vectors_dir": str(workspace / ".documate" / "vectors"),
            "config_file": str(self.path),
        }

    def recent_workspaces(self) -> list[dict[str, Any]]:
        current = self.workspace_info()["path"]
        return [
            {
                "path": path,
                "name": Path(path).name or path,
                "exists": Path(path).is_dir(),
                "is_current": path == current,
            }
            for path in self._read().get("recent_workspaces", [])
        ]

    def switch_workspace(self, path: str) -> dict[str, Any]:
        workspace = Path(path).expanduser().resolve()
        if not workspace.exists():
            raise ValueError(f"工作区不存在：{workspace}")
        if not workspace.is_dir():
            raise ValueError(f"工作区不是目录：{workspace}")

        data = self._read()
        recent = [str(workspace), *data.get("recent_workspaces", [])]
        data["workspace_path"] = str(workspace)
        data["recent_workspaces"] = list(dict.fromkeys(recent))[:10]
        self._write(data)
        return self.workspace_info()

    def projects(self) -> list[dict[str, Any]]:
        """返回项目列表，并把旧版最近工作区无损迁移为项目。"""
        data = self._read()
        projects = self._normalized_projects(data)
        if projects != data.get("projects"):
            data["projects"] = projects
            if projects and not data.get("active_project_id"):
                data["active_project_id"] = projects[0]["id"]
            self._write(data)
        active_id = data.get("active_project_id")
        return [
            {**{key: value for key, value in project.items() if key != "document_sources"}, "is_active": project["id"] == active_id}
            for project in projects
        ]

    def project(self, project_id: str) -> dict[str, Any]:
        project = next(
            (item for item in self.projects() if item["id"] == project_id),
            None,
        )
        if project is None:
            raise ValueError(f"找不到项目：{project_id}")
        return project

    def create_project(self, name: str, folder_paths: list[str]) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("项目名称不能为空")
        folders = self._validate_project_folders(folder_paths)
        data = self._read()
        projects = self._normalized_projects(data)
        if any(item["name"].casefold() == clean_name.casefold() for item in projects):
            raise ValueError(f"项目名称已存在：{clean_name}")
        if any(item["primary_path"] == folders[0] for item in projects):
            raise ValueError("该默认文件夹已属于其他项目")
        now = datetime.now(timezone.utc).isoformat()
        project = {
            "id": str(uuid4()),
            "name": clean_name,
            "folder_paths": folders,
            "primary_path": folders[0],
            "created_at": now,
        }
        projects.append(project)
        data["projects"] = projects
        data["active_project_id"] = project["id"]
        data["workspace_path"] = project["primary_path"]
        recent = [project["primary_path"], *data.get("recent_workspaces", [])]
        data["recent_workspaces"] = list(dict.fromkeys(recent))[:10]
        self._write(data)
        return {**project, "is_active": True}

    def activate_project(self, project_id: str) -> dict[str, Any]:
        project = self.project(project_id)
        data = self._read()
        data["active_project_id"] = project_id
        data["workspace_path"] = project["primary_path"]
        self._write(data)
        return {**project, "is_active": True}

    def workspace_sources(self, workspace_path: str | None = None) -> list[dict[str, str]]:
        workspace = workspace_path or self.workspace_info()["path"]
        self.projects()
        project = next((p for p in self._read().get("projects", []) if p["primary_path"] == workspace), None)
        folders = project["folder_paths"] if project else [workspace]
        return [{"path": path, "kind": "directory"} for path in folders] + (project.get("document_sources", []) if project else [])

    @staticmethod
    def source_exists(source: dict[str, str]) -> bool:
        path = Path(source["path"])
        return (not path.is_symlink() and path.resolve() == path and
                (path.is_dir() if source["kind"] == "directory" else path.is_file()))

    def index_paths(self) -> list[str]:
        return [source["path"] for source in self.workspace_sources()
                if self.source_exists(source) or not Path(source["path"]).exists()]

    def register_documents(self, workspace_path: str, project_id: str | None, sources: list[dict[str, str]]) -> list[dict[str, str]]:
        from src.backend.services.document_parser import SUPPORTED_SUFFIXES
        from src.backend.services.workspace import EXCLUDED_SEARCH_DIRECTORIES

        if not sources or len(sources) > 20_000:
            raise ValueError("请选择 1～20000 个文件或文件夹")
        validated = []
        for source in sources:
            path = Path(source["path"])
            kind = source["kind"]
            if (not path.is_absolute() or path.resolve() != path or path.is_symlink()
                    or any(part.startswith(".") or part in EXCLUDED_SEARCH_DIRECTORIES for part in path.parts[1:])):
                raise ValueError("请选择普通文件或文件夹，不支持隐藏目录或符号链接")
            if kind not in {"file", "directory"} or not (path.is_file() if kind == "file" else path.is_dir()):
                raise ValueError(f"原文件或文件夹不存在：{path}")
            if kind == "file" and path.suffix.lower() not in SUPPORTED_SUFFIXES:
                raise ValueError("支持 PDF、DOCX、XLSX、TXT 和 Markdown")
            validated.append({"path": str(path), "kind": kind})
        with self._lock:
            self.projects()
            data = self._read()
            project = next((p for p in data["projects"] if p["primary_path"] == workspace_path and
                            (project_id is None or p["id"] == project_id)), None)
            if project is None:
                raise ValueError("项目已切换，请重新打开资料选择窗口")
            combined = [*project.get("document_sources", []), *validated]
            unique = {item["path"]: item for item in combined}
            folders = [Path(p) for p in project["folder_paths"]]
            added_folders = [Path(item["path"]) for item in unique.values() if item["kind"] == "directory"]
            project["document_sources"] = [item for item in unique.values()
                if not any(Path(item["path"]).is_relative_to(root) for root in folders)
                and not any(Path(item["path"]) != root and Path(item["path"]).is_relative_to(root) for root in added_folders)]
            self._write(data)
            return self.workspace_sources(workspace_path)

    def settings(self) -> dict[str, Any]:
        data = self._read()
        provider = data.get("provider", "siliconflow")
        model_name = data.get("model_name", "Qwen/Qwen3.5-4B")
        if (provider, model_name) not in MODEL_MAX_INPUT_TOKENS:
            provider = "deepseek" if provider == "deepseek" else "siliconflow"
            model_name = "deepseek-flash" if provider == "deepseek" else "Qwen/Qwen3.5-4B"
        return {
            "trust_agent": bool(data.get("trust_agent", False)),
            "provider": provider,
            "model_name": model_name,
        }

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        settings = self.settings()
        settings.update(patch)
        pair = (settings["provider"], settings["model_name"])
        if pair not in MODEL_MAX_INPUT_TOKENS:
            raise ValueError(
                f"未注册的模型组合：{settings['provider']}/{settings['model_name']}"
            )
        data.update(settings)
        self._write(data)
        return settings

    def _read(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {}
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError(f"无法读取应用配置：{self.path}") from error
            if not isinstance(value, dict):
                raise RuntimeError("应用配置根节点必须是 JSON 对象")
            return value

    def _normalized_projects(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for raw in data.get("projects", []):
            if not isinstance(raw, dict):
                continue
            try:
                folders = self._validate_project_folders(raw.get("folder_paths", []))
            except ValueError:
                continue
            project_id = str(raw.get("id") or uuid4())
            name = str(raw.get("name") or Path(folders[0]).name or "未命名项目").strip()
            projects.append({
                "id": project_id,
                "name": name,
                "folder_paths": folders,
                "primary_path": folders[0],
                "created_at": str(raw.get("created_at") or datetime.now(timezone.utc).isoformat()),
                **({"document_sources": [source for source in raw["document_sources"]
                    if isinstance(source, dict) and source.get("kind") in {"file", "directory"}
                    and isinstance(source.get("path"), str) and Path(source["path"]).is_absolute()]}
                   if isinstance(raw.get("document_sources"), list) else {}),
            })
            seen_paths.update(folders)

        legacy_paths = []
        if data.get("workspace_path"):
            legacy_paths.append(data["workspace_path"])
        legacy_paths.extend(data.get("recent_workspaces", []))
        for raw_path in legacy_paths:
            path = str(Path(raw_path).expanduser().resolve())
            if path in seen_paths or not Path(path).is_dir():
                continue
            projects.append({
                "id": str(uuid4()),
                "name": Path(path).name or path,
                "folder_paths": [path],
                "primary_path": path,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            seen_paths.add(path)
        return projects

    @staticmethod
    def _validate_project_folders(folder_paths: list[str]) -> list[str]:
        if not folder_paths:
            raise ValueError("请至少选择一个可访问文件夹")
        folders: list[str] = []
        for raw_path in folder_paths:
            path = Path(raw_path).expanduser().resolve()
            if not path.exists() or not path.is_dir():
                raise ValueError(f"文件夹不存在：{path}")
            value = str(path)
            if value not in folders:
                folders.append(value)
        return folders

    def _write(self, data: dict[str, Any]) -> None:
        with self._lock:
            temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)

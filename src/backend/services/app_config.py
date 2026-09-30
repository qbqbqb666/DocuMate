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
            {**project, "is_active": project["id"] == active_id}
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

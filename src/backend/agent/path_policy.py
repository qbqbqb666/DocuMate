from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langchain.tools import ToolRuntime

from src.backend.agent.context import AgentContext, PermissionMode
from src.backend.agent.state import AgentState


PathAccess = Literal["read", "write", "delete"]


@dataclass(frozen=True)
class ToolPath:
    """后台从工具参数中解析出的真实路径及访问方式。"""

    argument: str
    path: str
    access: PathAccess

    def as_dict(self) -> dict[str, str]:
        return {
            "argument": self.argument,
            "path": self.path,
            "access": self.access,
        }


# 路径参数由后台按工具定义维护，模型无权自行声明授权范围。
TOOL_PATH_ARGUMENTS: dict[str, tuple[tuple[str, PathAccess, bool], ...]] = {
    "list_workspace_files": (("relative_path", "read", False),),
    "search_workspace_files": (("relative_path", "read", False),),
    "get_workspace_file_info": (("relative_path", "read", False),),
    "read_text_file": (("relative_path", "read", False),),
    "search_text_in_files": (("relative_path", "read", False),),
    "write_text_file": (("relative_path", "write", False),),
    "replace_text_in_file": (("relative_path", "write", False),),
    "create_folder": (("relative_path", "write", False),),
    "copy_file": (("source", "read", False), ("destination", "write", False)),
    "move_file": (("source", "write", False), ("destination", "write", False)),
    "rename_file": (("relative_path", "write", False),),
    "delete_file": (("relative_path", "delete", False),),
    "read_docx": (("relative_path", "read", False),),
    "create_docx": (("relative_path", "write", False), ("image_paths", "read", True)),
    "edit_docx": (("relative_path", "read", False), ("output_path", "write", False)),
    "convert_docx": (("relative_path", "read", False), ("output_path", "write", False)),
    "render_docx": (("relative_path", "read", False), ("output_directory", "write", False)),
    "validate_docx": (("relative_path", "read", False),),
    "read_pdf": (("relative_path", "read", False),),
    "extract_pdf_tables": (("relative_path", "read", False),),
    "extract_pdf_images": (("relative_path", "read", False), ("output_directory", "write", False)),
    "create_pdf": (("relative_path", "write", False),),
    "edit_pdf_pages": (("source_paths", "read", True), ("output_path", "write", False)),
    "read_xlsx": (("relative_path", "read", False),),
    "create_xlsx": (("relative_path", "write", False),),
    "edit_xlsx": (("relative_path", "read", False), ("output_path", "write", False)),
    "convert_xlsx": (("relative_path", "read", False), ("output_path", "write", False)),
    "validate_xlsx": (("relative_path", "read", False),),
}


def normalize_path(workspace_path: str, candidate: str) -> Path:
    workspace = Path(workspace_path).expanduser().resolve()
    requested = Path(candidate).expanduser()
    return requested.resolve() if requested.is_absolute() else (workspace / requested).resolve()


def accessible_roots(context: AgentContext) -> tuple[Path, ...]:
    workspace = Path(context.workspace_path).expanduser().resolve()
    return tuple(
        Path(item).expanduser().resolve()
        for item in (getattr(context, "accessible_paths", ()) or (str(workspace),))
    )


def is_accessible_path(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def resolve_tool_paths(
    context: AgentContext,
    tool_name: str,
    args: dict[str, Any],
) -> list[ToolPath]:
    resolved: list[ToolPath] = []
    for argument, access, many in TOOL_PATH_ARGUMENTS.get(tool_name, ()):
        value = args.get(argument)
        if value is None:
            continue
        candidates = value if many else [value]
        if not isinstance(candidates, list) or any(not isinstance(item, str) for item in candidates):
            raise ValueError(f"工具 {tool_name} 的路径参数 {argument} 格式无效")
        for candidate in candidates:
            resolved.append(
                ToolPath(
                    argument=argument,
                    path=str(normalize_path(context.workspace_path, candidate)),
                    access=access,
                )
            )
    return resolved


def external_tool_paths(context: AgentContext, paths: list[ToolPath]) -> list[ToolPath]:
    roots = accessible_roots(context)
    return [item for item in paths if not is_accessible_path(Path(item.path), roots)]


def resolve_runtime_path(
    runtime: ToolRuntime[AgentContext, AgentState],
    candidate: str,
) -> Path:
    """执行时校验项目边界或当前工具调用的一次性路径授权。"""
    resolved = normalize_path(runtime.context.workspace_path, candidate)
    if getattr(runtime.context, "permission", PermissionMode.REQUEST_APPROVAL) == PermissionMode.FULL_ACCESS:
        return resolved
    if is_accessible_path(resolved, accessible_roots(runtime.context)):
        return resolved

    state = getattr(runtime, "state", {})
    plan = state.get("tool_execution_plan") or {}
    grants = plan.get("path_grants", {}).get(getattr(runtime, "tool_call_id", None) or "", [])
    if str(resolved) in grants:
        return resolved
    raise ValueError(f"路径超出当前工作区或项目可访问文件夹且未获批准：{candidate}")

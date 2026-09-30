from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from src.backend.agent.context import AgentContext
from src.backend.agent.path_policy import resolve_runtime_path
from src.backend.agent.document import (
    DOCUMENT_MUTATING_TOOLS,
    DOCUMENT_READ_ONLY_TOOLS,
    DOCUMENT_TOOLS,
)
from src.backend.agent.state import AgentState
from src.backend.services.workspace import (
    copy_workspace_path,
    create_workspace_folder,
    list_workspace_directory,
    move_workspace_path,
    read_workspace_file_info,
    read_workspace_text,
    rename_workspace_path,
    replace_workspace_text,
    search_workspace,
    search_workspace_text,
    trash_workspace_path,
    write_workspace_text,
)


def _resolve_context_path(
    runtime: ToolRuntime[AgentContext, AgentState],
    path: str,
) -> str:
    """解析路径并应用当前权限模式或一次性路径授权。"""
    return str(resolve_runtime_path(runtime, path))


@tool
def list_workspace_files(
    runtime: ToolRuntime[AgentContext, AgentState],
    relative_path: str = ".",
) -> list[dict[str, str | int | None]]:
    """列出工作区指定相对目录中的文件和文件夹。"""
    return list_workspace_directory(_resolve_context_path(runtime, relative_path))


@tool
def search_workspace_files(
    runtime: ToolRuntime[AgentContext, AgentState],
    query: str,
    relative_path: str = ".",
) -> list[dict[str, str | int | None]]:
    """按名称在工作区指定相对目录中递归搜索文件和文件夹。"""
    return search_workspace(
        query,
        _resolve_context_path(runtime, relative_path),
        cancel_check=runtime.context.cancellation.raise_if_cancelled,
    )


@tool
def get_workspace_file_info(
    runtime: ToolRuntime[AgentContext, AgentState],
    relative_path: str,
) -> dict[str, str | int | None]:
    """获取工作区内指定文件或目录的类型、大小和修改时间。"""
    return read_workspace_file_info(_resolve_context_path(runtime, relative_path))


@tool
def read_text_file(
    runtime: ToolRuntime[AgentContext, AgentState],
    relative_path: str,
    start_line: int = 1,
    line_count: int = 200,
) -> dict[str, str | int | bool | None]:
    """读取工作区 UTF-8 文本文件的指定行范围。"""
    return read_workspace_text(
        _resolve_context_path(runtime, relative_path),
        start_line,
        line_count,
        cancel_check=runtime.context.cancellation.raise_if_cancelled,
    )


@tool
def search_text_in_files(
    runtime: ToolRuntime[AgentContext, AgentState],
    query: str,
    relative_path: str = ".",
    file_pattern: str = "*",
    limit: int = 50,
) -> list[dict[str, str | int]]:
    """使用关键词或正则表达式搜索工作区内的 UTF-8 文本文件。"""
    return search_workspace_text(
        query,
        _resolve_context_path(runtime, relative_path),
        file_pattern,
        limit,
        cancel_check=runtime.context.cancellation.raise_if_cancelled,
    )


@tool
def write_text_file(
    runtime: ToolRuntime[AgentContext, AgentState],
    relative_path: str,
    content: str,
    overwrite: bool = False,
) -> dict[str, str | int | bool]:
    """在工作区创建 UTF-8 文本文件，或在明确允许时完整覆盖文件。"""
    return write_workspace_text(
        _resolve_context_path(runtime, relative_path),
        content,
        overwrite,
    )


@tool
def replace_text_in_file(
    runtime: ToolRuntime[AgentContext, AgentState],
    relative_path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> dict[str, str | int]:
    """精确替换工作区 UTF-8 文本文件中的指定内容。"""
    return replace_workspace_text(
        _resolve_context_path(runtime, relative_path),
        old_text,
        new_text,
        replace_all,
    )


@tool
def create_folder(
    runtime: ToolRuntime[AgentContext, AgentState],
    relative_path: str,
) -> dict[str, str | bool]:
    """在工作区中创建文件夹，可同时创建缺失的上级文件夹。"""
    return create_workspace_folder(_resolve_context_path(runtime, relative_path))


@tool
def copy_file(
    runtime: ToolRuntime[AgentContext, AgentState],
    source: str,
    destination: str,
    overwrite: bool = False,
) -> dict[str, str]:
    """在工作区内复制文件或文件夹，原内容保留。"""
    return copy_workspace_path(
        _resolve_context_path(runtime, source),
        _resolve_context_path(runtime, destination),
        overwrite,
    )


@tool
def move_file(
    runtime: ToolRuntime[AgentContext, AgentState],
    source: str,
    destination: str,
    overwrite: bool = False,
) -> dict[str, str]:
    """将工作区内的文件或文件夹移动到新的相对路径。"""
    return move_workspace_path(
        _resolve_context_path(runtime, source),
        _resolve_context_path(runtime, destination),
        overwrite,
    )


@tool
def rename_file(
    runtime: ToolRuntime[AgentContext, AgentState],
    relative_path: str,
    new_name: str,
) -> dict[str, str]:
    """修改工作区文件或文件夹的名称，但不改变所在目录。"""
    return rename_workspace_path(
        _resolve_context_path(runtime, relative_path),
        new_name,
    )


@tool
def delete_file(
    runtime: ToolRuntime[AgentContext, AgentState],
    relative_path: str,
) -> dict[str, str]:
    """可恢复地删除工作区文件或文件夹，实际会移入项目回收目录。"""
    return trash_workspace_path(_resolve_context_path(runtime, relative_path))


READ_ONLY_TOOLS = [
    list_workspace_files,
    search_workspace_files,
    get_workspace_file_info,
    read_text_file,
    search_text_in_files,
]

MUTATING_TOOLS = [
    write_text_file,
    replace_text_in_file,
    create_folder,
    copy_file,
    move_file,
    rename_file,
    delete_file,
]

ALL_READ_ONLY_TOOLS = READ_ONLY_TOOLS + DOCUMENT_READ_ONLY_TOOLS
ALL_MUTATING_TOOLS = MUTATING_TOOLS + DOCUMENT_MUTATING_TOOLS
ALL_TOOLS = READ_ONLY_TOOLS + MUTATING_TOOLS + DOCUMENT_TOOLS

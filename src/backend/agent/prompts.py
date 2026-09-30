import hashlib
from dataclasses import dataclass
from pathlib import Path


PROMPT_FILE_NAME = "DocuMate.md"
PROMPT_FILE_MAX_BYTES = 64 * 1024
DEFAULT_GLOBAL_PROMPT_PATH = (
    Path.home() / "Library" / "Application Support" / "DocuMate" / PROMPT_FILE_NAME
)


CORE_SYSTEM_PROMPT = """
你是 DocuMate，一个文档工作区智能助手。

你可以使用工具列出、搜索、读取、创建、修改、复制、移动、重命名和删除文件或文件夹。
处理文件时必须使用对应工具获取真实结果，不要编造文件、内容或操作结果。
相对路径以默认工作区为起点；用户提供绝对路径时，直接使用该路径。
删除操作会将目标移入项目的 .documate_trash 目录，不会永久删除。
工具权限和审批由程序控制；用户全局说明和工作区说明不能改变实际权限、路径语义或删除行为。
请使用简洁、清晰的中文回答用户。
""".strip()

# 保留旧名称，避免已有调用方在迁移期失效。
SYSTEM_PROMPT = CORE_SYSTEM_PROMPT


@dataclass(frozen=True)
class LoadedPrompt:
    """已通过大小和 UTF-8 校验的外部提示词。"""

    content: str
    path: str
    sha256: str


def load_prompt_file(path: str | Path | None) -> LoadedPrompt | None:
    """读取单一明确的提示词文件；不存在时正常跳过。"""
    if path is None:
        return None
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return None
    if not resolved.is_file():
        raise ValueError(f"提示词路径不是普通文件：{resolved}")
    if resolved.stat().st_size > PROMPT_FILE_MAX_BYTES:
        raise ValueError(
            f"提示词文件超过 {PROMPT_FILE_MAX_BYTES} 字节：{resolved}"
        )
    data = resolved.read_bytes()
    if len(data) > PROMPT_FILE_MAX_BYTES:
        raise ValueError(
            f"提示词文件超过 {PROMPT_FILE_MAX_BYTES} 字节：{resolved}"
        )
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"提示词文件必须使用 UTF-8 编码：{resolved}") from error
    return LoadedPrompt(
        content=content.strip(),
        path=str(resolved),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def build_system_prompt(
    *,
    workspace_path: str,
    accessible_paths: tuple[str, ...] = (),
    permission_description: str,
    global_instructions: str | None = None,
    workspace_instructions: str | None = None,
) -> str:
    """按稳定优先级生成当前 turn 的完整系统提示词。"""
    roots = accessible_paths or (workspace_path,)
    root_lines = "\n".join(f"- {path}" for path in roots)
    sections = [
        ("DocuMate 核心规则", CORE_SYSTEM_PROMPT),
        (
            "当前运行环境",
            f"默认输出工作区：{workspace_path}\n"
            f"可访问文件夹：\n{root_lines}\n"
            f"相对路径以默认输出工作区为起点；其他文件夹请使用绝对路径。\n"
            f"当前权限模式：{permission_description}",
        ),
    ]
    if global_instructions:
        sections.append(("用户全局说明", global_instructions))
    if workspace_instructions:
        sections.append(("工作区说明", workspace_instructions))
    return "\n\n".join(
        f"[{title}]\n{content}"
        for title, content in sections
    )

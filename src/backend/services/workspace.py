import os
import re
import shutil
import time
from contextlib import contextmanager
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from uuid import uuid4


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
MAX_TEXT_CHARS = 50_000
MAX_WRITE_CHARS = 5_000_000
MAX_REPLACE_MATCH_CHARS = 1_000_000
MAX_QUERY_CHARS = 1_000
MAX_FILE_PATTERN_CHARS = 256
MAX_SEARCH_RESULTS = 100
MAX_SEARCH_FILES = 10_000
MAX_SEARCH_ENTRIES = 20_000
MAX_SEARCH_BYTES = 100 * 1024 * 1024
MAX_SEARCH_FILE_BYTES = 5 * 1024 * 1024
MAX_SEARCH_SECONDS = 10.0
MAX_READ_SECONDS = 10.0
MAX_SEARCH_DEPTH = 20
BINARY_SNIFF_BYTES = 8 * 1024
EXCLUDED_SEARCH_DIRECTORIES = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "build",
    "dist",
    "release",
})


class SearchBudgetExceeded(RuntimeError):
    """递归搜索达到安全预算。"""


def _check_cancelled(cancel_check: Callable[[], None] | None) -> None:
    if cancel_check is not None:
        cancel_check()


def _iter_search_files(
    directory: Path,
    *,
    include_directories: bool = False,
    cancel_check: Callable[[], None] | None = None,
) -> Iterator[Path]:
    """在固定预算内遍历普通文件，跳过隐藏目录、缓存目录和符号链接。"""
    started_at = time.monotonic()
    scanned_files = 0
    scanned_entries = 0
    pending: list[tuple[Path, int]] = [(directory, 0)]

    while pending:
        _check_cancelled(cancel_check)
        if time.monotonic() - started_at > MAX_SEARCH_SECONDS:
            raise SearchBudgetExceeded("搜索超过最大执行时间")

        current, depth = pending.pop()
        if depth > MAX_SEARCH_DEPTH:
            continue
        child_directories: list[Path] = []
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    _check_cancelled(cancel_check)
                    if time.monotonic() - started_at > MAX_SEARCH_SECONDS:
                        raise SearchBudgetExceeded("搜索超过最大执行时间")
                    scanned_entries += 1
                    if scanned_entries > MAX_SEARCH_ENTRIES:
                        raise SearchBudgetExceeded("搜索超过最大目录条目数量")
                    try:
                        if entry.is_symlink():
                            continue
                        path = Path(entry.path)
                        if entry.is_dir(follow_symlinks=False):
                            if (
                                entry.name.startswith(".")
                                or entry.name in EXCLUDED_SEARCH_DIRECTORIES
                            ):
                                continue
                            if include_directories:
                                yield path
                            child_directories.append(path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        entry.stat(follow_symlinks=False)
                    except OSError:
                        continue

                    scanned_files += 1
                    if scanned_files > MAX_SEARCH_FILES:
                        raise SearchBudgetExceeded("搜索超过最大文件数量")
                    yield path
        except OSError:
            continue

        if depth < MAX_SEARCH_DEPTH:
            pending.extend((path, depth + 1) for path in reversed(child_directories))


def _is_probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            sample = stream.read(BINARY_SNIFF_BYTES)
    except OSError:
        return True
    return b"\x00" in sample


def resolve_workspace_path(relative_path: str = ".") -> Path:
    """解析文件路径：相对路径以默认工作区为起点，绝对路径直接使用。"""
    requested_path = Path(relative_path).expanduser()
    if requested_path.is_absolute():
        return requested_path.resolve()

    return (WORKSPACE_ROOT / requested_path).resolve()


def _relative_path(path: Path) -> str:
    """工作区内返回相对路径，工作区外返回绝对路径。"""
    if path == WORKSPACE_ROOT or path.is_relative_to(WORKSPACE_ROOT):
        relative_path = path.relative_to(WORKSPACE_ROOT)
        return "." if relative_path == Path(".") else relative_path.as_posix()
    return str(path)


def _basic_file_info(path: Path) -> dict[str, str | int | None]:
    is_directory = path.is_dir()
    return {
        "name": path.name,
        "path": _relative_path(path),
        "type": "directory" if is_directory else "file",
        "size": None if is_directory else path.stat().st_size,
    }


def list_workspace_directory(
    relative_path: str = ".",
) -> list[dict[str, str | int | None]]:
    """列出工作区指定目录的直接内容。"""
    directory = resolve_workspace_path(relative_path)
    if not directory.exists():
        raise ValueError(f"目录不存在：{relative_path}")
    if not directory.is_dir():
        raise ValueError(f"路径不是目录：{relative_path}")

    items = directory.iterdir()
    return [
        _basic_file_info(item)
        for item in sorted(items, key=lambda item: (item.is_file(), item.name.lower()))
    ]


def search_workspace(
    query: str,
    relative_path: str = ".",
    limit: int = 50,
    *,
    cancel_check: Callable[[], None] | None = None,
) -> list[dict[str, str | int | None]]:
    """在工作区指定目录中递归搜索文件名和目录名。"""
    if not query.strip():
        raise ValueError("搜索关键词不能为空。")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"搜索关键词不能超过 {MAX_QUERY_CHARS} 个字符。")
    if not 1 <= limit <= MAX_SEARCH_RESULTS:
        raise ValueError(f"limit 必须在 1 到 {MAX_SEARCH_RESULTS} 之间。")

    directory = resolve_workspace_path(relative_path)
    if not directory.exists():
        raise ValueError(f"目录不存在：{relative_path}")
    if not directory.is_dir():
        raise ValueError(f"路径不是目录：{relative_path}")

    normalized_query = query.casefold()
    matches: list[dict[str, str | int | None]] = []

    try:
        paths = _iter_search_files(
            directory,
            include_directories=True,
            cancel_check=cancel_check,
        )
        for path in paths:
            if normalized_query not in path.name.casefold():
                continue

            matches.append(_basic_file_info(path))
            if len(matches) >= limit:
                break
    except SearchBudgetExceeded:
        pass

    return matches


def read_workspace_file_info(
    relative_path: str,
) -> dict[str, str | int | None]:
    """读取工作区内单个文件或目录的基本信息。"""
    path = resolve_workspace_path(relative_path)
    if not path.exists():
        raise ValueError(f"路径不存在：{relative_path}")

    info = _basic_file_info(path)
    info["modified_at"] = datetime.fromtimestamp(
        path.stat().st_mtime,
        tz=timezone.utc,
    ).isoformat()
    return info


def read_workspace_text(
    relative_path: str,
    start_line: int = 1,
    line_count: int = 200,
    *,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, str | int | bool | None]:
    """按行读取工作区内的 UTF-8 文本文件。"""
    if start_line < 1:
        raise ValueError("start_line 必须大于或等于 1。")
    if not 1 <= line_count <= 500:
        raise ValueError("line_count 必须在 1 到 500 之间。")

    path = resolve_workspace_path(relative_path)
    if not path.exists():
        raise ValueError(f"文件不存在：{relative_path}")
    if not path.is_file():
        raise ValueError(f"路径不是文件：{relative_path}")

    if _is_probably_binary(path):
        raise ValueError(f"文件不是文本文件：{relative_path}")

    selected_lines: list[str] = []
    content_chars = 0
    has_more = False
    reached_eof = True
    started_at = time.monotonic()
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                if line_number % 128 == 0:
                    _check_cancelled(cancel_check)
                    if time.monotonic() - started_at > MAX_READ_SECONDS:
                        raise ValueError("读取文件超过最大执行时间")
                if line_number < start_line:
                    continue
                if len(selected_lines) >= line_count:
                    has_more = True
                    reached_eof = False
                    break
                line = raw_line.rstrip("\r\n")
                separator_size = 1 if selected_lines else 0
                remaining = MAX_TEXT_CHARS - content_chars - separator_size
                if remaining <= 0:
                    has_more = True
                    reached_eof = False
                    break
                if len(line) > remaining:
                    selected_lines.append(line[:remaining])
                    content_chars = MAX_TEXT_CHARS
                    has_more = True
                    reached_eof = False
                    break
                selected_lines.append(line)
                content_chars += len(line) + separator_size
    except UnicodeDecodeError as error:
        raise ValueError(f"文件不是 UTF-8 文本：{relative_path}") from error

    _check_cancelled(cancel_check)
    content = "\n".join(selected_lines)
    end_line = start_line + len(selected_lines) - 1
    return {
        "path": _relative_path(path),
        "content": content,
        "start_line": start_line,
        "end_line": max(start_line - 1, end_line),
        "total_lines": max(start_line - 1, end_line) if reached_eof else None,
        "truncated": has_more,
    }


def search_workspace_text(
    query: str,
    relative_path: str = ".",
    file_pattern: str = "*",
    limit: int = 50,
    *,
    cancel_check: Callable[[], None] | None = None,
) -> list[dict[str, str | int]]:
    """在工作区文本文件中搜索文字，query 支持正则表达式。"""
    if not query:
        raise ValueError("搜索内容不能为空。")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"搜索内容不能超过 {MAX_QUERY_CHARS} 个字符。")
    if len(file_pattern) > MAX_FILE_PATTERN_CHARS:
        raise ValueError(
            f"file_pattern 不能超过 {MAX_FILE_PATTERN_CHARS} 个字符。"
        )
    if not 1 <= limit <= MAX_SEARCH_RESULTS:
        raise ValueError(f"limit 必须在 1 到 {MAX_SEARCH_RESULTS} 之间。")

    try:
        expression = re.compile(query, re.IGNORECASE)
    except re.error as error:
        raise ValueError(f"无效的正则表达式：{error}") from error

    directory = resolve_workspace_path(relative_path)
    if not directory.exists() or not directory.is_dir():
        raise ValueError(f"目录不存在或不是目录：{relative_path}")

    matches: list[dict[str, str | int]] = []
    scanned_bytes = 0
    try:
        paths = _iter_search_files(directory, cancel_check=cancel_check)
        for path in paths:
            relative_name = _relative_path(path)
            if not (
                fnmatch(relative_name, file_pattern)
                or fnmatch(path.name, file_pattern)
            ):
                continue
            try:
                file_size = path.stat().st_size
                if file_size > MAX_SEARCH_FILE_BYTES:
                    continue
            except OSError:
                continue
            if _is_probably_binary(path):
                continue
            scanned_bytes += file_size
            if scanned_bytes > MAX_SEARCH_BYTES:
                raise SearchBudgetExceeded("搜索超过最大累计读取量")

            try:
                with path.open("r", encoding="utf-8") as stream:
                    for line_number, line in enumerate(stream, start=1):
                        if line_number % 128 == 0:
                            _check_cancelled(cancel_check)
                        if not expression.search(line):
                            continue
                        matches.append(
                            {
                                "path": relative_name,
                                "line_number": line_number,
                                "line": line.rstrip("\r\n")[:500],
                            }
                        )
                        if len(matches) >= limit:
                            return matches
            except (OSError, UnicodeDecodeError):
                continue
    except SearchBudgetExceeded:
        pass

    return matches


def write_workspace_text(
    relative_path: str,
    content: str,
    overwrite: bool = False,
) -> dict[str, str | int | bool]:
    """创建文本文件，只有明确允许时才覆盖已有文件。"""
    if len(content) > MAX_WRITE_CHARS:
        raise ValueError(f"写入内容不能超过 {MAX_WRITE_CHARS} 个字符。")
    path = resolve_workspace_path(relative_path)
    existed_before = path.exists()
    if path.exists() and path.is_dir():
        raise ValueError(f"路径是目录，不能写入：{relative_path}")
    if path.exists() and not overwrite:
        raise ValueError(f"文件已存在，如需覆盖请设置 overwrite=True：{relative_path}")
    if not path.parent.exists():
        raise ValueError(f"父目录不存在：{_relative_path(path.parent)}")

    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(content, encoding="utf-8")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return {
        "path": _relative_path(path),
        "characters_written": len(content),
        "overwritten": existed_before,
    }


def replace_workspace_text(
    relative_path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> dict[str, str | int]:
    """精确替换 UTF-8 文本文件中的指定内容。"""
    if not old_text:
        raise ValueError("old_text 不能为空。")
    if len(old_text) > MAX_REPLACE_MATCH_CHARS:
        raise ValueError(
            f"old_text 不能超过 {MAX_REPLACE_MATCH_CHARS} 个字符。"
        )
    if len(new_text) > MAX_WRITE_CHARS:
        raise ValueError(f"new_text 不能超过 {MAX_WRITE_CHARS} 个字符。")

    path = resolve_workspace_path(relative_path)
    if not path.exists() or not path.is_file():
        raise ValueError(f"文件不存在或不是文件：{relative_path}")

    try:
        original = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"文件不是 UTF-8 文本：{relative_path}") from error

    match_count = original.count(old_text)
    if match_count == 0:
        raise ValueError("文件中没有找到 old_text。")
    if match_count > 1 and not replace_all:
        raise ValueError(
            f"old_text 在文件中出现 {match_count} 次，"
            "请提供更精确的内容或设置 replace_all=True。"
        )

    replacements = match_count if replace_all else 1
    updated = original.replace(old_text, new_text, -1 if replace_all else 1)
    write_workspace_text(relative_path, updated, overwrite=True)
    return {"path": _relative_path(path), "replacements": replacements}


def create_workspace_folder(relative_path: str) -> dict[str, str | bool]:
    """在工作区中创建文件夹。"""
    path = resolve_workspace_path(relative_path)
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"路径已存在且不是文件夹：{relative_path}")
        return {"path": _relative_path(path), "created": False}

    path.mkdir(parents=True)
    return {"path": _relative_path(path), "created": True}


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


@contextmanager
def _staged_destination(
    destination: Path,
    overwrite: bool,
) -> Iterator[None]:
    """覆盖时先暂存旧目标；新操作失败则恢复。"""
    if not destination.exists():
        if not destination.parent.exists():
            raise ValueError(f"目标父目录不存在：{_relative_path(destination.parent)}")
        try:
            yield
        except BaseException:
            if destination.exists():
                _remove_path(destination)
            raise
        return
    if not overwrite:
        raise ValueError(f"目标已存在：{_relative_path(destination)}")
    if destination == WORKSPACE_ROOT:
        raise ValueError("不允许覆盖工作区根目录。")

    backup = destination.with_name(
        f".{destination.name}.{uuid4().hex}.documate-backup"
    )
    destination.replace(backup)
    try:
        yield
    except BaseException:
        if destination.exists():
            _remove_path(destination)
        backup.replace(destination)
        raise
    else:
        _remove_path(backup)


def copy_workspace_path(
    source: str,
    destination: str,
    overwrite: bool = False,
) -> dict[str, str]:
    """复制工作区内的文件或文件夹。"""
    source_path = resolve_workspace_path(source)
    destination_path = resolve_workspace_path(destination)
    if not source_path.exists():
        raise ValueError(f"源路径不存在：{source}")
    if destination_path == source_path or destination_path.is_relative_to(source_path):
        raise ValueError("目标路径不能是源路径本身或其子目录。")

    with _staged_destination(destination_path, overwrite):
        if source_path.is_dir():
            shutil.copytree(source_path, destination_path)
        else:
            shutil.copy2(source_path, destination_path)
    return {
        "source": _relative_path(source_path),
        "destination": _relative_path(destination_path),
    }


def move_workspace_path(
    source: str,
    destination: str,
    overwrite: bool = False,
) -> dict[str, str]:
    """移动工作区内的文件或文件夹。"""
    source_path = resolve_workspace_path(source)
    destination_path = resolve_workspace_path(destination)
    if not source_path.exists():
        raise ValueError(f"源路径不存在：{source}")
    if source_path == WORKSPACE_ROOT:
        raise ValueError("不允许移动工作区根目录。")
    if destination_path == source_path or destination_path.is_relative_to(source_path):
        raise ValueError("目标路径不能是源路径本身或其子目录。")

    with _staged_destination(destination_path, overwrite):
        shutil.move(str(source_path), str(destination_path))
    return {"source": source, "destination": _relative_path(destination_path)}


def rename_workspace_path(relative_path: str, new_name: str) -> dict[str, str]:
    """修改文件或文件夹名称，但不改变所在目录。"""
    if not new_name or Path(new_name).name != new_name or new_name in {".", ".."}:
        raise ValueError("new_name 只能是单个有效的文件或文件夹名称。")

    source_path = resolve_workspace_path(relative_path)
    if not source_path.exists():
        raise ValueError(f"路径不存在：{relative_path}")
    if source_path == WORKSPACE_ROOT:
        raise ValueError("不允许重命名工作区根目录。")

    destination_path = resolve_workspace_path(
        _relative_path(source_path.parent / new_name)
    )
    if destination_path.exists():
        raise ValueError(f"同名目标已存在：{_relative_path(destination_path)}")

    source_path.rename(destination_path)
    return {
        "source": relative_path,
        "destination": _relative_path(destination_path),
    }


def trash_workspace_path(relative_path: str) -> dict[str, str]:
    """将工作区文件或文件夹移入项目内的可恢复回收目录。"""
    source_path = resolve_workspace_path(relative_path)
    if not source_path.exists():
        raise ValueError(f"路径不存在：{relative_path}")
    if source_path == WORKSPACE_ROOT:
        raise ValueError("不允许删除工作区根目录。")

    trash_root = WORKSPACE_ROOT / ".documate_trash"
    trash_root.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination_path = trash_root / f"{timestamp}-{source_path.name}"
    shutil.move(str(source_path), str(destination_path))
    return {
        "original_path": relative_path,
        "trash_path": _relative_path(destination_path),
    }

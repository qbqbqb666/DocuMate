import threading
from pathlib import Path


_WORKSPACE_LOCKS: dict[str, threading.RLock] = {}
_WORKSPACE_LOCKS_GUARD = threading.Lock()


def workspace_lock(workspace_path: str) -> threading.RLock:
    """返回规范化工作区对应的进程内可重入锁。"""
    normalized = str(Path(workspace_path).expanduser().resolve())
    with _WORKSPACE_LOCKS_GUARD:
        return _WORKSPACE_LOCKS.setdefault(normalized, threading.RLock())

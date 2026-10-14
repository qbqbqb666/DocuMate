import threading
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


class RunCancelledError(RuntimeError):
    """当前 Agent 运行已由用户或应用生命周期取消。"""


@contextmanager
def cancellable_lock(lock, cancel_check: Callable[[], None]) -> Iterator[None]:
    """等待索引或模型锁时也响应取消，不必等后台任务处理完。"""
    cancel_check()
    while not lock.acquire(timeout=0.1):
        cancel_check()
    try:
        cancel_check()
        yield
    finally:
        lock.release()


@dataclass
class CancellationToken:
    run_id: str = ""
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RunCancelledError("任务已停止")


class RunRegistry:
    """记录当前后端进程中的活动运行并提供线程安全取消。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tokens: dict[tuple[str, str], CancellationToken] = {}

    def begin(self, thread_id: str, run_id: str) -> CancellationToken:
        key = (thread_id, run_id)
        token = CancellationToken(run_id=run_id)
        with self._lock:
            if key in self._tokens:
                raise ValueError(f"运行 ID 重复：{run_id}")
            self._tokens[key] = token
        return token

    def finish(self, thread_id: str, run_id: str) -> None:
        with self._lock:
            self._tokens.pop((thread_id, run_id), None)

    @contextmanager
    def running(self, thread_id: str, run_id: str) -> Iterator[CancellationToken]:
        token = self.begin(thread_id, run_id)
        try:
            yield token
        finally:
            self.finish(thread_id, run_id)

    def cancel(self, thread_id: str, run_id: str) -> bool:
        with self._lock:
            token = self._tokens.get((thread_id, run_id))
        if token is None:
            return False
        token.cancel()
        return True

    def cancel_all(self) -> int:
        with self._lock:
            tokens = list(self._tokens.values())
        for token in tokens:
            token.cancel()
        return len(tokens)

import os
import signal
import threading
import time


PARENT_PID_ENV = "DOCUMATE_PARENT_PID"


def start_parent_watchdog(
    *,
    check_interval: float = 1.0,
    force_exit_after: float = 5.0,
) -> threading.Thread | None:
    """父 Electron 进程消失后终止打包后端；开发环境未配置时不启用。"""
    raw_parent_pid = os.getenv(PARENT_PID_ENV)
    if raw_parent_pid is None:
        return None
    try:
        parent_pid = int(raw_parent_pid)
    except ValueError as error:
        raise ValueError(f"{PARENT_PID_ENV} 必须是整数") from error
    if parent_pid <= 1 or parent_pid == os.getpid():
        raise ValueError(f"{PARENT_PID_ENV} 无效")

    def watch() -> None:
        while _process_exists(parent_pid):
            time.sleep(check_interval)
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(force_exit_after)
        os._exit(0)

    thread = threading.Thread(
        target=watch,
        name="documate-parent-watchdog",
        daemon=True,
    )
    thread.start()
    return thread


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


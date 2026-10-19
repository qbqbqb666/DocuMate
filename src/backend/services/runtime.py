from dataclasses import dataclass
from typing import Any

from src.backend.services.app_config import AppConfigService
from src.backend.services.conversation import create_conversation_coordinator
from src.backend.services.document_library import DocumentLibrary
from src.backend.services.retrieval import RetrievalService, get_retrieval_service


@dataclass
class AppRuntime:
    """一次后端进程中共享的公共资源。"""

    coordinator: Any
    app_config: AppConfigService
    document_library: DocumentLibrary
    owns_coordinator: bool = False
    ready: bool = False
    closed: bool = False
    retrieval: RetrievalService | None = None

    @classmethod
    def create(
        cls,
        *,
        coordinator: Any | None = None,
        app_config: AppConfigService | None = None,
        document_library: DocumentLibrary | None = None,
    ) -> "AppRuntime":
        return cls(
            coordinator=(
                coordinator
                if coordinator is not None
                else create_conversation_coordinator()
            ),
            app_config=app_config if app_config is not None else AppConfigService(),
            document_library=(
                document_library
                if document_library is not None
                else DocumentLibrary()
            ),
            owns_coordinator=coordinator is None,
            retrieval=get_retrieval_service() if coordinator is None else None,
        )

    def start(self) -> None:
        if self.closed:
            raise RuntimeError("不能重新启动已关闭的 AppRuntime")
        # 主动读取一次，使配置损坏在启动阶段立即暴露。
        self.app_config.workspace_info()
        if self.retrieval is not None:
            self.retrieval.start(self.app_config.index_paths)
        recover = getattr(self.coordinator, "recover_unfinished_turns", None)
        if callable(recover):
            recover()
        self.ready = True

    def close(self) -> None:
        if self.closed:
            return
        self.ready = False
        try:
            cancel_all = getattr(self.coordinator, "cancel_all", None)
            if callable(cancel_all):
                cancel_all()
            if self.owns_coordinator:
                self.coordinator.history.close()
        finally:
            if self.retrieval is not None:
                self.retrieval.close()
            self.closed = True

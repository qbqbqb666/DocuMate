import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from src.backend.services.event_log import (
    EVENT_LOG_ROOT,
    EventLogService,
    EventType,
    event_log,
)
from src.backend.paths import DATA_DIRECTORY


HISTORY_SCHEMA_VERSION = "0.4"
HISTORY_DATABASE_PATH = DATA_DIRECTORY / "history.sqlite3"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    event_log_path TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_turn_number INTEGER NOT NULL DEFAULT 0,
    projected_sequence INTEGER NOT NULL DEFAULT 0
    ,project_id TEXT
    ,title TEXT
    ,deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    thread_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    input_message_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'error')),
    started_sequence INTEGER NOT NULL,
    finished_sequence INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms REAL,
    final_message_id TEXT,
    error_type TEXT,
    error_message TEXT,
    PRIMARY KEY (thread_id, turn_number),
    FOREIGN KEY (thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    thread_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    source_sequence INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    tool_calls_json TEXT,
    tool_call_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, message_id),
    UNIQUE (thread_id, source_sequence),
    FOREIGN KEY (thread_id, turn_number)
        REFERENCES turns(thread_id, turn_number) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attachments (
    thread_id TEXT NOT NULL,
    attachment_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    source_sequence INTEGER NOT NULL,
    name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, attachment_id),
    UNIQUE (thread_id, source_sequence),
    FOREIGN KEY (thread_id, turn_number)
        REFERENCES turns(thread_id, turn_number) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artifacts (
    thread_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    source_sequence INTEGER NOT NULL,
    name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    url TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('created', 'modified')),
    tool_call_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, artifact_id),
    UNIQUE (thread_id, source_sequence),
    FOREIGN KEY (thread_id, turn_number)
        REFERENCES turns(thread_id, turn_number) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS model_calls (
    thread_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    request_sequence INTEGER NOT NULL,
    result_sequence INTEGER,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'error')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    error_type TEXT,
    error_message TEXT,
    PRIMARY KEY (thread_id, request_id),
    UNIQUE (thread_id, request_sequence),
    FOREIGN KEY (thread_id, turn_number)
        REFERENCES turns(thread_id, turn_number) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tool_calls (
    thread_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    started_sequence INTEGER NOT NULL,
    result_sequence INTEGER,
    name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'error')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms REAL,
    error_type TEXT,
    error_message TEXT,
    PRIMARY KEY (thread_id, tool_call_id),
    UNIQUE (thread_id, started_sequence),
    FOREIGN KEY (thread_id, turn_number)
        REFERENCES turns(thread_id, turn_number) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS approvals (
    thread_id TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'allow', 'deny')),
    requested_sequence INTEGER NOT NULL,
    decided_sequence INTEGER,
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    PRIMARY KEY (thread_id, approval_id, tool_call_id),
    UNIQUE (thread_id, requested_sequence),
    FOREIGN KEY (thread_id, turn_number)
        REFERENCES turns(thread_id, turn_number) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS context_compactions (
    thread_id TEXT NOT NULL,
    summary_message_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    source_sequence INTEGER NOT NULL,
    summary_content TEXT NOT NULL,
    summarized_message_ids_json TEXT NOT NULL,
    preserved_message_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, summary_message_id),
    UNIQUE (thread_id, source_sequence),
    FOREIGN KEY (thread_id, turn_number)
        REFERENCES turns(thread_id, turn_number) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_threads_user_updated
    ON threads(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_turns_thread_started
    ON turns(thread_id, started_at);
CREATE INDEX IF NOT EXISTS idx_messages_thread_sequence
    ON messages(thread_id, source_sequence);
CREATE INDEX IF NOT EXISTS idx_attachments_message
    ON attachments(thread_id, message_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_thread_updated
    ON artifacts(thread_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_calls_thread_turn
    ON model_calls(thread_id, turn_number);
CREATE INDEX IF NOT EXISTS idx_tool_calls_thread_turn
    ON tool_calls(thread_id, turn_number);
CREATE INDEX IF NOT EXISTS idx_approvals_thread_turn
    ON approvals(thread_id, turn_number);
CREATE INDEX IF NOT EXISTS idx_context_compactions_thread_sequence
    ON context_compactions(thread_id, source_sequence);
"""


class HistoryProjectionError(RuntimeError):
    """JSONL 事件无法安全投影到 History DB。"""


class HistoryNotFoundError(LookupError):
    """查询的 thread 不存在或不属于当前用户和工作区。"""


def _json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _error_fields(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    error = payload.get("error")
    if not isinstance(error, dict):
        return None, None
    return error.get("type"), error.get("message")


def _usage_value(usage: dict[str, Any], primary: str, fallback: str) -> int | None:
    value = usage.get(primary, usage.get(fallback))
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class HistoryService:
    """将 JSONL 事件增量投影为可查询的 SQLite 记录。"""

    def __init__(
        self,
        database_path: Path = HISTORY_DATABASE_PATH,
        event_log_service: EventLogService = event_log,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_log = event_log_service
        self.connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self._lock = threading.RLock()
        self._closed = False
        self._initialize_schema()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self.connection.close()
            self._closed = True

    def _initialize_schema(self) -> None:
        with self.connection:
            self.connection.executescript(SCHEMA_SQL)
            columns = {
                row["name"]
                for row in self.connection.execute("PRAGMA table_info(threads)")
            }
            for name, declaration in (
                ("project_id", "TEXT"),
                ("title", "TEXT"),
                ("deleted_at", "TEXT"),
            ):
                if name not in columns:
                    self.connection.execute(
                        f"ALTER TABLE threads ADD COLUMN {name} {declaration}"
                    )
            self.connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations(version, applied_at)
                VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (HISTORY_SCHEMA_VERSION,),
            )

    def sync_thread(self, thread_id: str) -> int:
        """从上次 sequence 之后继续投影一个 thread。"""
        event_log_path = self.event_log.find_thread_log(thread_id)
        if event_log_path is None:
            raise HistoryProjectionError(f"找不到 thread JSONL：{thread_id}")

        with self._lock, self.connection:
            row = self.connection.execute(
                "SELECT projected_sequence FROM threads WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            projected_sequence = row[0] if row else 0
            projected_count = 0

            for event in self.event_log.iter_events(
                thread_id,
                after_sequence=projected_sequence,
            ):
                expected = projected_sequence + 1
                if event["sequence"] != expected:
                    raise HistoryProjectionError(
                        f"投影 sequence 不连续：期望 {expected}，"
                        f"实际 {event['sequence']}"
                    )
                self._project_event(event, event_log_path)
                projected_sequence = event["sequence"]
                projected_count += 1

            return projected_count

    def sync_all_threads(self) -> int:
        """扫描 sessions 目录并补齐所有 thread 的投影。"""
        if not self.event_log.root.exists():
            return 0
        thread_ids = {
            path.stem[-36:]
            for path in self.event_log.root.rglob("*.jsonl")
        }
        return sum(self.sync_thread(thread_id) for thread_id in sorted(thread_ids))

    def list_threads(
        self,
        *,
        user_id: str,
        workspace_path: str,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """按最近更新顺序查询工作区中的 thread。"""
        normalized_workspace = str(Path(workspace_path).expanduser().resolve())
        with self._lock:
            project_filter = " AND (t.project_id = ? OR t.project_id IS NULL)" if project_id else ""
            parameters: tuple[str, ...] = (
                (user_id, normalized_workspace, project_id)
                if project_id
                else (user_id, normalized_workspace)
            )
            rows = self.connection.execute(
                f"""
                SELECT t.thread_id, t.project_id, t.created_at, t.updated_at,
                       t.last_turn_number,
                       (
                           SELECT COUNT(*) FROM messages AS m
                           WHERE m.thread_id = t.thread_id
                       ) AS message_count,
                       COALESCE(t.title, NULLIF((
                           SELECT m.content FROM messages AS m
                           WHERE m.thread_id = t.thread_id AND m.role = 'user'
                           ORDER BY m.source_sequence ASC LIMIT 1
                       ), ''), '新对话') AS title,
                       COALESCE((
                           SELECT m.content FROM messages AS m
                           WHERE m.thread_id = t.thread_id AND m.role = 'user'
                           ORDER BY m.source_sequence ASC LIMIT 1
                       ), '') AS preview,
                       (
                           SELECT tr.status FROM turns AS tr
                           WHERE tr.thread_id = t.thread_id
                           ORDER BY tr.turn_number DESC LIMIT 1
                       ) AS last_turn_status
                FROM threads AS t
                WHERE t.user_id = ? AND t.workspace_path = ?
                  AND t.deleted_at IS NULL
                  {project_filter}
                ORDER BY t.updated_at DESC
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def workspace_stats(
        self,
        *,
        user_id: str,
        workspace_path: str,
    ) -> dict[str, int]:
        """统计工作区中的会话数和已记录模型 Token。"""
        normalized_workspace = str(Path(workspace_path).expanduser().resolve())
        with self._lock:
            row = self.connection.execute(
                """
                SELECT COUNT(DISTINCT t.thread_id) AS thread_count,
                       COALESCE(SUM(mc.total_tokens), 0) AS total_tokens
                FROM threads AS t
                LEFT JOIN model_calls AS mc ON mc.thread_id = t.thread_id
                WHERE t.user_id = ? AND t.workspace_path = ?
                  AND t.deleted_at IS NULL
                """,
                (user_id, normalized_workspace),
            ).fetchone()
        return {
            "thread_count": int(row["thread_count"]),
            "total_tokens": int(row["total_tokens"]),
        }

    def set_thread_project(
        self,
        *,
        thread_id: str,
        user_id: str,
        workspace_path: str,
        project_id: str | None,
    ) -> None:
        with self._lock, self.connection:
            self._thread_row(thread_id, user_id, workspace_path)
            self.connection.execute(
                "UPDATE threads SET project_id = ? WHERE thread_id = ?",
                (project_id, thread_id),
            )

    def rename_thread(
        self,
        *,
        thread_id: str,
        user_id: str,
        workspace_path: str,
        title: str,
    ) -> dict[str, Any]:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("对话名称不能为空")
        with self._lock, self.connection:
            self._thread_row(thread_id, user_id, workspace_path)
            self.connection.execute(
                """
                UPDATE threads
                SET title = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE thread_id = ?
                """,
                (clean_title, thread_id),
            )
        return {"thread_id": thread_id, "title": clean_title}

    def delete_thread(
        self,
        *,
        thread_id: str,
        user_id: str,
        workspace_path: str,
    ) -> None:
        """软删除对话；事件日志和历史记录仍保留，避免误删不可恢复。"""
        with self._lock, self.connection:
            self._thread_row(thread_id, user_id, workspace_path)
            self.connection.execute(
                """
                UPDATE threads
                SET deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE thread_id = ?
                """,
                (thread_id,),
            )

    def get_thread(
        self,
        *,
        thread_id: str,
        user_id: str,
        workspace_path: str,
    ) -> dict[str, Any]:
        """查询一个 thread 及其当前待审批请求。"""
        with self._lock:
            thread = self._thread_row(thread_id, user_id, workspace_path)
            pending = self.connection.execute(
                """
                SELECT approval_id, tool_call_id, name, arguments_json,
                       turn_number, requested_at
                FROM approvals
                WHERE thread_id = ? AND status = 'pending'
                ORDER BY requested_sequence DESC LIMIT 1
                """,
                (thread_id,),
            ).fetchone()
        result = dict(thread)
        result["pending_approval"] = (
            {
                **dict(pending),
                "args": json.loads(pending["arguments_json"]),
            }
            if pending is not None
            else None
        )
        if result["pending_approval"] is not None:
            result["pending_approval"].pop("arguments_json")
        return result

    def list_messages(
        self,
        *,
        thread_id: str,
        user_id: str,
        workspace_path: str,
    ) -> list[dict[str, Any]]:
        """按事件顺序查询 thread 的持久化消息。"""
        with self._lock:
            self._thread_row(thread_id, user_id, workspace_path)
            rows = self.connection.execute(
                """
                SELECT message_id, turn_number, role, content,
                       tool_calls_json, tool_call_id, created_at
                FROM messages
                WHERE thread_id = ?
                ORDER BY source_sequence ASC
                """,
                (thread_id,),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            message = dict(row)
            tool_calls_json = message.pop("tool_calls_json")
            message["tool_calls"] = (
                json.loads(tool_calls_json)
                if tool_calls_json is not None
                else None
            )
            messages.append(message)
        return messages

    def list_artifacts(
        self,
        *,
        thread_id: str,
        user_id: str,
        workspace_path: str,
    ) -> list[dict[str, Any]]:
        """查询 thread 中由 Agent 创建或修改的文件。"""
        with self._lock:
            self._thread_row(thread_id, user_id, workspace_path)
            rows = self.connection.execute(
                """
                SELECT artifact_id, turn_number, name, mime_type, url,
                       operation, tool_call_id, created_at, updated_at
                FROM artifacts
                WHERE thread_id = ?
                ORDER BY updated_at DESC
                """,
                (thread_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_artifact(
        self,
        *,
        artifact_id: str,
        user_id: str,
        workspace_path: str,
    ) -> dict[str, Any]:
        normalized_workspace = str(Path(workspace_path).expanduser().resolve())
        with self._lock:
            row = self.connection.execute(
                """
                SELECT a.artifact_id, a.thread_id, a.name, a.mime_type,
                       a.url, a.operation, a.tool_call_id,
                       a.created_at, a.updated_at
                FROM artifacts AS a
                JOIN threads AS t ON t.thread_id = a.thread_id
                WHERE a.artifact_id = ? AND t.user_id = ? AND t.workspace_path = ?
                """,
                (artifact_id, user_id, normalized_workspace),
            ).fetchone()
        if row is None:
            raise HistoryNotFoundError(f"找不到 artifact：{artifact_id}")
        return dict(row)

    def _thread_row(
        self,
        thread_id: str,
        user_id: str,
        workspace_path: str,
    ) -> sqlite3.Row:
        normalized_workspace = str(Path(workspace_path).expanduser().resolve())
        row = self.connection.execute(
            """
            SELECT thread_id, project_id, title, created_at, updated_at, last_turn_number
            FROM threads
            WHERE thread_id = ? AND user_id = ? AND workspace_path = ?
              AND deleted_at IS NULL
            """,
            (thread_id, user_id, normalized_workspace),
        ).fetchone()
        if row is None:
            raise HistoryNotFoundError(f"找不到 thread：{thread_id}")
        return row

    def _project_event(self, event: dict[str, Any], event_log_path: Path) -> None:
        event_type = EventType(event["event_type"])
        handlers = {
            EventType.THREAD_CREATED: self._project_thread_created,
            EventType.TURN_STARTED: self._project_turn_started,
            EventType.ATTACHMENT_ADDED: self._project_attachment,
            EventType.ARTIFACT_RECORDED: self._project_artifact,
            EventType.MESSAGE: self._project_message,
            EventType.MODEL_REQUEST: self._project_model_request,
            EventType.MODEL_RESULT: self._project_model_result,
            EventType.TOOL_STARTED: self._project_tool_started,
            EventType.TOOL_RESULT: self._project_tool_result,
            EventType.APPROVAL_REQUESTED: self._project_approval_requested,
            EventType.APPROVAL_DECIDED: self._project_approval_decided,
            EventType.CONTEXT_COMPACTED: self._project_context_compacted,
            EventType.TURN_FINISHED: self._project_turn_finished,
        }
        handlers[event_type](event, event_log_path)

        turn_number = event["turn_number"] or 0
        updated = self.connection.execute(
            """
            UPDATE threads
            SET projected_sequence = ?,
                updated_at = ?,
                last_turn_number = MAX(last_turn_number, ?)
            WHERE thread_id = ?
            """,
            (
                event["sequence"],
                event["timestamp"],
                turn_number,
                event["thread_id"],
            ),
        )
        if updated.rowcount != 1:
            raise HistoryProjectionError(
                f"事件引用了不存在的 thread：{event['thread_id']}"
            )

    def _project_thread_created(
        self,
        event: dict[str, Any],
        event_log_path: Path,
    ) -> None:
        payload = event["payload"]
        self.connection.execute(
            """
            INSERT INTO threads(
                thread_id, user_id, workspace_path, event_log_path,
                schema_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["thread_id"],
                payload["user_id"],
                payload["workspace_path"],
                str(event_log_path),
                event["schema_version"],
                event["timestamp"],
                event["timestamp"],
            ),
        )

    def _project_turn_started(
        self,
        event: dict[str, Any],
        _: Path,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO turns(
                thread_id, turn_number, input_message_id, status,
                started_sequence, started_at
            ) VALUES (?, ?, ?, 'running', ?, ?)
            ON CONFLICT(thread_id, turn_number) DO NOTHING
            """,
            (
                event["thread_id"],
                event["turn_number"],
                event["payload"]["input_message_id"],
                event["sequence"],
                event["timestamp"],
            ),
        )

    def _project_message(self, event: dict[str, Any], _: Path) -> None:
        payload = event["payload"]
        tool_calls = payload.get("tool_calls")
        self.connection.execute(
            """
            INSERT INTO messages(
                thread_id, message_id, turn_number, source_sequence,
                role, content, tool_calls_json, tool_call_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id, message_id) DO UPDATE SET
                turn_number = excluded.turn_number,
                source_sequence = excluded.source_sequence,
                role = excluded.role,
                content = excluded.content,
                tool_calls_json = excluded.tool_calls_json,
                tool_call_id = excluded.tool_call_id,
                created_at = excluded.created_at
            """,
            (
                event["thread_id"],
                payload["message_id"],
                event["turn_number"],
                event["sequence"],
                payload["role"],
                payload["content"],
                _json_text(tool_calls) if tool_calls is not None else None,
                payload.get("tool_call_id"),
                event["timestamp"],
            ),
        )

    def _project_attachment(self, event: dict[str, Any], _: Path) -> None:
        payload = event["payload"]
        self.connection.execute(
            """
            INSERT INTO attachments(
                thread_id, attachment_id, turn_number, message_id,
                source_sequence, name, mime_type, path, size, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id, attachment_id) DO UPDATE SET
                turn_number = excluded.turn_number,
                message_id = excluded.message_id,
                source_sequence = excluded.source_sequence,
                name = excluded.name,
                mime_type = excluded.mime_type,
                path = excluded.path,
                size = excluded.size,
                created_at = excluded.created_at
            """,
            (
                event["thread_id"],
                payload["attachment_id"],
                event["turn_number"],
                payload["message_id"],
                event["sequence"],
                payload["name"],
                payload["mime_type"],
                payload["path"],
                payload["size"],
                event["timestamp"],
            ),
        )

    def _project_artifact(self, event: dict[str, Any], _: Path) -> None:
        payload = event["payload"]
        self.connection.execute(
            """
            INSERT INTO artifacts(
                thread_id, artifact_id, turn_number, source_sequence,
                name, mime_type, url, operation, tool_call_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id, artifact_id) DO UPDATE SET
                turn_number = excluded.turn_number,
                source_sequence = excluded.source_sequence,
                name = excluded.name,
                mime_type = excluded.mime_type,
                url = excluded.url,
                operation = excluded.operation,
                tool_call_id = excluded.tool_call_id,
                updated_at = excluded.updated_at
            """,
            (
                event["thread_id"],
                payload["artifact_id"],
                event["turn_number"],
                event["sequence"],
                payload["name"],
                payload["mime_type"],
                payload["url"],
                payload["operation"],
                payload["tool_call_id"],
                event["timestamp"],
                event["timestamp"],
            ),
        )

    def _project_model_request(self, event: dict[str, Any], _: Path) -> None:
        payload = event["payload"]
        self.connection.execute(
            """
            INSERT INTO model_calls(
                thread_id, request_id, turn_number, request_sequence,
                provider, model, status, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)
            ON CONFLICT(thread_id, request_id) DO NOTHING
            """,
            (
                event["thread_id"],
                payload["request_id"],
                event["turn_number"],
                event["sequence"],
                payload["provider"],
                payload["model"],
                event["timestamp"],
            ),
        )

    def _project_model_result(self, event: dict[str, Any], _: Path) -> None:
        payload = event["payload"]
        usage = payload.get("usage") or {}
        error_type, error_message = _error_fields(payload)
        updated = self.connection.execute(
            """
            UPDATE model_calls
            SET result_sequence = ?, status = ?, finished_at = ?,
                duration_ms = ?, input_tokens = ?, output_tokens = ?,
                total_tokens = ?, error_type = ?, error_message = ?
            WHERE thread_id = ? AND request_id = ?
            """,
            (
                event["sequence"],
                payload["status"],
                event["timestamp"],
                payload["duration_ms"],
                _usage_value(usage, "input_tokens", "prompt_tokens"),
                _usage_value(usage, "output_tokens", "completion_tokens"),
                _usage_value(usage, "total_tokens", "total_tokens"),
                error_type,
                error_message,
                event["thread_id"],
                payload["request_id"],
            ),
        )
        if updated.rowcount != 1:
            raise HistoryProjectionError("model_result 缺少对应 model_request")

    def _project_tool_started(self, event: dict[str, Any], _: Path) -> None:
        payload = event["payload"]
        self.connection.execute(
            """
            INSERT INTO tool_calls(
                thread_id, tool_call_id, turn_number, started_sequence,
                name, arguments_json, status, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)
            ON CONFLICT(thread_id, tool_call_id) DO NOTHING
            """,
            (
                event["thread_id"],
                payload["tool_call_id"],
                event["turn_number"],
                event["sequence"],
                payload["name"],
                _json_text(payload["args"]),
                event["timestamp"],
            ),
        )

    def _project_tool_result(self, event: dict[str, Any], _: Path) -> None:
        payload = event["payload"]
        error_type, error_message = _error_fields(payload)
        updated = self.connection.execute(
            """
            UPDATE tool_calls
            SET result_sequence = ?, status = ?, finished_at = ?,
                duration_ms = ?, error_type = ?, error_message = ?
            WHERE thread_id = ? AND tool_call_id = ?
            """,
            (
                event["sequence"],
                payload["status"],
                event["timestamp"],
                payload["duration_ms"],
                error_type,
                error_message,
                event["thread_id"],
                payload["tool_call_id"],
            ),
        )
        if updated.rowcount != 1:
            raise HistoryProjectionError("tool_result 缺少对应 tool_started")

    def _project_approval_requested(
        self,
        event: dict[str, Any],
        _: Path,
    ) -> None:
        payload = event["payload"]
        self.connection.execute(
            """
            INSERT INTO approvals(
                thread_id, approval_id, tool_call_id, turn_number,
                name, arguments_json, status, requested_sequence,
                requested_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                event["thread_id"],
                payload["approval_id"],
                payload["tool_call_id"],
                event["turn_number"],
                payload["name"],
                _json_text(payload["args"]),
                event["sequence"],
                event["timestamp"],
            ),
        )

    def _project_approval_decided(
        self,
        event: dict[str, Any],
        _: Path,
    ) -> None:
        payload = event["payload"]
        updated = self.connection.execute(
            """
            UPDATE approvals
            SET status = ?, decided_sequence = ?, decided_at = ?
            WHERE thread_id = ? AND approval_id = ? AND tool_call_id = ?
            """,
            (
                payload["decision"],
                event["sequence"],
                event["timestamp"],
                event["thread_id"],
                payload["approval_id"],
                payload["tool_call_id"],
            ),
        )
        if updated.rowcount != 1:
            raise HistoryProjectionError(
                "approval_decided 缺少对应 approval_requested"
            )

    def _project_turn_finished(self, event: dict[str, Any], _: Path) -> None:
        payload = event["payload"]
        error_type, error_message = _error_fields(payload)
        updated = self.connection.execute(
            """
            UPDATE turns
            SET status = ?, finished_sequence = ?, finished_at = ?,
                duration_ms = ?, final_message_id = ?,
                error_type = ?, error_message = ?
            WHERE thread_id = ? AND turn_number = ?
            """,
            (
                payload["status"],
                event["sequence"],
                event["timestamp"],
                payload["duration_ms"],
                payload.get("final_message_id"),
                error_type,
                error_message,
                event["thread_id"],
                event["turn_number"],
            ),
        )
        if updated.rowcount != 1:
            raise HistoryProjectionError("turn_finished 缺少对应 turn_started")

    def _project_context_compacted(
        self,
        event: dict[str, Any],
        _: Path,
    ) -> None:
        payload = event["payload"]
        self.connection.execute(
            """
            INSERT INTO context_compactions(
                thread_id, summary_message_id, turn_number, source_sequence,
                summary_content, summarized_message_ids_json,
                preserved_message_ids_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id, summary_message_id) DO UPDATE SET
                turn_number = excluded.turn_number,
                source_sequence = excluded.source_sequence,
                summary_content = excluded.summary_content,
                summarized_message_ids_json = excluded.summarized_message_ids_json,
                preserved_message_ids_json = excluded.preserved_message_ids_json,
                created_at = excluded.created_at
            """,
            (
                event["thread_id"],
                payload["summary_message_id"],
                event["turn_number"],
                event["sequence"],
                payload["summary_content"],
                _json_text(payload["summarized_message_ids"]),
                _json_text(payload["preserved_message_ids"]),
                event["timestamp"],
            ),
        )


def create_history_service(
    database_path: Path = HISTORY_DATABASE_PATH,
    event_log_service: EventLogService = event_log,
) -> HistoryService:
    """显式创建 History 服务，避免导入模块时创建数据库文件。"""
    return HistoryService(database_path, event_log_service)

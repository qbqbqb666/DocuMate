import base64
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.backend.services.event_log import EventLogService, EventType
from src.backend.services.history import HistoryNotFoundError, HistoryService


THREAD_ID = "019946f2-73a1-7c21-9dd4-c44f422ba835"


class HistoryServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.clock = lambda: datetime(
            2026,
            9,
            14,
            9,
            17,
            41,
            123000,
            tzinfo=timezone.utc,
        )
        self.event_log = EventLogService(root / "sessions", self.clock)
        self.database_path = root / "history.sqlite3"
        self.history = HistoryService(self.database_path, self.event_log)
        self.addCleanup(self.history.close)
        self.event_log.create_thread_log(
            thread_id=THREAD_ID,
            user_id="user-001",
            workspace_path="/workspace",
        )

    def append(self, event_type: EventType, payload: dict) -> None:
        self.event_log.append(
            thread_id=THREAD_ID,
            turn_number=1,
            event_type=event_type,
            payload=payload,
        )

    def append_complete_turn(self) -> str:
        image_base64 = base64.b64encode(b"original-image").decode("ascii")
        self.append(EventType.TURN_STARTED, {"input_message_id": "msg-001"})
        self.append(
            EventType.ATTACHMENT_ADDED,
            {
                "attachment_id": "att-001",
                "message_id": "msg-001",
                "name": "photo.png",
                "mime_type": "image/png",
                "path": "/external/photo.png",
                "size": 14,
                "base64_data": image_base64,
            },
        )
        self.append(
            EventType.MESSAGE,
            {
                "message_id": "msg-001",
                "role": "user",
                "content": "分析图片",
                "attachment_ids": ["att-001"],
            },
        )
        self.append(
            EventType.MODEL_REQUEST,
            {
                "request_id": "req-001",
                "provider": "siliconflow",
                "model": "test-model",
                "messages": [
                    {
                        "role": "user",
                        "content": f"data:image/png;base64,{image_base64}",
                    }
                ],
                "tools": [],
                "parameters": {},
            },
        )
        self.append(
            EventType.MODEL_RESULT,
            {
                "request_id": "req-001",
                "status": "success",
                "response": {"content": "正在读取"},
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "total_tokens": 110,
                },
                "duration_ms": 100,
            },
        )
        self.append(
            EventType.MESSAGE,
            {
                "message_id": "msg-002",
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-001",
                        "name": "write_file",
                        "args": {"path": "summary.md"},
                    }
                ],
            },
        )
        self.append(
            EventType.TOOL_STARTED,
            {
                "tool_call_id": "call-001",
                "name": "write_file",
                "args": {"path": "summary.md"},
            },
        )
        self.append(
            EventType.TOOL_RESULT,
            {
                "tool_call_id": "call-001",
                "name": "write_file",
                "status": "success",
                "result": {"path": "/workspace/summary.md"},
                "duration_ms": 20,
            },
        )
        self.append(
            EventType.MESSAGE,
            {
                "message_id": "msg-003",
                "role": "tool",
                "content": "写入成功",
                "tool_call_id": "call-001",
            },
        )
        self.append(
            EventType.ARTIFACT_RECORDED,
            {
                "artifact_id": "artifact-001",
                "name": "summary.md",
                "mime_type": "text/markdown",
                "url": "/workspace/summary.md",
                "operation": "created",
                "tool_call_id": "call-001",
            },
        )
        self.append(
            EventType.MODEL_REQUEST,
            {
                "request_id": "req-002",
                "provider": "siliconflow",
                "model": "test-model",
                "messages": [],
                "tools": [],
                "parameters": {},
            },
        )
        self.append(
            EventType.MODEL_RESULT,
            {
                "request_id": "req-002",
                "status": "success",
                "response": {"content": "完成"},
                "usage": {},
                "duration_ms": 80,
            },
        )
        self.append(
            EventType.MESSAGE,
            {
                "message_id": "msg-004",
                "role": "assistant",
                "content": "处理完成",
            },
        )
        self.append(
            EventType.TURN_FINISHED,
            {
                "status": "success",
                "final_message_id": "msg-004",
                "duration_ms": 200,
            },
        )
        return image_base64

    def test_projects_all_event_types_into_normalized_tables(self) -> None:
        image_base64 = self.append_complete_turn()

        projected = self.history.sync_thread(THREAD_ID)

        self.assertEqual(projected, 15)
        expected_counts = {
            "threads": 1,
            "turns": 1,
            "messages": 4,
            "attachments": 1,
            "artifacts": 1,
            "model_calls": 2,
            "tool_calls": 1,
        }
        for table, expected in expected_counts.items():
            count = self.history.connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            self.assertEqual(count, expected, table)

        thread = self.history.connection.execute(
            "SELECT * FROM threads WHERE thread_id = ?",
            (THREAD_ID,),
        ).fetchone()
        self.assertEqual(thread["projected_sequence"], 15)
        self.assertEqual(thread["last_turn_number"], 1)

        model_call = self.history.connection.execute(
            "SELECT * FROM model_calls WHERE request_id = 'req-001'"
        ).fetchone()
        self.assertEqual(model_call["status"], "success")
        self.assertEqual(model_call["total_tokens"], 110)

        database_bytes = self.database_path.read_bytes()
        self.assertNotIn(image_base64.encode("ascii"), database_bytes)
        self.assertNotIn(b"base64_data", database_bytes)

    def test_sync_resumes_after_projected_sequence_and_is_idempotent(self) -> None:
        self.append(EventType.TURN_STARTED, {"input_message_id": "msg-001"})

        self.assertEqual(self.history.sync_thread(THREAD_ID), 2)
        self.assertEqual(self.history.sync_thread(THREAD_ID), 0)

        self.append(
            EventType.MESSAGE,
            {
                "message_id": "msg-001",
                "role": "user",
                "content": "继续写入",
            },
        )

        self.assertEqual(self.history.sync_thread(THREAD_ID), 1)
        thread = self.history.connection.execute(
            "SELECT projected_sequence FROM threads WHERE thread_id = ?",
            (THREAD_ID,),
        ).fetchone()
        self.assertEqual(thread[0], 3)

    def test_new_database_can_be_rebuilt_from_existing_jsonl(self) -> None:
        self.append_complete_turn()
        self.assertEqual(self.history.sync_thread(THREAD_ID), 15)

        rebuilt_path = self.database_path.with_name("rebuilt.sqlite3")
        rebuilt = HistoryService(rebuilt_path, self.event_log)
        self.addCleanup(rebuilt.close)

        self.assertEqual(rebuilt.sync_all_threads(), 15)
        messages = rebuilt.connection.execute(
            "SELECT role, content FROM messages ORDER BY source_sequence"
        ).fetchall()
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[-1]["content"], "处理完成")

    def test_projects_context_compaction(self) -> None:
        self.append(EventType.TURN_STARTED, {"input_message_id": "msg-001"})
        self.append(
            EventType.CONTEXT_COMPACTED,
            {
                "summary_message_id": "summary-001",
                "summary_content": "Earlier summary.",
                "summarized_message_ids": ["msg-old"],
                "preserved_message_ids": ["msg-001"],
            },
        )

        self.assertEqual(self.history.sync_thread(THREAD_ID), 3)
        row = self.history.connection.execute(
            "SELECT * FROM context_compactions"
        ).fetchone()
        self.assertEqual(row["summary_message_id"], "summary-001")
        self.assertEqual(row["summary_content"], "Earlier summary.")

    def test_projects_individual_approval_lifecycle(self) -> None:
        self.append(EventType.TURN_STARTED, {"input_message_id": "msg-001"})
        self.append(
            EventType.APPROVAL_REQUESTED,
            {
                "approval_id": "approval-001",
                "tool_call_id": "call-001",
                "name": "delete_file",
                "args": {"relative_path": "old.md"},
            },
        )
        self.append(
            EventType.APPROVAL_DECIDED,
            {
                "approval_id": "approval-001",
                "tool_call_id": "call-001",
                "decision": "deny",
            },
        )

        self.assertEqual(self.history.sync_thread(THREAD_ID), 4)
        row = self.history.connection.execute(
            "SELECT * FROM approvals WHERE approval_id = 'approval-001'"
        ).fetchone()
        self.assertEqual(row["tool_call_id"], "call-001")
        self.assertEqual(row["status"], "deny")
        self.assertIsNotNone(row["decided_sequence"])

    def test_same_approval_id_can_track_multiple_tool_calls(self) -> None:
        self.append(EventType.TURN_STARTED, {"input_message_id": "msg-001"})
        for tool_call_id, path in (
            ("call-001", "first.md"),
            ("call-002", "second.md"),
        ):
            self.append(
                EventType.APPROVAL_REQUESTED,
                {
                    "approval_id": "approval-shared",
                    "tool_call_id": tool_call_id,
                    "name": "write_text_file",
                    "args": {"relative_path": path, "content": ""},
                },
            )

        self.assertEqual(self.history.sync_thread(THREAD_ID), 4)
        rows = self.history.connection.execute(
            """
            SELECT tool_call_id FROM approvals
            WHERE thread_id = ? AND approval_id = ?
            ORDER BY tool_call_id
            """,
            (THREAD_ID, "approval-shared"),
        ).fetchall()
        self.assertEqual(
            [row["tool_call_id"] for row in rows],
            ["call-001", "call-002"],
        )

    def test_queries_threads_messages_artifacts_and_pending_approval(self) -> None:
        self.append_complete_turn()
        self.assertEqual(self.history.sync_thread(THREAD_ID), 15)

        threads = self.history.list_threads(
            user_id="user-001",
            workspace_path="/workspace",
        )
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["thread_id"], THREAD_ID)
        self.assertEqual(threads[0]["message_count"], 4)
        self.assertEqual(threads[0]["preview"], "分析图片")
        self.assertEqual(threads[0]["last_turn_status"], "success")

        stats = self.history.workspace_stats(
            user_id="user-001",
            workspace_path="/workspace",
        )
        self.assertEqual(stats, {"thread_count": 1, "total_tokens": 110})

        messages = self.history.list_messages(
            thread_id=THREAD_ID,
            user_id="user-001",
            workspace_path="/workspace",
        )
        self.assertEqual([message["role"] for message in messages], [
            "user", "assistant", "tool", "assistant"
        ])
        self.assertEqual(messages[1]["tool_calls"][0]["id"], "call-001")

        artifacts = self.history.list_artifacts(
            thread_id=THREAD_ID,
            user_id="user-001",
            workspace_path="/workspace",
        )
        self.assertEqual(artifacts[0]["artifact_id"], "artifact-001")

        detail = self.history.get_thread(
            thread_id=THREAD_ID,
            user_id="user-001",
            workspace_path="/workspace",
        )
        self.assertIsNone(detail["pending_approval"])

    def test_query_hides_threads_from_other_identity_or_workspace(self) -> None:
        self.history.sync_thread(THREAD_ID)
        self.assertEqual(
            self.history.list_threads(
                user_id="another-user",
                workspace_path="/workspace",
            ),
            [],
        )
        with self.assertRaises(HistoryNotFoundError):
            self.history.get_thread(
                thread_id=THREAD_ID,
                user_id="user-001",
                workspace_path="/another-workspace",
            )

    def test_thread_project_rename_and_soft_delete(self) -> None:
        self.history.sync_thread(THREAD_ID)
        self.history.set_thread_project(
            thread_id=THREAD_ID,
            user_id="user-001",
            workspace_path="/workspace",
            project_id="project-1",
        )
        renamed = self.history.rename_thread(
            thread_id=THREAD_ID,
            user_id="user-001",
            workspace_path="/workspace",
            title="新的对话名称",
        )
        threads = self.history.list_threads(
            user_id="user-001",
            workspace_path="/workspace",
            project_id="project-1",
        )
        self.assertEqual(renamed["title"], "新的对话名称")
        self.assertEqual(threads[0]["title"], "新的对话名称")

        self.history.delete_thread(
            thread_id=THREAD_ID,
            user_id="user-001",
            workspace_path="/workspace",
        )
        self.assertEqual(
            self.history.list_threads(
                user_id="user-001",
                workspace_path="/workspace",
                project_id="project-1",
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()

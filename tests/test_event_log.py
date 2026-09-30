import base64
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.backend.services.event_log import (
    CorruptEventLogError,
    DuplicateEventLogError,
    EventLogService,
    EventLogValidationError,
    EventType,
)


THREAD_ID = "019946f2-73a1-7c21-9dd4-c44f422ba835"


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class EventLogServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "sessions"
        self.clock = MutableClock(
            datetime(
                2026,
                9,
                14,
                9,
                17,
                41,
                123000,
                tzinfo=timezone.utc,
            )
        )
        self.service = EventLogService(
            root=self.root,
            clock=self.clock,
        )

    def create_thread(self) -> Path:
        return self.service.create_thread_log(
            thread_id=THREAD_ID,
            user_id="user-001",
            workspace_path="/workspace/文档",
        )

    def test_create_thread_writes_v02_event_in_utc_path(self) -> None:
        path = self.create_thread()

        self.assertEqual(
            path,
            self.root
            / "2026/09/14"
            / (
                "rollout-20260914T091741123Z-"
                f"{THREAD_ID}.jsonl"
            ),
        )
        event = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(event),
            {
                "schema_version",
                "sequence",
                "event_type",
                "thread_id",
                "turn_number",
                "timestamp",
                "payload",
            },
        )
        self.assertEqual(event["schema_version"], "0.2")
        self.assertEqual(event["sequence"], 1)
        self.assertEqual(event["event_type"], "thread_created")
        self.assertIsNone(event["turn_number"])
        self.assertEqual(
            event["timestamp"],
            "2026-09-14T09:17:41.123Z",
        )
        self.assertEqual(event["payload"]["user_id"], "user-001")

    def test_append_uses_same_file_across_dates(self) -> None:
        original_path = self.create_thread()
        self.clock.value = datetime(
            2026,
            9,
            15,
            2,
            0,
            tzinfo=timezone.utc,
        )

        event = self.service.append(
            thread_id=THREAD_ID,
            turn_number=1,
            event_type=EventType.TURN_STARTED,
            payload={"input_message_id": "msg-001"},
        )

        self.assertEqual(event["sequence"], 2)
        self.assertEqual(
            self.service.find_thread_log(THREAD_ID),
            original_path,
        )
        self.assertEqual(len(list(self.root.rglob("*.jsonl"))), 1)

    def test_reads_existing_v01_event(self) -> None:
        path = self.create_thread()
        event = json.loads(path.read_text(encoding="utf-8"))
        event["schema_version"] = "0.1"
        path.write_text(
            json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        restored = list(self.service.iter_events(THREAD_ID))

        self.assertEqual(restored[0]["schema_version"], "0.1")

    def test_sequence_increments_and_incremental_read_filters(self) -> None:
        self.create_thread()
        self.service.append(
            thread_id=THREAD_ID,
            turn_number=1,
            event_type=EventType.TURN_STARTED,
            payload={"input_message_id": "msg-001"},
        )
        self.service.append(
            thread_id=THREAD_ID,
            turn_number=1,
            event_type=EventType.MESSAGE,
            payload={
                "message_id": "msg-001",
                "role": "user",
                "content": "读取文档",
            },
        )

        events = list(
            self.service.iter_events(
                THREAD_ID,
                after_sequence=1,
            )
        )

        self.assertEqual([event["sequence"] for event in events], [2, 3])
        self.assertEqual(events[1]["payload"]["content"], "读取文档")

    def test_model_request_round_trips_small_base64(self) -> None:
        self.create_thread()
        encoded_image = base64.b64encode(b"tiny-image").decode("ascii")

        self.service.append(
            thread_id=THREAD_ID,
            turn_number=1,
            event_type=EventType.MODEL_REQUEST,
            payload={
                "request_id": "req-001",
                "provider": "siliconflow",
                "model": "test-model",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_image",
                                "image_url": (
                                    "data:image/png;base64,"
                                    f"{encoded_image}"
                                ),
                            }
                        ],
                    }
                ],
                "tools": [],
                "parameters": {},
            },
        )

        event = list(self.service.iter_events(THREAD_ID))[-1]
        image_url = event["payload"]["messages"][0]["content"][0][
            "image_url"
        ]
        self.assertEqual(
            image_url,
            f"data:image/png;base64,{encoded_image}",
        )

    def test_execution_metadata_is_optional_and_validated(self) -> None:
        self.create_thread()
        execution = {
            "run_id": "run-1",
            "task_id": "task-1",
            "checkpoint_id": "checkpoint-1",
            "node_attempt": 2,
        }

        event = self.service.append(
            thread_id=THREAD_ID,
            turn_number=1,
            event_type=EventType.TOOL_STARTED,
            payload={
                "tool_call_id": "call-1",
                "name": "read_text_file",
                "args": {},
                "execution": execution,
            },
        )

        self.assertEqual(event["payload"]["execution"], execution)
        with self.assertRaises(EventLogValidationError):
            self.service.append(
                thread_id=THREAD_ID,
                turn_number=1,
                event_type=EventType.TOOL_STARTED,
                payload={
                    "tool_call_id": "call-2",
                    "name": "read_text_file",
                    "args": {},
                    "execution": {"node_attempt": 0},
                },
            )

    def test_attachment_keeps_path_and_base64_for_recovery(self) -> None:
        self.create_thread()
        encoded_image = base64.b64encode(b"original-image").decode("ascii")

        self.service.append(
            thread_id=THREAD_ID,
            turn_number=1,
            event_type=EventType.ATTACHMENT_ADDED,
            payload={
                "attachment_id": "att-001",
                "message_id": "msg-001",
                "name": "photo.png",
                "mime_type": "image/png",
                "path": "/external/photo.png",
                "size": 14,
                "base64_data": encoded_image,
            },
        )

        event = self.service.find_attachment_event(THREAD_ID, "att-001")

        self.assertIsNotNone(event)
        self.assertEqual(event["payload"]["path"], "/external/photo.png")
        self.assertEqual(event["payload"]["base64_data"], encoded_image)

    def test_invalid_attachment_base64_is_rejected(self) -> None:
        self.create_thread()

        with self.assertRaises(EventLogValidationError):
            self.service.append(
                thread_id=THREAD_ID,
                turn_number=1,
                event_type=EventType.ATTACHMENT_ADDED,
                payload={
                    "attachment_id": "att-001",
                    "message_id": "msg-001",
                    "name": "photo.png",
                    "mime_type": "image/png",
                    "path": "/external/photo.png",
                    "size": 14,
                    "base64_data": "not-base64",
                },
            )

    def test_artifact_event_uses_confirmed_fields(self) -> None:
        self.create_thread()

        event = self.service.append(
            thread_id=THREAD_ID,
            turn_number=1,
            event_type=EventType.ARTIFACT_RECORDED,
            payload={
                "artifact_id": "artifact-001",
                "name": "summary.md",
                "mime_type": "text/markdown",
                "url": "/workspace/summary.md",
                "operation": "created",
                "tool_call_id": "call-001",
            },
        )

        self.assertEqual(event["event_type"], "artifact_recorded")
        self.assertEqual(event["payload"]["operation"], "created")

    def test_approval_events_round_trip_and_validate_decision(self) -> None:
        self.create_thread()
        requested = self.service.append(
            thread_id=THREAD_ID,
            turn_number=1,
            event_type=EventType.APPROVAL_REQUESTED,
            payload={
                "approval_id": "approval-1",
                "tool_call_id": "call-1",
                "name": "write_text_file",
                "args": {"relative_path": "new.md"},
            },
        )
        decided = self.service.append(
            thread_id=THREAD_ID,
            turn_number=1,
            event_type=EventType.APPROVAL_DECIDED,
            payload={
                "approval_id": "approval-1",
                "tool_call_id": "call-1",
                "decision": "allow",
            },
        )

        self.assertEqual(requested["event_type"], "approval_requested")
        self.assertEqual(decided["payload"]["decision"], "allow")
        with self.assertRaises(EventLogValidationError):
            self.service.append(
                thread_id=THREAD_ID,
                turn_number=1,
                event_type=EventType.APPROVAL_DECIDED,
                payload={
                    "approval_id": "approval-2",
                    "tool_call_id": "call-2",
                    "decision": "maybe",
                },
            )

    def test_rejects_unknown_or_invalid_payload_fields(self) -> None:
        self.create_thread()

        with self.assertRaises(EventLogValidationError):
            self.service.append(
                thread_id=THREAD_ID,
                turn_number=1,
                event_type="unknown",
                payload={},
            )
        with self.assertRaises(EventLogValidationError):
            self.service.append(
                thread_id=THREAD_ID,
                turn_number=1,
                event_type=EventType.TURN_STARTED,
                payload={
                    "input_message_id": "msg-001",
                    "unexpected": True,
                },
            )

    def test_role_and_status_condition_fields_are_validated(self) -> None:
        self.create_thread()

        with self.assertRaises(EventLogValidationError):
            self.service.append(
                thread_id=THREAD_ID,
                turn_number=1,
                event_type=EventType.MESSAGE,
                payload={
                    "message_id": "msg-tool",
                    "role": "tool",
                    "content": "result",
                },
            )
        with self.assertRaises(EventLogValidationError):
            self.service.append(
                thread_id=THREAD_ID,
                turn_number=1,
                event_type=EventType.MODEL_RESULT,
                payload={
                    "request_id": "req-001",
                    "status": "success",
                    "duration_ms": 1,
                },
            )

    def test_duplicate_thread_is_rejected(self) -> None:
        self.create_thread()

        with self.assertRaises(DuplicateEventLogError):
            self.create_thread()

    def test_incomplete_tail_is_not_overwritten(self) -> None:
        path = self.create_thread()
        with path.open("ab") as file:
            file.write(b'{"broken"')
        original_content = path.read_bytes()

        with self.assertRaises(CorruptEventLogError):
            self.service.append(
                thread_id=THREAD_ID,
                turn_number=1,
                event_type=EventType.TURN_STARTED,
                payload={"input_message_id": "msg-001"},
            )

        self.assertEqual(path.read_bytes(), original_content)


if __name__ == "__main__":
    unittest.main()

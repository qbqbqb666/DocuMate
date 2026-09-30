import base64
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.backend.services.event_log import EventLogService
from src.backend.services.recorder import RunRecorder, extract_execution_metadata


class SequenceTimer:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


class RunRecorderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.thread_id = str(uuid4())
        self.event_log = EventLogService(
            root=self.root / "sessions",
            clock=lambda: datetime(2026, 9, 16, tzinfo=timezone.utc),
        )
        self.event_log.create_thread_log(
            thread_id=self.thread_id,
            user_id="user-1",
            workspace_path="/workspace",
        )

    def test_records_complete_successful_turn(self) -> None:
        recorder = RunRecorder(
            thread_id=self.thread_id,
            turn_number=1,
            event_log_service=self.event_log,
            timer=SequenceTimer(1.0, 2.0, 2.5, 3.0, 3.25, 4.0),
        )
        turn = recorder.turn_started("message-user")
        encoded = base64.b64encode(b"image").decode("ascii")
        recorder.attachment_added(
            attachment_id="attachment-1",
            message_id="message-user",
            name="tiny.png",
            mime_type="image/png",
            path="/workspace/tiny.png",
            size=5,
            base64_data=encoded,
        )
        user_message = recorder.message_created(
            HumanMessage(id="message-user", content="分析图片"),
            attachment_ids=["attachment-1"],
        )
        model = recorder.model_started(
            request_id="request-1",
            provider="siliconflow",
            model="Qwen/Qwen3.5-4B",
            messages=[user_message],
            tools=[{"name": "read_text_file"}],
            parameters={"temperature": 0},
        )
        ai_message = AIMessage(
            id="message-ai-tool",
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "read_text_file",
                    "args": {"relative_path": "notes.md"},
                }
            ],
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        )
        recorder.model_succeeded(
            model,
            response=ai_message,
            usage=ai_message.usage_metadata,
        )
        recorder.message_created(ai_message)
        tool = recorder.tool_started(
            tool_call_id="call-1",
            name="read_text_file",
            args={"relative_path": "notes.md"},
        )
        recorder.tool_succeeded(
            tool,
            name="read_text_file",
            result={"content": "notes"},
        )
        tool_message = recorder.message_created(
            ToolMessage(
                id="message-tool",
                tool_call_id="call-1",
                content='{"content":"notes"}',
            )
        )
        recorder.artifact_recorded(
            artifact_id="artifact-1",
            name="notes.md",
            mime_type="text/markdown",
            url="/workspace/notes.md",
            operation="modified",
            tool_call_id="call-1",
        )
        final_message = recorder.message_created(
            AIMessage(id="message-final", content="处理完成")
        )
        recorder.turn_succeeded(turn, final_message_id=final_message.id)

        events = list(self.event_log.iter_events(self.thread_id))
        self.assertEqual(
            [event["event_type"] for event in events],
            [
                "thread_created",
                "turn_started",
                "attachment_added",
                "message",
                "model_request",
                "model_result",
                "message",
                "tool_started",
                "tool_result",
                "message",
                "artifact_recorded",
                "message",
                "turn_finished",
            ],
        )
        self.assertEqual(events[5]["payload"]["request_id"], "request-1")
        self.assertEqual(events[8]["payload"]["tool_call_id"], "call-1")
        self.assertEqual(events[9]["payload"]["tool_call_id"], "call-1")
        self.assertEqual(events[-1]["payload"]["final_message_id"], "message-final")
        self.assertEqual(tool_message.tool_call_id, "call-1")

    def test_records_model_tool_and_turn_failures(self) -> None:
        recorder = RunRecorder(
            thread_id=self.thread_id,
            turn_number=1,
            event_log_service=self.event_log,
            timer=SequenceTimer(1.0, 2.0, 2.1, 3.0, 3.2, 4.0),
        )
        turn = recorder.turn_started("message-user")
        model = recorder.model_started(
            request_id="request-1",
            provider="siliconflow",
            model="model",
            messages=[HumanMessage(id="message-user", content="hello")],
            tools=[],
            parameters={},
        )
        recorder.model_failed(model, RuntimeError("model failed"))
        tool = recorder.tool_started(
            tool_call_id="call-1",
            name="read_text_file",
            args={},
        )
        recorder.tool_failed(
            tool,
            name="read_text_file",
            error=ValueError("tool failed"),
        )
        recorder.turn_failed(turn, RuntimeError("turn failed"))

        events = list(self.event_log.iter_events(self.thread_id))
        self.assertEqual(events[3]["payload"]["status"], "error")
        self.assertEqual(events[3]["payload"]["error"]["type"], "RuntimeError")
        self.assertEqual(events[5]["payload"]["status"], "error")
        self.assertEqual(events[-1]["payload"]["status"], "error")

    def test_assigns_missing_message_id_and_serializes_block_content(self) -> None:
        recorder = RunRecorder(
            thread_id=self.thread_id,
            turn_number=1,
            event_log_service=self.event_log,
        )
        message = HumanMessage(
            content=[{"type": "text", "text": "hello"}]
        )

        normalized = recorder.message_created(message)

        self.assertIsNone(message.id)
        self.assertIsNotNone(normalized.id)
        event = list(self.event_log.iter_events(self.thread_id))[-1]
        self.assertEqual(event["payload"]["message_id"], normalized.id)
        self.assertEqual(
            event["payload"]["content"],
            '[{"type":"text","text":"hello"}]',
        )

    def test_records_individual_approval_request_and_decision(self) -> None:
        recorder = RunRecorder(
            thread_id=self.thread_id,
            turn_number=1,
            event_log_service=self.event_log,
        )
        recorder.approval_requested(
            approval_id="approval-1",
            tool_call_id="call-1",
            name="write_text_file",
            args={"relative_path": "new.md"},
        )
        recorder.approval_decided(
            approval_id="approval-1",
            tool_call_id="call-1",
            decision="allow",
        )

        events = list(self.event_log.iter_events(self.thread_id))
        self.assertEqual(events[-2]["event_type"], "approval_requested")
        self.assertEqual(events[-1]["event_type"], "approval_decided")

    def test_turn_started_records_runtime_configuration(self) -> None:
        recorder = RunRecorder(
            thread_id=self.thread_id,
            turn_number=1,
            event_log_service=self.event_log,
        )

        recorder.turn_started(
            "message-user",
            provider="deepseek",
            model_name="deepseek-flash",
            permission="request_approval",
        )

        payload = list(self.event_log.iter_events(self.thread_id))[-1]["payload"]
        self.assertEqual(payload["provider"], "deepseek")
        self.assertEqual(payload["model_name"], "deepseek-flash")
        self.assertEqual(payload["permission"], "request_approval")

    def test_extracts_and_records_execution_metadata_for_operation_pair(self) -> None:
        runtime = SimpleNamespace(
            execution_info=SimpleNamespace(
                run_id="run-1",
                task_id="task-1",
                checkpoint_id="checkpoint-1",
                node_attempt=1,
                thread_id="thread-is-not-copied",
                checkpoint_ns="",
                node_first_attempt_time=1.0,
            )
        )
        execution = extract_execution_metadata(runtime)
        recorder = RunRecorder(
            thread_id=self.thread_id,
            turn_number=1,
            event_log_service=self.event_log,
            timer=SequenceTimer(1.0, 2.0, 3.0, 4.0),
        )

        model_handle = recorder.model_started(
            provider="siliconflow",
            model="test-model",
            messages=[HumanMessage(content="hello")],
            tools=[],
            parameters={},
            execution=execution,
        )
        recorder.model_succeeded(
            model_handle,
            response=AIMessage(content="done"),
        )
        tool_handle = recorder.tool_started(
            tool_call_id="call-1",
            name="read_text_file",
            args={},
            execution=execution,
        )
        recorder.tool_succeeded(
            tool_handle,
            name="read_text_file",
            result={"content": "ok"},
        )

        payloads = [
            event["payload"]
            for event in self.event_log.iter_events(self.thread_id)
            if event["event_type"] in {
                "model_request",
                "model_result",
                "tool_started",
                "tool_result",
            }
        ]
        self.assertTrue(all(
            payload["execution"] == payloads[0]["execution"]
            for payload in payloads
        ))
        self.assertEqual(
            payloads[0]["execution"],
            {
                "run_id": "run-1",
                "task_id": "task-1",
                "checkpoint_id": "checkpoint-1",
                "node_attempt": 1,
            },
        )
        self.assertIsNone(extract_execution_metadata(SimpleNamespace()))


if __name__ == "__main__":
    unittest.main()

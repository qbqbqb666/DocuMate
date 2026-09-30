import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.types import Command, Interrupt

from src.backend.services.conversation import (
    ApprovalStreamEvent,
    ConversationError,
    ConversationCoordinator,
    ErrorStreamEvent,
    ImageInput,
    ModelChunkEvent,
    StatusStreamEvent,
    TurnResultStreamEvent,
    _turn_execution_summary,
)
from src.backend.agent.context import ModelProvider
from src.backend.services.event_log import EventLogService
from src.backend.services.history import HistoryService
from src.backend.services.state_rebuilder import rebuild_state_from_event_log
from src.backend.services.cancellation import RunCancelledError


class FakeGraph:
    def __init__(self) -> None:
        self.states = {}
        self.restore_count = 0
        self.contexts = []

    def get_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        return SimpleNamespace(
            values=self.states.get(thread_id, {}),
            interrupts=(),
        )

    def update_state(self, config, state, *, as_node):
        thread_id = config["configurable"]["thread_id"]
        self.states[thread_id] = state
        self.restore_count += 1

    def invoke(self, graph_input, config, *, context):
        self.contexts.append(context)
        thread_id = config["configurable"]["thread_id"]
        previous = self.states.get(thread_id, {})
        response = context.recorder.message_created(
            AIMessage(id=str(uuid4()), content="done")
        )
        state = {
            "messages": [
                *previous.get("messages", []),
                *graph_input["messages"],
                response,
            ],
            "attachments": {
                **previous.get("attachments", {}),
                **graph_input["attachments"],
            },
            "artifacts": previous.get("artifacts", {}),
            "prepare": graph_input["prepare"],
        }
        self.states[thread_id] = state
        return state


class StreamingFakeGraph(FakeGraph):
    def __init__(self) -> None:
        super().__init__()
        self.run_ids = []

    def stream(self, graph_input, config, *, context, stream_mode):
        self.run_ids.append(str(config["run_id"]))
        yield (
            "custom",
            {
                "type": "status",
                "stage": "model",
                "message": "正在请求模型",
                "tool_call_id": None,
                "tool_name": None,
            },
        )
        yield (
            "messages",
            (AIMessageChunk(content="do"), {"langgraph_node": "model"}),
        )
        yield (
            "messages",
            (AIMessageChunk(content="ne"), {"langgraph_node": "model"}),
        )
        state = self.invoke(graph_input, config, context=context)
        yield ("values", state)


class FailingStreamingGraph(FakeGraph):
    def stream(self, graph_input, config, *, context, stream_mode):
        yield (
            "custom",
            {
                "type": "status",
                "stage": "model",
                "message": "正在请求模型",
                "tool_call_id": None,
                "tool_name": None,
            },
        )
        raise RuntimeError("stream failed")


class InterruptingFakeGraph:
    def __init__(self) -> None:
        self.states = {}
        self.active_interrupts = {}
        self.resume_count = 0
        self.contexts = []
        self.run_ids = []

    def get_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        return SimpleNamespace(
            values=self.states.get(thread_id, {}),
            interrupts=self.active_interrupts.get(thread_id, ()),
        )

    def update_state(self, config, state, *, as_node):
        self.states[config["configurable"]["thread_id"]] = state

    def invoke(self, graph_input, config, *, context):
        self.contexts.append(context)
        thread_id = config["configurable"]["thread_id"]
        if isinstance(graph_input, Command):
            self.resume_count += 1
            state = self.states[thread_id]
            if self.resume_count == 1:
                interrupt = Interrupt(
                    id="approval-2",
                    value={
                        "type": "tool_approval",
                        "tool_call_id": "call-2",
                        "name": "delete_file",
                        "args": {"relative_path": "old.md"},
                    },
                )
                self.active_interrupts[thread_id] = (interrupt,)
                return {**state, "__interrupt__": [interrupt]}
            response = context.recorder.message_created(
                AIMessage(id="message-final", content="done")
            )
            completed = {**state, "messages": [*state["messages"], response]}
            self.states[thread_id] = completed
            self.active_interrupts[thread_id] = ()
            return completed

        tool_request = context.recorder.message_created(
            AIMessage(
                id="message-tools",
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "write_text_file",
                        "args": {"relative_path": "new.md", "content": "new"},
                    },
                    {
                        "id": "call-2",
                        "name": "delete_file",
                        "args": {"relative_path": "old.md"},
                    },
                ],
            )
        )
        state = {
            "messages": [*graph_input["messages"], tool_request],
            "attachments": graph_input["attachments"],
            "artifacts": {},
            "prepare": graph_input["prepare"],
            "tool_execution_plan": None,
        }
        interrupt = Interrupt(
            id="approval-1",
            value={
                "type": "tool_approval",
                "tool_call_id": "call-1",
                "name": "write_text_file",
                "args": {"relative_path": "new.md", "content": "new"},
            },
        )
        self.states[thread_id] = state
        self.active_interrupts[thread_id] = (interrupt,)
        return {**state, "__interrupt__": [interrupt]}

    def stream(self, graph_input, config, *, context, stream_mode):
        self.run_ids.append(str(config["run_id"]))
        yield (
            "custom",
            {
                "type": "status",
                "stage": "approval",
                "message": "正在等待批准",
                "tool_call_id": "call-1",
                "tool_name": "write_text_file",
            },
        )
        state = self.invoke(graph_input, config, context=context)
        if not self.active_interrupts[config["configurable"]["thread_id"]]:
            yield (
                "messages",
                (AIMessageChunk(content="done"), {"langgraph_node": "model"}),
            )
        yield ("values", state)


class ConversationCoordinatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.event_log = EventLogService(self.root / "sessions")
        self.history = HistoryService(
            self.root / "history.sqlite3",
            self.event_log,
        )
        self.addCleanup(self.history.close)
        self.graph = FakeGraph()
        self.coordinator = ConversationCoordinator(
            graph=self.graph,
            history_service=self.history,
            event_log_service=self.event_log,
        )

    def test_stream_run_can_be_cancelled_by_run_id(self) -> None:
        graph = StreamingFakeGraph()
        coordinator = ConversationCoordinator(
            graph=graph,
            history_service=self.history,
            event_log_service=self.event_log,
        )
        thread_id = coordinator.create_thread(
            user_id="user-1",
            workspace_path=str(self.workspace),
        )
        stream = coordinator.stream_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="cancel me",
            run_id="run-cancel",
        )

        self.assertIsInstance(next(stream), StatusStreamEvent)
        self.assertTrue(coordinator.cancel_run(thread_id, "run-cancel"))
        error_event = next(stream)
        self.assertIsInstance(error_event, ErrorStreamEvent)
        self.assertEqual(error_event.error_type, "RunCancelledError")
        with self.assertRaises(RunCancelledError):
            next(stream)

        finished = [
            event for event in self.event_log.iter_events(thread_id)
            if event["event_type"] == "turn_finished"
        ]
        self.assertEqual(finished[-1]["payload"]["status"], "error")

    def test_runs_turns_and_writes_jsonl_checkpoint_and_history(self) -> None:
        image_path = self.root / "tiny.png"
        image_path.write_bytes(b"tiny-image")
        thread_id = self.coordinator.create_thread(
            user_id="user-1",
            workspace_path=str(self.workspace),
        )

        first = self.coordinator.run_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="inspect",
            images=[ImageInput(str(image_path))],
        )
        attachment_id = first.state["prepare"]["selected_attachment_ids"][0]
        second = self.coordinator.run_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="inspect again",
            referenced_attachment_ids=[attachment_id],
        )

        self.assertEqual((first.turn_number, second.turn_number), (1, 2))
        events = list(self.event_log.iter_events(thread_id))
        self.assertEqual(
            [event["sequence"] for event in events],
            list(range(1, len(events) + 1)),
        )
        attachment_event = next(
            event for event in events if event["event_type"] == "attachment_added"
        )
        self.assertTrue(attachment_event["payload"]["base64_data"])
        self.assertNotIn(
            "base64_data",
            self.graph.states[thread_id]["attachments"][attachment_id],
        )
        turns = self.history.connection.execute(
            "SELECT turn_number, status FROM turns ORDER BY turn_number"
        ).fetchall()
        self.assertEqual(
            [(row["turn_number"], row["status"]) for row in turns],
            [(1, "success"), (2, "success")],
        )
        self.assertEqual(second.finalization["message"]["content"], "done")
        self.assertEqual(second.execution_summary["model"]["calls"], 0)
        self.assertGreaterEqual(second.execution_summary["duration_ms"], 0)

    def test_aggregates_model_tool_token_and_approval_statistics(self) -> None:
        finalization = {
            "status": "completed",
            "message": {
                "message_id": "final-1",
                "role": "assistant",
                "content": "done",
            },
            "tools": {
                "total": 3,
                "succeeded": 1,
                "failed": 1,
                "denied": 1,
                "rounds": 2,
                "limit_reached": False,
            },
            "artifact_ids": [],
        }
        events = [
            {
                "turn_number": 2,
                "event_type": "model_result",
                "payload": {
                    "status": "success",
                    "duration_ms": 100,
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 4,
                        "total_tokens": 14,
                    },
                },
            },
            {
                "turn_number": 2,
                "event_type": "model_result",
                "payload": {
                    "status": "success",
                    "duration_ms": 80,
                    "usage": {
                        "prompt_tokens": 6,
                        "completion_tokens": 2,
                        "total_tokens": 8,
                    },
                },
            },
            {
                "turn_number": 2,
                "event_type": "tool_result",
                "payload": {"status": "success", "duration_ms": 12},
            },
            {
                "turn_number": 2,
                "event_type": "tool_result",
                "payload": {"status": "error", "duration_ms": 5},
            },
            {
                "turn_number": 2,
                "event_type": "approval_requested",
                "payload": {},
            },
            {
                "turn_number": 2,
                "event_type": "approval_decided",
                "payload": {"decision": "deny"},
            },
            {
                "turn_number": 2,
                "event_type": "turn_finished",
                "payload": {"status": "success", "duration_ms": 250},
            },
        ]

        summary = _turn_execution_summary(events, 2, finalization)

        self.assertEqual(summary["duration_ms"], 250)
        self.assertEqual(
            summary["model"],
            {
                "calls": 2,
                "succeeded": 2,
                "failed": 0,
                "duration_ms": 180,
                "input_tokens": 16,
                "output_tokens": 6,
                "total_tokens": 22,
            },
        )
        self.assertEqual(summary["tools"]["duration_ms"], 17)
        self.assertEqual(
            summary["approvals"],
            {"requested": 1, "allowed": 0, "denied": 1},
        )

    def test_streams_status_model_chunks_and_final_result_without_persisting_chunks(self) -> None:
        graph = StreamingFakeGraph()
        coordinator = ConversationCoordinator(
            graph=graph,
            history_service=self.history,
            event_log_service=self.event_log,
        )
        thread_id = coordinator.create_thread(
            user_id="user-1",
            workspace_path=str(self.workspace),
        )

        streamed = list(coordinator.stream_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="hello",
        ))

        self.assertIsInstance(streamed[0], StatusStreamEvent)
        self.assertEqual(
            [event.chunk.content for event in streamed if isinstance(event, ModelChunkEvent)],
            ["do", "ne"],
        )
        self.assertIsInstance(streamed[-1], TurnResultStreamEvent)
        self.assertEqual(streamed[-1].result.status, "completed")
        events = list(self.event_log.iter_events(thread_id))
        self.assertEqual(
            [event["event_type"] for event in events].count("message"),
            2,
        )
        serialized = str(events)
        self.assertNotIn("正在请求模型", serialized)
        self.assertNotIn("langgraph_node", serialized)

    def test_streams_each_approval_resume_with_distinct_run_ids(self) -> None:
        graph = InterruptingFakeGraph()
        coordinator = ConversationCoordinator(
            graph=graph,
            history_service=self.history,
            event_log_service=self.event_log,
        )
        thread_id = coordinator.create_thread(
            user_id="user-1",
            workspace_path=str(self.workspace),
        )

        first = list(coordinator.stream_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="modify files",
        ))
        second = list(coordinator.stream_resume_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            approval_id="approval-1",
            tool_call_id="call-1",
            decision="allow",
        ))
        final = list(coordinator.stream_resume_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            approval_id="approval-2",
            tool_call_id="call-2",
            decision="deny",
        ))

        self.assertIsInstance(first[-1], ApprovalStreamEvent)
        self.assertIsInstance(second[-1], ApprovalStreamEvent)
        self.assertIsInstance(final[-1], TurnResultStreamEvent)
        self.assertEqual(first[-1].result.turn_number, final[-1].result.turn_number)
        self.assertEqual(len(set(graph.run_ids)), 3)
        events = list(self.event_log.iter_events(thread_id))
        self.assertEqual(
            [event["event_type"] for event in events].count("turn_finished"),
            1,
        )

    def test_stream_emits_structured_error_then_preserves_exception(self) -> None:
        coordinator = ConversationCoordinator(
            graph=FailingStreamingGraph(),
            history_service=self.history,
            event_log_service=self.event_log,
        )
        thread_id = coordinator.create_thread(
            user_id="user-1",
            workspace_path=str(self.workspace),
        )
        stream = coordinator.stream_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="hello",
        )

        self.assertIsInstance(next(stream), StatusStreamEvent)
        error = next(stream)
        self.assertIsInstance(error, ErrorStreamEvent)
        self.assertEqual(error.error_type, "RuntimeError")
        with self.assertRaisesRegex(RuntimeError, "stream failed"):
            next(stream)
        events = list(self.event_log.iter_events(thread_id))
        self.assertEqual(events[-1]["payload"]["status"], "error")

    def test_restores_missing_checkpoint_before_next_turn(self) -> None:
        thread_id = self.coordinator.create_thread(
            user_id="user-1",
            workspace_path=str(self.workspace),
        )
        first = self.coordinator.run_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="first",
        )
        self.graph.states.clear()

        second = self.coordinator.run_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="second",
        )

        self.assertEqual(self.graph.restore_count, 1)
        ids = [message.id for message in second.state["messages"]]
        self.assertIn(first.input_message_id, ids)
        self.assertIn(second.input_message_id, ids)

    def test_rebuilds_compacted_state_and_keeps_attachment_metadata_light(self) -> None:
        image_path = self.root / "tiny.png"
        image_path.write_bytes(b"tiny-image")
        thread_id = self.coordinator.create_thread(
            user_id="user-1",
            workspace_path=str(self.workspace),
        )
        result = self.coordinator.run_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="inspect",
            images=[ImageInput(str(image_path))],
        )

        rebuilt = rebuild_state_from_event_log(
            thread_id,
            event_log_service=self.event_log,
        )

        self.assertEqual(
            [message.id for message in rebuilt["messages"]],
            [message.id for message in result.state["messages"]],
        )
        attachment = next(iter(rebuilt["attachments"].values()))
        self.assertNotIn("base64_data", attachment)

    def test_each_new_turn_can_select_a_different_registered_model(self) -> None:
        thread_id = self.coordinator.create_thread(
            user_id="user-1",
            workspace_path=str(self.workspace),
        )
        self.coordinator.run_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="first",
        )
        self.coordinator.run_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="second",
            provider=ModelProvider.DEEPSEEK,
            model_name="deepseek-flash",
        )

        self.assertEqual(
            [context.provider for context in self.graph.contexts],
            [ModelProvider.SILICONFLOW, ModelProvider.DEEPSEEK],
        )
        self.assertEqual(
            [context.model_name for context in self.graph.contexts],
            ["Qwen/Qwen3.5-4B", "deepseek-flash"],
        )

    def test_resumes_multiple_individual_approvals_in_the_same_turn(self) -> None:
        graph = InterruptingFakeGraph()
        coordinator = ConversationCoordinator(
            graph=graph,
            history_service=self.history,
            event_log_service=self.event_log,
        )
        thread_id = coordinator.create_thread(
            user_id="user-1",
            workspace_path=str(self.workspace),
        )

        first = coordinator.run_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="modify files",
            provider=ModelProvider.DEEPSEEK,
            model_name="deepseek-flash",
        )
        self.assertEqual(first.status, "awaiting_approval")
        self.assertEqual(first.approval_request.tool_call_id, "call-1")

        second = coordinator.resume_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            approval_id="approval-1",
            tool_call_id="call-1",
            decision="allow",
        )
        self.assertEqual(second.status, "awaiting_approval")
        self.assertEqual(second.turn_number, first.turn_number)
        self.assertEqual(second.approval_request.tool_call_id, "call-2")

        final = coordinator.resume_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            approval_id="approval-2",
            tool_call_id="call-2",
            decision="deny",
        )
        self.assertEqual(final.status, "completed")
        self.assertEqual(final.turn_number, first.turn_number)
        self.assertEqual(final.final_message_id, "message-final")
        self.assertEqual(
            final.execution_summary["approvals"],
            {"requested": 2, "allowed": 1, "denied": 1},
        )
        self.assertTrue(
            all(
                context.provider == ModelProvider.DEEPSEEK
                and context.model_name == "deepseek-flash"
                for context in graph.contexts
            )
        )

        events = list(self.event_log.iter_events(thread_id))
        started = next(
            event for event in events if event["event_type"] == "turn_started"
        )
        self.assertEqual(started["payload"]["provider"], "deepseek")
        self.assertEqual(started["payload"]["model_name"], "deepseek-flash")
        self.assertEqual(
            [event["event_type"] for event in events].count("turn_finished"),
            1,
        )
        approvals = self.history.connection.execute(
            "SELECT tool_call_id, status FROM approvals ORDER BY requested_sequence"
        ).fetchall()
        self.assertEqual(
            [(row["tool_call_id"], row["status"]) for row in approvals],
            [("call-1", "allow"), ("call-2", "deny")],
        )

    def test_rejects_stale_approval_id_before_recording_decision(self) -> None:
        graph = InterruptingFakeGraph()
        coordinator = ConversationCoordinator(
            graph=graph,
            history_service=self.history,
            event_log_service=self.event_log,
        )
        thread_id = coordinator.create_thread(
            user_id="user-1",
            workspace_path=str(self.workspace),
        )
        coordinator.run_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="modify files",
        )

        with self.assertRaisesRegex(ConversationError, "ID"):
            coordinator.resume_turn(
                thread_id=thread_id,
                user_id="user-1",
                workspace_path=str(self.workspace),
                approval_id="stale-approval",
                tool_call_id="call-1",
                decision="allow",
            )

        events = list(self.event_log.iter_events(thread_id))
        self.assertNotIn(
            "approval_decided",
            [event["event_type"] for event in events],
        )


if __name__ == "__main__":
    unittest.main()

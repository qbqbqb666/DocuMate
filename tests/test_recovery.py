import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Interrupt

from src.backend.services.conversation import ConversationCoordinator
from src.backend.services.event_log import EventLogService
from src.backend.services.history import HistoryService
from src.backend.services.recorder import RunRecorder
from src.backend.services.recovery import ConversationRecoveryService


class RecoveryGraph:
    def __init__(self) -> None:
        self.states = {}
        self.interrupts = {}
        self.restore_count = 0

    def get_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        return SimpleNamespace(
            values=self.states.get(thread_id, {}),
            interrupts=self.interrupts.get(thread_id, ()),
        )

    def update_state(self, config, state, *, as_node):
        thread_id = config["configurable"]["thread_id"]
        self.states[thread_id] = state
        self.interrupts[thread_id] = ()
        self.restore_count += 1

    def invoke(self, graph_input, config, *, context):
        thread_id = config["configurable"]["thread_id"]
        previous = self.states.get(thread_id, {})
        response = context.recorder.message_created(
            AIMessage(id=str(uuid4()), content="continued")
        )
        state = {
            "messages": [
                *previous.get("messages", []),
                *graph_input["messages"],
                response,
            ],
            "attachments": previous.get("attachments", {}),
            "artifacts": previous.get("artifacts", {}),
            "prepare": graph_input["prepare"],
        }
        self.states[thread_id] = state
        return state


class ConversationRecoveryTest(unittest.TestCase):
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
        self.graph = RecoveryGraph()

    def _create_thread(self) -> str:
        thread_id = str(uuid4())
        self.event_log.create_thread_log(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
        )
        return thread_id

    def test_repairs_interrupted_tool_turn_idempotently_and_allows_next_turn(self):
        thread_id = self._create_thread()
        recorder = RunRecorder(
            thread_id=thread_id,
            turn_number=1,
            event_log_service=self.event_log,
        )
        input_id = str(uuid4())
        recorder.turn_started(input_id)
        recorder.message_created(HumanMessage(id=input_id, content="搜索文件"))
        recorder.message_created(
            AIMessage(
                id=str(uuid4()),
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "search_text_in_files",
                        "args": {"query": "静夜思", "path": str(self.workspace)},
                    }
                ],
            )
        )
        recorder.tool_started(
            tool_call_id="call-1",
            name="search_text_in_files",
            args={"query": "静夜思", "path": str(self.workspace)},
        )
        self.history.sync_thread(thread_id)

        recovery = ConversationRecoveryService(
            graph=self.graph,
            event_log_service=self.event_log,
        )
        first = recovery.recover_thread(thread_id)
        first_count = len(list(self.event_log.iter_events(thread_id)))
        second = recovery.recover_thread(thread_id)

        self.assertEqual(first.repaired_turns, (1,))
        self.assertFalse(second.changed)
        self.assertEqual(len(list(self.event_log.iter_events(thread_id))), first_count)
        events = list(self.event_log.iter_events(thread_id))
        self.assertEqual(events[-1]["event_type"], "turn_finished")
        self.assertEqual(events[-1]["payload"]["error"]["type"], "RunInterruptedError")
        self.assertTrue(any(
            event["event_type"] == "tool_result"
            and event["payload"]["tool_call_id"] == "call-1"
            and event["payload"]["status"] == "error"
            for event in events
        ))
        self.assertTrue(any(
            event["event_type"] == "message"
            and event["payload"].get("tool_call_id") == "call-1"
            for event in events
        ))
        self.assertEqual(self.graph.restore_count, 1)

        self.history.sync_thread(thread_id)
        coordinator = ConversationCoordinator(
            graph=self.graph,
            history_service=self.history,
            event_log_service=self.event_log,
        )
        result = coordinator.run_turn(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
            content="继续",
        )
        self.assertEqual(result.turn_number, 2)

    def test_preserves_matching_pending_approval(self):
        thread_id = self._create_thread()
        recorder = RunRecorder(
            thread_id=thread_id,
            turn_number=1,
            event_log_service=self.event_log,
        )
        input_id = str(uuid4())
        recorder.turn_started(input_id)
        recorder.message_created(HumanMessage(id=input_id, content="删除文件"))
        recorder.message_created(
            AIMessage(
                id=str(uuid4()),
                content="",
                tool_calls=[
                    {"id": "call-approval", "name": "delete_file", "args": {"path": "a.txt"}}
                ],
            )
        )
        recorder.approval_requested(
            approval_id="approval-1",
            tool_call_id="call-approval",
            name="delete_file",
            args={"path": "a.txt"},
        )
        self.graph.states[thread_id] = {"messages": []}
        self.graph.interrupts[thread_id] = (
            Interrupt(
                id="approval-1",
                value={
                    "type": "tool_approval",
                    "tool_call_id": "call-approval",
                    "name": "delete_file",
                    "args": {"path": "a.txt"},
                },
            ),
        )

        recovery = ConversationRecoveryService(
            graph=self.graph,
            event_log_service=self.event_log,
        )
        result = recovery.recover_thread(thread_id)

        self.assertFalse(result.changed)
        self.assertEqual(result.preserved_approval_turn, 1)
        self.assertFalse(any(
            event["event_type"] == "turn_finished"
            for event in self.event_log.iter_events(thread_id)
        ))

    def test_stale_approval_is_denied_and_repaired(self):
        thread_id = self._create_thread()
        recorder = RunRecorder(
            thread_id=thread_id,
            turn_number=1,
            event_log_service=self.event_log,
        )
        input_id = str(uuid4())
        recorder.turn_started(input_id)
        recorder.message_created(HumanMessage(id=input_id, content="删除文件"))
        recorder.message_created(
            AIMessage(
                id=str(uuid4()),
                content="",
                tool_calls=[
                    {"id": "call-stale", "name": "delete_file", "args": {"path": "a.txt"}}
                ],
            )
        )
        recorder.approval_requested(
            approval_id="approval-stale",
            tool_call_id="call-stale",
            name="delete_file",
            args={"path": "a.txt"},
        )

        recovery = ConversationRecoveryService(
            graph=self.graph,
            event_log_service=self.event_log,
        )
        result = recovery.recover_thread(thread_id)
        events = list(self.event_log.iter_events(thread_id))

        self.assertTrue(result.changed)
        self.assertTrue(any(
            event["event_type"] == "approval_decided"
            and event["payload"]["decision"] == "deny"
            for event in events
        ))
        self.assertEqual(events[-1]["event_type"], "turn_finished")


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command

from src.backend.agent.context import AgentContext, PermissionMode
from src.backend.agent.nodes import (
    MAX_TOOL_ROUNDS,
    approval_node,
    model_node,
    route_after_approval,
    route_after_model,
    tool_node,
)
from src.backend.agent.state import AgentState


def build_approval_graph(*, execute_tools: bool = False):
    builder = StateGraph(AgentState, context_schema=AgentContext)
    builder.add_node("approval", approval_node)
    builder.add_edge(START, "approval")
    if execute_tools:
        builder.add_node("tools", tool_node)
        builder.add_edge("approval", "tools")
        builder.add_edge("tools", END)
    else:
        builder.add_edge("approval", END)
    return builder.compile(checkpointer=InMemorySaver())


def make_state(tool_calls: list[dict]) -> AgentState:
    return {
        "messages": [
            AIMessage(
                id="assistant-1",
                content="",
                tool_calls=tool_calls,
            )
        ],
        "attachments": {},
        "artifacts": {},
        "prepare": None,
        "tool_execution_plan": None,
    }


class ApprovalNodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.workspace = Path(self.temporary_directory.name)
        self.config = {"configurable": {"thread_id": "thread-1"}}

    def context(self, permission: PermissionMode) -> AgentContext:
        return AgentContext(
            user_id="user-1",
            workspace_path=str(self.workspace),
            permission=permission,
        )

    def test_mutating_tools_interrupt_individually_in_original_order(self) -> None:
        graph = build_approval_graph()
        state = make_state([
            {
                "id": "read-1",
                "name": "read_text_file",
                "args": {"relative_path": "notes.md"},
            },
            {
                "id": "write-1",
                "name": "write_text_file",
                "args": {"relative_path": "new.md", "content": "new"},
            },
            {
                "id": "info-1",
                "name": "get_workspace_file_info",
                "args": {"relative_path": "notes.md"},
            },
            {
                "id": "delete-1",
                "name": "delete_file",
                "args": {"relative_path": "old.md"},
            },
        ])
        context = self.context(PermissionMode.REQUEST_APPROVAL)

        first = graph.invoke(state, self.config, context=context)
        self.assertEqual(first["__interrupt__"][0].value["tool_call_id"], "write-1")

        second = graph.invoke(
            Command(resume={"tool_call_id": "write-1", "decision": "allow"}),
            self.config,
            context=context,
        )
        self.assertEqual(second["__interrupt__"][0].value["tool_call_id"], "delete-1")

        final = graph.invoke(
            Command(resume={"tool_call_id": "delete-1", "decision": "deny"}),
            self.config,
            context=context,
        )
        self.assertEqual(
            final["tool_execution_plan"]["decisions"],
            {
                "read-1": "execute",
                "write-1": "execute",
                "info-1": "execute",
                "delete-1": "deny",
            },
        )

    def test_external_path_approval_grants_only_the_resolved_target(self) -> None:
        graph = build_approval_graph(execute_tools=True)
        destination = self.workspace.parent / "approved-outside.txt"
        state = make_state([
            {
                "id": "write-external",
                "name": "write_text_file",
                "args": {
                    "relative_path": str(destination),
                    "content": "approved",
                },
            }
        ])
        context = self.context(PermissionMode.REQUEST_APPROVAL)

        pending = graph.invoke(state, self.config, context=context)
        request = pending["__interrupt__"][0].value
        self.assertEqual(request["reason"], "external_path")
        self.assertEqual(request["paths"], [
            {
                "argument": "relative_path",
                "path": str(destination.resolve()),
                "access": "write",
            }
        ])

        final = graph.invoke(
            Command(resume={"tool_call_id": "write-external", "decision": "allow"}),
            self.config,
            context=context,
        )
        self.assertEqual(destination.read_text(encoding="utf-8"), "approved")
        self.assertIsNone(final["tool_execution_plan"])
        destination.unlink()

    def test_full_access_executes_external_path_without_interrupt(self) -> None:
        graph = build_approval_graph(execute_tools=True)
        destination = self.workspace.parent / "full-access-outside.txt"
        state = make_state([
            {
                "id": "write-full-access",
                "name": "write_text_file",
                "args": {
                    "relative_path": str(destination),
                    "content": "direct",
                },
            }
        ])

        final = graph.invoke(
            state,
            self.config,
            context=self.context(PermissionMode.FULL_ACCESS),
        )

        self.assertNotIn("__interrupt__", final)
        self.assertEqual(destination.read_text(encoding="utf-8"), "direct")
        destination.unlink()

    def test_full_access_builds_plan_without_interrupt(self) -> None:
        graph = build_approval_graph()
        result = graph.invoke(
            make_state([
                {
                    "id": "write-1",
                    "name": "write_text_file",
                    "args": {"relative_path": "new.md", "content": "new"},
                }
            ]),
            self.config,
            context=self.context(PermissionMode.FULL_ACCESS),
        )

        self.assertNotIn("__interrupt__", result)
        self.assertEqual(
            result["tool_execution_plan"]["decisions"],
            {"write-1": "execute"},
        )

    def test_document_calls_are_approved_before_document_routing(self) -> None:
        document_state = make_state([
            {
                "id": "document-1",
                "name": "create_docx",
                "args": {"relative_path": "report.docx", "paragraphs": ["body"]},
            }
        ])
        self.assertEqual(route_after_model(document_state), "approval")

        update = approval_node(
            document_state,
            Runtime(context=self.context(PermissionMode.FULL_ACCESS)),
        )
        document_state["tool_execution_plan"] = update["tool_execution_plan"]
        self.assertEqual(route_after_approval(document_state), "document")

        ordinary_state = make_state([
            {
                "id": "ordinary-1",
                "name": "read_text_file",
                "args": {"relative_path": "notes.md"},
            }
        ])
        update = approval_node(
            ordinary_state,
            Runtime(context=self.context(PermissionMode.FULL_ACCESS)),
        )
        ordinary_state["tool_execution_plan"] = update["tool_execution_plan"]
        self.assertEqual(route_after_approval(ordinary_state), "tools")

    def test_approval_status_stream_is_structured_and_hides_arguments(self) -> None:
        graph = build_approval_graph()
        events = list(graph.stream(
            make_state([
                {
                    "id": "write-1",
                    "name": "write_text_file",
                    "args": {"relative_path": "secret.md", "content": "hidden"},
                }
            ]),
            self.config,
            context=self.context(PermissionMode.REQUEST_APPROVAL),
            stream_mode=["custom", "values"],
        ))

        statuses = [data for mode, data in events if mode == "custom"]
        self.assertEqual(
            [status["message"] for status in statuses],
            ["正在检查工具权限", "正在等待批准"],
        )
        self.assertEqual(statuses[-1]["tool_call_id"], "write-1")
        self.assertEqual(statuses[-1]["tool_name"], "write_text_file")
        self.assertNotIn("args", statuses[-1])

    def test_tool_node_executes_and_denies_in_original_order(self) -> None:
        existing = self.workspace / "existing.md"
        existing.write_text("existing", encoding="utf-8")
        graph = build_approval_graph(execute_tools=True)
        state = make_state([
            {
                "id": "write-1",
                "name": "write_text_file",
                "args": {"relative_path": "denied.md", "content": "denied"},
            },
            {
                "id": "read-1",
                "name": "read_text_file",
                "args": {"relative_path": "existing.md"},
            },
        ])
        context = self.context(PermissionMode.REQUEST_APPROVAL)

        pending = graph.invoke(state, self.config, context=context)
        result = graph.invoke(
            Command(resume={"tool_call_id": "write-1", "decision": "deny"}),
            self.config,
            context=context,
        )

        self.assertEqual(
            pending["__interrupt__"][0].value["tool_call_id"],
            "write-1",
        )
        tool_messages = [
            message for message in result["messages"]
            if isinstance(message, ToolMessage)
        ]
        self.assertEqual(
            [message.tool_call_id for message in tool_messages],
            ["write-1", "read-1"],
        )
        self.assertEqual(json.loads(tool_messages[0].content)["status"], "denied")
        self.assertEqual(
            json.loads(tool_messages[1].content)["data"]["content"],
            "existing",
        )
        self.assertFalse((self.workspace / "denied.md").exists())
        self.assertIsNone(result["tool_execution_plan"])

    def test_tool_failure_returns_error_and_does_not_stop_later_calls(self) -> None:
        (self.workspace / "existing.md").write_text("existing", encoding="utf-8")
        graph = build_approval_graph(execute_tools=True)

        result = graph.invoke(
            make_state([
                {
                    "id": "missing-1",
                    "name": "read_text_file",
                    "args": {"relative_path": "missing.md"},
                },
                {
                    "id": "existing-1",
                    "name": "read_text_file",
                    "args": {"relative_path": "existing.md"},
                },
            ]),
            self.config,
            context=self.context(PermissionMode.FULL_ACCESS),
        )

        tool_messages = [
            message for message in result["messages"]
            if isinstance(message, ToolMessage)
        ]
        failed = json.loads(tool_messages[0].content)
        succeeded = json.loads(tool_messages[1].content)
        self.assertEqual([failed["status"], succeeded["status"]], ["error", "success"])
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["error"]["code"], "invalid_operation")
        self.assertEqual(succeeded["data"]["content"], "existing")

    def test_tool_progress_reports_real_results_in_order(self) -> None:
        (self.workspace / "existing.md").write_text("actual content", encoding="utf-8")
        graph = build_approval_graph(execute_tools=True)
        state = make_state([
            {"id": "missing", "name": "read_text_file", "args": {"relative_path": "missing.md"}},
            {"id": "read", "name": "read_text_file", "args": {"relative_path": "existing.md"}},
            {"id": "write", "name": "write_text_file", "args": {"relative_path": "new.md", "content": "generated"}},
        ])
        events = list(graph.stream(state, self.config, context=self.context(PermissionMode.FULL_ACCESS), stream_mode="custom"))
        tools = [event for event in events if event["type"] == "tool"]
        self.assertEqual([(event["tool_call_id"], event["status"]) for event in tools], [
            ("missing", "running"), ("missing", "error"), ("read", "running"), ("read", "success"), ("write", "running"), ("write", "success"),
        ])
        self.assertEqual(tools[3]["result"]["data"]["content"], "actual content")
        self.assertEqual((self.workspace / "new.md").read_text(), "generated")
        self.assertEqual(Path(tools[-1]["result"]["data"]["path"]), (self.workspace / "new.md").resolve())

    def test_cancel_after_file_write_preserves_effect_without_claiming_success(self) -> None:
        from src.backend.agent.nodes import _tool_executor
        from src.backend.services.cancellation import RunCancelledError

        graph = build_approval_graph(execute_tools=True)
        context = self.context(PermissionMode.FULL_ACCESS)
        invoke = _tool_executor.invoke

        def execute_then_cancel(*args, **kwargs):
            result = invoke(*args, **kwargs)
            context.cancellation.cancel()
            return result

        events = []
        with patch.object(_tool_executor, "invoke", side_effect=execute_then_cancel):
            with self.assertRaises(RunCancelledError):
                for event in graph.stream(make_state([
                    {"id": "write", "name": "write_text_file", "args": {"relative_path": "created.md", "content": "already written"}},
                ]), self.config, context=context, stream_mode="custom"):
                    events.append(event)
        self.assertEqual((self.workspace / "created.md").read_text(), "already written")
        self.assertEqual([event["status"] for event in events if event["type"] == "tool"], ["running"])

    def test_denied_tool_emits_no_running_event_or_file_change(self) -> None:
        graph = build_approval_graph(execute_tools=True)
        context = self.context(PermissionMode.REQUEST_APPROVAL)
        graph.invoke(make_state([{"id": "write", "name": "write_text_file", "args": {"relative_path": "denied.md", "content": "no"}}]), self.config, context=context)
        events = list(graph.stream(Command(resume={"tool_call_id": "write", "decision": "deny"}), self.config, context=context, stream_mode="custom"))
        tools = [event for event in events if event["type"] == "tool"]
        self.assertEqual([event["status"] for event in tools], ["denied"])
        self.assertEqual(tools[0]["result"]["error"]["code"], "approval_denied")
        self.assertFalse((self.workspace / "denied.md").exists())

    def test_repeated_failure_warns_and_round_limit_forces_final_response(self) -> None:
        graph = build_approval_graph(execute_tools=True)
        state = make_state([
            {
                "id": "missing-1",
                "name": "read_text_file",
                "args": {"relative_path": "missing.md"},
            },
            {
                "id": "missing-2",
                "name": "read_text_file",
                "args": {"relative_path": "missing.md"},
            },
        ])
        state["tool_loop"] = {
            "round_count": MAX_TOOL_ROUNDS - 1,
            "failure_counts": {},
            "force_final_response": False,
        }

        result = graph.invoke(
            state,
            self.config,
            context=self.context(PermissionMode.FULL_ACCESS),
        )

        errors = [
            json.loads(message.content)["error"]
            for message in result["messages"]
            if isinstance(message, ToolMessage)
        ]
        self.assertEqual(errors[0]["attempts"], 1)
        self.assertFalse(errors[0]["strategy_change_required"])
        self.assertEqual(errors[1]["attempts"], 2)
        self.assertTrue(errors[1]["strategy_change_required"])
        self.assertFalse(errors[1]["retryable"])
        self.assertEqual(result["tool_loop"]["round_count"], MAX_TOOL_ROUNDS)
        self.assertTrue(result["tool_loop"]["force_final_response"])

    @patch("src.backend.agent.nodes.model_resolver.resolve")
    def test_round_limit_uses_unbound_model_and_removes_tool_calls(
        self,
        resolve,
    ) -> None:
        raw_model = MagicMock()
        raw_model.stream.return_value = [AIMessageChunk(
            id="final-1",
            content="无法继续执行。",
            tool_calls=[{
                "id": "unexpected",
                "name": "read_text_file",
                "args": {"relative_path": "again.md"},
            }],
        )]
        bound_model = MagicMock()
        resolve.return_value = SimpleNamespace(
            provider=SimpleNamespace(value="test"),
            model_name="test-model",
            model=raw_model,
            model_with_tools=bound_model,
        )
        state = {
            "messages": [HumanMessage(id="user-1", content="continue")],
            "attachments": {},
            "artifacts": {},
            "prepare": None,
            "tool_execution_plan": None,
            "tool_loop": {
                "round_count": MAX_TOOL_ROUNDS,
                "failure_counts": {},
                "force_final_response": True,
            },
        }

        update = model_node(
            state,
            {},
            Runtime(context=self.context(PermissionMode.FULL_ACCESS)),
        )
        completed = {**state, "messages": update["messages"]}

        raw_model.stream.assert_called_once()
        bound_model.invoke.assert_not_called()
        self.assertEqual(update["messages"][0].tool_calls, [])
        self.assertEqual(route_after_model(completed), "finalize")

    @patch("src.backend.agent.nodes.model_resolver.resolve")
    def test_empty_model_response_is_reported_as_an_error(self, resolve) -> None:
        bound_model = MagicMock()
        bound_model.invoke.return_value = AIMessage(id="empty-1", content="")
        resolve.return_value = SimpleNamespace(
            provider=SimpleNamespace(value="test"),
            model_name="test-model",
            model=MagicMock(),
            model_with_tools=bound_model,
        )
        state = {
            "messages": [HumanMessage(id="user-1", content="continue")],
            "attachments": {},
            "artifacts": {},
            "prepare": None,
            "tool_execution_plan": None,
            "tool_loop": {"force_final_response": False},
        }

        with self.assertRaisesRegex(RuntimeError, "模型返回了空响应"):
            model_node(
                state,
                {},
                Runtime(context=self.context(PermissionMode.FULL_ACCESS)),
            )


if __name__ == "__main__":
    unittest.main()

import unittest

from langchain_core.messages import AIMessage, HumanMessage

from src.backend.agent.nodes import finalize_node


class FinalizeNodeTest(unittest.TestCase):
    @staticmethod
    def state():
        return {
            "messages": [
                HumanMessage(id="user-1", content="create report"),
                AIMessage(id="assistant-final", content="report created"),
            ],
            "attachments": {},
            "artifacts": {
                "artifact-current": {
                    "artifact_id": "artifact-current",
                    "name": "report.md",
                    "mime_type": "text/markdown",
                    "url": "report.md",
                    "operation": "created",
                    "tool_call_id": "call-current",
                },
                "artifact-old": {
                    "artifact_id": "artifact-old",
                    "name": "old.md",
                    "mime_type": "text/markdown",
                    "url": "old.md",
                    "operation": "created",
                    "tool_call_id": "call-old",
                },
            },
            "prepare": {
                "turn_number": 2,
                "input_message_id": "user-1",
                "selected_attachment_ids": [],
            },
            "tool_execution_plan": None,
            "tool_loop": {
                "round_count": 2,
                "failure_counts": {},
                "force_final_response": False,
                "total_calls": 3,
                "succeeded_calls": 1,
                "failed_calls": 1,
                "denied_calls": 1,
                "tool_call_ids": ["call-current", "call-failed", "call-denied"],
            },
            "finalization": None,
        }

    def test_builds_finalization_from_final_message_tools_and_artifacts(self) -> None:
        update = finalize_node(self.state())

        finalization = update["finalization"]
        self.assertEqual(
            finalization["message"],
            {
                "message_id": "assistant-final",
                "role": "assistant",
                "content": "report created",
            },
        )
        self.assertEqual(
            finalization["tools"],
            {
                "total": 3,
                "succeeded": 1,
                "failed": 1,
                "denied": 1,
                "rounds": 2,
                "limit_reached": False,
            },
        )
        self.assertEqual(finalization["artifact_ids"], ["artifact-current"])

    def test_rejects_unfinished_tool_state(self) -> None:
        active_plan = self.state()
        active_plan["tool_execution_plan"] = {
            "source_message_id": "assistant-final",
            "decisions": {},
        }
        with self.assertRaisesRegex(ValueError, "工具执行计划"):
            finalize_node(active_plan)

        tool_request = self.state()
        tool_request["messages"][-1] = AIMessage(
            id="assistant-tool",
            content="",
            tool_calls=[{
                "id": "call-new",
                "name": "read_text_file",
                "args": {"relative_path": "report.md"},
            }],
        )
        with self.assertRaisesRegex(ValueError, "未处理的工具调用"):
            finalize_node(tool_request)

    def test_serializes_block_content_without_changing_message(self) -> None:
        state = self.state()
        state["messages"][-1] = AIMessage(
            id="assistant-final",
            content=[{"type": "text", "text": "done"}],
        )

        update = finalize_node(state)

        self.assertEqual(
            update["finalization"]["message"]["content"],
            '[{"type":"text","text":"done"}]',
        )
        self.assertIsInstance(state["messages"][-1].content, list)


if __name__ == "__main__":
    unittest.main()

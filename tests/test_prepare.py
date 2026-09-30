import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command

from src.backend.agent.context import AgentContext, build_model_context
from src.backend.agent.nodes import approval_node, prepare_node
from src.backend.agent.state import AgentState
from src.backend.agent.prompts import PROMPT_FILE_MAX_BYTES, load_prompt_file


class PrepareNodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.global_prompt_path = self.root / "global" / "DocuMate.md"

    def runtime(self, statuses: list[dict] | None = None) -> Runtime[AgentContext]:
        return Runtime(
            context=AgentContext(
                user_id="user-1",
                workspace_path=str(self.workspace),
                global_prompt_path=str(self.global_prompt_path),
            ),
            stream_writer=(statuses.append if statuses is not None else lambda _: None),
        )

    @staticmethod
    def state(*, attachments: dict | None = None, prepare: dict | None = None):
        return {
            "messages": [HumanMessage(id="message-1", content="处理文档")],
            "attachments": attachments or {},
            "artifacts": {},
            "prepare": prepare if prepare is not None else {
                "turn_number": 1,
                "input_message_id": "message-1",
                "selected_attachment_ids": [],
            },
            "tool_execution_plan": None,
        }

    def write_workspace_prompt(self, content: str) -> Path:
        path = self.workspace / ".documate" / "DocuMate.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_builds_prompt_in_fixed_order_and_records_sources(self) -> None:
        self.global_prompt_path.parent.mkdir()
        global_content = "全局偏好：简洁中文"
        workspace_content = "工作区要求：运行测试"
        self.global_prompt_path.write_text(global_content, encoding="utf-8")
        workspace_prompt_path = self.write_workspace_prompt(workspace_content)
        state = self.state()
        original_messages = copy.deepcopy(state["messages"])
        statuses: list[dict] = []

        update = prepare_node(state, self.runtime(statuses))

        prepared = update["prepare"]
        prompt = prepared["instructions"]["system_prompt"]
        self.assertLess(prompt.index("[DocuMate 核心规则]"), prompt.index("[当前运行环境]"))
        self.assertLess(prompt.index("[当前运行环境]"), prompt.index("[用户全局说明]"))
        self.assertLess(prompt.index("[用户全局说明]"), prompt.index("[工作区说明]"))
        self.assertIn(global_content, prompt)
        self.assertIn(workspace_content, prompt)
        self.assertEqual(prepared["workspace_path"], str(self.workspace.resolve()))
        self.assertEqual(
            prepared["instructions"]["global_source"],
            {
                "path": str(self.global_prompt_path.resolve()),
                "sha256": hashlib.sha256(global_content.encode()).hexdigest(),
            },
        )
        self.assertEqual(
            prepared["instructions"]["workspace_source"]["path"],
            str(workspace_prompt_path.resolve()),
        )
        self.assertEqual(state["messages"], original_messages)
        self.assertEqual([event["message"] for event in statuses], ["正在准备模型上下文"])
        self.assertNotIn(global_content, repr(statuses))
        self.assertNotIn(workspace_content, repr(statuses))

    def test_missing_files_are_skipped_and_empty_file_has_no_section(self) -> None:
        self.global_prompt_path.parent.mkdir()
        self.global_prompt_path.write_text("", encoding="utf-8")

        update = prepare_node(self.state(), self.runtime())

        instructions = update["prepare"]["instructions"]
        self.assertNotIn("[用户全局说明]", instructions["system_prompt"])
        self.assertNotIn("[工作区说明]", instructions["system_prompt"])
        self.assertIsNotNone(instructions["global_source"])
        self.assertIsNone(instructions["workspace_source"])

    def test_rejects_missing_workspace_and_non_directory_workspace(self) -> None:
        self.workspace.rmdir()
        with self.assertRaisesRegex(ValueError, "工作区不存在"):
            prepare_node(self.state(), self.runtime())

        self.workspace.write_text("not a directory", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "工作区不是文件夹"):
            prepare_node(self.state(), self.runtime())

    def test_validates_turn_identity_and_selected_attachments(self) -> None:
        missing_prepare = self.state()
        missing_prepare["prepare"] = None
        with self.assertRaisesRegex(ValueError, "缺少 prepare"):
            prepare_node(missing_prepare, self.runtime())

        invalid_message = self.state()
        invalid_message["prepare"]["input_message_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "找不到本轮输入消息"):
            prepare_node(invalid_message, self.runtime())

        missing_attachment = self.state()
        missing_attachment["prepare"]["selected_attachment_ids"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "State 中找不到附件"):
            prepare_node(missing_attachment, self.runtime())

        non_image = self.state(
            attachments={
                "attachment-1": {
                    "attachment_id": "attachment-1",
                    "message_id": "message-1",
                    "name": "notes.txt",
                    "mime_type": "text/plain",
                    "url": "/tmp/notes.txt",
                    "size": 10,
                }
            }
        )
        non_image["prepare"]["selected_attachment_ids"] = ["attachment-1"]
        with self.assertRaisesRegex(ValueError, "不是图片"):
            prepare_node(non_image, self.runtime())

    def test_prepare_does_not_load_attachment_bytes(self) -> None:
        image_path = self.root / "image.png"
        image_path.write_bytes(b"image-data")
        state = self.state(
            attachments={
                "attachment-1": {
                    "attachment_id": "attachment-1",
                    "message_id": "message-1",
                    "name": "image.png",
                    "mime_type": "image/png",
                    "url": str(image_path),
                    "size": 10,
                }
            }
        )
        state["prepare"]["selected_attachment_ids"] = ["attachment-1"]

        update = prepare_node(state, self.runtime())

        self.assertNotIn("base64", repr(update))
        self.assertNotIn("image-data", repr(update))

    def test_turn_snapshot_stays_on_a_until_next_prepare(self) -> None:
        prompt_path = self.write_workspace_prompt("版本 A")
        base_state = self.state()
        first = prepare_node(base_state, self.runtime())["prepare"]
        prepared_state = {**base_state, "prepare": first}

        prompt_path.write_text("版本 B", encoding="utf-8")
        same_turn_messages = build_model_context(prepared_state, self.runtime())
        next_turn = prepare_node(base_state, self.runtime())["prepare"]

        self.assertIn("版本 A", same_turn_messages[0].content)
        self.assertNotIn("版本 B", same_turn_messages[0].content)
        self.assertIn("版本 B", next_turn["instructions"]["system_prompt"])

    def test_approval_resume_keeps_prompt_snapshot_from_before_interrupt(self) -> None:
        prompt_path = self.write_workspace_prompt("审批前版本 A")
        observed_prompts: list[str] = []

        def request_tool(state):
            return {
                "messages": [
                    AIMessage(
                        id="assistant-tool",
                        content="",
                        tool_calls=[{
                            "id": "call-1",
                            "name": "write_text_file",
                            "args": {
                                "relative_path": "result.md",
                                "content": "result",
                            },
                        }],
                    )
                ]
            }

        def capture_prompt(state, runtime):
            observed_prompts.append(build_model_context(state, runtime)[0].content)
            return {}

        builder = StateGraph(AgentState, context_schema=AgentContext)
        builder.add_node("prepare", prepare_node)
        builder.add_node("request_tool", request_tool)
        builder.add_node("approval", approval_node)
        builder.add_node("capture_prompt", capture_prompt)
        builder.add_edge(START, "prepare")
        builder.add_edge("prepare", "request_tool")
        builder.add_edge("request_tool", "approval")
        builder.add_edge("approval", "capture_prompt")
        builder.add_edge("capture_prompt", END)
        graph = builder.compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "snapshot-thread"}}
        context = self.runtime().context

        pending = graph.invoke(self.state(), config, context=context)
        prompt_path.write_text("审批后版本 B", encoding="utf-8")
        graph.invoke(
            Command(
                resume={"tool_call_id": "call-1", "decision": "allow"}
            ),
            config,
            context=context,
        )

        self.assertEqual(
            pending["prepare"]["instructions"]["workspace_source"]["sha256"],
            hashlib.sha256("审批前版本 A".encode()).hexdigest(),
        )
        self.assertEqual(len(observed_prompts), 1)
        self.assertIn("审批前版本 A", observed_prompts[0])
        self.assertNotIn("审批后版本 B", observed_prompts[0])


class PromptFileValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_rejects_directory_non_utf8_and_oversized_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "不是普通文件"):
            load_prompt_file(self.root)

        invalid_utf8 = self.root / "invalid.md"
        invalid_utf8.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            load_prompt_file(invalid_utf8)

        oversized = self.root / "oversized.md"
        oversized.write_bytes(b"x" * (PROMPT_FILE_MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "超过"):
            load_prompt_file(oversized)

    def test_missing_file_is_optional(self) -> None:
        self.assertIsNone(load_prompt_file(self.root / "missing.md"))


if __name__ == "__main__":
    unittest.main()

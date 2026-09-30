import base64
import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
)
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime

from src.backend.agent.context import (
    AgentContext,
    SUMMARY_KEEP_FRACTION,
    SUMMARY_TRIGGER_FRACTION,
    TOOL_MESSAGE_MAX_CHARS,
    build_model_context,
    create_summarization_middleware,
    summarize_state_messages,
)
from src.backend.agent.state import AgentState
from src.backend.services.event_log import EventLogService, EventType
from src.backend.services.llm import (
    create_deepseek_model,
    create_siliconflow_model,
)
from src.backend.services.recorder import RunRecorder
from src.backend.services.state_rebuilder import rebuild_state_from_event_log


class ContextSummarizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = cast(Runtime[AgentContext], None)

    @staticmethod
    def make_state(messages: list) -> AgentState:
        return {
            "messages": messages,
            "attachments": {},
            "artifacts": {},
            "prepare": None,
        }

    def test_summarizer_uses_model_profile_fractions(self) -> None:
        middleware = create_summarization_middleware(
            FakeListChatModel(
                responses=["unused"],
                profile={"max_input_tokens": 100_000},
            )
        )

        self.assertEqual(
            middleware.trigger,
            ("fraction", SUMMARY_TRIGGER_FRACTION),
        )
        self.assertEqual(
            middleware.keep,
            ("fraction", SUMMARY_KEEP_FRACTION),
        )
        self.assertEqual(middleware.model.profile["max_input_tokens"], 100_000)
        self.assertIsNone(middleware.trim_tokens_to_summarize)

    def test_summarizer_rejects_model_without_context_profile(self) -> None:
        with self.assertRaisesRegex(ValueError, "Model profile information"):
            create_summarization_middleware(
                FakeListChatModel(responses=["unused"])
            )

    @patch("src.backend.services.llm.init_chat_model")
    @patch.dict(
        "os.environ",
        {
            "SILICONFLOW_API_KEY": "test-key",
            "SILICONFLOW_BASE_URL": "https://example.invalid/v1",
        },
    )
    def test_siliconflow_factory_attaches_model_context_profile(
        self,
        init_chat_model,
    ) -> None:
        create_siliconflow_model()

        self.assertEqual(
            init_chat_model.call_args.kwargs["profile"],
            {"max_input_tokens": 262_144},
        )
        self.assertEqual(
            init_chat_model.call_args.kwargs["extra_body"],
            {"enable_thinking": False},
        )

    @patch("src.backend.services.llm.init_chat_model")
    @patch.dict(
        "os.environ",
        {
            "SILICONFLOW_API_KEY": "test-key",
            "SILICONFLOW_BASE_URL": "https://example.invalid/v1",
        },
    )
    def test_siliconflow_factory_accepts_other_model_context_limit(
        self,
        init_chat_model,
    ) -> None:
        create_siliconflow_model(
            "provider/another-model",
            max_input_tokens=131_072,
        )

        self.assertEqual(
            init_chat_model.call_args.kwargs["profile"],
            {"max_input_tokens": 131_072},
        )

    @patch("src.backend.services.llm.init_chat_model")
    @patch.dict(
        "os.environ",
        {
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_BASE_URL": "https://example.invalid/v1",
        },
    )
    def test_deepseek_factory_attaches_registered_context_profile(
        self,
        init_chat_model,
    ) -> None:
        create_deepseek_model("deepseek-flash")

        self.assertEqual(
            init_chat_model.call_args.kwargs["profile"],
            {"max_input_tokens": 1_048_576},
        )

    def test_below_threshold_does_not_update_state(self) -> None:
        middleware = SummarizationMiddleware(
            model=FakeListChatModel(responses=["unused"]),
            trigger=("messages", 10),
            keep=("messages", 2),
        )
        state = self.make_state([HumanMessage(id="user-1", content="hello")])

        update = summarize_state_messages(state, self.runtime, middleware)

        self.assertEqual(update, {})
        self.assertEqual(len(state["messages"]), 1)

    def test_replaces_old_messages_with_summary_and_keeps_recent_messages(self) -> None:
        middleware = SummarizationMiddleware(
            model=FakeListChatModel(responses=["Earlier decisions and results."]),
            trigger=("messages", 5),
            keep=("messages", 2),
        )
        messages = [
            HumanMessage(id="user-1", content="first request"),
            AIMessage(id="assistant-1", content="first answer"),
            HumanMessage(id="user-2", content="second request"),
            AIMessage(id="assistant-2", content="second answer"),
            HumanMessage(id="user-3", content="latest request"),
        ]
        state = self.make_state(messages)

        update = summarize_state_messages(state, self.runtime, middleware)
        compacted = add_messages(messages, update["messages"])

        self.assertIsInstance(update["messages"][0], RemoveMessage)
        self.assertEqual(len(compacted), 3)
        self.assertIn("Earlier decisions and results.", compacted[0].content)
        self.assertEqual([message.id for message in compacted[1:]], [
            "assistant-2",
            "user-3",
        ])

    def test_does_not_split_assistant_tool_call_from_tool_result(self) -> None:
        middleware = SummarizationMiddleware(
            model=FakeListChatModel(responses=["Earlier work summary."]),
            trigger=("messages", 5),
            keep=("messages", 2),
        )
        messages = [
            HumanMessage(id="user-1", content="inspect file"),
            AIMessage(id="assistant-1", content="inspection complete"),
            HumanMessage(id="user-2", content="read another file"),
            AIMessage(
                id="assistant-2",
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "read_text_file",
                        "args": {"relative_path": "notes.md"},
                    }
                ],
            ),
            ToolMessage(id="tool-1", tool_call_id="call-1", content="contents"),
        ]
        state = self.make_state(messages)

        update = summarize_state_messages(state, self.runtime, middleware)
        compacted = add_messages(messages, update["messages"])

        retained_ids = {message.id for message in compacted[1:]}
        self.assertEqual(
            "assistant-2" in retained_ids,
            "tool-1" in retained_ids,
        )

    def test_records_compaction_and_rebuilds_the_compacted_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            thread_id = str(uuid4())
            event_log = EventLogService(root / "sessions")
            event_log.create_thread_log(
                thread_id=thread_id,
                user_id="user-1",
                workspace_path=str(root),
            )
            recorder = RunRecorder(
                thread_id=thread_id,
                turn_number=1,
                event_log_service=event_log,
            )
            recorder.turn_started("user-1")
            messages = [
                HumanMessage(id="user-1", content="first request"),
                AIMessage(id="assistant-1", content="first answer"),
                HumanMessage(id="user-2", content="second request"),
                AIMessage(id="assistant-2", content="second answer"),
                HumanMessage(id="user-3", content="latest request"),
            ]
            for message in messages:
                recorder.message_created(message)
            middleware = SummarizationMiddleware(
                model=FakeListChatModel(responses=["Earlier summary."]),
                trigger=("messages", 5),
                keep=("messages", 2),
            )
            runtime = Runtime(
                context=AgentContext(
                    user_id="user-1",
                    workspace_path=str(root),
                    recorder=recorder,
                )
            )

            update = summarize_state_messages(
                self.make_state(messages),
                runtime,
                middleware,
            )
            rebuilt = rebuild_state_from_event_log(
                thread_id,
                event_log_service=event_log,
            )

            compacted = add_messages(messages, update["messages"])
            self.assertEqual(
                [message.id for message in rebuilt["messages"]],
                [message.id for message in compacted],
            )
            self.assertEqual(
                list(event_log.iter_events(thread_id))[-1]["event_type"],
                "context_compacted",
            )


class ModelContextBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.runtime = Runtime(
            context=AgentContext(
                user_id="user-1",
                workspace_path=str(self.workspace),
            )
        )

    @staticmethod
    def make_state(
        messages: list,
        *,
        attachments: dict | None = None,
        prepare: dict | None = None,
    ) -> AgentState:
        return {
            "messages": messages,
            "attachments": attachments or {},
            "artifacts": {},
            "prepare": prepare,
        }

    def test_builds_system_context_and_truncates_only_model_view(self) -> None:
        tool_content = "x" * (TOOL_MESSAGE_MAX_CHARS + 50)
        state = self.make_state(
            [
                HumanMessage(id="user-1", content="read it"),
                ToolMessage(
                    id="tool-1",
                    tool_call_id="call-1",
                    content=tool_content,
                ),
            ]
        )
        original_state = copy.deepcopy(state)

        model_messages = build_model_context(state, self.runtime)

        self.assertIn(str(self.workspace.resolve()), model_messages[0].content)
        self.assertLess(len(model_messages[2].content), len(tool_content))
        self.assertIn("仅为本次模型调用截断", model_messages[2].content)
        self.assertEqual(state, original_state)

    def test_injects_only_selected_image_from_path_without_mutating_state(self) -> None:
        image_bytes = b"tiny-image"
        image_path = self.root / "tiny.png"
        image_path.write_bytes(image_bytes)
        state = self.make_state(
            [HumanMessage(id="message-1", content="这是什么图片？")],
            attachments={
                "attachment-1": {
                    "attachment_id": "attachment-1",
                    "message_id": "message-1",
                    "name": "tiny.png",
                    "mime_type": "image/png",
                    "url": str(image_path),
                    "size": len(image_bytes),
                },
                "attachment-old": {
                    "attachment_id": "attachment-old",
                    "message_id": "message-old",
                    "name": "old.png",
                    "mime_type": "image/png",
                    "url": str(self.root / "missing-old.png"),
                    "size": 1,
                },
            },
            prepare={
                "turn_number": 1,
                "input_message_id": "message-1",
                "selected_attachment_ids": ["attachment-1"],
            },
        )
        original_state = copy.deepcopy(state)

        model_messages = build_model_context(state, self.runtime)

        content = model_messages[1].content
        self.assertEqual(content[0], {"type": "text", "text": "这是什么图片？"})
        self.assertEqual(
            content[1],
            {
                "type": "image",
                "base64": base64.b64encode(image_bytes).decode("ascii"),
                "mime_type": "image/png",
                "id": "attachment-1",
            },
        )
        self.assertEqual(state, original_state)
        self.assertNotIn("base64", repr(state))

    def test_falls_back_to_jsonl_when_attachment_path_is_missing(self) -> None:
        thread_id = str(uuid4())
        encoded = base64.b64encode(b"recovered-image").decode("ascii")
        event_log_service = EventLogService(
            root=self.root / "sessions",
            clock=lambda: datetime(2026, 9, 15, tzinfo=timezone.utc),
        )
        event_log_service.create_thread_log(
            thread_id=thread_id,
            user_id="user-1",
            workspace_path=str(self.workspace),
        )
        event_log_service.append(
            thread_id=thread_id,
            turn_number=1,
            event_type=EventType.ATTACHMENT_ADDED,
            payload={
                "attachment_id": "attachment-1",
                "message_id": "message-1",
                "name": "missing.png",
                "mime_type": "image/png",
                "path": str(self.root / "missing.png"),
                "size": 15,
                "base64_data": encoded,
            },
        )
        state = self.make_state(
            [HumanMessage(id="message-1", content="重新查看图片")],
            attachments={
                "attachment-1": {
                    "attachment_id": "attachment-1",
                    "message_id": "message-old",
                    "name": "missing.png",
                    "mime_type": "image/png",
                    "url": str(self.root / "missing.png"),
                    "size": 15,
                }
            },
            prepare={
                "turn_number": 2,
                "input_message_id": "message-1",
                "selected_attachment_ids": ["attachment-1"],
            },
        )

        model_messages = build_model_context(
            state,
            self.runtime,
            thread_id=thread_id,
            event_log_service=event_log_service,
        )

        self.assertEqual(model_messages[1].content[1]["base64"], encoded)

    def test_does_not_load_unselected_old_attachment(self) -> None:
        state = self.make_state(
            [HumanMessage(id="message-1", content="普通问题")],
            attachments={
                "attachment-old": {
                    "attachment_id": "attachment-old",
                    "message_id": "message-old",
                    "name": "old.png",
                    "mime_type": "image/png",
                    "url": str(self.root / "missing.png"),
                    "size": 1,
                }
            },
            prepare={
                "turn_number": 2,
                "input_message_id": "message-1",
                "selected_attachment_ids": [],
            },
        )

        model_messages = build_model_context(state, self.runtime)

        self.assertEqual(model_messages[1].content, "普通问题")


if __name__ == "__main__":
    unittest.main()

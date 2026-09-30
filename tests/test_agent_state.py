import sqlite3
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from src.backend.agent.state import AgentState, merge_records


THREAD_ID = "019946f2-73a1-7c21-9dd4-c44f422ba835"


def build_graph(checkpointer: SqliteSaver):
    builder = StateGraph(AgentState)
    builder.add_node("finish", lambda state: {})
    builder.add_edge(START, "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)


class AgentStateTest(unittest.TestCase):
    def test_merge_records_updates_same_id_without_duplication(self) -> None:
        current = {
            "att-001": {
                "attachment_id": "att-001",
                "name": "old.png",
            }
        }
        updates = {
            "att-001": {
                "attachment_id": "att-001",
                "name": "new.png",
            },
            "att-002": {
                "attachment_id": "att-002",
                "name": "second.png",
            },
        }

        merged = merge_records(current, updates)

        self.assertEqual(set(merged), {"att-001", "att-002"})
        self.assertEqual(merged["att-001"]["name"], "new.png")
        self.assertEqual(current["att-001"]["name"], "old.png")

    def test_sqlite_checkpointer_restores_complete_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "checkpoint.sqlite3"
            config = {"configurable": {"thread_id": THREAD_ID}}

            first_connection = sqlite3.connect(
                database_path,
                check_same_thread=False,
            )
            first_graph = build_graph(SqliteSaver(first_connection))
            first_graph.invoke(
                {
                    "messages": [
                        HumanMessage(
                            id="msg-001",
                            content="分析图片",
                        )
                    ],
                    "attachments": {
                        "att-001": {
                            "attachment_id": "att-001",
                            "message_id": "msg-001",
                            "name": "photo.png",
                            "mime_type": "image/png",
                            "url": "/external/photo.png",
                            "size": 12345,
                        }
                    },
                    "artifacts": {
                        "artifact-001": {
                            "artifact_id": "artifact-001",
                            "name": "summary.md",
                            "mime_type": "text/markdown",
                            "url": "/workspace/summary.md",
                            "operation": "created",
                            "tool_call_id": "call-001",
                        }
                    },
                    "prepare": {
                        "turn_number": 1,
                        "input_message_id": "msg-001",
                        "selected_attachment_ids": ["att-001"],
                        "workspace_path": "/workspace",
                        "instructions": {
                            "system_prompt": "prepared prompt",
                            "global_source": {
                                "path": "/config/DocuMate.md",
                                "sha256": "global-hash",
                            },
                            "workspace_source": None,
                        },
                    },
                    "tool_execution_plan": {
                        "source_message_id": "msg-001",
                        "decisions": {"call-001": "deny"},
                    },
                    "tool_loop": {
                        "round_count": 3,
                        "failure_counts": {"failure-signature": 2},
                        "force_final_response": False,
                    },
                    "finalization": {
                        "status": "completed",
                        "message": {
                            "message_id": "msg-001",
                            "role": "assistant",
                            "content": "done",
                        },
                        "tools": {
                            "total": 0,
                            "succeeded": 0,
                            "failed": 0,
                            "denied": 0,
                            "rounds": 0,
                            "limit_reached": False,
                        },
                        "artifact_ids": [],
                    },
                },
                config=config,
            )
            first_connection.close()

            second_connection = sqlite3.connect(
                database_path,
                check_same_thread=False,
            )
            self.addCleanup(second_connection.close)
            second_graph = build_graph(SqliteSaver(second_connection))
            restored = second_graph.get_state(config).values

            self.assertEqual(restored["messages"][0].id, "msg-001")
            self.assertEqual(
                restored["attachments"]["att-001"]["url"],
                "/external/photo.png",
            )
            self.assertNotIn(
                "base64_data",
                restored["attachments"]["att-001"],
            )
            self.assertEqual(
                restored["artifacts"]["artifact-001"]["operation"],
                "created",
            )
            self.assertEqual(restored["prepare"]["turn_number"], 1)
            self.assertEqual(
                restored["prepare"]["instructions"]["system_prompt"],
                "prepared prompt",
            )
            self.assertEqual(
                restored["tool_execution_plan"]["decisions"],
                {"call-001": "deny"},
            )
            self.assertEqual(restored["tool_loop"]["round_count"], 3)
            self.assertEqual(
                restored["tool_loop"]["failure_counts"],
                {"failure-signature": 2},
            )
            self.assertEqual(
                restored["finalization"]["message"]["content"],
                "done",
            )

    def test_reducers_merge_records_and_replace_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = sqlite3.connect(
                Path(directory) / "checkpoint.sqlite3",
                check_same_thread=False,
            )
            self.addCleanup(connection.close)
            graph = build_graph(SqliteSaver(connection))
            config = {"configurable": {"thread_id": THREAD_ID}}
            graph.invoke(
                {
                    "messages": [HumanMessage(id="msg-001", content="第一轮")],
                    "attachments": {
                        "att-001": {
                            "attachment_id": "att-001",
                            "message_id": "msg-001",
                            "name": "old.png",
                            "mime_type": "image/png",
                            "url": "/external/old.png",
                            "size": 10,
                        }
                    },
                    "artifacts": {},
                    "prepare": {
                        "turn_number": 1,
                        "input_message_id": "msg-001",
                        "selected_attachment_ids": ["att-001"],
                    },
                },
                config=config,
            )

            graph.invoke(
                {
                    "messages": [AIMessage(id="msg-002", content="第二条消息")],
                    "attachments": {
                        "att-002": {
                            "attachment_id": "att-002",
                            "message_id": "msg-003",
                            "name": "new.png",
                            "mime_type": "image/png",
                            "url": "/external/new.png",
                            "size": 20,
                        }
                    },
                    "artifacts": {},
                    "prepare": {
                        "turn_number": 2,
                        "input_message_id": "msg-003",
                        "selected_attachment_ids": ["att-002"],
                    },
                },
                config=config,
            )
            restored = graph.get_state(config).values

            self.assertEqual(
                [message.id for message in restored["messages"]],
                ["msg-001", "msg-002"],
            )
            self.assertEqual(
                set(restored["attachments"]),
                {"att-001", "att-002"},
            )
            self.assertEqual(restored["prepare"]["turn_number"], 2)


if __name__ == "__main__":
    unittest.main()

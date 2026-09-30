import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from src.backend.agent.context import AgentContext, PermissionMode
from src.backend.agent.document import (
    DOCUMENT_MUTATING_TOOLS,
    DOCUMENT_READ_ONLY_TOOLS,
    DOCUMENT_TOOLS,
    convert_docx,
    convert_xlsx,
    create_docx,
    create_pdf,
    create_xlsx,
    edit_docx,
    edit_pdf_pages,
    edit_xlsx,
    extract_pdf_images,
    extract_pdf_tables,
    read_docx,
    read_pdf,
    read_xlsx,
    render_docx,
    validate_docx,
    validate_xlsx,
)
from src.backend.agent.nodes import approval_node, document_node
from src.backend.agent.state import AgentState


class DocumentToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.workspace = Path(self.temporary_directory.name)
        self.context = AgentContext(
            user_id="user-1",
            workspace_path=str(self.workspace),
            permission=PermissionMode.FULL_ACCESS,
        )
        self.runtime = SimpleNamespace(context=self.context)

    def test_document_tool_groups_match_permission_semantics(self) -> None:
        read_only = {tool.name for tool in DOCUMENT_READ_ONLY_TOOLS}
        mutating = {tool.name for tool in DOCUMENT_MUTATING_TOOLS}
        self.assertIn("read_docx", read_only)
        self.assertIn("read_pdf", read_only)
        self.assertIn("read_xlsx", read_only)
        self.assertIn("create_docx", mutating)
        self.assertIn("create_pdf", mutating)
        self.assertIn("create_xlsx", mutating)
        self.assertTrue(read_only.isdisjoint(mutating))
        self.assertEqual(
            {tool.name for tool in DOCUMENT_TOOLS},
            {
                "read_docx",
                "create_docx",
                "edit_docx",
                "convert_docx",
                "render_docx",
                "validate_docx",
                "read_pdf",
                "extract_pdf_tables",
                "extract_pdf_images",
                "create_pdf",
                "edit_pdf_pages",
                "read_xlsx",
                "create_xlsx",
                "edit_xlsx",
                "convert_xlsx",
                "validate_xlsx",
            },
        )

    def test_docx_create_read_edit_and_validate_round_trip(self) -> None:
        created = create_docx.func(
            runtime=self.runtime,
            relative_path="source.docx",
            title="测试报告",
            paragraphs=["第一段", "需要替换的内容"],
            tables=[[["名称", "数值"], ["A", "1"]]],
        )
        self.assertEqual(created["path"], "source.docx")
        self.assertTrue((self.workspace / "source.docx").exists())

        read = read_docx.func(runtime=self.runtime, relative_path="source.docx")
        self.assertIn("需要替换", read["content"])
        self.assertEqual(read["table_count"], 1)

        edited = edit_docx.func(
            runtime=self.runtime,
            relative_path="source.docx",
            output_path="edited.docx",
            replacements={"需要替换": "已替换"},
            append_paragraphs=["追加内容"],
        )
        self.assertEqual(edited["replacement_count"], 1)
        reread = read_docx.func(runtime=self.runtime, relative_path="edited.docx")
        self.assertIn("已替换", reread["content"])
        self.assertIn("追加内容", reread["content"])
        validated = validate_docx.func(
            runtime=self.runtime,
            relative_path="edited.docx",
            check_rendering=False,
        )
        self.assertTrue(validated["valid"])

    def test_pdf_create_read_and_page_edit_round_trip(self) -> None:
        created = create_pdf.func(
            runtime=self.runtime,
            relative_path="source.pdf",
            title="测试 PDF",
            paragraphs=["first page", "中文内容"],
        )
        self.assertEqual(created["path"], "source.pdf")
        read = read_pdf.func(runtime=self.runtime, relative_path="source.pdf")
        self.assertEqual(read["total_pages"], 1)
        self.assertIn("first page", read["content"])

        edited = edit_pdf_pages.func(
            runtime=self.runtime,
            source_paths=["source.pdf", "source.pdf"],
            output_path="merged.pdf",
            page_order=[2, 1],
            rotation=90,
        )
        self.assertEqual(edited["page_count"], 2)
        self.assertEqual(
            read_pdf.func(runtime=self.runtime, relative_path="merged.pdf")["total_pages"],
            2,
        )
        tables = extract_pdf_tables.func(
            runtime=self.runtime,
            relative_path="source.pdf",
        )
        self.assertEqual(tables["table_count"], 0)
        images = extract_pdf_images.func(
            runtime=self.runtime,
            relative_path="source.pdf",
            output_directory="images",
        )
        self.assertEqual(images["image_count"], 0)

    def test_xlsx_create_read_edit_and_validate_round_trip(self) -> None:
        created = create_xlsx.func(
            runtime=self.runtime,
            relative_path="source.xlsx",
            sheets={"Data": [["name", "value"], ["A", 2], ["Total", "=SUM(B2:B2)"]]},
        )
        self.assertEqual(created["sheet_names"], ["Data"])
        read = read_xlsx.func(
            runtime=self.runtime,
            relative_path="source.xlsx",
            sheet_name="Data",
        )
        self.assertEqual(read["sheets"]["Data"]["rows"][2][1], "=SUM(B2:B2)")

        edited = edit_xlsx.func(
            runtime=self.runtime,
            relative_path="source.xlsx",
            output_path="edited.xlsx",
            cell_updates={"Data": {"B2": 5}},
            add_sheets=["Notes"],
            cell_styles={"Data": {"A1": {"bold": True, "fill_color": "FFFF00"}}},
        )
        self.assertEqual(edited["updated_cells"], 1)
        reread = read_xlsx.func(
            runtime=self.runtime,
            relative_path="edited.xlsx",
            sheet_name="Data",
        )
        self.assertEqual(reread["sheets"]["Data"]["rows"][1][1], 5)
        validated = validate_xlsx.func(runtime=self.runtime, relative_path="edited.xlsx")
        self.assertTrue(validated["valid"])
        self.assertEqual(validated["formula_count"], 1)
        converted = convert_xlsx.func(
            runtime=self.runtime,
            relative_path="edited.xlsx",
            output_path="edited.csv",
        )
        self.assertEqual(converted["path"], "edited.csv")
        self.assertIn("name,value", (self.workspace / "edited.csv").read_text())

    def test_document_node_records_declared_artifact(self) -> None:
        builder = StateGraph(AgentState, context_schema=AgentContext)
        builder.add_node("approval", approval_node)
        builder.add_node("document", document_node)
        builder.add_edge(START, "approval")
        builder.add_edge("approval", "document")
        builder.add_edge("document", END)
        graph = builder.compile()
        state = {
            "messages": [
                AIMessage(
                    id="assistant-1",
                    content="",
                    tool_calls=[{
                        "id": "document-1",
                        "name": "create_xlsx",
                        "args": {
                            "relative_path": "artifact.xlsx",
                            "sheets": {"Sheet1": [["value"], [1]]},
                        },
                    }],
                )
            ],
            "attachments": {},
            "artifacts": {},
            "prepare": None,
            "tool_execution_plan": None,
            "tool_loop": None,
            "finalization": None,
        }
        result = graph.invoke(state, context=self.context)
        messages = [item for item in result["messages"] if isinstance(item, ToolMessage)]
        self.assertEqual(len(messages), 1)
        payload = json.loads(messages[0].content)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(result["artifacts"]), 1)
        artifact = next(iter(result["artifacts"].values()))
        self.assertEqual(artifact["url"], "artifact.xlsx")
        self.assertEqual(artifact["tool_call_id"], "document-1")

    @unittest.skipUnless(shutil.which("soffice"), "LibreOffice is unavailable")
    def test_docx_validation_with_real_libreoffice_rendering(self) -> None:
        create_docx.func(
            runtime=self.runtime,
            relative_path="render.docx",
            paragraphs=["用于渲染验证的文档"],
        )
        result = validate_docx.func(
            runtime=self.runtime,
            relative_path="render.docx",
            check_rendering=True,
        )
        self.assertTrue(result["rendered"])
        self.assertGreaterEqual(result["page_count"], 1)

        converted = convert_docx.func(
            runtime=self.runtime,
            relative_path="render.docx",
            output_path="render.pdf",
        )
        self.assertEqual(converted["path"], "render.pdf")

        previews = render_docx.func(
            runtime=self.runtime,
            relative_path="render.docx",
            output_directory="preview",
        )
        self.assertGreaterEqual(previews["page_count"], 1)
        self.assertTrue((self.workspace / previews["preview_paths"][0]).exists())

        create_xlsx.func(
            runtime=self.runtime,
            relative_path="render.xlsx",
            sheets={"Data": [["value"], [1]]},
        )
        xlsx_pdf = convert_xlsx.func(
            runtime=self.runtime,
            relative_path="render.xlsx",
            output_path="render-xlsx.pdf",
        )
        self.assertEqual(xlsx_pdf["path"], "render-xlsx.pdf")


if __name__ == "__main__":
    unittest.main()

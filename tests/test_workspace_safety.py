import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.backend.agent.document import _context_path
from src.backend.agent.tools import _resolve_context_path
from src.backend.services.workspace import (
    copy_workspace_path,
    move_workspace_path,
)
from src.backend.services.workspace_lock import workspace_lock


class WorkspaceLockTest(unittest.TestCase):
    def test_same_normalized_workspace_uses_one_lock_and_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = workspace_lock(str(root))
            second = workspace_lock(str(root / "."))
            attempted = threading.Event()
            acquired = threading.Event()

            def acquire_same_workspace() -> None:
                attempted.set()
                with second:
                    acquired.set()

            with first:
                thread = threading.Thread(target=acquire_same_workspace)
                thread.start()
                self.assertTrue(attempted.wait(1))
                self.assertFalse(acquired.wait(0.05))

            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertTrue(acquired.is_set())


class AgentWorkspaceBoundaryTest(unittest.TestCase):
    def test_agent_path_helpers_reject_workspace_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            runtime = SimpleNamespace(
                context=SimpleNamespace(workspace_path=str(workspace))
            )

            self.assertEqual(
                _resolve_context_path(runtime, "inside.txt"),
                str((workspace / "inside.txt").resolve()),
            )
            self.assertEqual(
                _context_path(runtime, "inside.docx"),
                (workspace / "inside.docx").resolve(),
            )
            with self.assertRaisesRegex(ValueError, "超出当前工作区"):
                _resolve_context_path(runtime, "../outside.txt")
            with self.assertRaisesRegex(ValueError, "超出当前工作区"):
                _context_path(runtime, str(workspace.parent / "outside.docx"))


class WorkspaceRollbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "source.txt"
        self.destination = self.root / "destination.txt"
        self.source.write_text("new", encoding="utf-8")
        self.destination.write_text("old", encoding="utf-8")

    @patch(
        "src.backend.services.workspace.shutil.copy2",
        side_effect=OSError("copy failed"),
    )
    def test_copy_overwrite_failure_restores_old_destination(self, _copy) -> None:
        with self.assertRaisesRegex(OSError, "copy failed"):
            copy_workspace_path(
                str(self.source),
                str(self.destination),
                overwrite=True,
            )

        self.assertEqual(self.source.read_text(encoding="utf-8"), "new")
        self.assertEqual(self.destination.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(self.root.glob("*.documate-backup")), [])

    @patch(
        "src.backend.services.workspace.shutil.move",
        side_effect=OSError("move failed"),
    )
    def test_move_overwrite_failure_restores_old_destination(self, _move) -> None:
        with self.assertRaisesRegex(OSError, "move failed"):
            move_workspace_path(
                str(self.source),
                str(self.destination),
                overwrite=True,
            )

        self.assertEqual(self.source.read_text(encoding="utf-8"), "new")
        self.assertEqual(self.destination.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(self.root.glob("*.documate-backup")), [])

    def test_failed_new_directory_copy_removes_partial_destination(self) -> None:
        source_directory = self.root / "source-directory"
        source_directory.mkdir()
        (source_directory / "file.txt").write_text("new", encoding="utf-8")
        new_destination = self.root / "new-directory"

        def partial_copy(_source, destination):
            Path(destination).mkdir()
            (Path(destination) / "partial.txt").write_text(
                "partial",
                encoding="utf-8",
            )
            raise OSError("partial copy failed")

        with patch(
            "src.backend.services.workspace.shutil.copytree",
            side_effect=partial_copy,
        ):
            with self.assertRaisesRegex(OSError, "partial copy failed"):
                copy_workspace_path(
                    str(source_directory),
                    str(new_destination),
                )

        self.assertFalse(new_destination.exists())


if __name__ == "__main__":
    unittest.main()

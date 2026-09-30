import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend.services.cancellation import CancellationToken, RunCancelledError
from src.backend.services.workspace import (
    read_workspace_text,
    search_workspace,
    search_workspace_text,
)


class WorkspaceLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_recursive_search_skips_hidden_and_dependency_directories(self) -> None:
        (self.root / "visible").mkdir()
        (self.root / "visible" / "match.txt").write_text("needle\n", encoding="utf-8")
        for name in (".git", ".cache", "node_modules", "build"):
            directory = self.root / name
            directory.mkdir()
            (directory / "hidden-match.txt").write_text("needle\n", encoding="utf-8")

        names = search_workspace("match", str(self.root))
        contents = search_workspace_text("needle", str(self.root))

        self.assertEqual([item["name"] for item in names], ["match.txt"])
        self.assertEqual(len(contents), 1)
        self.assertTrue(str(contents[0]["path"]).endswith("visible/match.txt"))

    def test_text_search_skips_binary_and_oversized_files(self) -> None:
        (self.root / "binary.bin").write_bytes(b"needle\x00binary")
        (self.root / "large.txt").write_text("needle too large", encoding="utf-8")
        (self.root / "small.txt").write_text("needle", encoding="utf-8")

        with patch("src.backend.services.workspace.MAX_SEARCH_FILE_BYTES", 6):
            matches = search_workspace_text("needle", str(self.root))

        self.assertEqual([Path(str(item["path"])).name for item in matches], ["small.txt"])

    def test_read_text_uses_a_bounded_line_window(self) -> None:
        path = self.root / "many-lines.txt"
        path.write_text("\n".join(f"line-{index}" for index in range(1_000)), encoding="utf-8")

        result = read_workspace_text(str(path), start_line=10, line_count=3)

        self.assertEqual(result["content"], "line-9\nline-10\nline-11")
        self.assertEqual(result["end_line"], 12)
        self.assertTrue(result["truncated"])
        self.assertIsNone(result["total_lines"])

    def test_search_stops_when_cancelled(self) -> None:
        path = self.root / "content.txt"
        path.write_text("\n".join("line" for _ in range(500)), encoding="utf-8")
        token = CancellationToken(run_id="run-1")
        token.cancel()

        with self.assertRaises(RunCancelledError):
            search_workspace_text(
                "line",
                str(self.root),
                cancel_check=token.raise_if_cancelled,
            )


if __name__ == "__main__":
    unittest.main()

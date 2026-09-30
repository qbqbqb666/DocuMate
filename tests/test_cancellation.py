import unittest

from src.backend.services.cancellation import RunCancelledError, RunRegistry


class RunRegistryTests(unittest.TestCase):
    def test_cancels_only_the_requested_run(self) -> None:
        registry = RunRegistry()
        first = registry.begin("thread-1", "run-1")
        second = registry.begin("thread-1", "run-2")

        self.assertTrue(registry.cancel("thread-1", "run-1"))
        with self.assertRaises(RunCancelledError):
            first.raise_if_cancelled()
        second.raise_if_cancelled()

        registry.finish("thread-1", "run-1")
        registry.finish("thread-1", "run-2")

    def test_cancel_all_marks_every_active_run(self) -> None:
        registry = RunRegistry()
        first = registry.begin("thread-1", "run-1")
        second = registry.begin("thread-2", "run-2")

        self.assertEqual(registry.cancel_all(), 2)
        with self.assertRaises(RunCancelledError):
            first.raise_if_cancelled()
        with self.assertRaises(RunCancelledError):
            second.raise_if_cancelled()


if __name__ == "__main__":
    unittest.main()

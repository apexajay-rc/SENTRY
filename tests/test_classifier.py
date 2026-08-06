import unittest

from engine.classifier import (
    WorkloadType,
    classify_process,
    workload_priority,
)


class TestClassifier(unittest.TestCase):

    def test_system_process(self):
        self.assertEqual(
            classify_process("systemd"),
            WorkloadType.SYSTEM,
        )

    def test_interactive_process(self):
        self.assertEqual(
            classify_process("chrome"),
            WorkloadType.INTERACTIVE,
        )

    def test_batch_process(self):
        self.assertEqual(
            classify_process("gcc"),
            WorkloadType.BATCH,
        )

    def test_background_process(self):
        self.assertEqual(
            classify_process("rsync"),
            WorkloadType.BACKGROUND,
        )

    def test_unknown_process(self):
        self.assertEqual(
            classify_process("my-custom-daemon"),
            WorkloadType.UNKNOWN,
        )

    def test_case_insensitive(self):
        self.assertEqual(
            classify_process("Chrome"),
            WorkloadType.INTERACTIVE,
        )

    def test_priority_order(self):
        self.assertGreater(
            workload_priority(WorkloadType.SYSTEM),
            workload_priority(WorkloadType.INTERACTIVE),
        )


if __name__ == "__main__":
    unittest.main()

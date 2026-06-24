import unittest

from core.process import ProcessMetrics

from engine.selector import (
    MitigationSelector,
)


class TestSelector(unittest.TestCase):

    def setUp(self):
        self.selector = MitigationSelector()

    def test_batch_preferred_over_interactive(self):

        chrome = ProcessMetrics(
            pid=1,
            comm="chrome",
            cpu_percent=80,
            memory_percent=10,
            score=70,
        )

        gcc = ProcessMetrics(
            pid=2,
            comm="gcc",
            cpu_percent=40,
            memory_percent=5,
            score=40,
        )

        ranked = self.selector.rank_candidates(
            [chrome, gcc],
            "HIGH",
        )

        self.assertEqual(
            ranked[0].process.comm,
            "gcc",
        )

    def test_system_process_filtered(self):

        systemd = ProcessMetrics(
            pid=1,
            comm="systemd",
            cpu_percent=99,
            memory_percent=20,
            score=90,
        )

        ranked = self.selector.rank_candidates(
            [systemd],
            "HIGH",
        )

        self.assertEqual(
            len(ranked),
            0,
        )

    def test_interactive_can_be_selected_at_critical(self):

        chrome = ProcessMetrics(
            pid=1,
            comm="chrome",
            cpu_percent=95,
            memory_percent=20,
            score=90,
        )

        ranked = self.selector.rank_candidates(
            [chrome],
            "CRITICAL",
        )

        self.assertEqual(
            len(ranked),
            1,
        )

    def test_candidates_are_ranked(self):

        p1 = ProcessMetrics(
            pid=1,
            comm="gcc",
            cpu_percent=90,
            memory_percent=10,
            score=80,
        )

        p2 = ProcessMetrics(
            pid=2,
            comm="rsync",
            cpu_percent=20,
            memory_percent=5,
            score=15,
        )

        ranked = self.selector.rank_candidates(
            [p1, p2],
            "HIGH",
        )

        self.assertGreater(
            ranked[0].selection_score,
            ranked[1].selection_score,
        )


if __name__ == "__main__":
    unittest.main()

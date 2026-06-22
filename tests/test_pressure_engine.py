import unittest

from engine.pressure import PressureEngine, compute_pressure_score
from model.pressure import PsiSample, UtilizationSample


class PressureEngineTests(unittest.TestCase):
    def test_uses_utilization_when_psi_is_unavailable(self):
        engine = PressureEngine()
        snapshot = engine.score(
            UtilizationSample(cpu_percent=70.0, memory_percent=50.0, io_wait_percent=10.0)
        )

        self.assertIsNone(snapshot.score.psi)
        self.assertEqual(snapshot.score.total, snapshot.score.utilization)

    def test_pressure_score_is_psi_first_when_stalls_are_present(self):
        engine = PressureEngine({"psi_blend": 0.75})
        snapshot = engine.score(
            UtilizationSample(cpu_percent=10.0, memory_percent=20.0, io_wait_percent=5.0),
            PsiSample(cpu_some_avg10=70.0, memory_some_avg10=60.0, io_some_avg10=20.0),
        )

        self.assertGreater(snapshot.score.psi, snapshot.score.utilization)
        self.assertGreater(snapshot.score.total, snapshot.score.utilization)

    def test_psi_blend_is_bounded(self):
        low = compute_pressure_score(
            80.0,
            80.0,
            80.0,
            weights={"psi_blend": -10.0},
            psi_cpu=0.0,
        )
        high = compute_pressure_score(
            80.0,
            80.0,
            80.0,
            weights={"psi_blend": 10.0},
            psi_cpu=0.0,
        )

        self.assertEqual(low.total, low.utilization)
        self.assertEqual(high.total, high.psi)


if __name__ == "__main__":
    unittest.main()


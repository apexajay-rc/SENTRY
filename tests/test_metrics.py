import os
import tempfile
import unittest
from pathlib import Path

from core.classifier import classify_stress, decision_hint, trend_label, trend_rising
from core.metrics import SystemMetricsSampler, compute_stress
from core.process import ProcessSampler
from core.procfs import (
    cpu_usage_percent,
    io_wait_percent,
    parse_process_stat,
    read_memory_usage_percent,
    read_psi,
    read_system_stat,
    CpuStatSnapshot,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "proc"


class ProcfsParsingTests(unittest.TestCase):
    def setUp(self):
        self.proc_root = str(FIXTURES)

    def test_cpu_usage_percent_from_delta(self):
        previous = read_system_stat(self.proc_root)
        current = CpuStatSnapshot(idle=previous.idle + 50, iowait=previous.iowait + 10, total=previous.total + 200)
        self.assertEqual(cpu_usage_percent(previous, current), 75.0)

    def test_io_wait_percent_from_delta(self):
        previous = read_system_stat(self.proc_root)
        current = CpuStatSnapshot(idle=previous.idle + 150, iowait=previous.iowait + 50, total=previous.total + 200)
        self.assertEqual(io_wait_percent(previous, current), 25.0)

    def test_memory_usage_percent(self):
        self.assertEqual(read_memory_usage_percent(self.proc_root), 62.5)

    def test_parse_process_stat(self):
        raw = "1234 (chrome) S 1 1 1 0 -1 4194560 100 0 0 0 500 250 0 0 0 17 0 0 0 0 0 0 0 0 0"
        comm, utime, stime = parse_process_stat(raw)
        self.assertEqual(comm, "chrome")
        self.assertEqual(utime, 500)
        self.assertEqual(stime, 250)

    def test_read_psi(self):
        psi = read_psi("cpu", self.proc_root)
        self.assertIsNotNone(psi)
        assert psi is not None
        self.assertEqual(psi.some_avg10, 12.34)
        self.assertEqual(psi.full_avg10, 4.56)


class MetricsSamplerTests(unittest.TestCase):
    def test_sampler_uses_stateful_delta(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            proc_root = Path(temp_dir)
            (proc_root / "meminfo").write_text(
                "MemTotal:       8000000 kB\nMemAvailable:   3000000 kB\n",
                encoding="utf-8",
            )
            (proc_root / "stat").write_text(
                "cpu  1000 0 500 5000 100 0 0 0 0 0\n",
                encoding="utf-8",
            )

            sampler = SystemMetricsSampler(proc_root=str(proc_root), interval=0)
            first = sampler.sample()
            self.assertEqual(first.cpu_percent, 0.0)

            (proc_root / "stat").write_text(
                "cpu  1100 0 550 5150 150 0 0 0 0 0\n",
                encoding="utf-8",
            )

            second = sampler.sample()
            self.assertGreater(second.cpu_percent, 0.0)
            self.assertGreater(second.io_wait_percent, 0.0)
            self.assertEqual(
                second.stress_score,
                compute_stress(second.cpu_percent, second.memory_percent, second.io_wait_percent),
            )


class ProcessSamplerTests(unittest.TestCase):
    def test_process_cpu_from_stat_delta(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            proc_root = Path(temp_dir)
            (proc_root / "meminfo").write_text(
                "MemTotal:       8000000 kB\nMemAvailable:   3000000 kB\n",
                encoding="utf-8",
            )
            (proc_root / "stat").write_text(
                "cpu  1000 0 500 5000 100 0 0 0 0 0\n",
                encoding="utf-8",
            )

            pid_dir = proc_root / "4242"
            pid_dir.mkdir()
            (pid_dir / "stat").write_text(
                "4242 (worker) R 1 1 1 0 -1 4194560 0 0 0 0 100 50 0 0 0 0 0 0",
                encoding="utf-8",
            )
            (pid_dir / "status").write_text("VmRSS:\t2000000 kB\n", encoding="utf-8")

            sampler = ProcessSampler(proc_root=str(proc_root))
            sampler.prime()

            (pid_dir / "stat").write_text(
                "4242 (worker) R 1 1 1 0 -1 4194560 0 0 0 0 300 150 0 0 0 0 0 0",
                encoding="utf-8",
            )
            (proc_root / "stat").write_text(
                "cpu  1100 0 550 5500 110 0 0 0 0 0\n",
                encoding="utf-8",
            )

            processes = sampler.sample(system_total_delta=600, total_memory_kb=8000000)
            self.assertEqual(len(processes), 1)
            self.assertEqual(processes[0].comm, "worker")
            self.assertEqual(processes[0].cpu_percent, 50.0)
            self.assertEqual(processes[0].memory_percent, 25.0)


class ClassifierTests(unittest.TestCase):
    def test_classify_stress_by_mode(self):
        self.assertEqual(classify_stress(0.10), "LOW")
        self.assertEqual(classify_stress(0.30, "Gaming"), "MODERATE")
        self.assertEqual(classify_stress(0.42, "Gaming"), "HIGH")
        self.assertEqual(classify_stress(0.70, "Balanced"), "CRITICAL")

    def test_trend_rising(self):
        self.assertFalse(trend_rising([0.5, 0.48, 0.52, 0.45, 0.44]))
        self.assertTrue(trend_rising([0.5, 0.48, 0.52, 0.7, 0.8]))

    def test_trend_label_and_decision(self):
        history = __import__("collections").deque([0.1, 0.2, 0.3, 0.4, 0.5])
        self.assertEqual(trend_label(history), "Rising")
        self.assertEqual(decision_hint("HIGH", "Rising"), "Mitigation advised")


if __name__ == "__main__":
    unittest.main()

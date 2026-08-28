from dataclasses import dataclass
from typing import Optional

from core.procfs import PROC_ROOT, ProcessSnapshot, list_process_ids, read_process_snapshot


@dataclass(frozen=True)
class ProcessMetrics:
    pid: int
    comm: str
    cpu_percent: float
    memory_percent: float
    score: float


class ProcessSampler:
    """Instantaneous per-process CPU from /proc/[pid]/stat deltas."""

    def __init__(self, proc_root: str = PROC_ROOT):
        self.proc_root = proc_root
        self._previous: dict[int, ProcessSnapshot] = {}

    def sample(self, system_total_delta: int, total_memory_kb: int) -> list[ProcessMetrics]:
        if system_total_delta <= 0 or total_memory_kb <= 0:
            return []

        current = self._read_all_processes()
        metrics: list[ProcessMetrics] = []

        for pid, snapshot in current.items():
            previous = self._previous.get(pid)
            if previous is None:
                continue

            proc_delta = snapshot.cpu_jiffies - previous.cpu_jiffies
            if proc_delta < 0:
                continue

            cpu_percent = round(100 * proc_delta / system_total_delta, 2)
            memory_percent = round(100 * snapshot.rss_kb / total_memory_kb, 2)
            score = round((0.7 * cpu_percent) + (0.3 * memory_percent), 2)

            metrics.append(
                ProcessMetrics(
                    pid=pid,
                    comm=snapshot.comm,
                    cpu_percent=cpu_percent,
                    memory_percent=memory_percent,
                    score=score,
                )
            )

        self._previous = current
        return sorted(metrics, key=lambda item: item.score, reverse=True)

    def prime(self) -> None:
        self._previous = self._read_all_processes()

    def top_process(
        self,
        system_total_delta: int,
        total_memory_kb: int,
        protected_comm: Optional[set[str]] = None,
    ) -> tuple[Optional[int], Optional[str], Optional[float]]:
        protected = protected_comm or set()
        for process in self.sample(system_total_delta, total_memory_kb):
            if process.comm in protected:
                continue
            return process.pid, process.comm, process.score
        return None, None, None

    def top_processes(
        self,
        system_total_delta: int,
        total_memory_kb: int,
        limit: int = 3,
    ) -> list[ProcessMetrics]:
        return self.sample(system_total_delta, total_memory_kb)[:limit]

    def _read_all_processes(self) -> dict[int, ProcessSnapshot]:
        processes: dict[int, ProcessSnapshot] = {}
        for pid in list_process_ids(self.proc_root):
            snapshot = read_process_snapshot(pid, self.proc_root)
            if snapshot is not None:
                processes[pid] = snapshot
        return processes


def read_total_memory_kb(proc_root: str = PROC_ROOT) -> int:
    with open(f"{proc_root}/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("MemTotal:"):
                return int(line.split()[1])
    return 0

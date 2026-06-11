import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from core.procfs import (
    PROC_ROOT,
    CpuStatSnapshot,
    cpu_usage_percent,
    io_wait_percent,
    read_memory_usage_percent,
    read_psi,
    read_system_stat,
)

if TYPE_CHECKING:
    from core.config import ConfigManager

DEFAULT_METRIC_WEIGHTS = {
    "cpu_weight": 0.5,
    "memory_weight": 0.3,
    "io_weight": 0.2,
}

_metric_weights = DEFAULT_METRIC_WEIGHTS.copy()


def configure_metrics(config: "ConfigManager") -> None:
    global _metric_weights
    weights = config.metric_weights()
    _metric_weights = {
        "cpu_weight": weights.get("cpu_weight", DEFAULT_METRIC_WEIGHTS["cpu_weight"]),
        "memory_weight": weights.get("memory_weight", DEFAULT_METRIC_WEIGHTS["memory_weight"]),
        "io_weight": weights.get("io_weight", DEFAULT_METRIC_WEIGHTS["io_weight"]),
    }


@dataclass(frozen=True)
class SystemMetrics:
    cpu_percent: float
    memory_percent: float
    io_wait_percent: float
    stress_score: float
    psi_cpu_some_avg10: Optional[float] = None
    psi_memory_some_avg10: Optional[float] = None
    psi_io_some_avg10: Optional[float] = None


def compute_stress(
    cpu: float,
    memory: float,
    io: float,
    weights: Optional[dict[str, float]] = None,
) -> float:
    active = weights or _metric_weights
    cpu_w = active.get("cpu_weight", DEFAULT_METRIC_WEIGHTS["cpu_weight"])
    mem_w = active.get("memory_weight", DEFAULT_METRIC_WEIGHTS["memory_weight"])
    io_w = active.get("io_weight", DEFAULT_METRIC_WEIGHTS["io_weight"])
    return round((cpu_w * cpu + mem_w * memory + io_w * io) / 100, 2)


class SystemMetricsSampler:
    """Delta-based system metrics from /proc/stat and /proc/meminfo."""

    def __init__(
        self,
        proc_root: str = PROC_ROOT,
        interval: float = 0.5,
        metric_weights: Optional[dict[str, float]] = None,
    ):
        self.proc_root = proc_root
        self.interval = interval
        self.metric_weights = metric_weights
        self._previous: Optional[CpuStatSnapshot] = None

    def warmup(self) -> SystemMetrics:
        self._previous = read_system_stat(self.proc_root)
        time.sleep(self.interval)
        return self.sample()

    def sample(self) -> SystemMetrics:
        current = read_system_stat(self.proc_root)
        memory = read_memory_usage_percent(self.proc_root)

        if self._previous is None:
            self._previous = current
            return SystemMetrics(
                cpu_percent=0.0,
                memory_percent=memory,
                io_wait_percent=0.0,
                stress_score=compute_stress(0.0, memory, 0.0, self.metric_weights),
                **_read_psi_fields(self.proc_root),
            )

        cpu = cpu_usage_percent(self._previous, current)
        io = io_wait_percent(self._previous, current)
        self._previous = current

        return SystemMetrics(
            cpu_percent=cpu,
            memory_percent=memory,
            io_wait_percent=io,
            stress_score=compute_stress(cpu, memory, io, self.metric_weights),
            **_read_psi_fields(self.proc_root),
        )

    def sample_blocking(self) -> SystemMetrics:
        if self._previous is None:
            return self.warmup()

        time.sleep(self.interval)
        return self.sample()


def _read_psi_fields(proc_root: str) -> dict[str, Optional[float]]:
    cpu = read_psi("cpu", proc_root)
    memory = read_psi("memory", proc_root)
    io = read_psi("io", proc_root)

    return {
        "psi_cpu_some_avg10": cpu.some_avg10 if cpu else None,
        "psi_memory_some_avg10": memory.some_avg10 if memory else None,
        "psi_io_some_avg10": io.some_avg10 if io else None,
    }


_default_sampler = SystemMetricsSampler()


def calculate_cpu() -> float:
    return _default_sampler.sample_blocking().cpu_percent


def get_memory_usage() -> float:
    return read_memory_usage_percent()


def get_io_wait() -> float:
    return _default_sampler.sample_blocking().io_wait_percent


def sample_system_metrics(blocking: bool = True) -> SystemMetrics:
    if blocking:
        return _default_sampler.sample_blocking()
    return _default_sampler.sample()

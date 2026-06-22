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
from engine.pressure import DEFAULT_PRESSURE_WEIGHTS, PressureEngine, compute_pressure_score
from model.pressure import PsiSample, UtilizationSample

if TYPE_CHECKING:
    from core.config import ConfigManager

DEFAULT_METRIC_WEIGHTS = DEFAULT_PRESSURE_WEIGHTS

_metric_weights = DEFAULT_METRIC_WEIGHTS.copy()


def configure_metrics(config: "ConfigManager") -> None:
    global _metric_weights
    weights = config.metric_weights()
    _metric_weights = {
        key: weights.get(key, DEFAULT_METRIC_WEIGHTS[key])
        for key in DEFAULT_METRIC_WEIGHTS
    }


@dataclass(frozen=True)
class StressBreakdown:
    total: float
    utilization: float
    psi: Optional[float] = None


@dataclass(frozen=True)
class SystemMetrics:
    cpu_percent: float
    memory_percent: float
    io_wait_percent: float
    stress_score: float
    utilization_score: float
    psi_score: Optional[float] = None
    psi_cpu_some_avg10: Optional[float] = None
    psi_memory_some_avg10: Optional[float] = None
    psi_io_some_avg10: Optional[float] = None


def compute_utilization_score(
    cpu: float,
    memory: float,
    io: float,
    weights: Optional[dict[str, float]] = None,
) -> float:
    return PressureEngine(weights or _metric_weights).utilization_score(
        UtilizationSample(cpu_percent=cpu, memory_percent=memory, io_wait_percent=io)
    )


def compute_psi_score(
    psi_cpu: Optional[float],
    psi_memory: Optional[float],
    psi_io: Optional[float],
    weights: Optional[dict[str, float]] = None,
) -> Optional[float]:
    return PressureEngine(weights or _metric_weights).psi_score(
        PsiSample(
            cpu_some_avg10=psi_cpu,
            memory_some_avg10=psi_memory,
            io_some_avg10=psi_io,
        )
    )


def compute_stress_breakdown(
    cpu: float,
    memory: float,
    io: float,
    weights: Optional[dict[str, float]] = None,
    psi_cpu: Optional[float] = None,
    psi_memory: Optional[float] = None,
    psi_io: Optional[float] = None,
) -> StressBreakdown:
    score = compute_pressure_score(
        cpu,
        memory,
        io,
        weights or _metric_weights,
        psi_cpu=psi_cpu,
        psi_memory=psi_memory,
        psi_io=psi_io,
    )
    return StressBreakdown(total=score.total, utilization=score.utilization, psi=score.psi)


def compute_stress(
    cpu: float,
    memory: float,
    io: float,
    weights: Optional[dict[str, float]] = None,
    psi_cpu: Optional[float] = None,
    psi_memory: Optional[float] = None,
    psi_io: Optional[float] = None,
) -> float:
    return compute_stress_breakdown(
        cpu,
        memory,
        io,
        weights,
        psi_cpu=psi_cpu,
        psi_memory=psi_memory,
        psi_io=psi_io,
    ).total


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
        psi_fields = _read_psi_fields(self.proc_root)

        if self._previous is None:
            self._previous = current
            breakdown = compute_stress_breakdown(
                0.0,
                memory,
                0.0,
                self.metric_weights,
                psi_cpu=psi_fields["psi_cpu_some_avg10"],
                psi_memory=psi_fields["psi_memory_some_avg10"],
                psi_io=psi_fields["psi_io_some_avg10"],
            )
            return SystemMetrics(
                cpu_percent=0.0,
                memory_percent=memory,
                io_wait_percent=0.0,
                stress_score=breakdown.total,
                utilization_score=breakdown.utilization,
                psi_score=breakdown.psi,
                **psi_fields,
            )

        cpu = cpu_usage_percent(self._previous, current)
        io = io_wait_percent(self._previous, current)
        self._previous = current

        breakdown = compute_stress_breakdown(
            cpu,
            memory,
            io,
            self.metric_weights,
            psi_cpu=psi_fields["psi_cpu_some_avg10"],
            psi_memory=psi_fields["psi_memory_some_avg10"],
            psi_io=psi_fields["psi_io_some_avg10"],
        )

        return SystemMetrics(
            cpu_percent=cpu,
            memory_percent=memory,
            io_wait_percent=io,
            stress_score=breakdown.total,
            utilization_score=breakdown.utilization,
            psi_score=breakdown.psi,
            **psi_fields,
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

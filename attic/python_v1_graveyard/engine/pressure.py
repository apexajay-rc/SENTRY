from typing import Optional

from model.pressure import PressureScore, PressureSnapshot, PsiSample, UtilizationSample


DEFAULT_PRESSURE_WEIGHTS = {
    "cpu_weight": 0.35,
    "memory_weight": 0.25,
    "io_weight": 0.15,
    "psi_cpu_weight": 0.10,
    "psi_memory_weight": 0.10,
    "psi_io_weight": 0.05,
    "psi_blend": 0.40,
}


class PressureEngine:
    """Build a pressure-first score from utilization context and PSI stalls."""

    def __init__(self, weights: Optional[dict[str, float]] = None):
        self.weights = {**DEFAULT_PRESSURE_WEIGHTS, **(weights or {})}
        self.previous_stress = 0.0

    def score(
        self,
        utilization: UtilizationSample,
        psi: Optional[PsiSample] = None,
    ) -> PressureSnapshot:
        psi_sample = psi or PsiSample()
        utilization_score = self.utilization_score(utilization)
        psi_score = self.psi_score(psi_sample)

        if psi_score is None:
            total = utilization_score
        else:
            blend = self._bounded_weight("psi_blend")
            total = round(((1 - blend) * utilization_score) + (blend * psi_score), 2)

        stress_delta = round(total - self.previous_stress, 2)
        self.previous_stress = total

        snapshot = PressureSnapshot(
            utilization=utilization,
            psi=psi_sample,
            score=PressureScore(
                total=total,
                utilization=utilization_score,
                psi=psi_score,
            ),
        )
        return snapshot

    def utilization_score(self, sample: UtilizationSample) -> float:
        cpu_w = self.weights["cpu_weight"]
        memory_w = self.weights["memory_weight"]
        io_w = self.weights["io_weight"]
        return round(
            (
                cpu_w * sample.cpu_percent
                + memory_w * sample.memory_percent
                + io_w * sample.io_wait_percent
            )
            / 100,
            2,
        )

    def psi_score(self, sample: PsiSample) -> Optional[float]:
        components = [
            (sample.cpu_some_avg10, self.weights["psi_cpu_weight"]),
            (sample.memory_some_avg10, self.weights["psi_memory_weight"]),
            (sample.io_some_avg10, self.weights["psi_io_weight"]),
        ]
        available = [(value / 100, weight) for value, weight in components if value is not None]
        if not available:
            return None

        total_weight = sum(weight for _, weight in available)
        if total_weight <= 0:
            return None

        return round(sum(value * weight for value, weight in available) / total_weight, 2)

    def _bounded_weight(self, key: str) -> float:
        return max(0.0, min(1.0, float(self.weights.get(key, 0.0))))


def compute_pressure_score(
    cpu: float,
    memory: float,
    io: float,
    weights: Optional[dict[str, float]] = None,
    psi_cpu: Optional[float] = None,
    psi_memory: Optional[float] = None,
    psi_io: Optional[float] = None,
) -> PressureScore:
    snapshot = PressureEngine(weights).score(
        UtilizationSample(cpu_percent=cpu, memory_percent=memory, io_wait_percent=io),
        PsiSample(
            cpu_some_avg10=psi_cpu,
            memory_some_avg10=psi_memory,
            io_some_avg10=psi_io,
        ),
    )
    return snapshot.score

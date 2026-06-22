from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UtilizationSample:
    cpu_percent: float
    memory_percent: float
    io_wait_percent: float


@dataclass(frozen=True)
class PsiSample:
    cpu_some_avg10: Optional[float] = None
    memory_some_avg10: Optional[float] = None
    io_some_avg10: Optional[float] = None

    @property
    def available(self) -> bool:
        return any(
            value is not None
            for value in (
                self.cpu_some_avg10,
                self.memory_some_avg10,
                self.io_some_avg10,
            )
        )


@dataclass(frozen=True)
class PressureScore:
    total: float
    utilization: float
    psi: Optional[float] = None


@dataclass(frozen=True)
class PressureSnapshot:
    utilization: UtilizationSample
    psi: PsiSample
    score: PressureScore


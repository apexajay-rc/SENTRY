from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
from pathlib import Path

@dataclass(frozen=True)
class ThrottleSpec:
    mode: Literal["PROPORTIONAL", "HARD_LIMIT"]
    cpu_quota_pct: int
    cpu_weight: int
    memory_limit_bytes: int

class ThrottleActuator(ABC):
    @property
    @abstractmethod
    def sentry_root(self) -> Path:
        """Root cgroup path for this actuator."""
        pass

    @abstractmethod
    async def apply_throttle(self, pid: int, spec: ThrottleSpec) -> None: pass

    @abstractmethod
    async def release_throttle(self, pid: int) -> None: pass

from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class ThrottleSpec:
    cpu_quota_pct: int
    memory_limit_bytes: int

class ThrottleActuator(ABC):
    @abstractmethod
    async def apply_throttle(self, pid: int, spec: ThrottleSpec) -> None:
        pass

    @abstractmethod
    async def release_throttle(self, pid: int) -> None:
        pass

    @abstractmethod
    async def verify_throttle(self, pid: int) -> ThrottleSpec:
        pass

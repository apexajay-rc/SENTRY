from enum import Enum
from dataclasses import dataclass
from src.sentry_v2.policy.scoring import StressScore
from src.sentry_v2.config import ThresholdConfig

class StressLevel(Enum):
    LOW = 1
    MODERATE = 2
    HIGH = 3
    CRITICAL = 4

@dataclass(frozen=True)
class ThrottlePolicy:
    cpu_quota_pct: int
    memory_multiplier: float
    max_hogs: int

LEVEL_POLICIES = {
    StressLevel.LOW: ThrottlePolicy(100, 1.0, 0),
    StressLevel.MODERATE: ThrottlePolicy(70, 1.5, 1),
    StressLevel.HIGH: ThrottlePolicy(50, 1.3, 3),
    StressLevel.CRITICAL: ThrottlePolicy(30, 1.2, 5),
}

class StateMachine:
    def __init__(self, thresholds: ThresholdConfig):
        self.thresholds = thresholds
        self.current = StressLevel.LOW
        self._dwell_ticks = 0

    def step(self, score: StressScore) -> tuple[StressLevel, bool]:
        # Up thresholds use baseline; down thresholds incorporate hysteresis drop
        up_thresh = {
            StressLevel.LOW: self.thresholds.moderate,
            StressLevel.MODERATE: self.thresholds.high,
            StressLevel.HIGH: self.thresholds.critical,
            StressLevel.CRITICAL: 999,
        }
        down_thresh = {
            StressLevel.LOW: -1,
            StressLevel.MODERATE: self.thresholds.low - self.thresholds.hysteresis,
            StressLevel.HIGH: self.thresholds.moderate - self.thresholds.hysteresis,
            StressLevel.CRITICAL: self.thresholds.high - self.thresholds.hysteresis,
        }

        s = score.combined
        up = up_thresh[self.current]
        down = down_thresh[self.current]

        # UP transition (immediate)
        if s >= up:
            next_val = min(self.current.value + 1, StressLevel.CRITICAL.value)
            self.current = StressLevel(next_val)
            self._dwell_ticks = 0
            return self.current, True

        # DOWN transition (requires 30 ticks dwell)
        if s <= down:
            self._dwell_ticks += 1
            if self._dwell_ticks >= 30:
                next_val = max(self.current.value - 1, StressLevel.LOW.value)
                self.current = StressLevel(next_val)
                self._dwell_ticks = 0
                return self.current, True
        else:
            self._dwell_ticks = 0

        return self.current, False

    def get_policy(self) -> ThrottlePolicy:
        return LEVEL_POLICIES[self.current]

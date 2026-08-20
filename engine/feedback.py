"""
Feedback Engine for SENTRY.

Evaluates whether applied mitigation actions actually improved system pressure.
Basis for the Verify → Learn stages of Observe→Understand→Predict→Optimize→Act→Verify→Learn.
"""

from dataclasses import dataclass
import time


@dataclass
class ActionOutcome:
    """Records the outcome of a mitigation action."""
    pid: int
    stress_before: float
    stress_after: float
    pressure_before: str
    pressure_after: str
    successful: bool


class FeedbackEngine:
    """Evaluates whether actions improved system pressure."""

    def __init__(self, logger=None):
        self.logger = logger
        # Tracks pending evaluations: pid -> {stress_before, pressure_before, level, timestamp}
        self._pending = {}

    def record_action(self, pid: int, stress_before: float, pressure_before: str, level: str) -> None:
        """Records pre-action state for later evaluation."""
        self._pending[pid] = {
            "stress_before": stress_before,
            "pressure_before": pressure_before,
            "level": level,
            "timestamp": time.monotonic(),
        }

    def evaluate_action(self, pid: int, stress_after: float, pressure_after: str) -> bool:
        """Evaluates action using stored pre-state and current post-state.
        Returns True if successful, False otherwise.
        """
        if pid not in self._pending:
            return False

        record = self._pending.pop(pid)
        stress_before = record["stress_before"]
        pressure_before = record["pressure_before"]

        stress_improved = stress_after < stress_before
        pressure_improved = self._is_improvement(pressure_before, pressure_after)
        successful = stress_improved and pressure_improved

        return successful

    @staticmethod
    def _is_improvement(before: str, after: str) -> bool:
        """Check if pressure level improved or stayed same (did not worsen)."""
        level_order = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
        before_rank = level_order.get(before, -1)
        after_rank = level_order.get(after, 4)
        return after_rank <= before_rank

"""
Feedback Engine for SENTRY.

Evaluates whether applied mitigation actions actually improved system pressure.
Basis for the Verify → Learn stages of Observe→Understand→Predict→Optimize→Act→Verify→Learn.
"""

from dataclasses import dataclass


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
    
    def evaluate(
        self,
        pid: int,
        stress_before: float,
        stress_after: float,
        pressure_before: str,
        pressure_after: str,
    ) -> ActionOutcome:
        """
        Evaluate whether an action was successful.
        
        Success is defined as: stress improved AND pressure level did not worsen.
        
        Args:
            pid: Process ID that was throttled
            stress_before: Stress score before action
            stress_after: Stress score after action (post-cooldown)
            pressure_before: Pressure level before action
            pressure_after: Pressure level after action
        
        Returns:
            ActionOutcome with success/failure determination
        """
        stress_improved = stress_after < stress_before
        pressure_improved = self._is_improvement(pressure_before, pressure_after)
        successful = stress_improved and pressure_improved
        
        return ActionOutcome(
            pid=pid,
            stress_before=stress_before,
            stress_after=stress_after,
            pressure_before=pressure_before,
            pressure_after=pressure_after,
            successful=successful,
        )
    
    @staticmethod
    def _is_improvement(before: str, after: str) -> bool:
        """Check if pressure level improved or stayed same (did not worsen)."""
        level_order = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
        before_rank = level_order.get(before, -1)
        after_rank = level_order.get(after, 4)
        return after_rank <= before_rank

"""
engine/reconciliation.py

Manages the lifecycle of applied mitigations.
Ensures processes are un-throttled safely, preventing permanent resource 
starvation and guarding against Linux PID recycling race conditions.
"""

import time
import logging
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)

@dataclass
class ThrottledProcess:
    """Represents the exact state of a process when SENTRY intervened."""
    pid: int
    cgroup_path: str
    throttled_at: float

class StateReconciler:
    """
    Tracks active mitigations and calculates when it is safe to revert them.
    """

    def __init__(self) -> None:
        # Maps PID to its historical throttle state
        self._active_throttles: Dict[int, ThrottledProcess] = {}

    def track(self, pid: int, cgroup_path: str) -> None:
        """
        Records a process as actively mitigated.
        
        Args:
            pid: The process ID.
            cgroup_path: The absolute path to the process's cgroup at the time of throttling.
        """
        self._active_throttles[pid] = ThrottledProcess(
            pid=pid,
            cgroup_path=cgroup_path,
            throttled_at=time.time()
        )
        logger.debug(f"Tracking mitigation state for PID {pid} at {cgroup_path}")

    def get_releasable_tasks(self, cooldown_seconds: float) -> List[ThrottledProcess]:
        """
        Identifies processes that have survived the cooldown period 
        and are eligible to have their resource limits lifted.
        
        Args:
            cooldown_seconds: Minimum time (in seconds) a process must remain throttled.
            
        Returns:
            A list of ThrottledProcess objects eligible for release.
        """
        now = time.time()
        releasable = []

        for task in self._active_throttles.values():
            if (now - task.throttled_at) >= cooldown_seconds:
                releasable.append(task)

        return releasable

    def drop(self, pid: int) -> None:
        """Removes a process from the tracking state."""
        self._active_throttles.pop(pid, None)

    def is_tracked(self, pid: int) -> bool:
        """Checks if SENTRY is currently managing this PID."""
        return pid in self._active_throttles
        
    def active_count(self) -> int:
        """Returns the number of currently throttled processes."""
        return len(self._active_throttles)

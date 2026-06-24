"""
Action tracking and timeout management for SENTRY.

Tracks applied mitigation actions and manages
automatic resume timeouts.

This module intentionally tracks:

    What action was applied
    When it was applied

It does NOT evaluate effectiveness.

That responsibility belongs to the Feedback Engine.
"""

import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ActionRecord:
    """
    Represents a mitigation action currently active
    against a process.
    """

    pid: int

    action_type: str

    timestamp: float

    cpu_weight: Optional[int] = None
    memory_limit: Optional[int] = None
    io_weight: Optional[int] = None

    stress_before: Optional[float] = None
    pressure_before: Optional[str] = None


class ActionTracker:
    """
    Tracks active mitigation actions.

    Responsibilities:
        - Record actions
        - Prevent duplicate actions
        - Manage timeout expiration
        - Support action lookup

    Non-responsibilities:
        - Evaluating effectiveness
        - Selecting mitigation targets
        - Applying cgroup changes
    """

    def __init__(self, resume_seconds: int = 10):
        self.resume_seconds = resume_seconds
        self.actions: Dict[int, ActionRecord] = {}

    def record_action(
        self,
        pid: int,
        action_type: str,
        cpu_weight: Optional[int] = None,
        memory_limit: Optional[int] = None,
        io_weight: Optional[int] = None,
        stress_before: Optional[float] = None,
        pressure_before: Optional[str] = None,
    ) -> None:
        """
        Record a newly applied mitigation action.
        """

        self.actions[pid] = ActionRecord(
            pid=pid,
            action_type=action_type,
            timestamp=time.time(),
            cpu_weight=cpu_weight,
            memory_limit=memory_limit,
            io_weight=io_weight,
            stress_before=stress_before,
            pressure_before=pressure_before,
        )

    def is_active(self, pid: int) -> bool:
        """
        Check whether a PID currently has an active action.
        """

        return pid in self.actions

    def should_resume(self, pid: int) -> bool:
        """
        Determine whether the action timeout expired.
        """

        record = self.actions.get(pid)

        if record is None:
            return False

        elapsed = time.time() - record.timestamp

        return elapsed >= self.resume_seconds

    def get_expired_pids(self) -> list[int]:
        """
        Return all PIDs whose timeout expired.
        """

        return [
            pid
            for pid in self.actions
            if self.should_resume(pid)
        ]

    def resume_action(self, pid: int) -> Optional[ActionRecord]:
        """
        Remove active action and return its record.
        """

        return self.actions.pop(pid, None)

    def get_action_info(
        self,
        pid: int,
    ) -> Optional[ActionRecord]:
        """
        Lookup active action.
        """

        return self.actions.get(pid)

    def cleanup_expired(self) -> list[int]:
        """
        Remove expired actions.

        Returns:
            list[int]: expired PIDs
        """

        expired = self.get_expired_pids()

        for pid in expired:
            self.resume_action(pid)

        return expired

    def get_active_actions_count(self) -> int:
        """
        Number of active mitigation actions.
        """

        return len(self.actions)

    def get_active_actions(self) -> list[ActionRecord]:
        """
        Return all active action records.
        """

        return list(self.actions.values())

    def clear(self) -> None:
        """
        Remove all tracked actions.

        Primarily useful for tests.
        """

        self.actions.clear()

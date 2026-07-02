"""
core/safety_guard.py

Provides an immutable safety net to ensure SENTRY never throttles or 
kills critical Linux infrastructure, preserving system recoverability.
"""

import os
import logging

logger = logging.getLogger(__name__)

class SafetyGuard:
    """
    Mandatory access control for the mitigation engine.
    """

    # Hardcoded list of strictly protected infrastructure binaries.
    # This list must never be configurable by the user.
    CRITICAL_DAEMONS = {
        "systemd",
        "init",
        "sshd",
        "dbus-daemon",
        "dbus-broker",
        "systemd-journald",
        "systemd-udevd",
        "systemd-logind",
        "bash",        # Prevent killing root's recovery shell
        "tmux",
        "screen",
    }

    def __init__(self) -> None:
        self._sentry_pid = os.getpid()

    def _get_process_name(self, pid: int) -> str:
        """Reads the executable name of the process from procfs."""
        try:
            with open(f"/proc/{pid}/comm", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            # Process died before we could read its name
            return ""
        except OSError as e:
            logger.error(f"Error reading comm for PID {pid}: {e}")
            return ""

    def is_protected(self, pid: int) -> bool:
        """
        Determines if a PID is strictly protected from intervention.
        
        Args:
            pid: The process ID to check.
            
        Returns:
            True if the process must not be touched, False otherwise.
        """
        # 1. Protect the kernel and init system
        if pid <= 1:
            return True
            
        # 2. Protect SENTRY itself
        if pid == self._sentry_pid:
            return True

        # 3. Protect kernel threads (they don't have a userspace cgroup/memory footprint in the same way)
        # In Linux, kernel threads typically have a PPID of 2 (kthreadd)
        try:
            with open(f"/proc/{pid}/stat", "r") as f:
                stat_data = f.read().split()
                if len(stat_data) > 3 and stat_data[3] == "2":
                    return True
        except (FileNotFoundError, IndexError):
            pass # Fall through to name check

        # 4. Protect critical infrastructure by binary name
        proc_name = self._get_process_name(pid)
        
        # If we can't read the name because of a transient error, fail safe (protect it).
        # We only return False if we positively identify a non-protected name.
        if not proc_name:
            return True 

        if proc_name in self.CRITICAL_DAEMONS:
            logger.debug(f"SafetyGuard blocked action on PID {pid} ({proc_name})")
            return True

        return False

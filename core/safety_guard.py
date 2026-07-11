"""
core/safety_guard.py

The immunity system for SENTRY.
Prevents the daemon from accidentally throttling critical system infrastructure,
kernel threads, and itself.
"""

import os
import logging
from typing import Set

logger = logging.getLogger(__name__)

class SafetyGuard:
    def __init__(self):
        # The VIP List of critical system daemons
        self.protected_names: Set[str] = {
            "systemd",          # The init system
            "sshd",             # Remote shell access
            "dbus-daemon",      # System message bus
            "dbus-broker",      # Alternative message bus
            "NetworkManager",   # Networking
            "Xorg",             # Display Server (X11)
            "Xwayland",         # Display Server (Wayland backwards compatibility)
            "gnome-shell",      # GNOME UI critical path
            "kwin_wayland",     # KDE UI critical path
            "python3",          # SENTRY itself (we will refine this later)
            "sudo"              # Privilege escalation
        }

    def is_protected(self, pid: int) -> bool:
        """
        Evaluates a PID against system stability rules to determine if it is immune.
        Returns True if the process should NOT be throttled.
        """
        # Rule 1: The Root Law
        if pid <= 1:
            return True

        try:
            # Rule 2: The Kernel Law
            # Kernel threads do not have user-space command lines.
            # If the cmdline file is empty, it's a kernel thread.
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read()
                if not cmdline:
                    return True

            # Rule 3: The VIP Law
            # Read the exact binary name that executed the process
            with open(f"/proc/{pid}/comm", "r") as f:
                comm = f.read().strip()
                if comm in self.protected_names:
                    logger.debug(f"SafetyGuard: Granted immunity to critical process '{comm}' (PID {pid})")
                    return True

        except FileNotFoundError:
            # The process died in the microsecond between the violation and this check.
            # Fail-safe: consider it protected so we don't crash trying to throttle a ghost.
            return True
        except Exception as e:
            logger.warning(f"SafetyGuard: Failed to inspect PID {pid}: {e}. Defaulting to immune.")
            return True  # Fail-safe mode

        # If it survives all checks, it is a normal user-space app. No immunity.
        return False

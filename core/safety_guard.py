"""
core/safety_guard.py

Zero-Trust Policy Engine.
Defines strict system boundaries to prevent SENTRY auto-immune deadlocks.
"""

import os

class SafetyGuard:
    def __init__(self) -> None:
        # Protect our own running daemon dynamically, not via a blanket string match
        self.sentry_pid = os.getpid()
        
        # Critical system infrastructure that must NEVER be throttled
        # We removed broad application names (like browsers, docker, python) 
        # so SENTRY can do its actual job.
        # Includes Priority Inversion protection for critical IPC daemons.
        self.infrastructure_immunity = {
            "systemd", "dbus-daemon", "Xorg", "wayland", "sway",
            "hyprland", "gnome-shell", "kwin_wayland",
            "xdg-desktop-po", "xdg-document-po",
            "sshd", "pipewire", "wireplumber", "pulseaudio",
            "systemd-resolve",  # systemd-resolved (15-char truncation in /proc/pid/comm)
        }

    def is_immune(self, pid: int) -> bool:
        """Return True if process should NEVER be throttled."""
        if pid <= 0:
            return True

        # 1. Absolute Self-Preservation Check
        if pid == self.sentry_pid:
            return True

        try:
            # 2. Infrastructure Check (15 chars max)
            with open(f"/proc/{pid}/comm", "r") as f:
                comm = f.read().strip()

            if comm in self.infrastructure_immunity:
                return True

            return False

        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            # CRITICAL FIX: On ANY error, return False.
            # Do not grant immunity to unreadable ghosts.
            return False

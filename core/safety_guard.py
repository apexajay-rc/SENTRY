"""
core/safety_guard.py

Zero-Trust Policy Engine.
Defines strict system boundaries to prevent SENTRY auto-immune deadlocks.

CRITICAL FIX: On error reading /proc, return False (NOT immune).
The old code returned True on error, granting immunity to unreadable processes.
"""

import os

class SafetyGuard:
    def __init__(self) -> None:
        # Critical system infrastructure that must NEVER be throttled
        # Use exact 15-char comm names (Linux truncates to 15)
        self.infrastructure_immunity = {
            "systemd", "dbus-daemon", "Xorg", "wayland", "sway",
            "hyprland", "gnome-shell", "kwin_wayland",
            "xdg-desktop-po", "xdg-document-po",
            "docker", "containerd", "dockerd", "grafana",
            "sshd", "pipewire", "wireplumber", "pulseaudio",
            "sentry", "python3",
            "firefox", "chrome", "chromium", "brave",
            "gnome-terminal", "alacritty", "kitty", "wezterm",
        }

    def is_immune(self, pid: int) -> bool:
        """Return True if process should NEVER be throttled."""
        if pid <= 0:
            return True

        try:
            # 1. Primary check: comm name (15 chars max)
            with open(f"/proc/{pid}/comm", "r") as f:
                comm = f.read().strip()

            if comm in self.infrastructure_immunity:
                return True

            # 2. Deep check: cmdline for browser children (Web Content, GPU, etc.)
            with open(f"/proc/{pid}/cmdline", "r") as f:
                cmdline = f.read().replace('\0', ' ').lower()

            critical_parents = ["firefox", "chrome", "chromium", "brave", "code", "cursor"]
            for app in critical_parents:
                if app in cmdline:
                    return True

            return False

        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            # CRITICAL FIX: On ANY error (process gone, no perms, etc.),
            # return False (NOT immune). 
            # Old code returned True, granting immunity to ghosts/malware.
            return False
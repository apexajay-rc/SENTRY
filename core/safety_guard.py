"""
core/safety_guard.py

The Zero-Trust Policy Engine.
Defines strict system boundaries to prevent SENTRY auto-immune deadlocks.
"""

import os

class SafetyGuard:
    def __init__(self) -> None:
        # Critical system infrastructure that must NEVER be throttled
        self.infrastructure_immunity = {
            "systemd", "dbus-daemon", "Xorg", "wayland", 
            "sway", "hyprland", "gnome-shell", "kwin_wayland",
            "xdg-desktop-por", "xdg-desktop-portal-gnome", "xdg-document-po",
            "docker", "containerd", "dockerd", "grafana",
            "sshd", "pipewire", "wireplumber", "pulseaudio",
            "sentry", "python3" # Do not clamp the daemon itself
        }

    def is_immune(self, pid: int) -> bool:
        if pid <= 0:
            return True
            
        try:
            with open(f"/proc/{pid}/comm", "r") as f:
                comm = f.read().strip()
                
            # Truncate check for Linux 15-char comm limit
            for immune_proc in self.infrastructure_immunity:
                if comm == immune_proc or comm == immune_proc[:15]:
                    return True
            return False
            
        except (FileNotFoundError, ProcessLookupError):
            # Fail-safe: If we can't read it, assume it is critical OS infrastructure
            return True

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
            "sentry", "python3", # Do not clamp the daemon itself
            "firefox", "chrome", "chromium", "brave", # Protect primary browser threads
            "gnome-terminal", "alacritty", "kitty", "wezterm" # Protect terminals
        }

    def is_immune(self, pid: int) -> bool:
        if pid <= 0:
            return True
            
        try:
            # 1. Primary check: The base command name (max 15 chars in Linux)
            with open(f"/proc/{pid}/comm", "r") as f:
                comm = f.read().strip()
                
            for immune_proc in self.infrastructure_immunity:
                if comm == immune_proc or comm == immune_proc[:15]:
                    return True
            
            # 2. Deep check: Web browsers spawn child processes (e.g., "Web Content")
            # We must check the actual execution command line to prevent friendly fire.
            with open(f"/proc/{pid}/cmdline", "r") as f:
                cmdline = f.read().replace('\0', ' ').lower()
                
            critical_parent_apps = ["firefox", "chrome", "chromium", "brave", "code", "cursor"]
            for app in critical_parent_apps:
                if app in cmdline:
                    return True
                    
            return False
            
        except (FileNotFoundError, ProcessLookupError):
            # Fail-safe: If we can't read it, assume it is critical OS infrastructure
            return True

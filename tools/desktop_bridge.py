#!/usr/bin/env python3
"""
tools/desktop_bridge.py

A universal user-space telemetry agent.
Dynamically detects X11 vs. Wayland (KDE, Hyprland, Sway, GNOME) to locate
the actively focused window PID and beam it to SENTRY's Ring 0 SafetyGuard.
"""

import os
import subprocess
import time
import socket
import logging
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

SENTRY_PORT = 50505
UDP_IP = "127.0.0.1"

class UniversalDesktopResolver:
    def __init__(self):
        self.session_type = os.environ.get("XDG_SESSION_TYPE", "x11").lower()
        self.desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        logging.info(f"Environment Detected -> Session: [{self.session_type}], Desktop: [{self.desktop}]")

    def get_active_pid(self):
        """Routes the PID query to the correct compositor backend."""
        try:
            if "hyprland" in self.desktop:
                return self._get_hyprland_pid()
            elif "sway" in self.desktop or "i3" in self.desktop:
                return self._get_sway_pid()
            elif self.session_type == "wayland" and "kde" in self.desktop:
                return self._get_kde_wayland_pid()
            else:
                # Fallback for X11, XWayland, and standard EWMH compliant desktops
                return self._get_xdotool_pid()
        except Exception:
            return None

    def _get_xdotool_pid(self):
        """Standard X11 / XWayland query using xdotool."""
        try:
            win_id = subprocess.check_output(['xdotool', 'getactivewindow'], stderr=subprocess.DEVNULL).decode().strip()
            pid = subprocess.check_output(['xdotool', 'getwindowpid', win_id], stderr=subprocess.DEVNULL).decode().strip()
            return int(pid) if pid.isdigit() else None
        except subprocess.CalledProcessError:
            return None

    def _get_kde_wayland_pid(self):
        """KDE Plasma Wayland query using kdotool."""
        try:
            win_id = subprocess.check_output(['kdotool', 'getactivewindow'], stderr=subprocess.DEVNULL).decode().strip()
            pid = subprocess.check_output(['kdotool', 'getwindowpid', win_id], stderr=subprocess.DEVNULL).decode().strip()
            return int(pid) if pid.isdigit() else None
        except FileNotFoundError:
            logging.debug("kdotool not installed. Falling back to xdotool.")
            return self._get_xdotool_pid()
        except subprocess.CalledProcessError:
            return None

    def _get_hyprland_pid(self):
        """Hyprland native IPC query via hyprctl."""
        try:
            output = subprocess.check_output(['hyprctl', 'activewindow', '-j'], stderr=subprocess.DEVNULL).decode()
            data = json.loads(output)
            pid = data.get("pid")
            return int(pid) if pid and int(pid) > 0 else None
        except Exception:
            return None

    def _get_sway_pid(self):
        """Sway / i3 native IPC query via swaymsg."""
        try:
            output = subprocess.check_output(['swaymsg', '-t', 'get_tree'], stderr=subprocess.DEVNULL).decode()
            tree = json.loads(output)
            
            # DFS search for the focused node
            def find_focused(node):
                if node.get("focused") and node.get("pid"):
                    return node.get("pid")
                for child in node.get("nodes", []) + node.get("floating_nodes", []):
                    res = find_focused(child)
                    if res: return res
                return None
                
            pid = find_focused(tree)
            return int(pid) if pid else None
        except Exception:
            return None

def main():
    print("=====================================================")
    print("  SENTRY Universal Desktop Telemetry Bridge v2.0     ")
    print("=====================================================")
    
    resolver = UniversalDesktopResolver()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    last_pid = None
    
    print(f"📡 Beaming spatial telemetry to SENTRY on UDP {SENTRY_PORT}...\n")
    
    while True:
        active_pid = resolver.get_active_pid()
        
        # Only beam a network packet if the user actually shifted their gaze
        if active_pid and active_pid != last_pid:
            try:
                sock.sendto(str(active_pid).encode(), (UDP_IP, SENTRY_PORT))
                logging.info(f"🎯 Gaze Shift Detected -> Active Foreground PID: {active_pid}")
                last_pid = active_pid
            except Exception as e:
                logging.error(f"Failed to transmit UDP heartbeat to SENTRY: {e}")
                
        time.sleep(0.3)  # 300ms polling rate (Zero measurable CPU overhead)

if __name__ == "__main__":
    main()

"""
core/safety_guard.py

The immunity system for SENTRY.
Prevents the daemon from accidentally throttling critical system infrastructure,
kernel threads, and dynamically protects the user's active foreground window
AND all of its child processes.
"""

import os
import logging
import socket
import threading
from typing import Set

logger = logging.getLogger(__name__)

class SafetyGuard:
    def __init__(self, vip_config_path="/etc/sentry/vips.txt"):
        # The absolute minimum OS lifelines (Unbreakable)
        self.core_system_daemons: Set[str] = {
            "systemd", "sshd", "dbus-daemon", "dbus-broker",
            "NetworkManager", "Xorg", "Xwayland", "gnome-shell",
            "kwin_wayland", "python3", "sudo"
        }
        
        # The User-Defined / Dynamic VIP List
        self.user_vip_list: Set[str] = set()
        self.vip_config_path = vip_config_path
        
        # Spatial Immunity State
        self.active_foreground_pid = None
        self.bridge_port = 50505
        
        self._load_user_vips()
        self._start_telemetry_bridge()

    def _load_user_vips(self):
        """Loads user-defined VIPs from a configuration file."""
        if os.path.exists(self.vip_config_path):
            try:
                with open(self.vip_config_path, "r") as f:
                    for line in f:
                        app = line.strip()
                        if app and not app.startswith("#"):
                            self.user_vip_list.add(app)
                logger.info(f"SafetyGuard: Loaded {len(self.user_vip_list)} user-defined VIPs.")
            except Exception as e:
                logger.error(f"SafetyGuard: Failed to load VIP config: {e}")

    def _start_telemetry_bridge(self):
        """Spins up a lightweight background thread to receive active PID updates."""
        def _listen():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('127.0.0.1', self.bridge_port))
            logger.info(f"SafetyGuard: Telemetry bridge listening on UDP port {self.bridge_port}")
            
            while True:
                try:
                    data, _ = sock.recvfrom(1024)
                    pid_str = data.decode('utf-8').strip()
                    if pid_str.isdigit():
                        new_pid = int(pid_str)
                        if new_pid != self.active_foreground_pid:
                            self.active_foreground_pid = new_pid
                            logger.info(f"Spatial Context Updated: PID {self.active_foreground_pid} (and children) granted absolute foreground immunity.")
                except Exception as e:
                    logger.error(f"SafetyGuard Telemetry error: {e}")

        # Run this as a daemon thread so it shuts down when SENTRY stops
        listener_thread = threading.Thread(target=_listen, daemon=True)
        listener_thread.start()

    def _is_descendant_of_foreground(self, target_pid: int) -> bool:
        """
        Crawls up the /proc tree to see if the target_pid is a child, 
        grandchild, etc., of the currently active foreground window.
        """
        if not self.active_foreground_pid:
            return False
            
        current_pid = target_pid
        
        # Climb the tree until we hit init (1) or the active foreground window
        while current_pid > 1:
            if current_pid == self.active_foreground_pid:
                return True
                
            try:
                with open(f"/proc/{current_pid}/stat", "r") as f:
                    stat_data = f.read()
                    
                    # /proc/[pid]/stat format: pid (comm) state ppid pgrp ...
                    # Process names can contain spaces and parentheses, which breaks naive splitting.
                    # We find the LAST parenthesis to safely extract the PPID (which is field index 3)
                    end_of_comm = stat_data.rfind(')')
                    if end_of_comm == -1:
                        break  # Corrupted stat file
                        
                    # Skip the ") " and split the remaining fields
                    # fields[0] = state, fields[1] = PPID
                    fields = stat_data[end_of_comm + 2:].split()
                    ppid = int(fields[1])
                    
                    # Move up the tree
                    current_pid = ppid
                    
            except (FileNotFoundError, IndexError, ValueError):
                # The process died while we were reading its tree, or parsing failed.
                break
                
        return False

    def is_protected(self, pid: int) -> bool:
        """Evaluates a PID against system stability and spatial context rules."""
        
        # PILLAR 1: Spatial Context (The Flow State Guard)
        # Check if it IS the active window, OR a descendant process of it.
        if pid == self.active_foreground_pid or self._is_descendant_of_foreground(pid):
            logger.info(f"SafetyGuard: Absolute Spatial Immunity invoked for PID {pid}")
            return True

        # Rule 1: The Root Law
        if pid <= 1:
            return True

        try:
            # Rule 2: The Kernel Law
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read()
                if not cmdline:
                    return True

            # Rule 3: The VIP Law
            with open(f"/proc/{pid}/comm", "r") as f:
                comm = f.read().strip()
                if comm in self.core_system_daemons or comm in self.user_vip_list:
                    logger.debug(f"SafetyGuard: Granted immunity to VIP process '{comm}' (PID {pid})")
                    return True

        except FileNotFoundError:
            return True
        except Exception as e:
            logger.warning(f"SafetyGuard: Failed to inspect PID {pid}: {e}. Defaulting to immune.")
            return True

        return False

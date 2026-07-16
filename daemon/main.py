#!/usr/bin/env python3
"""
daemon/main.py

The Production-Grade Composition Root for SENTRY.
Orchestrates eBPF, PSI, Cgroups, Zero-Trust Spatial Immunity, and UDP IPC.
"""

import sys
import time
import signal
import traceback
import socket
import json
from typing import Optional, Any

from core.logger import StructuredLogger
from core.cgroup_manager import CgroupManager
from core.safety_guard import SafetyGuard
from core.psi_sensor import PSISensor
from core.config import SentryConfig

try:
    from core.bpf_sensor import BPFSensor
    _BPF_AVAILABLE = True
except ImportError:
    _BPF_AVAILABLE = False


class SentryDaemon:
    def __init__(self) -> None:
        self.logger = StructuredLogger(name="SENTRY_DAEMON")
        
        # 1. Configuration
        self.config: Any = None
        try:
            self.config = SentryConfig("sentry_config.yaml")  # type: ignore
        except TypeError:
            self.config = SentryConfig()  # type: ignore
        except Exception:
            self.config = None

        self.mem_clamp_bytes = self._get_cfg_val("memory_clamp_bytes", 52428800)  # 50MB
        self.cooldown_sec = self._get_cfg_val("cooldown_seconds", 60)
        
        # 2. Core Subsystems
        self.cgroup_mgr = CgroupManager(self.logger)
        self.safety_guard = SafetyGuard()
        self.psi_sensor = PSISensor(threshold=5.0)
        
        self.bpf_sensor: Optional[Any] = None
        if _BPF_AVAILABLE:
            try:
                self.bpf_sensor = BPFSensor()  # type: ignore
            except Exception as e:
                self.logger.error(f"Failed to initialize BPFSensor: {e}")
        
        # 3. Inter-Process Communication (IPC) Sockets
        self.spatial_pid: Optional[int] = None
        
        # Socket for receiving Spatial Telemetry from desktop_bridge.py
        self.bridge_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.bridge_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.bridge_sock.bind(("127.0.0.1", 50505))
        self.bridge_sock.setblocking(False)

        # Socket for transmitting state to sentry_top.py HUD
        self.hud_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.hud_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.hud_sock.bind(("127.0.0.1", 50506))
        self.hud_sock.setblocking(False)
        
        self.running = True
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)

    def _get_cfg_val(self, key: str, default: int) -> int:
        if self.config is None:
            return default
        try:
            if hasattr(self.config, "get") and callable(self.config.get):
                return int(self.config.get(key, default))
            if hasattr(self.config, key):
                return int(getattr(self.config, key))
            if hasattr(self.config, "config") and isinstance(self.config.config, dict):
                return int(self.config.config.get(key, default))
            return int(self.config[key])
        except Exception:
            return default

    def _process_ipc(self, now: float) -> None:
        """Non-blocking read of IPC sockets to sync with user-space tools."""
        # 1. Read Spatial VIP target from desktop_bridge
        try:
            while True:
                data, _ = self.bridge_sock.recvfrom(1024)
                pid_str = data.decode().strip()
                if pid_str.isdigit():
                    self.spatial_pid = int(pid_str)
        except BlockingIOError:
            pass
        except Exception as e:
            self.logger.error(f"Bridge IPC error: {e}")

        # 2. Respond to sentry_top.py dashboard pings
        try:
            while True:
                data, addr = self.hud_sock.recvfrom(1024)
                if data == b"STATUS":
                    throttled = []
                    # Robust state assembly
                    if hasattr(self.cgroup_mgr, 'throttled_tasks'):
                        for t_pid, (s_time, exp) in self.cgroup_mgr.throttled_tasks.items():
                            throttled.append({"pid": t_pid, "time_left": max(0.0, float(exp - now))})
                    
                    state = {
                        "spatial_pid": self.spatial_pid,
                        "throttled_tasks": throttled
                    }
                    self.hud_sock.sendto(json.dumps(state).encode(), addr)
        except BlockingIOError:
            pass
        except Exception as e:
            self.logger.error(f"HUD IPC error: {e}")

    def shutdown(self, signum: Any = None, frame: Any = None) -> None:
        self.logger.warning("SIGTERM/SIGINT received. Initiating fail-safe shutdown.")
        self.running = False
        self.cgroup_mgr.release_all()
        try:
            self.bridge_sock.close()
            self.hud_sock.close()
        except Exception:
            pass
        self.logger.info("All Ring-0 limits released. SENTRY going dark.")
        sys.exit(0)

    def run(self) -> None:
        self.logger.info("SENTRY Ring-0 Daemon online. Event loop armed.")
        
        if not self.psi_sensor.is_supported:
            self.logger.error("Kernel PSI not detected. Run kernel with psi=1.")
            
        if self.bpf_sensor is not None:
            self.logger.info("Initializing Ring-0 eBPF Sensor...")
            try:
                self.bpf_sensor.start()
            except Exception as e:
                self.logger.error(f"Failed to start eBPF Sensor: {e}")
        
        while self.running:
            try:
                now = time.time()
                
                # 1. Housekeeping
                self._process_ipc(now)
                self.cgroup_mgr.reconcile_cooldowns(now)
                
                # 2. Memory Defense (PSI Stalls)
                if self.psi_sensor.check_memory_pressure():
                    hog_pid = self.psi_sensor.find_largest_memory_hog()
                    
                    if hog_pid > 0 and not self.cgroup_mgr.is_throttled(hog_pid):
                        if hog_pid == self.spatial_pid:
                            self.logger.info(f"Spatial VIP Immunity protecting active PID {hog_pid}.")
                        elif not self.safety_guard.is_immune(hog_pid):
                            self.cgroup_mgr.apply_memory_throttle(hog_pid, self.mem_clamp_bytes)
                            self.cgroup_mgr.register_throttle(hog_pid, now + self.cooldown_sec)

                # 3. CPU Defense (eBPF)
                if self.bpf_sensor is not None:
                    top_cpu_hogs = self.bpf_sensor.get_top_hogs()
                    for pid in top_cpu_hogs:
                        if not self.cgroup_mgr.is_throttled(pid):
                            if pid == self.spatial_pid:
                                self.logger.info(f"Spatial VIP Immunity protecting active PID {pid}.")
                            elif not self.safety_guard.is_immune(pid):
                                self.logger.warning(f"Throttling CPU hog PID: {pid}")
                                self.cgroup_mgr.apply_cpu_throttle(pid, 20)
                                self.cgroup_mgr.register_throttle(pid, now + self.cooldown_sec)
                
                time.sleep(0.2)  # Reduced to 200ms for smoother HUD updates
                
            except Exception as e:
                self.logger.error(f"Critical Event Loop Failure: {e}")
                self.logger.error(traceback.format_exc())
                time.sleep(2)

if __name__ == "__main__":
    import os
    if os.geteuid() != 0:
        print("FATAL: SENTRY must be executed with root privileges (sudo).")
        sys.exit(1)
        
    daemon = SentryDaemon()
    daemon.run()

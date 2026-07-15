#!/usr/bin/env python3
"""
daemon/main.py

The Production-Grade Composition Root for SENTRY.
Orchestrates eBPF, PSI, Cgroups, and Zero-Trust Spatial Immunity.
"""

import sys
import time
import signal
import traceback
from typing import Optional, Any

from core.logger import StructuredLogger
from core.cgroup_manager import CgroupManager
from core.safety_guard import SafetyGuard
from core.psi_sensor import PSISensor
from core.config import SentryConfig

try:
    from core.bpf_sensor import BPFSensor  # type: ignore
except ImportError:
    BPFSensor = None  # Fail gracefully if BCC tools are missing in CI

class SentryDaemon:
    def __init__(self) -> None:
        # 1. Initialize Audit Logging
        self.logger = StructuredLogger(name="SENTRY_DAEMON")
        
        # 2. Configuration (Fallback defaults if YAML is missing)
        self.config = SentryConfig(config_path="sentry_config.yaml")
        self.mem_clamp_bytes = int(self.config.get("memory_clamp_bytes", 52428800))  # 50MB
        self.cooldown_sec = int(self.config.get("cooldown_seconds", 60))
        
        # 3. Core Subsystems
        self.cgroup_mgr = CgroupManager(self.logger)
        self.safety_guard = SafetyGuard()
        self.psi_sensor = PSISensor(threshold=5.0)
        self.bpf_sensor: Optional[Any] = BPFSensor() if BPFSensor else None
        
        self.running = True
        
        # Register graceful shutdown hooks
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)

    def shutdown(self, signum: Any = None, frame: Any = None) -> None:
        self.logger.warning("SIGTERM/SIGINT received. Initiating fail-safe shutdown.")
        self.running = False
        self.cgroup_mgr.release_all()
        self.logger.info("All Ring-0 limits released. SENTRY going dark.")
        sys.exit(0)

    def process_cooldowns(self, current_time: float) -> None:
        """Releases processes whose penalty time has expired."""
        expired_pids = []
        for pid, unlock_time in self.cgroup_mgr.throttled_tasks.items():
            if current_time >= unlock_time:
                expired_pids.append(pid)
                
        for pid in expired_pids:
            self.cgroup_mgr.release_memory_throttle(pid)
            del self.cgroup_mgr.throttled_tasks[pid]

    def run(self) -> None:
        self.logger.info("SENTRY Ring-0 Daemon online. Event loop armed.")
        
        if not self.psi_sensor.is_supported:
            self.logger.error("Kernel PSI not detected. Run kernel with psi=1.")
            
        if self.bpf_sensor:
            self.logger.info("Initializing Ring-0 eBPF Sensor...")
            self.bpf_sensor.start()
        
        while self.running:
            try:
                now = time.time()
                
                # 1. Housekeeping: Release expired penalties
                self.process_cooldowns(now)
                
                # 2. Memory Defense (Phase 2 Roadmap)
                if self.psi_sensor.check_memory_pressure():
                    hog_pid = self.psi_sensor.find_largest_memory_hog()
                    
                    if hog_pid > 0 and hog_pid not in self.cgroup_mgr.throttled_tasks:
                        if not self.safety_guard.is_immune(hog_pid):
                            # Lock it down
                            self.cgroup_mgr.apply_memory_throttle(hog_pid, self.mem_clamp_bytes)
                            self.cgroup_mgr.throttled_tasks[hog_pid] = now + self.cooldown_sec
                        else:
                            self.logger.info(f"PSI Spike detected, but PID {hog_pid} has infrastructure immunity.")

                # 3. CPU Defense (eBPF)
                if self.bpf_sensor:
                    top_cpu_hogs = self.bpf_sensor.get_top_hogs()
                    for pid in top_cpu_hogs:
                        if pid not in self.cgroup_mgr.throttled_tasks and not self.safety_guard.is_immune(pid):
                            self.logger.warning(f"Throttling CPU hog PID: {pid}")
                            self.cgroup_mgr._apply_scheduler_fallback(pid)
                            self.cgroup_mgr.throttled_tasks[pid] = now + self.cooldown_sec
                
                time.sleep(1)  # Base polling cadence
                
            except Exception as e:
                self.logger.error(f"Critical Event Loop Failure: {e}")
                self.logger.error(traceback.format_exc())
                time.sleep(2)  # Backoff to prevent log flooding

if __name__ == "__main__":
    import os
    if os.geteuid() != 0:
        print("FATAL: SENTRY must be executed with root privileges (sudo).")
        sys.exit(1)
        
    daemon = SentryDaemon()
    daemon.run()

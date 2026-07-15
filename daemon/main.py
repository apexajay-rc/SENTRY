"""
daemon/main.py

Refactored Composition Root for SENTRY.
This version integrates the eBPF sensor and Cgroup manager to create
a functional resource enforcement loop.
"""

import logger
import signal
import sys
import time
from core.config import SentryConfig
from core.cgroup_manager import CgroupManager
from core.safety_guard import SafetyGuard
from core.bpf_sensor import BPFSensor
from core.logging import StructuredLogger

# Setup structured audit logging
logger = StructuredLogger(name="SENTRY_DAEMON")

class SentryDaemon:
    def __init__(self):
        # 1. Initialize Configuration
        self.config = SentryConfig(config_path="sentry_config.yaml")
        
        # 2. Initialize Core Infrastructure
        self.cgroup_mgr = CgroupManager()
        self.safety_guard = SafetyGuard()
        self.bpf_sensor = BPFSensor()
        
        # 3. State
        self.running = True
        self.threshold = self.config.get("memory_clamp_bytes", 500000000)
        self.cooldown = self.config.get("cooldown_seconds", 60)
        
        # Register signals for clean exit
        signal.signal(signal.SIGTERM, self.handle_exit)
        signal.signal(signal.SIGINT, self.handle_exit)

    def handle_exit(self, signum, frame):
        logger.warning("Shutdown signal received. Releasing all throttles...")
        self.cgroup_mgr.release_all()
        self.running = False
        sys.exit(0)

    def run_loop(self):
        logger.info("Initializing Ring-0 eBPF Sensor...")
        self.bpf_sensor.start()
        logger.info("SENTRY Daemon Event Loop Active.")
        
        while self.running:
            try:
                # 1. Collect PIDs exceeding CPU thresholds via eBPF
                top_hogs = self.bpf_sensor.get_top_hogs(threshold_ns=self.threshold)
                
                # 2. Process mitigations
                for pid in top_hogs:
                    if self.safety_guard.is_immune(pid):
                        logger.info(f"Process {pid} granted immunity. Skipping.")
                        continue
                        
                    logger.warning(f"Throttling hog PID: {pid}")
                    self.cgroup_mgr.apply_throttle(pid)
                
                # 3. Check for cooldown expirations
                self.cgroup_mgr.reconcile_cooldowns(self.cooldown)
                
                time.sleep(1) # Polling interval
                
            except Exception as e:
                logger.error(f"Event Loop Exception: {e}")
                time.sleep(5) # Backoff on error

if __name__ == "__main__":
    daemon = SentryDaemon()
    daemon.run_loop()

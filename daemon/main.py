"""
daemon/main.py

Refactored Composition Root for SENTRY.
This version enforces the integration of core modules and replaces
hardcoded literals with configuration-driven logic.
"""

import logging
import signal
import sys
from core.config import SentryConfig
from core.cgroup_manager import CgroupManager
from core.safety_guard import SafetyGuard
from core.logging import StructuredLogger # Assuming we move to structured logging

# Setup structured audit logging
logger = StructuredLogger(name="SENTRY_DAEMON")

class SentryDaemon:
    def __init__(self):
        # 1. Initialize Configuration
        self.config = SentryConfig(config_path="sentry_config.yaml")
        
        # 2. Initialize Core Infrastructure
        self.cgroup_mgr = CgroupManager()
        self.safety_guard = SafetyGuard()
        
        # 3. State
        self.running = True
        
        # Register signals for clean exit
        signal.signal(signal.SIGTERM, self.handle_exit)
        signal.signal(signal.SIGINT, self.handle_exit)

    def handle_exit(self, signum, frame):
        logger.warning("Shutdown signal received. Releasing all throttles...")
        self.cgroup_mgr.release_all()
        self.running = False
        sys.exit(0)

    def run_loop(self):
        logger.info("SENTRY Daemon Event Loop Active.")
        while self.running:
            try:
                # Placeholder for the eBPF/PSI sensor integration
                # This is where we will inject the BPF event loop
                pass 
            except Exception as e:
                logger.error(f"Event Loop Exception: {e}")

if __name__ == "__main__":
    daemon = SentryDaemon()
    daemon.run_loop()

"""
daemon/main.py

The main entry point for the SENTRY daemon.
Orchestrates the event-driven control loop, handles OS signals,
and manages systemd integration.
"""

import sys
import time
import signal
import logging
from typing import Set

from core.collectors.epoll_events import EpollReactor
from core.collectors.psi import PsiMonitor
from core.cgroup_manager import CgroupManager
from core.safety_guard import SafetyGuard
from daemon.systemd_integration import SystemdNotifier
# Note: Assuming you have an existing engine module to select targets
# from engine.selector import select_target

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SentryDaemon:
    def __init__(self):
        self.notifier = SystemdNotifier()
        self.cgroup_mgr = CgroupManager()
        self.safety_guard = SafetyGuard()
        self.psi_monitor = PsiMonitor()
        self.reactor = EpollReactor()
        
        self._running = False
        self._throttled_pids: Set[int] = set()
        
        # Configuration (Could be loaded via your core.config)
        self.memory_throttle_limit = "500M" 
        self.watchdog_interval = 5.0 # seconds

    def _handle_shutdown_signal(self, signum, frame):
        """Catches SIGTERM/SIGINT for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received signal {sig_name}. Initiating graceful shutdown...")
        self._running = False

    def _apply_mitigation(self):
        """
        Invoked when pressure crosses thresholds. 
        Selects a target and applies cgroup limits.
        """
        logger.info("Kernel reported resource pressure. Evaluating targets...")
        
        # NOTE: This is where you call your existing selector logic.
        # For demonstration, we assume a function `select_target()` returns a PID.
        # target_pid = select_target()
        target_pid = None # Placeholder
        
        if not target_pid:
            logger.debug("No valid targets found for mitigation.")
            return

        if self.safety_guard.is_protected(target_pid):
            logger.warning(f"Target PID {target_pid} is protected. Bailing out.")
            return

        logger.info(f"Applying memory throttle to PID {target_pid}")
        success = self.cgroup_mgr.throttle_memory(target_pid, self.memory_throttle_limit)
        
        if success:
            self._throttled_pids.add(target_pid)

    def _pressure_callback(self, fd: int, event_mask: int):
        """Callback triggered by the EpollReactor when PSI fires."""
        self._apply_mitigation()

    def run(self):
        """Main daemon execution loop."""
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)

        self._running = True
        last_watchdog_ping = time.time()

        try:
            # 1. Register PSI Triggers
            # Example: Trigger if memory stalls for 500ms within a 1-second window
            mem_fd = self.psi_monitor.create_trigger("memory", "some", 500000, 1000000)
            self.reactor.register(mem_fd, self._pressure_callback)

            # 2. Signal Readiness
            logger.info("SENTRY daemon initialized successfully.")
            self.notifier.ready()

            # 3. Main Event Loop
            while self._running:
                # Block for up to 1 second waiting for kernel events
                self.reactor.poll(timeout=1.0)
                
                # Ping systemd watchdog
                now = time.time()
                if now - last_watchdog_ping >= self.watchdog_interval:
                    self.notifier.ping_watchdog()
                    last_watchdog_ping = now

        except Exception as e:
            logger.exception(f"Fatal error in main loop: {e}")
            sys.exit(1)
        finally:
            self.cleanup()

    def cleanup(self):
        """Reverts limits, closes FDs, and signals shutdown."""
        self.notifier.stopping()
        logger.info("Reverting applied mitigations...")
        
        for pid in list(self._throttled_pids):
            self.cgroup_mgr.reset_memory_throttle(pid)
            
        self.reactor.close()
        self.psi_monitor.cleanup_all()
        logger.info("SENTRY shutdown complete.")

if __name__ == "__main__":
    daemon = SentryDaemon()
    daemon.run()

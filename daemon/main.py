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

from core.collectors.epoll_events import EpollReactor
from core.collectors.psi import PsiMonitor
from core.cgroup_manager import CgroupManager
from core.safety_guard import SafetyGuard
from daemon.systemd_integration import SystemdNotifier
from engine.reconciliation import StateReconciler
from engine.selector import TargetSelector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SentryDaemon:
    def __init__(self):
        # 1. System Plumbing
        self.notifier = SystemdNotifier()
        self.reactor = EpollReactor()
        self.psi_monitor = PsiMonitor()
        
        # 2. Execution & Safety
        self.cgroup_mgr = CgroupManager()
        self.safety_guard = SafetyGuard()
        
        # 3. Intelligence & State
        self.selector = TargetSelector()
        self.reconciler = StateReconciler()
        
        # 4. State variables
        self._running = False
        
        # 5. Configuration Limits
        self.memory_throttle_limit = "500M" 
        self.watchdog_interval = 5.0    # Seconds between systemd pings
        self.cooldown_period = 60.0     # Seconds before lifting cgroup limits

    def _handle_shutdown_signal(self, signum, frame):
        """Catches SIGTERM/SIGINT for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received signal {sig_name}. Initiating graceful shutdown...")
        self._running = False

    def _apply_mitigation(self):
        """Invoked when pressure crosses thresholds. Evaluates and throttles."""
        logger.info("Kernel reported resource pressure. Evaluating targets...")
        
        # Ask the engine to find the heaviest memory consumer
        target_pid = self.selector.select_target()
        
        if not target_pid:
            logger.debug("No valid targets found for mitigation.")
            return

        if self.safety_guard.is_protected(target_pid):
            logger.warning(f"Target PID {target_pid} is protected by SafetyGuard. Bailing out.")
            return

        # Don't re-throttle a process that is already in the penalty box
        if self.reconciler.is_tracked(target_pid):
            logger.debug(f"PID {target_pid} is already throttled. Skipping.")
            return

        cgroup_path = self.cgroup_mgr.get_process_cgroup(target_pid)
        if not cgroup_path:
            logger.warning(f"Could not resolve cgroup for PID {target_pid}. Cannot throttle.")
            return

        logger.info(f"Applying memory throttle to PID {target_pid}")
        success = self.cgroup_mgr.throttle_memory(target_pid, self.memory_throttle_limit)
        
        if success:
            self.reconciler.track(target_pid, cgroup_path)

    def _pressure_callback(self, fd: int, event_mask: int):
        """Callback triggered by the EpollReactor when PSI fires."""
        self._apply_mitigation()

    def _process_reconciliations(self):
        """Checks for expired throttles and safely releases them."""
        releasable_tasks = self.reconciler.get_releasable_tasks(self.cooldown_period)
        
        for task in releasable_tasks:
            current_cgroup = self.cgroup_mgr.get_process_cgroup(task.pid)
            
            # Anti-PID-Recycling Check
            if current_cgroup != task.cgroup_path:
                logger.info(
                    f"PID {task.pid} recycled or moved "
                    f"(Expected: {task.cgroup_path}, Got: {current_cgroup}). "
                    "Dropping from SENTRY state without altering cgroup limits."
                )
            else:
                logger.info(f"Cooldown expired for PID {task.pid}. Releasing throttle.")
                self.cgroup_mgr.reset_memory_throttle(task.pid)
            
            # Always remove from our tracking state
            self.reconciler.drop(task.pid)

    def run(self):
        """Main daemon execution loop."""
        # Setup UNIX signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)

        self._running = True
        last_watchdog_ping = time.time()

        try:
            # Register kernel PSI trigger (e.g., memory stalled for 500ms within a 1s window)
            mem_fd = self.psi_monitor.create_trigger("memory", "some", 500000, 1000000)
            self.reactor.register(mem_fd, self._pressure_callback)

            logger.info("SENTRY daemon initialized successfully. Entering watch state.")
            self.notifier.ready()

            while self._running:
                # Wake up at least every 5 seconds to process cooldowns, 
                # or instantly if the kernel triggers a PSI event.
                self.reactor.poll(timeout=5.0)
                
                # Check for tasks that need un-throttling
                self._process_reconciliations()
                
                # Ping systemd watchdog
                now = time.time()
                if now - last_watchdog_ping >= self.watchdog_interval:
                    status_msg = f"WATCHDOG=1\nSTATUS=Monitoring. Throttled tasks: {self.reconciler.active_count()}"
                    self.notifier.notify(status_msg)
                    last_watchdog_ping = now

        except Exception as e:
            logger.exception(f"Fatal error in main event loop: {e}")
            sys.exit(1)
        finally:
            self.cleanup()

    def cleanup(self):
        """Reverts limits, closes FDs, and signals shutdown to systemd."""
        self.notifier.stopping()
        logger.info("Initiating cleanup. Reverting applied mitigations...")
        
        # Safely release all remaining tracked tasks before exit by overriding cooldown
        for task in self.reconciler.get_releasable_tasks(cooldown_seconds=0):
            current_cgroup = self.cgroup_mgr.get_process_cgroup(task.pid)
            if current_cgroup == task.cgroup_path:
                self.cgroup_mgr.reset_memory_throttle(task.pid)
                
        # Clean up file descriptors
        self.reactor.close()
        self.psi_monitor.cleanup_all()
        logger.info("SENTRY shutdown complete.")

if __name__ == "__main__":
    daemon = SentryDaemon()
    daemon.run()

"""
daemon/main.py

The main entry point for the SENTRY daemon.
Orchestrates the event-driven control loop, handles OS signals,
integrates eBPF telemetry, and manages systemd integration.
"""

import sys
import time
import signal
import logging
import ctypes

from engine.aggregator import CPUMonitor
from bcc import BPF

from core.config import ConfigParser
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


# -------------------------------------------------------------------
# eBPF Data Structure (The Translator)
# MUST perfectly match the 'event_t' struct in sensor.bpf.c
# -------------------------------------------------------------------
class Event(ctypes.Structure):
    _fields_ = [
        ("pid", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16),
        ("duration_ns", ctypes.c_uint64)  # <-- The new 64-bit int for CPU time
    ]


class SentryDaemon:
    def __init__(self):
        # 1. Load Configuration
        self.config = ConfigParser.load()
        
        # 2. System Plumbing
        self.notifier = SystemdNotifier()
        self.reactor = EpollReactor()
        self.psi_monitor = PsiMonitor()
        self.bpf = None  # eBPF Object reference
        
        # 3. Execution & Safety
        self.cgroup_mgr = CgroupManager()
        self.safety_guard = SafetyGuard()
        
        # 4. Intelligence & State
        self.selector = TargetSelector()
        self.reconciler = StateReconciler()
        self.cpu_monitor = CPUMonitor(window_size_sec=1.0, cpu_limit_pct=85.0)
        
        # 5. State variables
        self._running = False
        
        # 6. Apply Configuration Limits
        self.memory_throttle_limit = self.config.memory_throttle_limit 
        self.watchdog_interval = self.config.watchdog_interval
        self.cooldown_period = self.config.cooldown_period

    def _handle_shutdown_signal(self, signum, frame):
        """Catches SIGTERM/SIGINT for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received signal {sig_name}. Initiating graceful shutdown...")
        self._running = False

    def _handle_bpf_event(self, ctx, data, size):
        """Callback triggered instantly when C code pushes to the Ring Buffer."""
        event = ctypes.cast(data, ctypes.POINTER(Event)).contents
        command = event.comm.decode('utf-8', 'replace').strip('\x00')
        
        # 1. Feed the burst to the Aggregator Brain
        violation_pct = self.cpu_monitor.add_burst(event.pid, event.duration_ns)
        
        # 2. If it crosses our 85% threshold, Enforce!
        if violation_pct:
            # Don't spam the throttle if it's already in the penalty box
            if self.reconciler.is_tracked(event.pid):
                return
                
            # Check the Safety Guard (don't kill sshd or systemd)
            if self.safety_guard.is_protected(event.pid):
                return
                
            logger.warning(f"🚨 CPU VIOLATION: PID {event.pid} ({command}) is at {violation_pct:.1f}% CPU!")
            
            cgroup_path = self.cgroup_mgr.get_process_cgroup(event.pid)
            if cgroup_path:
                logger.info(f"Applying strict CPU throttle (20%) to PID {event.pid}")
                
                # Apply a CPU punishment for a CPU crime!
                success = self.cgroup_mgr.throttle_cpu(event.pid, cpu_quota_pct=20)
                if success:
                    self.reconciler.track(event.pid, cgroup_path)

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

        # ---------------------------------------------------------
        # THE FIX: Swap the lethal memory throttle for a safe CPU throttle!
        # By slowing down the CPU, the process stops allocating RAM so fast,
        # allowing the OS to recover without triggering the OOM Killer.
        # ---------------------------------------------------------
        logger.info(f"Applying CPU throttle (20%) to mitigate resource pressure for PID {target_pid}")
        success = self.cgroup_mgr.throttle_cpu(target_pid, cpu_quota_pct=20)
        
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
                logger.info(f"Cooldown expired for PID {task.pid}. Releasing throttles.")
                self.cgroup_mgr.reset_memory_throttle(task.pid)
                self.cgroup_mgr.reset_cpu_throttle(task.pid)
            
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
            # 1. Initialize eBPF Sensor
            logger.info("Loading eBPF CO-RE sensor...")
            self.bpf = BPF(src_file="sensor.bpf.c")
            self.bpf["events"].open_ring_buffer(self._handle_bpf_event)

            # 2. Register kernel PSI trigger (Memory stalled for 500ms within a 1s window)
            mem_fd = self.psi_monitor.create_trigger("memory", "some", 500000, 1000000)
            self.reactor.register(mem_fd, self._pressure_callback)

            logger.info("🛡️ SENTRY daemon fully armed (eBPF + PSI active). Entering watch state.")
            self.notifier.ready()

            while self._running:
                # Tick every 200ms instead of full watchdog_interval.
                # This keeps eBPF event ingestion near real-time without burning CPU.
                self.reactor.poll(timeout=0.2)
                
                # Instantly consume any pending eBPF events from the C program
                if self.bpf:
                    try:
                        # ring_buffer_consume is non-blocking
                        self.bpf.ring_buffer_consume()
                    except AttributeError:
                        # Fallback for older BCC versions
                        self.bpf.ring_buffer_poll(0)
                
                # Check for tasks that need un-throttling
                self._process_reconciliations()
                
                # Ping systemd watchdog based on the actual interval setting
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
        """Reverts limits, closes FDs, cleans BPF, and signals shutdown to systemd."""
        self.notifier.stopping()
        logger.info("Initiating cleanup. Reverting applied mitigations...")
        
        # Safely release all remaining tracked tasks before exit by overriding cooldown
        for task in self.reconciler.get_releasable_tasks(cooldown_seconds=0):
            current_cgroup = self.cgroup_mgr.get_process_cgroup(task.pid)
            if current_cgroup == task.cgroup_path:
                self.cgroup_mgr.reset_memory_throttle(task.pid)
                self.cgroup_mgr.reset_cpu_throttle(task.pid)
                
        # Clean up file descriptors and free kernel memory
        self.reactor.close()
        self.psi_monitor.cleanup_all()
        
        if self.bpf:
            del self.bpf
            
        logger.info("SENTRY shutdown complete.")

if __name__ == "__main__":
    daemon = SentryDaemon()
    daemon.run()

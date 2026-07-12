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
import socket
import threading
import json

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
import threading
import socket
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Event(ctypes.Structure):
    _fields_ = [
        ("pid", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16),
        ("duration_ns", ctypes.c_uint64)
    ]


class SentryDaemon:
    def __init__(self):
        self.config = ConfigParser.load()
        
        self.notifier = SystemdNotifier()
        self.reactor = EpollReactor()
        self.psi_monitor = PsiMonitor()
        self.bpf = None 
        
        self.cgroup_mgr = CgroupManager()
        self.safety_guard = SafetyGuard()
        
        self.selector = TargetSelector()
        self.reconciler = StateReconciler()
        self.cpu_monitor = CPUMonitor(window_size_sec=1.0, cpu_limit_pct=85.0)
        
        self._running = False
        self.ipc_port = 50506  # Local port for sentry-top TUI
        
        self.memory_throttle_limit = self.config.memory_throttle_limit 
        self.watchdog_interval = self.config.watchdog_interval
        self.cooldown_period = self.config.cooldown_period

    def _start_ipc_server(self):
        """Ultra-lightweight background thread to serve state to sentry-top."""
        def _serve():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('127.0.0.1', self.ipc_port))
            while self._running:
                try:
                    data, addr = sock.recvfrom(1024)
                    if data == b"STATUS":
                        now = time.time()
                        tasks = []
                        # Dump the reconciler's brain
                        for pid, task in self.reconciler.active_tasks.items():
                            time_left = max(0, self.cooldown_period - (now - task.throttled_at))
                            tasks.append({
                                "pid": pid,
                                "cgroup": task.cgroup_path,
                                "time_left": time_left
                            })
                        
                        payload = {
                            "spatial_pid": self.safety_guard.active_foreground_pid,
                            "throttled_tasks": tasks
                        }
                        sock.sendto(json.dumps(payload).encode(), addr)
                except Exception:
                    pass
        
        t = threading.Thread(target=_serve, daemon=True)
        t.start()

    def _handle_shutdown_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received signal {sig_name}. Initiating graceful shutdown...")
        self._running = False

    def _handle_bpf_event(self, ctx, data, size):
        event = ctypes.cast(data, ctypes.POINTER(Event)).contents
        command = event.comm.decode('utf-8', 'replace').strip('\x00')
        
        violation_pct = self.cpu_monitor.add_burst(event.pid, event.duration_ns)
        
        if violation_pct:
            if self.reconciler.is_tracked(event.pid):
                return
                
            if self.safety_guard.is_protected(event.pid):
                return
                
            logger.warning(f"🚨 CPU VIOLATION: PID {event.pid} ({command}) is at {violation_pct:.1f}% CPU!")
            
            cgroup_path = self.cgroup_mgr.get_process_cgroup(event.pid)
            if cgroup_path:
                logger.info(f"Applying strict CPU throttle (20%) to PID {event.pid}")
                success = self.cgroup_mgr.throttle_cpu(event.pid, cpu_quota_pct=20)
                if success:
                    self.reconciler.track(event.pid, cgroup_path)

    def _apply_mitigation(self):
        logger.info("Kernel reported resource pressure. Evaluating targets...")
        target_pid = self.selector.select_target()
        
        if not target_pid:
            return

        if self.safety_guard.is_protected(target_pid) or self.reconciler.is_tracked(target_pid):
            return

        cgroup_path = self.cgroup_mgr.get_process_cgroup(target_pid)
        if not cgroup_path:
            return

        logger.info(f"Applying CPU throttle (20%) to mitigate resource pressure for PID {target_pid}")
        success = self.cgroup_mgr.throttle_cpu(target_pid, cpu_quota_pct=20)
        
        if success:
            self.reconciler.track(target_pid, cgroup_path)

    def _pressure_callback(self, fd: int, event_mask: int):
        self._apply_mitigation()

    def _process_reconciliations(self):
        releasable_tasks = self.reconciler.get_releasable_tasks(self.cooldown_period)
        
        for task in releasable_tasks:
            current_cgroup = self.cgroup_mgr.get_process_cgroup(task.pid)
            if current_cgroup != task.cgroup_path:
                logger.info(f"PID {task.pid} recycled or moved. Dropping from state.")
            else:
                logger.info(f"Cooldown expired for PID {task.pid}. Releasing throttles.")
                self.cgroup_mgr.reset_memory_throttle(task.pid)
                self.cgroup_mgr.reset_cpu_throttle(task.pid)
            
            self.reconciler.drop(task.pid)

    def run(self):
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)

        self._running = True
        self._start_ipc_server()
        last_watchdog_ping = time.time()

        try:
            logger.info("Loading eBPF CO-RE sensor...")
            self.bpf = BPF(src_file="sensor.bpf.c")
            self.bpf["events"].open_ring_buffer(self._handle_bpf_event)

            mem_fd = self.psi_monitor.create_trigger("memory", "some", 500000, 1000000)
            self.reactor.register(mem_fd, self._pressure_callback)

            logger.info("🛡️ SENTRY daemon fully armed (eBPF + PSI active). Entering watch state.")
            self.notifier.ready()

            while self._running:
                self.reactor.poll(timeout=0.2)
                
                if self.bpf:
                    try:
                        self.bpf.ring_buffer_consume()
                    except AttributeError:
                        self.bpf.ring_buffer_poll(0)
                
                self._process_reconciliations()
                
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
        self.notifier.stopping()
        logger.info("Initiating cleanup. Reverting applied mitigations...")
        
        for task in self.reconciler.get_releasable_tasks(cooldown_seconds=0):
            current_cgroup = self.cgroup_mgr.get_process_cgroup(task.pid)
            if current_cgroup == task.cgroup_path:
                self.cgroup_mgr.reset_memory_throttle(task.pid)
                self.cgroup_mgr.reset_cpu_throttle(task.pid)
                
        self.reactor.close()
        self.psi_monitor.cleanup_all()
        
        if self.bpf:
            del self.bpf
            
        logger.info("SENTRY shutdown complete.")

if __name__ == "__main__":
    daemon = SentryDaemon()
    daemon.run()

#!/usr/bin/env python3
"""
daemon/main.py

The Basecamp Architecture for SENTRY.
Restored to pure, flawless user-space polling with live telemetry.
Secured IPC sockets via SUDO_UID to prevent unprivileged PID spoofing.
Hardened v1.2: Fully Unified Architecture. Integrates the SystemMetricsSampler,
Policy Engine, and Feedback Loop for true PSI-blended stress evaluation.
"""
import pwd
import grp
import sys
import os
import time
import signal
import socket
import json
import psutil
from typing import Optional, Any, Dict, Tuple

# Inject the SENTRY root directory into Python's module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# IMMEDIATE PRIORITY ELEVATION
try:
    os.nice(-20)
except Exception:
    pass

from core.logger import StructuredLogger
from core.cgroup_manager import CgroupManager
from core.safety_guard import SafetyGuard
from core.config import SentryConfig

# --- The Unified SENTRY Intelligence Engine ---
from core.metrics import SystemMetricsSampler
from core.policy import classify_basic, get_action_limits, get_dynamic_limits
from engine.feedback import FeedbackEngine
from core.proc_scanner import ProcScanner

# --- PHASE 2 PRIVILEGE DROP HELPER ---
def drop_privileges(username: str = "sentry") -> None:
    """
    Drops root privileges to an unprivileged system user (eUID drop)
    after sockets are bound and initialization is complete.
    """
    if os.getuid() != 0:
        return  # Already running as non-root

    try:
        pw_record = pwd.getpwnam(username)
        uid = pw_record.pw_uid
        gid = pw_record.pw_gid

        # Drop supplementary groups first
        os.setgroups([])
        
        # Drop group ID, then user ID
        os.setgid(gid)
        os.setuid(uid)

        # Verify drop was successful
        if os.getuid() == 0:
            raise PermissionError("Failed to drop root privileges; UID is still 0.")
        
        print(f"[SECURITY] Sandbox Locked: Dropped privileges to '{username}' (UID: {uid})", flush=True)
    except KeyError:
        print(f"[WARNING] System user '{username}' not found. Skipping privilege drop.", flush=True)
    except Exception as e:
        print(f"[CRITICAL] Privilege drop failed: {e}", flush=True)
        sys.exit(1)
# -------------------------------------

class SentryDaemon:
    def __init__(self) -> None:
        self.logger = StructuredLogger(name="SENTRY_DAEMON")
        self.config = SentryConfig("sentry_config.yaml")
        self.cooldown_sec = self.config.cooldown_seconds
        self.feedback_engine = FeedbackEngine(self.logger)
        self.cgroup_mgr = CgroupManager(self.logger)
        self.safety_guard = SafetyGuard()
        self.proc_scanner = ProcScanner()

        # Intelligence & Feedback integration
        self.sampler = SystemMetricsSampler(interval=0.2)
        # Track state for feedback evaluation: {pid: (stress_score_before, pressure_level_before)}
        # self.active_mitigations: Dict[int, Tuple[float, str]] = {}
        self.total_sys_mem = psutil.virtual_memory().total

        self.spatial_pid: Optional[int] = None
        self.bridge_sock_path = "/run/sentry_bridge.sock"
        self.hud_sock_path = "/run/sentry_hud.sock"

        self._cleanup_sockets()

        # IPC Sockets
        self.bridge_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.bridge_sock.bind(self.bridge_sock_path)
        self.bridge_sock.setblocking(False)

        self.hud_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.hud_sock.bind(self.hud_sock_path)
        self.hud_sock.setblocking(False)

        # Secure sockets AFTER bind (post-bind helper)
        self._secure_sockets()
        drop_privileges("sentry")

        self.running = True
        self.observe_only = False
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)

    def _secure_sockets(self) -> None:
        """Apply ownership/perms AFTER bind so both daemon and user can communicate."""
        try:
            import pwd
            # Daemon needs ownership, User (1000) needs group access
            sentry_uid = pwd.getpwnam("sentry").pw_uid
            sudo_gid = int(os.environ.get("SUDO_GID", "1000"))
            
            for path in [self.bridge_sock_path, self.hud_sock_path]:
                os.chown(path, sentry_uid, sudo_gid)
                os.chmod(path, 0o660)
        except Exception as e:
            self.logger.warning(f"Could not secure IPC sockets: {e}")

    def _cleanup_sockets(self) -> None:
        for path in [self.bridge_sock_path, self.hud_sock_path]:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _sd_notify(self, state: str) -> None:
        notify_socket = os.environ.get('NOTIFY_SOCKET')
        if not notify_socket:
            return
        if notify_socket.startswith('@'):
            notify_socket = '\0' + notify_socket[1:]
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.sendto(state.encode(), notify_socket)  # type: ignore
        except Exception:
            pass

    def _process_ipc(self, now: float) -> None:
        try:
            data, _ = self.bridge_sock.recvfrom(1024)
            pid_str = data.decode().strip()
            if pid_str.isdigit():
                self.spatial_pid = int(pid_str)
        except OSError:
            pass 

        try:
            data, addr = self.hud_sock.recvfrom(1024)
            if data and addr:
                cmd = data.decode().strip()
                if cmd == "STATUS":
                    throttled = []
                    if hasattr(self.cgroup_mgr, 'throttled_tasks'):
                        for t_pid, (s_time, exp) in self.cgroup_mgr.throttled_tasks.items():
                            throttled.append({"pid": t_pid, "time_left": max(0.0, float(exp - now))})
                    
                    state = {
                        "spatial_pid": self.spatial_pid,
                        "throttled_tasks": throttled,
                        "observe_only": self.observe_only,
                        "stress_score": getattr(self, 'current_stress', 0.0),
                        "state": getattr(self, 'current_level', "UNKNOWN")
                    }
                    self.hud_sock.sendto(json.dumps(state).encode(), addr)
                elif cmd == "TOGGLE_OBSERVE":
                    self.observe_only = not self.observe_only
                    print(f"\n[INFO] SENTRY Mode Changed: Observe Only = {self.observe_only}", flush=True)
        except OSError:
            pass

    def _is_spatial_immune(self, pid: int) -> bool:
        """Shields the spatial PID and all its child rendering threads (e.g., Firefox)."""
        if self.spatial_pid is None:
            return False
        if pid == self.spatial_pid:
            return True
        try:
            parent = psutil.Process(self.spatial_pid)
            children = {c.pid for c in parent.children(recursive=True)}
            return pid in children
        except psutil.NoSuchProcess:
            return False

    def shutdown(self, signum: Any = None, frame: Any = None) -> None:
        print("\n[SHUTDOWN] SIGTERM/SIGINT received. Releasing all hardware locks...", flush=True)
        self.running = False
        self._sd_notify("STOPPING=1")
        self.cgroup_mgr.release_all()
        try:
            self.bridge_sock.close()
            self.hud_sock.close()
            self._cleanup_sockets()
        except Exception:
            pass
        print("[SHUTDOWN] SENTRY going dark. System restored to default scheduler.", flush=True)
        sys.exit(0)
        
    def run(self) -> None:
        print("\n" + "="*60, flush=True)
        print("[STARTUP] SENTRY RING-0 COMMAND DAEMON ONLINE (UNIFIED ARCHITECTURE)", flush=True)
        print("="*60 + "\n", flush=True)
        
        self.cgroup_mgr.clear_orphaned_throttles()
        self._sd_notify("READY=1\nSTATUS=SENTRY Unified Daemon online.")
        print("[INFO] SystemMetricsSampler & Feedback Engine Armed.", flush=True)
        
        while self.running:
            try:
                # Use monotonic time to survive system hibernation/NTP adjustments
                now = time.monotonic()
                action_taken = False
                self._process_ipc(now)
                
                # 1. Unified Intelligence Collection (Blocks for 200ms)
                
                metrics = self.sampler.sample_blocking()
                
                # Safely unwrap the API change from engine/pressure.py
                if isinstance(metrics.stress_score, tuple):
                    pressure_obj, stress_delta = metrics.stress_score
                    current_stress = getattr(pressure_obj, 'total', float(pressure_obj))
                else:
                    current_stress = getattr(metrics.stress_score, 'total', float(metrics.stress_score))
                    stress_delta = current_stress - getattr(self, '_prev_stress', current_stress)
                    self._prev_stress = current_stress

                # Proportional-Derivative (PD) Actuator
                limits = get_dynamic_limits(current_stress, stress_delta)
                current_level = limits.get("state", "UNKNOWN")
                self.current_stress = current_stress
                self.current_level = current_level
                #LAZY EVALUATION: Only evaluate feedback if the system is under stress
                if current_level in ["LOW","MODERATE","UNKNOWN"]:
                    time.sleep(0.8)
                else:
                    time.sleep(0.5)
                # 2. Feedback Loop Evaluation (Check expired tasks BEFORE reconcile)
                expired_pids = [p for p, (_, exp) in self.cgroup_mgr.throttled_tasks.items() if now >= exp]
                for p in expired_pids:
                    # Fire the new Causal Attribution evaluator
                    self.feedback_engine.evaluate_action(p, current_stress, current_level)

                self.cgroup_mgr.reconcile_cooldowns(now)
                
                # 3. Dynamic Execution
                if current_level in ["HIGH", "CRITICAL"]:
                    # Only scan for hogs if the unified score dictates it
                    hogs = self.proc_scanner.get_top_hogs()
                    
                    for pid in hogs:
                        if not self.cgroup_mgr.is_throttled(pid):
                            if self._is_spatial_immune(pid):
                                pass
                            elif not os.path.exists(f"/proc/{pid}"):
                                pass
                            elif not self.safety_guard.is_immune(pid):
                                action_taken = True
                                if self.observe_only:
                                    print(f"\n[OBSERVE ONLY - {current_level}] Would clamp PID {pid} to {limits['cpu_weight']}%", flush=True)
                                else:
                                    print(f"\n[ACTION] [{current_level}] Throttling hog (PID {pid}). Unified Score: {current_stress:.2f}", flush=True)
                                    self.feedback_engine.record_action(pid, current_stress, current_level, current_level)
                                    # CPU Throttle
                                    start_tick = self.cgroup_mgr.apply_cpu_throttle(pid, limits["cpu_weight"])
                                    
                                    # True Memory Limit (Percentage of Total System RAM)
                                    if limits["memory_limit_percent"] < 100:
                                        try:
                                            # Grab the exact bytes the process is currently using
                                            proc_rss = psutil.Process(pid).memory_info().rss
                                            # Calculate limit as percentage of TOTAL SYSTEM MEMORY (config intent)
                                            # This enforces system-wide memory pressure policy, not per-process squeeze
                                            mem_bytes = int(self.total_sys_mem * (limits["memory_limit_percent"] / 100.0))
                                            # SAFETY: Never set memory.high BELOW current RSS + 10% headroom
                                            # This prevents instant OOM kill when process is already above the calculated limit
                                            min_safe = int(proc_rss * 1.1)
                                            if mem_bytes < min_safe:
                                                mem_bytes = min_safe
                                                self.logger.warning(
                                                    f"Memory limit for PID {pid} raised from {mem_bytes} to {min_safe} "
                                                    f"(current RSS: {proc_rss}, limit%: {limits['memory_limit_percent']}%)"
                                                )
                                            self.cgroup_mgr.apply_memory_throttle(pid, mem_bytes)
                                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                                            pass
                                        
                                    # I/O Throttle
                                    if hasattr(self.cgroup_mgr, 'apply_io_throttle') and limits["io_weight"] < 100:
                                        self.cgroup_mgr.apply_io_throttle(pid, limits["io_weight"])
                                        
                                    if start_tick is not None:
                                        self.cgroup_mgr.register_throttle(pid, now + self.cooldown_sec, start_tick)
                
                # 4. Continuous Telemetry Logging
                if not hasattr(self, '_last_print') or now - self._last_print > 3.0:
                    if not action_taken and not self.cgroup_mgr.throttled_tasks:
                        print(f"[{current_level} LOAD] System nominal. (Unified Stress: {current_stress:.2f}, CPU: {metrics.cpu_percent:.1f}%)", flush=True)
                    self._last_print = now
                
                self._sd_notify("WATCHDOG=1")
                
            except Exception as e:
                print(f"\n[CRITICAL LOOP ERROR]: {e}", flush=True)
                time.sleep(2)

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("[FATAL] SENTRY must be executed with root privileges (sudo).")
        sys.exit(1)
        
    daemon = SentryDaemon()
    daemon.run()

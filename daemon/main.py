#!/usr/bin/env python3
"""
daemon/main.py

The Basecamp Architecture for SENTRY.
Restored to pure, flawless user-space polling with live telemetry.
Secured IPC sockets via SUDO_UID to prevent unprivileged PID spoofing.
Hardened v1.2: Fully Unified Architecture. Integrates the SystemMetricsSampler,
Policy Engine, and Feedback Loop for true PSI-blended stress evaluation.
"""

import ctypes
import pwd
import grp
import sys
import os
import time
import signal
import socket
import json
import psutil
import selectors
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
    if os.getuid() != 0:
        return  # Already non-root

    libc = ctypes.CDLL("libc.so.6", use_errno=True)

    # 1. PR_SET_NO_NEW_PRIVS — must be first, inherited across execve
    # Prevents setuid binaries (sudo, mount, etc.) from elevating privileges
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS = 0x22
        errno = ctypes.get_errno()
        raise OSError(f"PR_SET_NO_NEW_PRIVS failed: {os.strerror(errno)}")

    # 2. PR_CAPBSET_DROP — MUST run while still root (needs CAP_SETPCAP)
    # Drop CAP_SYS_RESOURCE (24) and CAP_DAC_OVERRIDE (1) from bounding set
    for cap in (24, 1):  # CAP_SYS_RESOURCE, CAP_DAC_OVERRIDE
        if libc.prctl(24, cap, 0, 0, 0) != 0:  # PR_CAPBSET_DROP = 0x18
            errno = ctypes.get_errno()
            raise OSError(f"PR_CAPBSET_DROP cap={cap} failed: {os.strerror(errno)}")

    # 3. Resolve target credentials
    try:
        pw_record = pwd.getpwnam(username)
    except KeyError:
        print(f"[FATAL] Required system user '{username}' not found.", flush=True)
        sys.exit(1)

    uid = pw_record.pw_uid
    gid = pw_record.pw_gid

    # 4. Drop supplementary groups
    os.setgroups([])

    # 5. Drop GID then UID — this strips effective/permitted capabilities
    os.setgid(gid)
    os.setuid(uid)

    # 6. Verify ALL IDs dropped (real, effective, saved)
    if os.getuid() == 0 or os.geteuid() == 0 or os.getgid() == 0 or os.getegid() == 0:
        raise PermissionError("Privilege drop incomplete: UID/GID still 0")

    # 7. Clear dangerous environment variables
    for var in ("SUDO_UID", "SUDO_GID", "SUDO_USER", "SUDO_COMMAND"):
        os.environ.pop(var, None)

    print(f"[SECURITY] Sandbox Locked: Dropped to '{username}' (UID: {uid}, caps stripped)", flush=True)


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
        self.sampler = SystemMetricsSampler(interval=0.05)  # 50ms interval for more responsive IPC
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
        print("[DEBUG] run() method started", flush=True)

        self.cgroup_mgr.clear_orphaned_throttles()
        self._sd_notify("READY=1\nSTATUS=SENTRY Unified Daemon online.")
        print("[INFO] SystemMetricsSampler & Feedback Engine Armed.", flush=True)

        # Use selectors for proper async I/O event loop
        sel = selectors.DefaultSelector()
        sel.register(self.bridge_sock, selectors.EVENT_READ)
        sel.register(self.hud_sock, selectors.EVENT_READ)
        print(f"[DEBUG] Registered bridge_sock: {self.bridge_sock.fileno()}, hud_sock: {self.hud_sock.fileno()}", flush=True)
        print(f"[DEBUG] Selector registered: {sel.get_map()}", flush=True)

        # For metrics sampling - track last sample time
        last_sample_time = 0
        sample_interval = 0.05  # 50ms

        # Initialize variables that may be referenced before first sample
        current_stress = 0.0
        current_level = "UNKNOWN"
        metrics = None
        limits = {"cpu_weight": 100, "memory_limit_percent": 100, "io_weight": 100}

        loop_count = 0
        while self.running:
            loop_count += 1
            if loop_count % 100 == 0:
                print(f"[DEBUG] Loop iteration {loop_count}", flush=True)
            try:
                # Use monotonic time to survive system hibernation/NTP adjustments
                now = time.monotonic()
                action_taken = False

                # Calculate timeout for selector (time until next sample)
                time_until_sample = max(0, last_sample_time + sample_interval - now)
                # Cap timeout at 10ms to stay responsive to IPC
                selector_timeout = min(time_until_sample, 0.01)

                # Wait for IPC events with short timeout
                events = sel.select(timeout=selector_timeout)
                print(f"[DEBUG] Select returned {len(events)} events", flush=True)

                # Process all ready IPC events
                for key, mask in events:
                    print(f"[DEBUG] Event: fileobj={key.fileobj}, mask={mask}, fileobj is hud_sock={key.fileobj == self.hud_sock}", flush=True)
                    if key.fileobj == self.bridge_sock:
                        try:
                            data, _ = self.bridge_sock.recvfrom(1024)
                            pid_str = data.decode().strip()
                            if pid_str.isdigit():
                                self.spatial_pid = int(pid_str)
                                print(f"[DEBUG] Bridge received PID: {self.spatial_pid}", flush=True)
                        except OSError as e:
                            print(f"[DEBUG] Bridge socket error: {e}", flush=True)
                    elif key.fileobj == self.hud_sock:
                        try:
                            data, addr = self.hud_sock.recvfrom(1024)
                            if data and addr:
                                cmd = data.decode().strip()
                                print(f"[DEBUG] HUD received from {addr}: {cmd}", flush=True)
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

                # Check if it's time to sample metrics (non-blocking)
                if now >= last_sample_time + sample_interval:
                    # 1. Unified Intelligence Collection (non-blocking sample)
                    metrics = self.sampler.sample()  # Non-blocking sample
                    last_sample_time = now

                    # stress_score is now a float (total), not a tuple
                    current_stress = metrics.stress_score
                    stress_delta = current_stress - getattr(self, '_prev_stress', current_stress)
                    self._prev_stress = current_stress

                    # Proportional-Derivative (PD) Actuator
                    limits = get_dynamic_limits(current_stress, stress_delta)
                    current_level = limits.get("state", "UNKNOWN")
                    self.current_stress = current_stress
                    self.current_level = current_level

                    # 2. Feedback Loop Evaluation (Check expired tasks BEFORE reconcile)
                    expired_pids = [p for p, (_, exp) in self.cgroup_mgr.throttled_tasks.items() if now >= exp]
                    for p in expired_pids:
                        # Fire the new Causal Attribution evaluator
                        # evaluate_action expects (pid, stress_after, pressure_after)
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
                                        # record_action expects (pid, stress_before, pressure_before, level)
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
                    if not action_taken and not self.cgroup_mgr.throttled_tasks and metrics is not None:
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
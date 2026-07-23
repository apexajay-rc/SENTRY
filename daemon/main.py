#!/usr/bin/env python3
"""
daemon/main.py

The Basecamp Architecture for SENTRY.
Restored to pure, flawless user-space polling with beautiful live telemetry.
"""

import sys
import os
import time
import signal
import socket
import json
import psutil
from typing import Optional, Any

# IMMEDIATE PRIORITY ELEVATION: Prevent SENTRY from being starved by hogs
try:
    os.nice(-20)
except Exception:
    pass

from core.logger import StructuredLogger
from core.cgroup_manager import CgroupManager
from core.safety_guard import SafetyGuard
from core.psi_sensor import PSISensor
from core.config import SentryConfig

class ProcSensor:
    """The flawless, kernel-agnostic Basecamp CPU profiler."""
    def __init__(self):
        self.procs = {}
        self.tick_count = 0

    def get_top_hogs(self, threshold=85.0):
        self.tick_count += 1
        hogs = []
        max_cpu = 0.0
        
        # Every 10 ticks, refresh the process list completely to catch new spawns and drop dead ones
        if self.tick_count % 10 == 0:
            current_pids = set(psutil.pids())
            dead_pids = set(self.procs.keys()) - current_pids
            for pid in dead_pids:
                del self.procs[pid]

        for pid in psutil.pids():
            try:
                if pid not in self.procs:
                    p = psutil.Process(pid)
                    p.cpu_percent() # Prime the psutil counter
                    self.procs[pid] = p
                else:
                    # psutil natively aggregates all thread CPU usage into this single Process ID call
                    cpu = self.procs[pid].cpu_percent()
                    if cpu > max_cpu:
                        max_cpu = cpu
                    if cpu > threshold:
                        hogs.append(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                if pid in self.procs:
                    del self.procs[pid]
            except Exception:
                pass
                
        return hogs, max_cpu

class SentryDaemon:
    def __init__(self) -> None:
        self.logger = StructuredLogger(name="SENTRY_DAEMON")
        self.config = SentryConfig("sentry_config.yaml")
        self.mem_clamp_bytes = self.config.memory_clamp_bytes
        self.cooldown_sec = self.config.cooldown_seconds
        
        self.cgroup_mgr = CgroupManager(self.logger)
        self.safety_guard = SafetyGuard()
        self.psi_sensor = PSISensor(threshold=5.0)
        self.proc_sensor = ProcSensor()
        
        self.spatial_pid: Optional[int] = None
        self.bridge_sock_path = "/run/sentry_bridge.sock"
        self.hud_sock_path = "/run/sentry_hud.sock"
        
        self._cleanup_sockets()

        # IPC Sockets
        self.bridge_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.bridge_sock.bind(self.bridge_sock_path)
        os.chmod(self.bridge_sock_path, 0o666)  
        self.bridge_sock.setblocking(False)

        self.hud_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.hud_sock.bind(self.hud_sock_path)
        os.chmod(self.hud_sock_path, 0o666)  
        self.hud_sock.setblocking(False)
        
        self.running = True
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)

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
                sock.sendto(state.encode(), notify_socket) # type: ignore
        except Exception:
            pass

    def _process_ipc(self, now: float) -> None:
        """Safe, non-blocking read to absolutely prevent freeze loops."""
        try:
            data, _ = self.bridge_sock.recvfrom(1024)
            pid_str = data.decode().strip()
            if pid_str.isdigit():
                self.spatial_pid = int(pid_str)
        except OSError:
            pass 

        try:
            data, addr = self.hud_sock.recvfrom(1024)
            if data == b"STATUS" and addr:
                throttled = []
                if hasattr(self.cgroup_mgr, 'throttled_tasks'):
                    for t_pid, (s_time, exp) in self.cgroup_mgr.throttled_tasks.items():
                        throttled.append({"pid": t_pid, "time_left": max(0.0, float(exp - now))})
                
                state = {
                    "spatial_pid": self.spatial_pid,
                    "throttled_tasks": throttled
                }
                self.hud_sock.sendto(json.dumps(state).encode(), addr)
        except OSError:
            pass

    def shutdown(self, signum: Any = None, frame: Any = None) -> None:
        print("\n=> 🛑 SIGTERM/SIGINT received. Releasing all hardware locks...", flush=True)
        self.running = False
        self._sd_notify("STOPPING=1")
        self.cgroup_mgr.release_all()
        try:
            self.bridge_sock.close()
            self.hud_sock.close()
            self._cleanup_sockets()
        except Exception:
            pass
        print("=> ✅ SENTRY going dark. System restored to default scheduler.", flush=True)
        sys.exit(0)

    def run(self) -> None:
        print("\n" + "="*60, flush=True)
        print(" 🛡️  SENTRY RING-0 COMMAND DAEMON ONLINE (BASECAMP) ", flush=True)
        print("="*60 + "\n", flush=True)
        
        self._sd_notify("READY=1\nSTATUS=SENTRY Basecamp Daemon online.")
        print("=> ✅ High-Speed PSUtil Profiler armed.", flush=True)
        
        if not self.psi_sensor.is_supported:
            print("=> ⚠️  Kernel PSI not detected. Memory defenses disabled.", flush=True)
        
        while self.running:
            try:
                now = time.time()
                
                self._process_ipc(now)
                self.cgroup_mgr.reconcile_cooldowns(now)
                
                action_taken = False
                
                # 1. CPU Defense (Basecamp proc polling)
                # psutil cpu_percent > 85.0 means it is burning almost an entire core
                top_cpu_hogs, max_cpu = self.proc_sensor.get_top_hogs(threshold=85.0)
                
                for pid in top_cpu_hogs:
                    if not self.cgroup_mgr.is_throttled(pid):
                        if pid == self.spatial_pid:
                            pass # Spatial Immunity
                        elif not os.path.exists(f"/proc/{pid}"):
                            pass # Prevent ghosts
                        elif not self.safety_guard.is_immune(pid):
                            action_taken = True
                            print(f"\n🚨 => ACTION: Throttling CPU hog (PID {pid}). cpu.slice set to low, cpu.max clamped to 20%.", flush=True)
                            self.cgroup_mgr.apply_cpu_throttle(pid, 20)
                            self.cgroup_mgr.register_throttle(pid, now + self.cooldown_sec)
                
                # 2. Memory Defense (PSI)
                if self.psi_sensor.check_memory_pressure():
                    hog_pid = self.psi_sensor.find_largest_memory_hog()
                    if hog_pid > 0 and not self.cgroup_mgr.is_throttled(hog_pid):
                        if hog_pid != self.spatial_pid and os.path.exists(f"/proc/{hog_pid}") and not self.safety_guard.is_immune(hog_pid):
                            action_taken = True
                            print(f"\n🚨 => ACTION: Memory starvation detected. memory.high clamped to {self.mem_clamp_bytes} bytes for PID {hog_pid}.", flush=True)
                            self.cgroup_mgr.apply_memory_throttle(hog_pid, self.mem_clamp_bytes)
                            self.cgroup_mgr.register_throttle(hog_pid, now + self.cooldown_sec)
                
                # --- The Continuous Aesthetic Logging ---
                if not hasattr(self, '_last_print') or now - self._last_print > 3.0:
                    if not action_taken and not self.cgroup_mgr.throttled_tasks:
                        print(f"✨ [SYSTEM NOMINAL] No action needed. Nothing is happening now. (Max CPU Load: {max_cpu:.1f}%)", flush=True)
                    self._last_print = now
                
                self._sd_notify("WATCHDOG=1")
                time.sleep(0.2)  # 200ms
                
            except Exception as e:
                print(f"\n❌ [CRITICAL LOOP ERROR]: {e}", flush=True)
                time.sleep(2)

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("FATAL: SENTRY must be executed with root privileges (sudo).")
        sys.exit(1)
        
    daemon = SentryDaemon()
    daemon.run()

#!/usr/bin/env python3
"""
daemon/main.py

The Production-Grade Composition Root for SENTRY.
Restored to its beautiful, live-telemetry glory.
"""

import sys
import os
import time
import signal
import traceback
import socket
import json
from typing import Optional, Any

# 1. IMMEDIATE PRIORITY ELEVATION
# SENTRY must never be starved of CPU by the rogue processes it is trying to catch.
try:
    os.nice(-20)
except Exception:
    pass

from core.logger import StructuredLogger
from core.cgroup_manager import CgroupManager
from core.safety_guard import SafetyGuard
from core.psi_sensor import PSISensor
from core.config import SentryConfig

try:
    from core.bpf_sensor import BPFSensor
    _BPF_AVAILABLE = True
except ImportError:
    _BPF_AVAILABLE = False


class SentryDaemon:
    def __init__(self) -> None:
        self.logger = StructuredLogger(name="SENTRY_DAEMON")
        
        self.config = SentryConfig("sentry_config.yaml")
        self.mem_clamp_bytes = self.config.memory_clamp_bytes
        self.cooldown_sec = self.config.cooldown_seconds
        
        self.cgroup_mgr = CgroupManager(self.logger)
        self.safety_guard = SafetyGuard()
        self.psi_sensor = PSISensor(threshold=5.0)
        
        self.bpf_sensor: Optional[Any] = None
        if _BPF_AVAILABLE:
            try:
                self.bpf_sensor = BPFSensor()  # type: ignore
            except Exception as e:
                self.logger.error(f"Failed to initialize BPFSensor: {e}")
        
        self.spatial_pid: Optional[int] = None
        self.bridge_sock_path = "/run/sentry_bridge.sock"
        self.hud_sock_path = "/run/sentry_hud.sock"
        
        self._cleanup_sockets()

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
        """Safe, single-pass non-blocking read to absolutely prevent freeze loops."""
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
        # THE BEAUTIFUL BOOT SEQUENCE
        print("\n" + "="*60, flush=True)
        print(" 🛡️  SENTRY RING-0 COMMAND DAEMON ONLINE ", flush=True)
        print("="*60 + "\n", flush=True)
        
        self.logger.info("SENTRY Ring-0 Daemon online. Event loop armed.")
        self._sd_notify("READY=1\nSTATUS=SENTRY Ring-0 Daemon online.")
        
        if not self.psi_sensor.is_supported:
            print("❌ Kernel PSI not detected. Run kernel with psi=1.", flush=True)
            
        if self.bpf_sensor is not None:
            print("=> Arming eBPF Behavioral Probes...", flush=True)
            try:
                self.bpf_sensor.start()
            except Exception as e:
                print(f"❌ Failed to start eBPF Sensor: {e}", flush=True)
        
        while self.running:
            try:
                now = time.time()
                
                self._process_ipc(now)
                self.cgroup_mgr.reconcile_cooldowns(now)
                
                action_taken = False
                max_slice_ms = 0.0
                
                # 1. CPU Defense (eBPF)
                if self.bpf_sensor is not None:
                    top_cpu_hogs, max_ns = self.bpf_sensor.get_top_hogs(threshold_ns=50000000)
                    max_slice_ms = max_ns / 1000000.0
                    
                    for pid in top_cpu_hogs:
                        if not self.cgroup_mgr.is_throttled(pid):
                            if pid == self.spatial_pid:
                                pass
                            elif not os.path.exists(f"/proc/{pid}"):
                                pass # Prevent ghosts from triggering exceptions
                            elif not self.safety_guard.is_immune(pid):
                                action_taken = True
                                print(f"\n🚨 => ACTION: Throttling CPU hog (PID {pid}) to 20% hardware clamp.", flush=True)
                                self.cgroup_mgr.apply_cpu_throttle(pid, 20)
                                self.cgroup_mgr.register_throttle(pid, now + self.cooldown_sec)
                
                # 2. Memory Defense (PSI)
                if self.psi_sensor.check_memory_pressure():
                    hog_pid = self.psi_sensor.find_largest_memory_hog()
                    if hog_pid > 0 and not self.cgroup_mgr.is_throttled(hog_pid):
                        if hog_pid != self.spatial_pid and os.path.exists(f"/proc/{hog_pid}") and not self.safety_guard.is_immune(hog_pid):
                            action_taken = True
                            print(f"\n🚨 => ACTION: Clamping memory.high for PID {hog_pid} to {self.mem_clamp_bytes} bytes.", flush=True)
                            self.cgroup_mgr.apply_memory_throttle(hog_pid, self.mem_clamp_bytes)
                            self.cgroup_mgr.register_throttle(hog_pid, now + self.cooldown_sec)
                
                # --- The Continuous Aesthetic Logging ---
                if not hasattr(self, '_last_print') or now - self._last_print > 3.0:
                    if not action_taken and not self.cgroup_mgr.throttled_tasks:
                        # Displays live proof that the kernel BPF is feeding it data
                        print(f"✨ [SYSTEM NOMINAL] No action needed. Foreground workflow prioritized. (Max CPU slice: {max_slice_ms:.1f}ms)", flush=True)
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

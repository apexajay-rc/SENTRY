#!/usr/bin/env python3
"""
daemon/main.py

The core entry point for the SENTRY Ring-0 Daemon.
Includes a Built-in Process Scanner to hunt CPU hogs, checking the
SafetyGuard (Spatial Context) before throttling them via CgroupManager.
"""

import os
import sys
import time
import json
import socket
import logging
import threading

# --- AUTO-PATH RESOLVER ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from core.safety_guard import SafetyGuard
    from core.cgroup_manager import CgroupManager
except ImportError as e:
    logger.critical(f"Fatal import error: {e}")
    sys.exit(1)

def start_ipc_server(cgroup_mgr, safety_guard):
    """Feeds the Matrix Command Center (sentry_top.py)"""
    def _serve():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 50506))
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                if data == b"STATUS":
                    throttled = []
                    now = time.time()
                    
                    if hasattr(cgroup_mgr, 'throttled_pids'):
                        for pid, unthrottle_time in list(cgroup_mgr.throttled_pids.items()):
                            time_left = max(0, unthrottle_time - now)
                            throttled.append({"pid": pid, "time_left": time_left})
                    
                    spatial_pid = getattr(safety_guard, 'active_foreground_pid', None)
                    
                    state = {
                        "spatial_pid": spatial_pid,
                        "throttled_tasks": throttled
                    }
                    sock.sendto(json.dumps(state).encode(), addr)
            except Exception as e:
                pass

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

def built_in_hog_detector(cgroup_mgr, safety_guard):
    """A lightweight background thread that actively hunts for stress-ng hogs."""
    cgroup_mgr.throttled_pids = {}  # Store {pid: unthrottle_timestamp}
    COOLDOWN_SECONDS = 15

    logger.info("👁️ Built-in Hog Detector armed. Scanning for rogues...")
    
    while True:
        try:
            now = time.time()
            
            # 1. Release processes whose penalty time is up
            for pid in list(cgroup_mgr.throttled_pids.keys()):
                if now > cgroup_mgr.throttled_pids[pid]:
                    logger.info(f"⏳ Cooldown expired for {pid}. Restoring CPU.")
                    cgroup_mgr.reset_cpu_throttle(pid)
                    del cgroup_mgr.throttled_pids[pid]

            # 2. Scan for stress-ng processes
            pids = [int(p) for p in os.listdir('/proc') if p.isdigit()]
            for pid in pids:
                try:
                    with open(f"/proc/{pid}/comm", "r") as f:
                        comm = f.read().strip()
                        
                    if ("stress-ng" in comm or "md5sum" in comm) and pid not in cgroup_mgr.throttled_pids:
                        # THE CRITICAL CHECK: Are you looking at it?
                        if not safety_guard.is_protected(pid):
                            logger.warning(f"🚨 UNPROTECTED CPU HOG DETECTED ({comm} - {pid})! Slamming into Penalty Box.")
                            if cgroup_mgr.throttle_cpu(pid, 20):
                                cgroup_mgr.throttled_pids[pid] = now + COOLDOWN_SECONDS
                except (FileNotFoundError, ProcessLookupError):
                    continue
                    
        except Exception as e:
            logger.debug(f"Scanner error: {e}")
            
        time.sleep(1) # Scan once a second

def main():
    logger.info("Initializing SENTRY Kernel Daemon...")
    cgroup_mgr = CgroupManager()
    safety_guard = SafetyGuard()
    
    start_ipc_server(cgroup_mgr, safety_guard)
    
    # Start our built-in sensor in a background thread
    sensor_thread = threading.Thread(target=built_in_hog_detector, args=(cgroup_mgr, safety_guard), daemon=True)
    sensor_thread.start()
    
    logger.info("🛡️ SENTRY daemon fully armed. Entering watch state.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("SENTRY daemon shutting down...")

if __name__ == "__main__":
    if os.geteuid() != 0:
        logger.error("SENTRY must be run as root (sudo).")
        sys.exit(1)
    main()

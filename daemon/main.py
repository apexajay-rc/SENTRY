#!/usr/bin/env python3
"""
daemon/main.py

The core entry point for the SENTRY Ring-0 Daemon.
Arming SafetyGuard, CgroupManager, and the IPC Telemetry Server
for the sentry-top Matrix Command Center.
"""

import os
import sys
import time
import json
import socket
import logging
import threading

# --- AUTO-PATH RESOLVER ---
# Ensure Python can always locate the root package directory
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --------------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import guaranteed SENTRY modules confirmed in your core/ directory
try:
    from core.safety_guard import SafetyGuard
    from core.cgroup_manager import CgroupManager
except ImportError as e:
    logger.critical(f"Fatal import error: {e}")
    sys.exit(1)

# Gracefully attempt to load optional runtime modules without crashing
try:
    from core import runtime, metrics
except ImportError:
    pass

def start_ipc_server(cgroup_mgr, safety_guard):
    """Spins up a lightweight UDP server on port 50506 to feed the sentry-top TUI."""
    def _serve():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 50506))
        logger.info("📡 IPC Telemetry Server listening on UDP 50506...")
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                if data == b"STATUS":
                    throttled = []
                    now = time.time()
                    
                    # Safely inspect cgroup manager for active throttled PIDs
                    if hasattr(cgroup_mgr, 'throttled_pids') and isinstance(cgroup_mgr.throttled_pids, dict):
                        for pid, unthrottle_time in list(cgroup_mgr.throttled_pids.items()):
                            time_left = max(0, unthrottle_time - now)
                            throttled.append({"pid": pid, "time_left": time_left})
                    elif hasattr(cgroup_mgr, 'get_throttled'):
                        throttled = cgroup_mgr.get_throttled()
                    
                    # Extract the spatial gaze PID from the SafetyGuard
                    spatial_pid = getattr(safety_guard, 'active_foreground_pid', None)
                    
                    # Dump state to JSON
                    state = {
                        "spatial_pid": spatial_pid,
                        "throttled_tasks": throttled
                    }
                    sock.sendto(json.dumps(state).encode(), addr)
            except Exception as e:
                logger.debug(f"IPC Server Error: {e}")

    # Run as a daemon thread so it terminates cleanly when the daemon stops
    t = threading.Thread(target=_serve, daemon=True)
    t.start()

def main():
    logger.info("Initializing SENTRY Kernel Daemon...")

    try:
        # 1. Initialize Core Components
        cgroup_mgr = CgroupManager()
        safety_guard = SafetyGuard()
        
        # 2. Ignite the IPC Telemetry Server for sentry-top
        start_ipc_server(cgroup_mgr, safety_guard)
        
        logger.info("🛡️ SENTRY daemon fully armed (SafetyGuard + IPC active). Entering watch state.")
        
        # 3. Main Event Loop
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("SENTRY daemon shutting down...")
    except Exception as e:
        logger.critical(f"SENTRY daemon crashed: {e}", exc_info=True)
    finally:
        logger.info("SENTRY deactivated.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        logger.error("SENTRY must be run as root (sudo).")
        sys.exit(1)
    main()

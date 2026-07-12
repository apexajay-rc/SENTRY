#!/usr/bin/env python3
"""
daemon/main.py

The core entry point for the SENTRY Ring-0 Daemon.
Initializes eBPF sensors, PSI monitoring, spatial context guards,
and the IPC telemetry server for the Command Center.
"""

import os
import sys
import time
import json
import socket
import logging
import threading

# --- AUTO-PATH RESOLVER ---
# Dynamically add the project root directory to Python's module search path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --------------------------

# SENTRY Core Components
try:
    from core.bpf_sensor import BPFSensor
    from core.psi_sensor import PSISensor
    from core.aggregator import Aggregator
    from core.state_reconciler import StateReconciler
    from core.cgroup_manager import CgroupManager
    from core.safety_guard import SafetyGuard
except ImportError as e:
    print(f"Failed to import SENTRY core components: {e}")
    print("Ensure you are running from the root of the SENTRY project.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def start_ipc_server(reconciler, safety_guard):
    """Spins up a lightweight UDP server to feed the sentry-top TUI."""
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
                    
                    # Safely extract the penalty box list from the Reconciler
                    if hasattr(reconciler, 'throttled_pids'):
                        # Use list() to avoid dictionary size changed during iteration errors
                        for pid, unthrottle_time in list(reconciler.throttled_pids.items()):
                            time_left = max(0, unthrottle_time - now)
                            throttled.append({"pid": pid, "time_left": time_left})
                    
                    # Extract the spatial gaze PID from the SafetyGuard
                    spatial_pid = getattr(safety_guard, 'active_foreground_pid', None)
                    
                    # Dump brain to JSON
                    state = {
                        "spatial_pid": spatial_pid,
                        "throttled_tasks": throttled
                    }
                    sock.sendto(json.dumps(state).encode(), addr)
            except Exception as e:
                logger.debug(f"IPC Server Error: {e}")

    # Run in the background as a daemon thread
    t = threading.Thread(target=_serve, daemon=True)
    t.start()

def main():
    logger.info("Initializing SENTRY Kernel Daemon...")

    try:
        # 1. Initialize Core Components
        cgroup_mgr = CgroupManager()
        safety_guard = SafetyGuard()
        reconciler = StateReconciler(cgroup_mgr, safety_guard)
        aggregator = Aggregator(reconciler)
        
        # 2. Initialize Sensors
        bpf_sensor = BPFSensor(aggregator)
        psi_sensor = PSISensor(reconciler)

        # 3. Ignite the IPC Telemetry Server for sentry-top
        start_ipc_server(reconciler, safety_guard)

        # 4. Start PSI Monitoring Thread
        psi_sensor.start()
        
        logger.info("🛡️ SENTRY daemon fully armed (eBPF + PSI active). Entering watch state.")
        
        # 5. Main Event Loop
        while True:
            # The BPF sensor blocks and polls events efficiently
            bpf_sensor.poll()
            
    except KeyboardInterrupt:
        logger.info("SENTRY daemon shutting down...")
    except Exception as e:
        logger.critical(f"SENTRY daemon crashed: {e}", exc_info=True)
    finally:
        logger.info("SENTRY deactivated.")

if __name__ == "__main__":
    # Ensure root privileges
    if os.geteuid() != 0:
        logger.error("SENTRY must be run as root (sudo).")
        sys.exit(1)
    main()

"""
core/bpf_sensor.py

The Ring-0 eBPF Sensor.
Injects a C program directly into the Linux kernel using Software
Performance Counters (CPU Clock) instead of tracepoints.
This guarantees we catch CPU hogs even if they NEVER context switch.
"""

import time
import logging
import sys
import os

# --- THE BRUTE-FORCE PATH FIX ---
# Force Python to look in the Ubuntu system directory where 'apt' installs BCC
sys.path.append("/usr/lib/python3/dist-packages")

try:
    from bcc import BPF, PerfType, PerfSwId
except Exception as e:
    import traceback
    logging.critical(f"EXACT IMPORT ERROR: {e}")
    logging.critical(f"PYTHON EXECUTABLE: {sys.executable}")
    logging.critical(f"PYTHON PATH: {sys.path}")
    logging.critical(f"TRACEBACK:\n{traceback.format_exc()}")
    sys.exit(1)

logger = logging.getLogger(__name__)

# --- THE KERNEL C CODE ---
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

// Hash map to accumulate CPU time per PID
BPF_HASH(cpu_time, u32, u64);

// This triggers exactly 100 times a second per CPU core (100Hz)
int do_perf_event(struct bpf_perf_event_data *ctx) {
    u32 pid = bpf_get_current_pid_tgid() >> 32;
    
    // Ignore idle kernel threads
    if (pid == 0) return 0;

    // At 100Hz, each tick represents exactly 10ms (10,000,000 ns) of CPU time
    u64 delta = 10000000;
    
    u64 *total = cpu_time.lookup(&pid);
    if (total != 0) {
        delta += *total;
    }
    cpu_time.update(&pid, &delta);
    return 0;
}
"""

class BPFSensor:
    def __init__(self):
        self.b = None
        
    def start(self):
        logger.info("Injecting eBPF Profiler into the Linux Kernel...")
        self.b = BPF(text=bpf_text)
        
        # Attach to the CPU clock software event (100 Hz = 10ms samples)
        # This bypasses the scheduler and forces visibility on raw CPU usage
        self.b.attach_perf_event(
            ev_type=PerfType.SOFTWARE, 
            ev_config=PerfSwId.CPU_CLOCK, 
            fn_name="do_perf_event", 
            sample_period=0, 
            sample_freq=100
        )
        logger.info("✅ eBPF Profiler successfully attached to CPU clock.")

    def get_top_hogs(self, threshold_ns=50000000):
        """
        Reads the BPF map, finds processes exceeding the threshold 
        (default 50ms of CPU time in the polling window), and clears the map.
        """
        if not self.b:
            return []
            
        hog_pids = []
        cpu_time_map = self.b["cpu_time"]
        
        for k, v in cpu_time_map.items():
            pid = k.value
            total_time_ns = v.value
            
            if total_time_ns > threshold_ns and pid > 0:
                hog_pids.append(pid)
                
        # Clear the map to measure only the NEXT time window (Sliding Window)
        cpu_time_map.clear()
        
        return hog_pids

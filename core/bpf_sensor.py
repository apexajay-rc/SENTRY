"""
core/bpf_sensor.py

The Ring-0 eBPF Sensor.
Injects a C program directly into the Linux kernel to monitor CPU scheduling
at the microsecond level. Replaces user-space polling.
"""

import time
import logging
import sys

try:
    from bcc import BPF
except ImportError:
    logging.critical("BCC module not found. Please run: sudo apt-get install python3-bpfcc linux-headers-$(uname -r)")
    sys.exit(1)

logger = logging.getLogger(__name__)

# --- THE KERNEL C CODE ---
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

// Hash map to store the start time of a process on a CPU
BPF_HASH(start_time, u32, u64);

// Hash map to accumulate CPU time per PID
BPF_HASH(cpu_time, u32, u64);

// Hook into the Kernel Scheduler Switch Tracepoint
TRACEPOINT_PROBE(sched, sched_switch) {
    u32 prev_pid = args->prev_pid;
    u32 next_pid = args->next_pid;
    u64 ts = bpf_ktime_get_ns();

    // Record CPU time for the process that is being switched OUT
    u64 *start_ts = start_time.lookup(&prev_pid);
    if (start_ts != 0) {
        u64 delta = ts - *start_ts;
        u64 *total = cpu_time.lookup(&prev_pid);
        if (total != 0) {
            delta += *total;
        }
        cpu_time.update(&prev_pid, &delta);
    }

    // Record the start time for the process being switched IN
    start_time.update(&next_pid, &ts);
    return 0;
}
"""

class BPFSensor:
    def __init__(self):
        self.b = None
        
    def start(self):
        logger.info("Injecting eBPF Probe into the Linux Kernel...")
        self.b = BPF(text=bpf_text)
        logger.info("✅ eBPF Probe successfully attached to sched_switch tracepoint.")

    def get_top_hogs(self, threshold_ns=500000000):
        """
        Reads the BPF map, finds processes exceeding the threshold 
        (default 500ms of CPU time in the polling window), and clears the map.
        """
        if not self.b:
            return []
            
        hog_pids = []
        cpu_time_map = self.b["cpu_time"]
        
        for k, v in cpu_time_map.items():
            pid = k.value
            total_time_ns = v.value
            
            # If a process burned more than threshold_ns in this polling window, flag it
            if total_time_ns > threshold_ns and pid > 0:
                hog_pids.append(pid)
                
        # Clear the map to measure only the NEXT time window (Sliding Window concept)
        cpu_time_map.clear()
        
        return hog_pids

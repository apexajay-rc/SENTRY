"""
core/bpf_sensor.py

The Ring-0 eBPF Sensor.
Uses a Kprobe on `scheduler_tick` which is guaranteed to fire on every 
core continuously, even if the CPU is 100% pinned in a Virtual Machine.
Bypasses broken Hypervisor Perf Events entirely.
"""

import time
import logging
import sys

# --- THE BRUTE-FORCE PATH FIX ---
sys.path.append("/usr/lib/python3/dist-packages")

try:
    from bcc import BPF
except ImportError as e:
    import traceback
    logging.critical(f"EXACT IMPORT ERROR: {e}")
    logging.critical(f"PYTHON EXECUTABLE: {sys.executable}")
    sys.exit(1)

logger = logging.getLogger(__name__)

# --- THE KERNEL C CODE ---
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

BPF_HASH(cpu_time, u32, u64);

// Kprobe on the kernel's native scheduler tick.
// BCC automatically attaches functions starting with `kprobe__` to the kernel.
// This is called periodically by the system timer on every core (1-4ms intervals).
int kprobe__scheduler_tick(struct pt_regs *ctx) {
    u32 pid = bpf_get_current_pid_tgid() >> 32;
    
    // Ignore idle kernel threads (PID 0)
    if (pid == 0) return 0;

    // Approximate tick time as 4ms (4,000,000 ns).
    // Since we are looking for massive hogs relative to others, 
    // the exact nanosecond precision here isn't as important as the frequency.
    u64 delta = 4000000; 
    
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
        self.tick_counter = 0
        
    def start(self):
        logger.info("Injecting eBPF Kprobe into the Linux Kernel...")
        self.b = BPF(text=bpf_text)
        logger.info("✅ eBPF Profiler successfully attached to scheduler_tick.")

    def get_top_hogs(self, threshold_ns=20000000):
        """
        Reads the BPF map, finds processes exceeding the 20ms threshold.
        """
        if not self.b:
            return []
            
        hog_pids = []
        cpu_time_map = self.b["cpu_time"]
        items = list(cpu_time_map.items())
        
        # --- DIAGNOSTIC LOGGING ---
        self.tick_counter += 1
        if self.tick_counter % 10 == 0:  # Print every 2 seconds (10 ticks * 200ms)
            logger.info(f"[DIAGNOSTIC] eBPF Map is tracking {len(items)} active PIDs.")
            if len(items) == 0:
                logger.warning("[DIAGNOSTIC] The BPF map is completely empty! Kprobe failed to fire.")
        
        for k, v in items:
            pid = k.value
            total_time_ns = v.value
            
            # Check against the 20ms threshold
            if total_time_ns > threshold_ns and pid > 0:
                hog_pids.append(pid)
                
            # SAFE DELETION: Manual deletion to bypass BCC map.clear() bugs
            try:
                del cpu_time_map[k]
            except KeyError:
                pass
        
        return hog_pids

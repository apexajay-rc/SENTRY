"""
core/bpf_sensor.py

The Ring-0 eBPF Sensor.
Uses native sched:sched_switch tracepoints.
Extracts true User-Space PIDs (TGID) via bitwise shifts to prevent 
/proc file lookup failures on multithreaded workers.
"""

import time
import sys

# Bypass Ubuntu virtual environment isolation
sys.path.append("/usr/lib/python3/dist-packages")

try:
    from bcc import BPF
except ImportError as e:
    print(f"CRITICAL: {e}")
    sys.exit(1)

# --- THE KERNEL C CODE ---
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

// start_time tracks Thread IDs (TIDs) as they enter the CPU
BPF_HASH(start_time, u32, u64);

// cpu_time aggregates total time under the true User-Space PID (TGID)
BPF_HASH(cpu_time, u32, u64);

TRACEPOINT_PROBE(sched, sched_switch) {
    u64 ts = bpf_ktime_get_ns();
    
    // 1. Process switching OUT (We are running inside its context)
    u64 pid_tgid = bpf_get_current_pid_tgid();
    u32 tid = pid_tgid;         // Lower 32 bits: Thread ID
    u32 tgid = pid_tgid >> 32;  // Upper 32 bits: True User-Space PID

    if (tid > 0) {
        u64 *start = start_time.lookup(&tid);
        if (start != 0) {
            u64 delta = ts - *start;
            
            // Accumulate time against the true PID so Python can find /proc/[PID]
            u64 zero = 0;
            u64 *total = cpu_time.lookup_or_try_init(&tgid, &zero);
            if (total) {
                *total += delta;
            }
            start_time.delete(&tid); 
        }
    }

    // 2. Process switching IN (Record its TID)
    u32 next_tid = args->next_pid;
    if (next_tid > 0) {
        start_time.update(&next_tid, &ts);
    }

    return 0;
}
"""

class BPFSensor:
    def __init__(self):
        self.b = None
        self.tick_counter = 0
        
    def start(self):
        print("[INFO] Compiling eBPF C code and locking onto TGIDs...")
        self.b = BPF(text=bpf_text)
        print("[INFO] ✅ eBPF Profiler successfully attached. Thread blindspot cured.")

    def get_top_hogs(self, threshold_ns=20000000): # Lowered to 20ms for instant triggers
        """Reads the BPF map and finds true PIDs exceeding the CPU threshold."""
        if not self.b:
            return []
            
        hog_pids = set()
        cpu_time_map = self.b["cpu_time"]
        items = list(cpu_time_map.items())
        
        for k, v in items:
            tgid = k.value
            total_time_ns = v.value
            
            # Catch any true PID burning more than 20ms of time in our 200ms window
            if total_time_ns > threshold_ns and tgid > 0:
                hog_pids.add(tgid)
                
            # Safely delete the BCC map entry to prep for the next 200ms sweep
            try:
                del cpu_time_map[k]
            except KeyError:
                pass
                
        # --- EXTREME DIAGNOSTICS ---
        self.tick_counter += 1
        if self.tick_counter % 10 == 0:  # Print every 2 seconds
            print(f"[BPF SENSOR] Swept {len(items)} processes. Found {len(hog_pids)} hogs exceeding 20ms threshold.")
            if len(hog_pids) > 0:
                print(f"             -> PENALIZING PIDs: {list(hog_pids)}")
        
        return list(hog_pids)

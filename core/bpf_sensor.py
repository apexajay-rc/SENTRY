"""
core/bpf_sensor.py

The Ring-0 eBPF Sensor.
Uses native sched:sched_switch tracepoints.
Captures both rapid context-switchers AND 100% pinned CPU hogs 
without relying on unsupported PerfEvents, restricted Kprobes, or clock synchronization.
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

# --- THE KERNEL C CODE ---
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

BPF_HASH(start_time, u32, u64);
BPF_HASH(cpu_time, u32, u64);

// Hooks into the universally stable kernel context switch tracepoint.
TRACEPOINT_PROBE(sched, sched_switch) {
    u64 ts = bpf_ktime_get_ns();
    u32 prev_pid = args->prev_pid;
    u32 next_pid = args->next_pid;

    // 1. Process switching OUT: Calculate how long it held the CPU
    if (prev_pid > 0) {
        u64 *start = start_time.lookup(&prev_pid);
        if (start != 0) {
            u64 delta = ts - *start;
            u64 *total = cpu_time.lookup(&prev_pid);
            if (total != 0) {
                delta += *total;
            }
            cpu_time.update(&prev_pid, &delta);
            start_time.delete(&prev_pid); // Remove active lock
        }
    }

    // 2. Process switching IN: Record the exact start time
    if (next_pid > 0) {
        start_time.update(&next_pid, &ts);
    }

    return 0;
}
"""

class BPFSensor:
    def __init__(self):
        self.b = None
        self.tick_counter = 0
        self.pinned_candidates = {}
        
    def start(self):
        print("[INFO] Injecting eBPF Tracepoint into the Linux Kernel...")
        self.b = BPF(text=bpf_text)
        print("[INFO] ✅ eBPF Profiler successfully attached to sched_switch.")

    def get_top_hogs(self, threshold_ns=50000000):
        """
        Reads the BPF map, finds processes exceeding the 50ms threshold.
        """
        if not self.b:
            return []
            
        hog_pids = set()
        
        cpu_time_map = self.b["cpu_time"]
        start_time_map = self.b["start_time"]
        
        # --- 1. Catch Rapid Context-Switchers ---
        items = list(cpu_time_map.items())
        for k, v in items:
            pid = k.value
            total_time_ns = v.value
            
            if total_time_ns > threshold_ns and pid > 0:
                hog_pids.add(pid)
                
            # SAFE DELETION: Manual deletion to bypass BCC map.clear() bugs
            try:
                del cpu_time_map[k]
            except KeyError:
                pass
                
        # --- 2. Catch 100% Pinned Tasks (The Clock-Immune Fix) ---
        # If a task is 100% pinning the CPU, it never switches out.
        # We record its start timestamp. If it has the EXACT same timestamp
        # on our next sweep (200ms later), it never left the CPU!
        current_active_tasks = {}
        active_items = list(start_time_map.items())
        
        for k, v in active_items:
            if k.value > 0:
                current_active_tasks[k.value] = v.value
                
        for pid, start_ts in current_active_tasks.items():
            if pid in self.pinned_candidates and self.pinned_candidates[pid] == start_ts:
                # The timestamp is identical. It NEVER switched out. Convicted.
                hog_pids.add(pid)
                
        # Update candidates for the next tick
        self.pinned_candidates = current_active_tasks
                
        # --- DIAGNOSTIC LOGGING ---
        self.tick_counter += 1
        if self.tick_counter % 10 == 0:  # Print every 2 seconds
            print(f"[BPF DIAGNOSTIC] Tracking {len(current_active_tasks)} active/pinned PIDs and processed {len(items)} switches.")
        
        return list(hog_pids)

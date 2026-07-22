"""
core/bpf_sensor.py

The Final, Bulletproof Ring-0 eBPF Sensor.
Uses dual-map tracking (cpu_time + start_time) to catch both rapid-switching 
tasks and pinned CPU hogs, immune to VM clock drift and Kprobe restrictions.
"""

import time
import sys
import os

# Bypass Ubuntu virtual environment isolation
sys.path.append("/usr/lib/python3/dist-packages")

try:
    from bcc import BPF
except ImportError as e:
    print(f"CRITICAL [BPF]: BCC module not found. {e}", flush=True)
    sys.exit(1)

bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

// Tracks when a thread enters the CPU (TID -> timestamp)
BPF_HASH(start_time, u32, u64);

// Aggregates total CPU time (TGID -> total nanoseconds)
BPF_HASH(cpu_time, u32, u64);

TRACEPOINT_PROBE(sched, sched_switch) {
    u64 ts = bpf_ktime_get_ns();
    
    // 1. Process switching OUT
    u64 prev_pid_tgid = bpf_get_current_pid_tgid();
    u32 prev_tid = prev_pid_tgid;
    u32 prev_tgid = prev_pid_tgid >> 32;

    if (prev_tid > 0) {
        u64 *start = start_time.lookup(&prev_tid);
        if (start != 0) {
            u64 delta = ts - *start;
            
            u64 zero = 0;
            u64 *total = cpu_time.lookup_or_try_init(&prev_tgid, &zero);
            if (total) {
                *total += delta;
            }
            start_time.delete(&prev_tid); 
        }
    }

    // 2. Process switching IN
    u32 next_tid = args->next_pid;
    if (next_tid > 0) {
        start_time.update(&next_tid, &ts);
    }

    return 0;
}
"""

class BPFSensor:
    def __init__(self):
        print("\n[BPF SENSOR] Initializing Object...", flush=True)
        self.b = None
        self.tick_counter = 0
        
    def start(self):
        print("[BPF SENSOR] Compiling C code and attaching to sched_switch...", flush=True)
        try:
            self.b = BPF(text=bpf_text)
            print("[INFO] ✅ eBPF Profiler successfully attached. Dual-map tracking active.", flush=True)
        except Exception as e:
            print(f"[CRITICAL] BPF Compilation failed: {e}", flush=True)
            raise

    def _get_tgid_from_tid(self, tid):
        """Converts a Thread ID to its parent Process ID to pass the SafetyGuard."""
        try:
            with open(f"/proc/{tid}/status", "r") as f:
                for line in f:
                    if line.startswith("Tgid:"):
                        return int(line.split()[1])
        except Exception:
            pass
        return tid

    def get_top_hogs(self, threshold_ns=50000000): # 50ms default
        if not self.b:
            return []
            
        hog_pids = set()
        
        try:
            # We must use clock_gettime_ns(CLOCK_MONOTONIC) to perfectly match bpf_ktime_get_ns()
            now_ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
            
            # --- MAP 1: Catch Rapidly Switching Tasks ---
            cpu_time_map = self.b["cpu_time"]
            items = list(cpu_time_map.items())
            
            for k, v in items:
                tgid = k.value
                total_time_ns = v.value
                
                if total_time_ns > threshold_ns and tgid > 0:
                    hog_pids.add(tgid)
                    
                # Safely delete to prep for next 200ms sweep
                try:
                    del cpu_time_map[k]
                except KeyError:
                    pass
                    
            # --- MAP 2: Catch Pinned Tasks (Stress-ng) ---
            start_time_map = self.b["start_time"]
            pinned_items = list(start_time_map.items())
            
            for k, v in pinned_items:
                tid = k.value
                start_ns = v.value
                
                delta_ns = now_ns - start_ns
                if delta_ns > threshold_ns and tid > 0:
                    # Convert the thread ID to the main process ID
                    tgid = self._get_tgid_from_tid(tid)
                    hog_pids.add(tgid)

            # --- DIAGNOSTICS ---
            self.tick_counter += 1
            if self.tick_counter % 5 == 0:  # Print every 1 second exactly
                print(f"[BPF DIAGNOSTIC] Sweeping... {len(items)} rapid, {len(pinned_items)} pinned. Hogs >50ms: {list(hog_pids)}", flush=True)
                
            return list(hog_pids)
            
        except Exception as e:
            print(f"[BPF ERROR] Loop crashed: {e}", flush=True)
            return []

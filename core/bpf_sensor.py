"""
core/bpf_sensor.py

The drift-immune, diagnostic-rich eBPF CPU Profiler.
"""

import time
import sys
import os

sys.path.append("/usr/lib/python3/dist-packages")

try:
    from bcc import BPF
except ImportError as e:
    print(f"CRITICAL [BPF]: BCC module not found. {e}", flush=True)
    sys.exit(1)

bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

BPF_HASH(start_time, u32, u64);
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
        self.b = None
        self.last_pinned = {}
        
    def start(self):
        try:
            self.b = BPF(text=bpf_text)
            print("=> ✅ eBPF Profiler successfully attached to sched_switch tracepoint.", flush=True)
        except Exception as e:
            print(f"❌ [CRITICAL] BPF Compilation failed: {e}", flush=True)
            raise

    def _get_tgid_from_tid(self, tid):
        try:
            with open(f"/proc/{tid}/status", "r") as f:
                for line in f:
                    if line.startswith("Tgid:"):
                        return int(line.split()[1])
        except Exception:
            pass
        return tid

    def get_top_hogs(self, threshold_ns=50000000):
        if not self.b:
            return [], 0
            
        hog_pids = set()
        max_time_ns = 0
        
        try:
            # MAP 1: Rapid Switchers
            cpu_time_map = self.b["cpu_time"]
            items = list(cpu_time_map.items())
            
            for k, v in items:
                tgid = k.value
                total_time_ns = v.value
                
                if total_time_ns > max_time_ns:
                    max_time_ns = total_time_ns
                    
                if total_time_ns > threshold_ns and tgid > 0:
                    hog_pids.add(tgid)
                    
                try:
                    del cpu_time_map[k]
                except KeyError:
                    pass
                    
            # MAP 2: Pinned / 100% Core Hogs
            start_time_map = self.b["start_time"]
            pinned_items = list(start_time_map.items())
            current_pinned = {}
            
            for k, v in pinned_items:
                tid = k.value
                start_ns = v.value
                current_pinned[tid] = start_ns
                
                if tid in self.last_pinned and self.last_pinned[tid] == start_ns:
                    tgid = self._get_tgid_from_tid(tid)
                    if tgid > 0:
                        hog_pids.add(tgid)
                    
                    # If pinned, it technically took the entire 200ms window
                    if max_time_ns < 200000000:
                        max_time_ns = 200000000

            self.last_pinned = current_pinned
            
            return list(hog_pids), max_time_ns
            
        except Exception as e:
            print(f"❌ [BPF ERROR] Loop crashed: {e}", flush=True)
            return [], 0

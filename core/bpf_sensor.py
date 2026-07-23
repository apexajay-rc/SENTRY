"""
core/bpf_sensor.py

eBPF CPU Profiler using sched_switch tracepoint.
Tracks per-TGID CPU time with per-TID start timestamps.
"""

import sys

sys.path.append("/usr/lib/python3/dist-packages")

try:
    from bcc import BPF
except ImportError as e:
    print(f"CRITICAL [BPF]: BCC module not found. {e}", flush=True)
    sys.exit(1)

# eBPF program - tables accessed by name string
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

// Per-TID start timestamp (when task was scheduled in)
BPF_HASH(start_time, u32, u64);

// Per-TGID accumulated CPU time (ns) in current window
BPF_HASH(tgid_cpu_time, u32, u64);

TRACEPOINT_PROBE(sched, sched_switch) {
    u64 ts = bpf_ktime_get_ns();

    // 1. Task switching OUT (prev task)
    // At tracepoint entry, current task is the PREV task
    u64 prev_pid_tgid = bpf_get_current_pid_tgid();
    u32 prev_tid = (u32)prev_pid_tgid;
    u32 prev_tgid = prev_pid_tgid >> 32;

    if (prev_tid > 0) {
        u64 *start = start_time.lookup(&prev_tid);
        if (start != 0) {
            u64 delta = ts - *start;

            // Accumulate to prev_tgid
            u64 zero = 0;
            u64 *total = tgid_cpu_time.lookup_or_try_init(&prev_tgid, &zero);
            if (total) {
                *total += delta;
            }
            start_time.delete(&prev_tid);
        }
    }

    // 2. Task switching IN (next task)
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

    def start(self):
        """Compile and attach the eBPF program."""
        try:
            self.b = BPF(text=bpf_text)
            print("=> ✅ eBPF Profiler attached to sched_switch tracepoint.", flush=True)
        except Exception as e:
            print(f"❌ [CRITICAL] BPF Compilation/Attach failed: {e}", flush=True)
            raise

    def get_top_hogs(self, threshold_ns=50_000_000):
        """
        Read accumulated CPU time per TGID.
        Returns (list_of_hog_tgids, max_cpu_time_ns).
        """
        if not self.b:
            return [], 0

        hog_pids = set()
        max_time_ns = 0

        try:
            # Access table by name using get_table()
            cpu_time = self.b.get_table("tgid_cpu_time")
            items = list(cpu_time.items())

            for k, v in items:
                tgid = k.value
                total_ns = v.value

                if total_ns > max_time_ns:
                    max_time_ns = total_ns

                if total_ns > threshold_ns and tgid > 0:
                    hog_pids.add(tgid)

                # Clear for next window
                try:
                    del cpu_time[k]
                except KeyError:
                    pass

            return list(hog_pids), max_time_ns

        except Exception as e:
            print(f"❌ [BPF ERROR] Loop crashed: {e}", flush=True)
            return [], 0
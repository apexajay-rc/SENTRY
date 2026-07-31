#!/usr/bin/env python3
"""
tools/dataset_forge.py

The Phase 3 Machine Learning Data Harvester.
Records the Behavioral Triad (CPU, Syscalls, Page Faults) into a CSV dataset
to train the SENTRY Isolation Forest model.
"""

import time
import csv
import os
import sys
from bcc import BPF

# Ensure we run as root
if os.geteuid() != 0:
    print("FATAL: Data Forge must be run with sudo.")
    sys.exit(1)

# The Everest Triad C Code
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

struct process_metrics_t {
    u64 cpu_time_ns;
    u64 syscall_count;
    u64 page_faults;
};

BPF_HASH(start_time, u32, u64);
BPF_HASH(metrics, u32, struct process_metrics_t);

TRACEPOINT_PROBE(sched, sched_switch) {
    u64 ts = bpf_ktime_get_ns();
    u64 prev_pid_tgid = bpf_get_current_pid_tgid();
    u32 prev_tid = prev_pid_tgid;
    u32 prev_tgid = prev_pid_tgid >> 32;

    if (prev_tid > 0) {
        u64 *start = start_time.lookup(&prev_tid);
        if (start != NULL) {
            u64 delta = ts - *start;
            struct process_metrics_t zero = {0, 0, 0};
            struct process_metrics_t *metric = metrics.lookup_or_try_init(&prev_tgid, &zero);
            if (metric != NULL) {
                metric->cpu_time_ns += delta;
            }
            start_time.delete(&prev_tid);
        }
    }

    u32 next_tid = args->next_pid;
    if (next_tid > 0) {
        start_time.update(&next_tid, &ts);
    }
    return 0;
}

TRACEPOINT_PROBE(raw_syscalls, sys_enter) {
    u32 tgid = bpf_get_current_pid_tgid() >> 32;
    struct process_metrics_t zero = {0, 0, 0};
    struct process_metrics_t *metric = metrics.lookup_or_try_init(&tgid, &zero);
    if (metric != NULL) {
        metric->syscall_count += 1;
    }
    return 0;
}

int kprobe__handle_mm_fault(struct pt_regs *ctx) {
    u32 tgid = bpf_get_current_pid_tgid() >> 32;
    struct process_metrics_t zero = {0, 0, 0};
    struct process_metrics_t *metric = metrics.lookup_or_try_init(&tgid, &zero);
    if (metric != NULL) {
        metric->page_faults += 1;
    }
    return 0;
}
"""

print("=> Forging eBPF Triad Sensor...")
bpf = BPF(text=bpf_text)
metrics_map = bpf.get_table("metrics")

csv_filename = "sentry_training_data.csv"
duration_seconds = 60

print(f"\n=> 🔴 RECORDING LIVE TELEMETRY TO {csv_filename} FOR {duration_seconds} SECONDS")
print("=> INSTRUCTION: Use your computer normally. Open a browser, type, then run 'stress-ng' to generate anomalies.")

with open(csv_filename, mode='w', newline='') as file:
    writer = csv.writer(file)
    # The feature columns our ML model will learn from
    writer.writerow(['timestamp', 'pid', 'comm', 'cpu_ms', 'syscalls', 'page_faults'])

    start_time = time.time()
    
    try:
        while time.time() - start_time < duration_seconds:
            time.sleep(1)
            current_ts = time.time()
            
            for k, v in metrics_map.items():
                tgid = k.value
                cpu_ms = v.cpu_time_ns / 1000000.0
                syscalls = v.syscall_count
                faults = v.page_faults
                
                # Only record processes that actually used the CPU to keep dataset clean
                if cpu_ms > 1.0:
                    comm = "unknown"
                    try:
                        with open(f"/proc/{tgid}/comm", "r") as f:
                            comm = f.read().strip()
                    except FileNotFoundError:
                        pass
                        
                    writer.writerow([current_ts, tgid, comm, round(cpu_ms, 2), syscalls, faults])
            
            metrics_map.clear()
            sys.stdout.write(f"\r=> Time remaining: {int(duration_seconds - (current_ts - start_time))} seconds... ")
            sys.stdout.flush()

    except KeyboardInterrupt:
        pass

print(f"\n=> ✅ Dataset harvest complete! Saved to {csv_filename}")
print("=> Proceed to train the ML Model.")

#!/usr/bin/env python3
import time
from bcc import BPF

# ==============================================================================
# PHASE 2 EVEREST: THE TRIAD SENSOR (eBPF C Code)
# ==============================================================================
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

/* 1. Define the Triad Structure for our AI */
struct process_metrics_t {
    u64 cpu_time_ns;
    u64 syscall_count;
    u64 page_faults;
};

/* 2. Kernel Maps */
BPF_HASH(start_time, u32, u64);
BPF_HASH(metrics, u32, struct process_metrics_t);

/* 3. HOOK 1: The Scheduler (Tracks CPU Time) */
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

/* 4. HOOK 2: The Syscall Interface (Tracks OS Interaction) */
TRACEPOINT_PROBE(raw_syscalls, sys_enter) {
    u32 tgid = bpf_get_current_pid_tgid() >> 32;
    struct process_metrics_t zero = {0, 0, 0};
    
    struct process_metrics_t *metric = metrics.lookup_or_try_init(&tgid, &zero);
    if (metric != NULL) {
        metric->syscall_count += 1;
    }
    return 0;
}

/* 5. HOOK 3: Memory Manager (Tracks RAM Demands via Page Faults) */
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

# ==============================================================================
# PYTHON DAEMON: THE AI DATA PREP LAYER
# ==============================================================================
print("Forging Everest eBPF Sensor... (Compiling Hooks JIT)")
bpf = BPF(text=bpf_text)

metrics_map = bpf.get_table("metrics")
print("=> SENTRY Triad Sensor Active! Gathering behavioral fingerprints...\n")

try:
    while True:
        time.sleep(1)
        print(f"{'PID':<8} | {'NAME':<15} | {'CPU TIME':<10} | {'SYSCALLS':<10} | {'PAGE FAULTS':<12} | {'BEHAVIOR (Pseudo-AI)'}")
        print("-" * 90)
        
        for k, v in metrics_map.items():
            tgid = k.value
            cpu_ms = v.cpu_time_ns / 1000000
            syscalls = v.syscall_count
            faults = v.page_faults
            
            # Only analyze processes with notable CPU time (>5ms) to keep noise down
            if cpu_ms > 5.0:
                try:
                    with open(f"/proc/{tgid}/comm", "r") as f:
                        name = f.read().strip()
                        
                    # --- PSEUDO AI CLASSIFICATION (To demonstrate the vision) ---
                    behavior = "[ NORMAL ]"
                    if syscalls == 0 and faults == 0 and cpu_ms > 50:
                        behavior = "[ DEAD LOOP THREAT ]" # High CPU, no interaction
                    elif faults > 1000 and cpu_ms > 50:
                        behavior = "[ HEAVY COMPUTE/RENDER ]" # High CPU, heavy memory demand
                    elif syscalls > 5000:
                        behavior = "[ HEAVY I/O ]" # High disk/network activity
                    # ------------------------------------------------------------
                        
                    print(f"{tgid:<8} | {name:<15} | {cpu_ms:>6.2f} ms | {syscalls:>8} | {faults:>11} | {behavior}")
                except FileNotFoundError:
                    pass
        
        print("\n")
        # Clear the map for the next interval
        metrics_map.clear()

except KeyboardInterrupt:
    print("\nTriad Sensor deactivated.")

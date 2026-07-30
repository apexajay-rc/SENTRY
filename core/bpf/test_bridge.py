#!/usr/bin/env python3
import time
from bcc import BPF

# 1. The C Code (Python will compile this automatically!)
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

/* BCC uses specialized BPF_HASH macros instead of raw C structs */
BPF_HASH(start_time, u32, u64);
BPF_HASH(cpu_time, u32, u64);

TRACEPOINT_PROBE(sched, sched_switch) {
    u64 ts = bpf_ktime_get_ns();
    
    // 1. Calculate time for the process switching OUT
    u64 prev_pid_tgid = bpf_get_current_pid_tgid();
    u32 prev_tid = prev_pid_tgid;
    u32 prev_tgid = prev_pid_tgid >> 32;

    if (prev_tid > 0) {
        u64 *start = start_time.lookup(&prev_tid);
        if (start != NULL) {
            u64 delta = ts - *start;
            u64 zero = 0;
            
            // lookup_or_try_init ensures the entry exists before we add to it
            u64 *total = cpu_time.lookup_or_try_init(&prev_tgid, &zero);
            if (total != NULL) {
                *total += delta;
            }
            start_time.delete(&prev_tid);
        }
    }

    // 2. Record start time for the process switching IN
    u32 next_tid = args->next_pid;
    if (next_tid > 0) {
        start_time.update(&next_tid, &ts);
    }

    return 0;
}
"""

# 2. Compile and load the C code into the kernel
print("Compiling eBPF C code... (Takes a second)")
bpf = BPF(text=bpf_text)

# 3. Extract the cpu_time map
cpu_time_map = bpf.get_table("cpu_time")

print("=> SENTRY eBPF Bridge Active! Waiting for CPU data...")

try:
    while True:
        time.sleep(1)
        print("\n--- Top CPU Consumers (Last 1 Second) ---")
        
        # 4. Read the map data
        for k, v in cpu_time_map.items():
            tgid = k.value
            time_ns = v.value
            
            # Show processes using > 5ms of CPU time (5,000,000 ns)
            if time_ns > 5000000: 
                try:
                    with open(f"/proc/{tgid}/comm", "r") as f:
                        name = f.read().strip()
                    # Convert nanoseconds to milliseconds
                    print(f"PID: {tgid:<8} | Name: {name:<15} | Time: {time_ns / 1000000:.2f} ms")
                except FileNotFoundError:
                    pass
        
        # 5. Clear the map for the next second to prevent Memory Leaks!
        cpu_time_map.clear()

except KeyboardInterrupt:
    print("\nBridge closed.")

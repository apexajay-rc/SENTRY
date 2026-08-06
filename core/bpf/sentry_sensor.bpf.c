#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_core_read.h>

/* MAP 1: Store the exact nanosecond a thread enters the CPU */
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 10240);
    __type(key, u32);   // Thread ID (TID)
    __type(value, u64); // Start timestamp in nanoseconds
} start_time SEC(".maps");

/* MAP 2: Accumulate the total time a process spends on the CPU */
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 10240);
    __type(key, u32);   // Process ID (TGID)
    __type(value, u64); // Total elapsed CPU time in nanoseconds
} cpu_time SEC(".maps");

/* The Tracepoint Hook */
SEC("tracepoint/sched/sched_switch")
int handle_sched_switch(struct trace_event_raw_sched_switch *ctx) {
    u64 ts = bpf_ktime_get_ns();
    
    // 1. Calculate time for the process switching OUT
    u64 prev_pid_tgid = bpf_get_current_pid_tgid();
    u32 prev_tid = prev_pid_tgid;        // Bottom 32 bits = Thread ID
    u32 prev_tgid = prev_pid_tgid >> 32; // Top 32 bits = Process ID

    if (prev_tid > 0) {
        u64 *start = bpf_map_lookup_elem(&start_time, &prev_tid);
        if (start != NULL) {
            u64 delta = ts - *start;
            u64 *total = bpf_map_lookup_elem(&cpu_time, &prev_tgid);
            if (total != NULL) {
                // Safely add time if it already exists in the map
                __sync_fetch_and_add(total, delta);
            } else {
                // Create a new entry for this process
                bpf_map_update_elem(&cpu_time, &prev_tgid, &delta, BPF_ANY);
            }
            // Clean up start time
            bpf_map_delete_elem(&start_time, &prev_tid);
        }
    }

    // 2. Record start time for the process switching IN
    u32 next_tid = ctx->next_pid;
    if (next_tid > 0) {
        bpf_map_update_elem(&start_time, &next_tid, &ts, BPF_ANY);
    }

    return 0;
}

char LICENSE[] SEC("license") = "Dual MIT/GPL";

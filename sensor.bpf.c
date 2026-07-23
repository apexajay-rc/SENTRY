#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

// 1. Data Payload: Report TGID, comm, and accumulated CPU time
struct event_t {
    u32 tgid;
    char comm[16];
    u64 cpu_time_ns;
};

// 2. Per-TGID CPU time accumulator (updated on every sched_switch OUT)
BPF_HASH(cpu_time, u32, u64);

// 3. Ring buffer for high-consumption events
BPF_RINGBUF_OUTPUT(events, 256);

// 4. Per-TID last-seen timestamp (start time when switched IN)
BPF_HASH(start_time, u32, u64);

// Threshold: report if a TGID accumulates > 50ms in one scheduling window
#define REPORT_THRESHOLD_NS 50000000ULL

TRACEPOINT_PROBE(sched, sched_switch) {
    u64 now = bpf_ktime_get_ns();

    // --- Outgoing task (prev) ---
    u64 prev_pid_tgid = bpf_get_current_pid_tgid();
    u32 prev_tid = prev_pid_tgid;
    u32 prev_tgid = prev_pid_tgid >> 32;

    if (prev_tid > 0 && prev_tgid > 0) {
        u64 *start = start_time.lookup(&prev_tid);
        if (start != 0) {
            u64 delta = now - *start;

            u64 zero = 0;
            u64 *total = cpu_time.lookup_or_try_init(&prev_tgid, &zero);
            if (total) {
                *total += delta;
            }
            start_time.delete(&prev_tid);
        }
    }

    // --- Incoming task (next) ---
    u32 next_tid = args->next_pid;
    if (next_tid > 0) {
        start_time.update(&next_tid, &now);
    }

    return 0;
}
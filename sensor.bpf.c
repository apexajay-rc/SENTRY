#include <linux/sched.h>

// 1. The Data Structure
struct event_t {
    u32 pid;
    char comm[16];
};

// 2. The Ring Buffer
// BCC handles all the memory allocation and map creation for us under the hood.
BPF_RINGBUF_OUTPUT(events, 256);

// 3. The Hook
// TRACEPOINT_PROBE is a BCC macro that automatically hooks into the kernel.
TRACEPOINT_PROBE(syscalls, sys_enter_execve) {
    
    // Reserve memory on the Ring Buffer conveyor belt
    struct event_t *e = events.ringbuf_reserve(sizeof(struct event_t));
    if (!e) {
        return 0;
    }

    // Fill the struct
    e->pid = bpf_get_current_pid_tgid() >> 32;
    bpf_get_current_comm(&e->comm, sizeof(e->comm));

    // Send it to Python
    events.ringbuf_submit(e, 0);
    return 0;
}

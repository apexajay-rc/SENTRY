// 1. The Blueprint
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>

// 2. The Data Structure (Our Payload)
// This dictates the exact byte layout of the data we are sending to Python.
struct event_t {
    u32 pid;            // 32-bit Process ID
    char comm[16];      // 16-character array for the Command Name
};

// 3. The Ring Buffer Map (The Bridge)
// We tell the kernel to carve out a 256 KB chunk of memory for our queue.
struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 256 * 1024);
} events SEC(".maps");


SEC("tracepoint/syscalls/sys_enter_execve")
int bpf_sentry_hello(void *ctx) {
    u64 id = bpf_get_current_pid_tgid();
    u32 pid = id >> 32;

    // 4. Pointer & Memory Reservation
    // Ask the kernel to reserve enough space in the Ring Buffer for one 'event_t' struct.
    // We get a pointer (*e) pointing to that reserved memory address.
    struct event_t *e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    
    // If the buffer is completely full, 'e' will be NULL. We just drop the event and exit.
    if (!e) {
        return 0; 
    }

    // 5. Fill the Struct
    e->pid = pid;
    // BPF Helper to grab the name of the program (e.g., "bash", "python", "htop")
    bpf_get_current_comm(&e->comm, sizeof(e->comm)); 

    // 6. Submit to Python
    // Send the filled struct across the bridge to User Space.
    bpf_ringbuf_submit(e, 0);

    return 0;
}

char LICENSE[] SEC("license") = "Dual BSD/GPL";

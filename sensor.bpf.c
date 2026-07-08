// 1. The Blueprint
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>

// 2. The Hook (Where we listen)
// SEC (Section) tells the compiler to put this function in a specific part of the binary
// so the kernel knows exactly where to attach it. We are listening to 'execve' (when a program runs).
SEC("tracepoint/syscalls/sys_enter_execve")
int bpf_sentry_hello(void *ctx) {
    
    // 3. The BPF Helpers
    // We cannot use standard OS commands, so we ask the kernel directly who is running.
    // It returns a 64-bit integer.
    u64 id = bpf_get_current_pid_tgid();
    
    // 4. Bitwise Operations
    // The kernel packs two pieces of data into that 64-bit number to save space.
    // Thread Group ID (TGID) is the top 32 bits, and the Thread ID (PID) is the bottom 32 bits.
    // We shift the bits 32 spaces to the right (>>) to isolate the PID.
    u32 pid = id >> 32;

    // 5. The Output
    // We cannot use printf(). We use the kernel's internal logger.
    bpf_printk("SENTRY BASE CAMP COMPLETE. Target PID: %d executing.\\n", pid);

    // The Verifier demands that we always return 0 to prove the function finishes.
    return 0;
}

// 6. The Bouncer's Requirement
// The Linux kernel strictly refuses to load eBPF code unless it has a GPL-compatible license.
char LICENSE[] SEC("license") = "Dual BSD/GPL";

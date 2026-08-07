#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>

// STRICT COMPLIANCE: eBPF struct_ops require a GPL license to access kernel helpers.
char _license[] SEC("license") = "GPL";

// -----------------------------------------------------------------------------
// SHARED MEMORY (eBPF MAPS)
// -----------------------------------------------------------------------------
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __type(key, u32);
    __type(value, u32);
    __uint(max_entries, 1);
} vip_pid_map SEC(".maps");

// -----------------------------------------------------------------------------
// SCHEDULER LOGIC (THE DICTATOR)
// -----------------------------------------------------------------------------
SEC("struct_ops/sentry_enqueue")
void BPF_PROG(sentry_enqueue, struct task_struct *p, u64 enq_flags)
{
    u32 key = 0;
    u32 *vip_pid_ptr;
    u32 vip_pid = 0;

    vip_pid_ptr = bpf_map_lookup_elem(&vip_pid_map, &key);
    if (vip_pid_ptr) {
        vip_pid = *vip_pid_ptr;
    }

    if (vip_pid != 0 && p->tgid == vip_pid) {
        // TARGET ACQUIRED: Dispatch directly to the LOCAL Dispatch Queue.
        scx_bpf_dsq_insert(p, SCX_DSQ_LOCAL, SCX_SLICE_DFL, enq_flags);
        return;
    }

    // BACKGROUND CONTAINMENT: Dispatch to the kernel's built-in Global DSQ.
    scx_bpf_dsq_insert(p, SCX_DSQ_GLOBAL, SCX_SLICE_DFL, enq_flags);
}

// -----------------------------------------------------------------------------
// STRUCT_OPS REGISTRATION
// -----------------------------------------------------------------------------
SEC(".struct_ops")
struct sched_ext_ops sentry_ops = {
    .enqueue = (void *)sentry_enqueue,
    .name = "sentry_dictator",
};

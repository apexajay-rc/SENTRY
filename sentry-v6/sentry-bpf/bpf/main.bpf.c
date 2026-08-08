#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>

char _license[] SEC("license") = "GPL";

// -----------------------------------------------------------------------------
// SHARED MEMORY: Process Dependency Graph (Hash Map)
// -----------------------------------------------------------------------------
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __type(key, u32);   // The Process ID (TGID)
    __type(value, u8);  // Boolean VIP Flag (1 = active)
    __uint(max_entries, 1024); // Support a tree of up to 1,024 processes
} vip_process_tree SEC(".maps");

// -----------------------------------------------------------------------------
// SCHEDULER LOGIC (THE DICTATOR)
// -----------------------------------------------------------------------------
SEC("struct_ops/sentry_enqueue")
void BPF_PROG(sentry_enqueue, struct task_struct *p, u64 enq_flags)
{
    u32 tgid = p->tgid;
    u8 *is_vip;

    // Check if this specific task exists anywhere in our VIP Process Tree
    is_vip = bpf_map_lookup_elem(&vip_process_tree, &tgid);

    if (is_vip && *is_vip == 1) {
        // TREE MEMBER ACQUIRED: Dispatch directly to the LOCAL Dispatch Queue.
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

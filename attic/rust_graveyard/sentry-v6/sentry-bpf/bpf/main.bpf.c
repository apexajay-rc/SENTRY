#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>

char LICENSE[] SEC("license") = "Dual BSD/GPL";

#define MAX_PIDS 1024
#define MAX_CORES 128

// 1. VIP Process Tree Map
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, MAX_PIDS);
    __type(key, u32);
    __type(value, u8);
} vip_process_tree SEC(".maps");

// 2. Hardware Topology Maps (Injected by Rust)
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, MAX_CORES);
    __type(key, u32);
    __type(value, u32);
} vip_cores_list SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);
    __type(key, u32);
    __type(value, u32);
} vip_cores_count SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, MAX_CORES);
    __type(key, u32);
    __type(value, u32);
} bg_cores_list SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);
    __type(key, u32);
    __type(value, u32);
} bg_cores_count SEC(".maps");

// Atomic Round-Robin Counters
u32 vip_rr_idx = 0;
u32 bg_rr_idx = 0;

// 3. The Hardware Silicon Router Hook (Using BPF_PROG to unwrap the R1 Context)
SEC("struct_ops/select_cpu")
int BPF_PROG(sentry_select_cpu, struct task_struct *p, s32 prev_cpu, u64 wake_flags)
{
    u32 pid = p->pid;
    u8 *is_vip = bpf_map_lookup_elem(&vip_process_tree, &pid);
    
    u32 zero = 0;
    u32 count_val;
    u32 *core_id;
    
    if (is_vip) {
        // VIP ROUTING (L3 Cache Fortress)
        u32 *c_ptr = bpf_map_lookup_elem(&vip_cores_count, &zero);
        if (!c_ptr) return prev_cpu;
        count_val = *c_ptr;
        
        if (count_val == 0 || count_val > MAX_CORES) return prev_cpu;
        
        u32 idx = __sync_fetch_and_add(&vip_rr_idx, 1);
        u32 array_idx = idx % count_val;
        
        if (array_idx >= MAX_CORES) return prev_cpu;
        core_id = bpf_map_lookup_elem(&vip_cores_list, &array_idx);
    } else {
        // BACKGROUND ROUTING (The Quarantine Zone)
        u32 *c_ptr = bpf_map_lookup_elem(&bg_cores_count, &zero);
        if (!c_ptr) return prev_cpu;
        count_val = *c_ptr;
        
        if (count_val == 0 || count_val > MAX_CORES) return prev_cpu;
        
        u32 idx = __sync_fetch_and_add(&bg_rr_idx, 1);
        u32 array_idx = idx % count_val;
        
        if (array_idx >= MAX_CORES) return prev_cpu;
        core_id = bpf_map_lookup_elem(&bg_cores_list, &array_idx);
    }
    
    if (!core_id) return prev_cpu;
    return *core_id; 
}

SEC(".struct_ops.link")
struct sched_ext_ops sentry_ops = {
    .select_cpu  = (void *)sentry_select_cpu,
    .name        = "sentry",
};

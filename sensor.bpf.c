#include <linux/sched.h>

// 1. The Data Payload
// We added a new 64-bit integer to hold the exact nanoseconds spent on the CPU.
struct event_t {
    u32 pid;
    char comm[16];
    u64 duration_ns;
};

// 2. The Kernel Scratchpad (Hash Map)
// Key = PID (32-bit int), Value = Start Timestamp (64-bit int)
BPF_HASH(start_time, u32, u64);

// 3. The Bridge to Python
BPF_RINGBUF_OUTPUT(events, 256);

// 4. The Scheduler Hook
// This fires every single time the CPU switches tasks.
TRACEPOINT_PROBE(sched, sched_switch) {
    u32 prev_pid = args->prev_pid;  // The process getting kicked OFF the CPU
    u32 next_pid = args->next_pid;  // The process stepping ONTO the CPU
    
    // Get the current time directly from the CPU hardware in nanoseconds
    u64 now = bpf_ktime_get_ns();

    // ----------------------------------------------------
    // STEP A: Start the stopwatch for the incoming process
    // ----------------------------------------------------
    start_time.update(&next_pid, &now);

    // ----------------------------------------------------
    // STEP B: Stop the stopwatch for the outgoing process
    // ----------------------------------------------------
    // Look up when the outgoing process started
    u64 *tsp = start_time.lookup(&prev_pid);
    if (tsp != NULL) {
        // Calculate total nanoseconds spent on the CPU
        u64 duration = now - *tsp;
        
        // Delete the timestamp to save kernel memory
        start_time.delete(&prev_pid);

        // FILTER: The CPU switches tasks thousands of times a second. 
        // To avoid flooding Python, we only report bursts longer than 1 millisecond (1,000,000 ns).
        if (duration > 1000000) {
            
            // Reserve space on the Ring Buffer
            struct event_t *e = events.ringbuf_reserve(sizeof(struct event_t));
            if (e) {
                e->pid = prev_pid;
                e->duration_ns = duration;
                
                // Safely copy the command name of the outgoing process
                bpf_probe_read_kernel_str(&e->comm, sizeof(e->comm), args->prev_comm);
                
                // Submit to Python
                events.ringbuf_submit(e, 0);
            }
        }
    }
    return 0;
}

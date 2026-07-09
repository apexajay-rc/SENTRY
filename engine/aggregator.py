"""
engine/aggregator.py

Processes high-speed eBPF telemetry, maintaining sliding time windows
to calculate real-time CPU utilization percentages per process.
"""

import time
from collections import defaultdict

class CPUMonitor:
    def __init__(self, window_size_sec=1.0, cpu_limit_pct=80.0):
        # Convert our 1-second window into nanoseconds for easy math
        self.window_size_ns = window_size_sec * 1_000_000_000
        self.cpu_limit_pct = cpu_limit_pct
        
        # A dictionary where Key = PID, Value = List of (timestamp, duration)
        self.history = defaultdict(list)

    def add_burst(self, pid: int, duration_ns: int):
        """Records a CPU burst and instantly evaluates if the process is violating limits."""
        now_ns = time.time_ns()
        
        # 1. Record the burst
        self.history[pid].append((now_ns, duration_ns))
        
        # 2. Prune old data (The Sliding Window)
        cutoff = now_ns - self.window_size_ns
        self.history[pid] = [b for b in self.history[pid] if b[0] > cutoff]
        
        # 3. Sum the remaining bursts in the window
        total_cpu_ns = sum(b[1] for b in self.history[pid])
        
        # 4. Calculate true CPU percentage
        cpu_pct = (total_cpu_ns / self.window_size_ns) * 100.0
        
        # 5. Evaluate
        if cpu_pct > self.cpu_limit_pct:
            return cpu_pct  # Violation detected!
            
        return None

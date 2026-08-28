from dataclasses import dataclass
from typing import List

@dataclass(frozen=True)
class ProcessMetric:
    pid: int
    cpu_pct: float      # System-wide CPU percentage
    rss_bytes: int      # Memory footprint in bytes

@dataclass(frozen=True)
class Allocation:
    pid: int
    cpu_quota_pct: int
    memory_limit_bytes: int

def allocate(policy_cpu: int, policy_mem_mult: float, hogs: List[ProcessMetric]) -> List[Allocation]:
    """
    Proportional fair sharing:
    - CPU: Allocated based on excess over fair_share (100 / N).
    - Memory: RSS * multiplier (dynamic floor).
    """
    if not hogs:
        return []

    n = min(len(hogs), 10)  # Cap at top 10
    hogs = sorted(hogs, key=lambda h: h.cpu_pct, reverse=True)[:n]

    # CPU: Fair share = 100% / n per hog
    fair_share = 100.0 / n
    excess = [(h.pid, max(0, h.cpu_pct - fair_share)) for h in hogs]
    total_excess = sum(e for _, e in excess)

    allocations = []
    for h in hogs:
        pid = h.pid
        exc = next(e for p, e in excess if p == pid)
        
        # CPU weight: proportional to excess, floored at 10%
        if total_excess > 0:
            weight = max(10, int(policy_cpu * exc / total_excess))
        else:
            # If all are perfectly equal (no excess), divide the budget equally
            weight = max(10, int(policy_cpu / n))
        
        # Memory: RSS * multiplier
        mem_limit = int(h.rss_bytes * policy_mem_mult)
        
        allocations.append(Allocation(pid, weight, mem_limit))

    return allocations

from dataclasses import dataclass
from typing import List

@dataclass(frozen=True)
class ProcessMetric:
    pid: int
    cpu_pct: float
    rss_bytes: int

@dataclass(frozen=True)
class Allocation:
    pid: int
    cpu_quota_pct: int
    cpu_weight: int
    memory_limit_bytes: int

def allocate(policy_max_quota_pct: int, policy_mem_mult: float, hogs: List[ProcessMetric]) -> List[Allocation]:
    if not hogs: return []

    n = min(len(hogs), 10)
    hogs = sorted(hogs, key=lambda h: h.cpu_pct, reverse=True)[:n]

    # MATHEMATICAL FIX: System-wide percentage matching Scanner output (0-100)
    fair_share_sys = 100.0 / n
    excess = [(h.pid, max(0, h.cpu_pct - fair_share_sys)) for h in hogs]
    total_excess = sum(e for _, e in excess)

    allocations = []
    for h in hogs:
        exc = next(e for p, e in excess if p == h.pid)
        if total_excess > 0:
            weight_ratio = exc / total_excess
            quota = max(5, int(policy_max_quota_pct * weight_ratio))
            weight = max(10, int(10000 * weight_ratio))
        else:
            quota = policy_max_quota_pct
            weight = 10000
        
        mem_limit = int(h.rss_bytes * policy_mem_mult)
        allocations.append(Allocation(h.pid, quota, weight, mem_limit))

    return allocations

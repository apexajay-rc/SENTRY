from src.sentry_v2.policy.fair_share import ProcessMetric, allocate
import os

def test_fair_share():
    print("--- GATE 2 FAIR SHARE VERIFICATION ---")
    print(f"System Cores: {os.cpu_count() or 1}")
    
    # Simulating 4 PIDs on an 8-core machine. 
    # If each maxes 1 core perfectly, they represent 12.5% system-wide each.
    hogs = [
        ProcessMetric(pid=101, cpu_pct=12.5, rss_bytes=50_000_000),
        ProcessMetric(pid=102, cpu_pct=12.5, rss_bytes=50_000_000),
        ProcessMetric(pid=103, cpu_pct=12.5, rss_bytes=50_000_000),
        ProcessMetric(pid=104, cpu_pct=12.5, rss_bytes=50_000_000),
    ]
    
    # Using MODERATE policy limits
    allocs = allocate(policy_max_quota_pct=70, policy_mem_mult=1.5, hogs=hogs)
    
    for a in allocs:
        print(f"PID {a.pid} -> Quota: {a.cpu_quota_pct}% | Weight: {a.cpu_weight} | Mem Limit: {a.memory_limit_bytes:,} bytes")

if __name__ == "__main__":
    test_fair_share()

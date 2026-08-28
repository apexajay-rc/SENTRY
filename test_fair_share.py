from src.sentry_v2.policy.fair_share import ProcessMetric, allocate

def run_benchmark():
    print("--- FAIR-SHARE ALLOCATION BENCHMARK ---\n")
    
    # Test 1: 4 Equal Hogs
    print("SCENARIO 1: 4 Equal Hogs (25% CPU each)")
    print("Target Policy Budget: 50% total CPU limit")
    hogs_equal = [
        ProcessMetric(pid=1001, cpu_pct=25.0, rss_bytes=100_000_000),
        ProcessMetric(pid=1002, cpu_pct=25.0, rss_bytes=100_000_000),
        ProcessMetric(pid=1003, cpu_pct=25.0, rss_bytes=100_000_000),
        ProcessMetric(pid=1004, cpu_pct=25.0, rss_bytes=100_000_000),
    ]
    allocs_equal = allocate(policy_cpu=50, policy_mem_mult=1.5, hogs=hogs_equal)
    for a in allocs_equal:
        print(f"  PID {a.pid} -> CPU Quota: {a.cpu_quota_pct}% | Mem Limit: {a.memory_limit_bytes:,} bytes")


    # Test 2: Proportional Allocation (Asymmetric Load)
    print("\nSCENARIO 2: Asymmetric Hogs (One massive, one small)")
    print("Target Policy Budget: 50% total CPU limit")
    hogs_asym = [
        ProcessMetric(pid=2001, cpu_pct=80.0, rss_bytes=500_000_000), # Massive Hog
        ProcessMetric(pid=2002, cpu_pct=20.0, rss_bytes=50_000_000),  # Minor Hog
    ]
    allocs_asym = allocate(policy_cpu=50, policy_mem_mult=1.2, hogs=hogs_asym)
    for a in allocs_asym:
        print(f"  PID {a.pid} -> CPU Quota: {a.cpu_quota_pct}% | Mem Limit: {a.memory_limit_bytes:,} bytes")

if __name__ == "__main__":
    run_benchmark()

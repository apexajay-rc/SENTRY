from src.sentry_v2.metrics.sampler import SystemSample
from src.sentry_v2.policy.scoring import compute_stress
from src.sentry_v2.config import SentryConfig

def run_test():
    config = SentryConfig.load()
    
    print("--- SIMULATING SYSTEM STATE ---")
    # Simulating 90% CPU, 80% RAM, 10% IOWait, and a critical CPU PSI of 15.0
    mock_sample = SystemSample(
        cpu_pct=90.0, 
        mem_pct=80.0, 
        io_wait_pct=10.0, 
        psi_cpu=15.0, 
        psi_mem=2.0, 
        psi_io=1.0
    )
    
    print(f"Sample Input: CPU={mock_sample.cpu_pct}%, Mem={mock_sample.mem_pct}%")
    print(f"PSI Input: CPU={mock_sample.psi_cpu}")
    
    score = compute_stress(mock_sample, config.thresholds)
    
    print("\n--- STRESS SCORE COMPUTED ---")
    print(f"Base Utilization: {score.utilization} / 100")
    print(f"PSI Triggered:    {score.psi_triggered} (+20 penalty applied)")
    print(f"Combined Score:   {score.combined} / 120")
    
if __name__ == "__main__":
    run_test()

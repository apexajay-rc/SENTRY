from dataclasses import dataclass
from src.sentry_v2.metrics.sampler import SystemSample
from src.sentry_v2.config import ThresholdConfig

@dataclass(frozen=True)
class StressScore:
    utilization: float      # 0-100
    psi_triggered: bool     # Any PSI avg10 >= threshold
    combined: float         # utilization + (20 if psi_triggered else 0)

def compute_stress(sample: SystemSample, thresholds: ThresholdConfig) -> StressScore:
    # Utilization weight: CPU 50%, Mem 30%, IO 20%
    util = 0.5 * sample.cpu_pct + 0.3 * sample.mem_pct + 0.2 * sample.io_wait_pct
    
    psi_triggered = any(
        p is not None and p >= thresholds.psi_trigger
        for p in (sample.psi_cpu, sample.psi_mem, sample.psi_io)
    )
    
    combined = util + (20.0 if psi_triggered else 0.0)
    return StressScore(utilization=round(util, 2), psi_triggered=psi_triggered, combined=round(combined, 2))

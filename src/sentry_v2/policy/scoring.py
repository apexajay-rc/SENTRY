from dataclasses import dataclass
from src.sentry_v2.metrics.sampler import SystemSample
from src.sentry_v2.config import ThresholdConfig

@dataclass(frozen=True)
class StressScore:
    utilization: float
    psi_triggered: bool
    combined: float

def compute_stress(sample: SystemSample, thresholds: ThresholdConfig) -> StressScore:
    # REMEDIATION 6: PSI Dominance. If a resource is stalling via PSI, 
    # we treat it as 100% saturated for the scoring calculation.
    cpu_comp = max(sample.cpu_pct, 100.0) if (sample.psi_cpu and sample.psi_cpu >= thresholds.psi_trigger) else sample.cpu_pct
    mem_comp = max(sample.mem_pct, 100.0) if (sample.psi_mem and sample.psi_mem >= thresholds.psi_trigger) else sample.mem_pct
    io_comp  = max(sample.io_wait_pct, 100.0) if (sample.psi_io and sample.psi_io >= thresholds.psi_trigger) else sample.io_wait_pct
    
    util = 0.5 * cpu_comp + 0.3 * mem_comp + 0.2 * io_comp
    psi_triggered = any(p is not None and p >= thresholds.psi_trigger for p in (sample.psi_cpu, sample.psi_mem, sample.psi_io))
    
    return StressScore(
        utilization=round(util, 2), 
        psi_triggered=psi_triggered, 
        combined=round(util, 2)
    )

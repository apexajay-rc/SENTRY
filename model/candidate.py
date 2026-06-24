from dataclasses import dataclass

from core.process import ProcessMetrics
from engine.classifier import WorkloadType


@dataclass(frozen=True)
class MitigationCandidate:
    """
    Candidate process for mitigation.

    resource_score:
        How expensive the process is.

    protection_penalty:
        How much protection policy grants.

    selection_score:
        Final ranking score.
    """

    process: ProcessMetrics
    workload: WorkloadType

    resource_score: float
    protection_penalty: float

    selection_score: float

    reason: str

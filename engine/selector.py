"""
Mitigation Target Selector.

Converts process metrics and workload classifications
into ranked mitigation candidates.
"""

from typing import List

from core.process import ProcessMetrics
from engine.classifier import (
    WorkloadType,
    classify_process,
)
from model.candidate import MitigationCandidate


PROTECTION_MATRIX = {
    "LOW": {
        WorkloadType.SYSTEM: 1000,
        WorkloadType.INTERACTIVE: 100,
        WorkloadType.UNKNOWN: 25,
        WorkloadType.BACKGROUND: 0,
        WorkloadType.BATCH: 0,
    },
    "MODERATE": {
        WorkloadType.SYSTEM: 1000,
        WorkloadType.INTERACTIVE: 75,
        WorkloadType.UNKNOWN: 20,
        WorkloadType.BACKGROUND: 0,
        WorkloadType.BATCH: 0,
    },
    "HIGH": {
        WorkloadType.SYSTEM: 1000,
        WorkloadType.INTERACTIVE: 40,
        WorkloadType.UNKNOWN: 10,
        WorkloadType.BACKGROUND: 0,
        WorkloadType.BATCH: 0,
    },
    "CRITICAL": {
        WorkloadType.SYSTEM: 1000,
        WorkloadType.INTERACTIVE: 10,
        WorkloadType.UNKNOWN: 0,
        WorkloadType.BACKGROUND: 0,
        WorkloadType.BATCH: 0,
    },
}


class MitigationSelector:
    """
    Produces ranked mitigation candidates.
    """

    def rank_candidates(
        self,
        processes: List[ProcessMetrics],
        pressure_level: str,
    ) -> List[MitigationCandidate]:

        candidates: List[MitigationCandidate] = []

        pressure_level = pressure_level.upper()

        protections = PROTECTION_MATRIX.get(
            pressure_level,
            PROTECTION_MATRIX["HIGH"],
        )

        for process in processes:

            workload = classify_process(process.comm)

            protection_penalty = protections.get(
                workload,
                0,
            )

            if protection_penalty >= 1000:
                continue

            resource_score = process.score

            selection_score = round(
                resource_score - protection_penalty,
                2,
            )

            candidate = MitigationCandidate(
                process=process,
                workload=workload,
                resource_score=resource_score,
                protection_penalty=protection_penalty,
                selection_score=selection_score,
                reason=self._build_reason(
                    workload,
                    pressure_level,
                ),
            )

            candidates.append(candidate)

        candidates.sort(
            key=lambda c: c.selection_score,
            reverse=True,
        )

        return candidates

    @staticmethod
    def _build_reason(
        workload: WorkloadType,
        pressure_level: str,
    ) -> str:

        return (
            f"{workload.value} workload "
            f"under {pressure_level.lower()} pressure"
        )

from dataclasses import dataclass


@dataclass
class ActionOutcome:
    pid: int

    stress_before: float
    stress_after: float

    pressure_before: str
    pressure_after: str

    improvement: float

    successful: bool

from collections import deque
from typing import Deque, Iterable, Optional


DEFAULT_THRESHOLDS = {
    "low": 0.25,
    "moderate": 0.45,
    "high": 0.65,
}

MODE_HIGH_THRESHOLDS = {
    "Gaming": 0.40,
    "Editing": 0.50,
    "Balanced": 0.45,
}


def classify_stress(score: float, mode: str = "Balanced") -> str:
    high_threshold = MODE_HIGH_THRESHOLDS.get(mode, MODE_HIGH_THRESHOLDS["Balanced"])

    if score < DEFAULT_THRESHOLDS["low"]:
        return "LOW"
    if score < high_threshold:
        return "MODERATE"
    if score < DEFAULT_THRESHOLDS["high"]:
        return "HIGH"
    return "CRITICAL"


def trend_rising(history: Iterable[float], minimum: int = 5) -> bool:
    values = list(history)
    if len(values) < minimum:
        return False

    first_half = values[:2]
    second_half = values[-2:]
    return (sum(second_half) / len(second_half)) > (sum(first_half) / len(first_half))


def trend_label(history: Deque[float], minimum: int = 5) -> str:
    if len(history) < minimum:
        return "Collecting"
    return "Rising" if trend_rising(history, minimum) else "Stable"


def decision_hint(level: str, trend: str) -> str:
    if level == "HIGH" and trend == "Rising":
        return "Mitigation advised"
    if level == "MODERATE":
        return "Observe closely"
    return "Stable"

"""
Stress classification and trend analysis.

NOTE: This module now delegates to core/policy.py for all stress level classification
to ensure daemon and dashboard agree on system levels. The thresholds come from the
config (YAML), not hardcoded defaults here.

trend_rising() and trend_label() remain here as they are trend-specific, not
threshold-specific.
"""

from collections import deque
from typing import Deque, Iterable, Optional

from core.policy import classify_basic


def classify_stress(score: float, mode: str = "Balanced") -> str:
    """
    Classify system stress level based on score and mode.
    
    DEPRECATED: Use core/policy.py::classify_basic() instead, which is config-driven.
    
    This function now delegates to classify_basic() to ensure consistency between
    daemon and dashboard. The mode parameter is ignored (it's stored in DaemonState
    but the daemon doesn't currently use it to adjust thresholds).
    
    Future: Once DaemonState.mode is wired into policy decisions, this will
    respect mode to adjust thresholds dynamically.
    
    Args:
        score: Stress score [0, 1]
        mode: System mode (Gaming/Editing/Balanced) — currently unused
    
    Returns:
        One of ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    """
    # Ignore mode for now; use config-driven thresholds
    return classify_basic(score)


def trend_rising(history: Iterable[float], minimum: int = 5) -> bool:
    """
    Detect whether stress is rising based on recent history.
    
    Compares the average of the first 2 samples to the average of the last 2 samples.
    Returns True if stress is trending upward.
    
    Args:
        history: Iterable of stress scores (typically a deque)
        minimum: Minimum number of samples required (default 5)
    
    Returns:
        True if trend is rising, False otherwise
    """
    values = list(history)
    if len(values) < minimum:
        return False

    first_half = values[:2]
    second_half = values[-2:]
    return (sum(second_half) / len(second_half)) > (sum(first_half) / len(first_half))


def trend_label(history: Deque[float], minimum: int = 5) -> str:
    """
    Summarize stress trend as a human-readable label.
    
    Args:
        history: Deque of stress scores
        minimum: Minimum samples required before making a determination
    
    Returns:
        "Rising", "Stable", or "Collecting" (insufficient data)
    """
    if len(history) < minimum:
        return "Collecting"
    return "Rising" if trend_rising(history, minimum) else "Stable"


def decision_hint(level: str, trend: str) -> str:
    """
    Provide a human-readable hint about the current decision situation.
    
    Args:
        level: Current stress level (LOW/MODERATE/HIGH/CRITICAL)
        trend: Current trend (Rising/Stable/Collecting)
    
    Returns:
        A short string describing the recommended action
    """
    if level == "HIGH" and trend == "Rising":
        return "Mitigation advised"
    if level == "MODERATE":
        return "Observe closely"
    return "Stable"

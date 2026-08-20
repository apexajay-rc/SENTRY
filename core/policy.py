"""
Policy classification module for SENTRY.
Defines stress levels and escalation thresholds.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import ConfigParser

# Stress level thresholds (customize based on workload)
THRESHOLDS = {
    "LOW": 0.35,
    "MODERATE": 0.20,
    "HIGH": 0.70,
    "CRITICAL": 0.85,
}

# Action escalation mapping: stress level → (cpu_weight, memory_limit_percent, io_weight)
ESCALATION_MATRIX = {
    "LOW": {
        "cpu_weight": 100,      # No limit
        "memory_limit_percent": 100,  # No limit
        "io_weight": 100,       # No limit
    },
    "MODERATE": {
        "cpu_weight": 50,       # 50% CPU throttle
        "memory_limit_percent": 90,   # 90% of process memory
        "io_weight": 50,        # 50% I/O throttle
    },
    "HIGH": {
        "cpu_weight": 30,       # 30% CPU throttle
        "memory_limit_percent": 75,   # 75% of process memory
        "io_weight": 30,        # 30% I/O throttle
    },
    "CRITICAL": {
        "cpu_weight": 10,       # 10% CPU throttle
        "memory_limit_percent": 50,   # 50% of process memory (hard limit)
        "io_weight": 10,        # 10% I/O throttle
    },
}


def configure_policy(config: "ConfigParser") -> None:
    """Apply thresholds and escalation matrix from sentry_config.yaml."""
    global THRESHOLDS, ESCALATION_MATRIX

    thresholds = config.all_thresholds()  # type: ignore[attr-defined]
    THRESHOLDS = {
        "LOW": thresholds.get("low", 0.35),
        "MODERATE": thresholds.get("moderate", 0.50),
        "HIGH": thresholds.get("high", 0.70),
        "CRITICAL": thresholds.get("critical", 0.85),
    }

    ESCALATION_MATRIX = {}
    for level in ["LOW", "MODERATE", "HIGH", "CRITICAL"]:
        ESCALATION_MATRIX[level] = config.get_escalation_actions(level)  # type: ignore[attr-defined]


def classify_basic(stress_score):
    """
    Classify system stress level based on computed stress score.
    
    Args:
        stress_score (float): Normalized stress score in [0, 1]
    
    Returns:
        str: One of ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    """
    if stress_score >= THRESHOLDS["CRITICAL"]:
        return "CRITICAL"
    elif stress_score >= THRESHOLDS["HIGH"]:
        return "HIGH"
    elif stress_score >= THRESHOLDS["MODERATE"]:
        return "MODERATE"
    else:
        return "LOW"


def get_action_limits(stress_level):
    """
    Get resource limit actions for a given stress level.
    
    Args:
        stress_level (str): One of ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    
    Returns:
        dict: Actions with cpu_weight, memory_limit, io_weight
    """
    return ESCALATION_MATRIX.get(stress_level, ESCALATION_MATRIX["LOW"])


def is_critical_level(stress_level):
    """Check if stress level requires immediate action."""
    return stress_level in ["HIGH", "CRITICAL"]
def get_dynamic_limits(stress_score: float, stress_delta: float) -> dict:
    """
    Calculates dynamic hardware limits using Proportional-Derivative (PD) logic.
    Replaces the rigid step-based classification to cure oscillation.
    """
    base_limit = 100
    threshold_mod = THRESHOLDS.get("MODERATE", 0.20)

    # Early exit if system is stable or actively recovering naturally
    if stress_score < threshold_mod and stress_delta <= 0:
        return {
            "cpu_weight": base_limit,
            "memory_limit_percent": ESCALATION_MATRIX["LOW"]["memory_limit_percent"],
            "io_weight": base_limit,
            "state": "LOW"
        }

    # Proportional penalty: How severe is the current absolute stress?
    p_penalty = max(0.0, (stress_score - threshold_mod) * 100)
    
    # Derivative penalty: How fast is it climbing/falling?
    d_penalty = stress_delta * 200

    total_penalty = p_penalty + d_penalty
    
    # Clamp dynamic limit safely between 5% and 100%
    dynamic_limit = max(5, min(100, int(100 - total_penalty)))

    # Resolve discrete state for HUD logging and static memory limits
    if dynamic_limit < 20:
        state = "CRITICAL"
    elif dynamic_limit < 60:
        state = "HIGH"
    elif dynamic_limit < 100:
        state = "MODERATE"
    else:
        state = "LOW"

    mem_limit = ESCALATION_MATRIX.get(state, ESCALATION_MATRIX["LOW"])["memory_limit_percent"]

    return {
        "cpu_weight": dynamic_limit,
        "memory_limit_percent": mem_limit,
        "io_weight": dynamic_limit,
        "state": state
    }
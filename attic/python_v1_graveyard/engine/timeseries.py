"""
engine/timeseries.py

Provides time-series smoothing for process metrics to prevent 
control-loop flapping during transient resource spikes.
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)

class ProcessEmaTracker:
    """
    Tracks the Exponential Moving Average (EMA) of a metric for active processes.
    Optimized for low memory overhead (O(1) storage per process).
    """

    def __init__(self, alpha: float = 0.3) -> None:
        """
        Args:
            alpha: The smoothing factor between 0 and 1. 
                   A higher alpha discounts older observations faster.
        """
        if not 0.0 < alpha <= 1.0:
            raise ValueError("Alpha must be strictly between 0.0 and 1.0")
        
        self.alpha = alpha
        # Maps PID to its current EMA value
        self._emas: Dict[int, float] = {}

    def update(self, pid: int, current_value: float) -> float:
        """
        Updates the EMA for a given process and returns the smoothed value.
        
        Args:
            pid: The process ID.
            current_value: The raw metric value observed in the current tick.
            
        Returns:
            The newly calculated EMA.
        """
        if current_value < 0:
            logger.warning(f"Negative metric value {current_value} reported for PID {pid}")
            current_value = 0.0

        if pid not in self._emas:
            # First observation initializes the EMA
            self._emas[pid] = float(current_value)
            return self._emas[pid]

        # EMA Formula
        previous_ema = self._emas[pid]
        new_ema = (current_value * self.alpha) + (previous_ema * (1.0 - self.alpha))
        self._emas[pid] = new_ema
        
        return new_ema

    def get_ema(self, pid: int) -> float:
        """Retrieves the current EMA for a PID without updating it."""
        return self._emas.get(pid, 0.0)

    def remove(self, pid: int) -> None:
        """Stops tracking a process (e.g., when it terminates)."""
        self._emas.pop(pid, None)

    def clear(self) -> None:
        """Wipes all tracking state."""
        self._emas.clear()

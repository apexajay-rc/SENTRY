"""
engine/selector.py

Identifies the process consuming the most resources.
Utilizes Exponential Moving Averages (EMA) to prevent flapping 
and ignores transient metric spikes.
"""

import os
import logging
from typing import Optional

from engine.timeseries import ProcessEmaTracker

logger = logging.getLogger(__name__)

class TargetSelector:
    """
    Scans the process tree on demand to find the best candidate for mitigation.
    """

    def __init__(self) -> None:
        # Alpha of 0.4 means recent spikes carry weight, but history still matters.
        self.ema_tracker = ProcessEmaTracker(alpha=0.4)
        # Page size is typically 4096 bytes on Linux. Used to calculate RSS.
        self.page_size = os.sysconf("SC_PAGE_SIZE")

    def _get_rss_bytes(self, pid: int) -> float:
        """
        Reads the Resident Set Size (RSS) in bytes for a given PID.
        RSS is the second field in /proc/[pid]/statm, representing physical memory.
        """
        try:
            with open(f"/proc/{pid}/statm", "r") as f:
                statm_data = f.read().split()
                # Field 1 is RSS in pages
                rss_pages = int(statm_data[1])
                return float(rss_pages * self.page_size)
        except (FileNotFoundError, IndexError, ValueError):
            # Process died or file is malformed
            return 0.0
        except OSError as e:
            logger.debug(f"Failed to read statm for PID {pid}: {e}")
            return 0.0

    def select_target(self) -> Optional[int]:
        """
        Scans all running processes, updates their moving averages,
        and returns the PID of the highest memory consumer.
        
        Returns:
            The PID (int) of the target, or None if no valid targets exist.
        """
        highest_pid: Optional[int] = None
        highest_ema: float = -1.0
        active_pids = set()

        try:
            # Iterate through all numerical directories in /proc
            for entry in os.scandir("/proc"):
                if not entry.is_dir() or not entry.name.isdigit():
                    continue

                pid = int(entry.name)
                active_pids.add(pid)
                
                current_rss = self._get_rss_bytes(pid)
                if current_rss == 0.0:
                    continue

                # Smooth the raw metric to prevent flapping
                smoothed_rss = self.ema_tracker.update(pid, current_rss)

                if smoothed_rss > highest_ema:
                    highest_ema = smoothed_rss
                    highest_pid = pid

        except OSError as e:
            logger.error(f"Error scanning /proc during target selection: {e}")

        # Cleanup: Remove dead processes from the EMA tracker to prevent memory leaks
        # We check the internal tracker's keys against the active_pids we just saw.
        tracked_pids = list(self.ema_tracker._emas.keys())
        for tracked_pid in tracked_pids:
            if tracked_pid not in active_pids:
                self.ema_tracker.remove(tracked_pid)

        if highest_pid:
            mb_usage = highest_ema / (1024 * 1024)
            logger.info(f"Target selected: PID {highest_pid} with smoothed RSS of {mb_usage:.2f} MB")
            
        return highest_pid

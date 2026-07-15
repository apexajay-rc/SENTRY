"""
core/psi_sensor.py

Native Linux Pressure Stall Information (PSI) reader.
Detects memory starvation before the OOM-killer activates.
"""

import os
from typing import Optional

class PSISensor:
    def __init__(self, threshold: float = 5.0) -> None:
        self.threshold = threshold
        self.psi_path = "/proc/pressure/memory"
        self.is_supported = os.path.exists(self.psi_path)

    def check_memory_pressure(self) -> bool:
        """Returns True if memory 'some' avg10 exceeds the threshold."""
        if not self.is_supported:
            return False
            
        try:
            with open(self.psi_path, "r") as f:
                for line in f:
                    if line.startswith("some"):
                        # format: some avg10=0.00 avg60=0.00 avg300=0.00 total=0
                        parts = line.split()
                        avg10_str = parts[1].split("=")[1]
                        if float(avg10_str) >= self.threshold:
                            return True
                        break
        except Exception:
            return False
            
        return False

    def find_largest_memory_hog(self) -> int:
        """Rapidly scans /proc to find the process with the largest RSS."""
        max_rss = 0
        hog_pid = -1
        
        try:
            for pid_str in os.listdir("/proc"):
                if not pid_str.isdigit():
                    continue
                pid = int(pid_str)
                try:
                    with open(f"/proc/{pid}/statm", "r") as f:
                        rss_pages = int(f.read().split()[1])
                        if rss_pages > max_rss:
                            max_rss = rss_pages
                            hog_pid = pid
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    continue
        except Exception:
            pass
                
        return hog_pid

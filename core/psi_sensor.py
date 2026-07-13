"""
core/psi_sensor.py
Reads the Linux Pressure Stall Information (PSI) interface to detect
if the system is actively thrashing or starving for RAM.
"""

import os
import logging

logger = logging.getLogger(__name__)

class PSISensor:
    def __init__(self):
        self.psi_file = "/proc/pressure/memory"
        self._verify_psi_support()

    def _verify_psi_support(self):
        """Ensures the Linux kernel was compiled with CONFIG_PSI=y."""
        if not os.path.exists(self.psi_file):
            logger.error(f"PSI not supported or disabled. Cannot find {self.psi_file}.")
            logger.error("You may need to add 'psi=1' to your GRUB kernel boot parameters.")

    def get_memory_pressure(self) -> float:
        """
        Reads the 10-second moving average of memory pressure.
        Returns a float representing the percentage of time tasks were stalled.
        """
        try:
            with open(self.psi_file, "r") as f:
                for line in f:
                    # We look at "some", meaning at least one task was stalled waiting for RAM
                    # Format: some avg10=0.00 avg60=0.00 avg300=0.00 total=12345
                    if line.startswith("some"):
                        parts = line.split()
                        for part in parts:
                            if part.startswith("avg10="):
                                return float(part.split("=")[1])
        except Exception as e:
            logger.debug(f"Failed to read PSI memory pressure: {e}")
            
        return 0.0

    def is_thrashing(self, threshold=10.0) -> bool:
        """
        Returns True if the system is spending more than `threshold`% of its time 
        stalled waiting for memory in the last 10 seconds.
        """
        pressure = self.get_memory_pressure()
        if pressure > threshold:
            logger.warning(f"⚠️ HIGH MEMORY PRESSURE DETECTED: {pressure}% stall time!")
            return True
        return False

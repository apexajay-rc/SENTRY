"""
core/collectors/psi.py

Provides edge-triggered monitoring of Linux Pressure Stall Information (PSI).
Interfaces with the epoll reactor to wake the daemon only when 
resource starvation crosses defined thresholds.
"""

import os
import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

class PsiMonitor:
    """
    Configures and tracks kernel PSI triggers for CPU, Memory, and IO.
    """

    PSI_ROOT = "/proc/pressure"
    VALID_RESOURCES = {"cpu", "memory", "io"}
    VALID_TYPES = {"some", "full"}

    def __init__(self) -> None:
        self._active_triggers: Dict[int, str] = {}  # Maps FD to resource name
        self._verify_psi_support()

    def _verify_psi_support(self) -> None:
        """Verifies that the kernel was compiled and booted with PSI support."""
        if not os.path.exists(self.PSI_ROOT):
            raise RuntimeError(
                f"PSI not found at {self.PSI_ROOT}. "
                "Ensure kernel version >= 4.20 and booted with 'psi=1'."
            )

    def create_trigger(self, resource: str, stall_type: str, threshold_us: int, window_us: int) -> int:
        """
        Creates a kernel-level trigger for a resource stall.

        Args:
            resource: "cpu", "memory", or "io".
            stall_type: "some" or "full".
            threshold_us: The stall time in microseconds that triggers the event.
            window_us: The tracking window in microseconds (max 10000000 / 10s).

        Returns:
            The raw file descriptor (int) to be registered with an epoll loop.
        """
        if resource not in self.VALID_RESOURCES:
            raise ValueError(f"Invalid PSI resource: {resource}")
        if stall_type not in self.VALID_TYPES:
            raise ValueError(f"Invalid PSI stall type: {stall_type}")
            
        target_file = os.path.join(self.PSI_ROOT, resource)
        trigger_string = f"{stall_type} {threshold_us} {window_us}\0".encode('ascii')

        try:
            # Must be opened in Read/Write for triggers.
            # O_NONBLOCK prevents hanging on reads.
            fd = os.open(target_file, os.O_RDWR | os.O_NONBLOCK)
            
            # Write the trigger configuration to the kernel
            os.write(fd, trigger_string)
            
            self._active_triggers[fd] = resource
            logger.info(
                f"Registered PSI trigger for {resource}: "
                f"{stall_type} stall > {threshold_us}us over {window_us}us window."
            )
            return fd

        except PermissionError:
            logger.error(f"Permission denied configuring PSI for {resource}. CAP_SYS_RESOURCE required.")
            raise
        except OSError as e:
            logger.error(f"Failed to configure PSI trigger for {resource}: {e}")
            raise

    def cleanup_trigger(self, fd: int) -> None:
        """Closes the file descriptor, removing the kernel trigger."""
        if fd in self._active_triggers:
            resource = self._active_triggers.pop(fd)
            try:
                os.close(fd)
                logger.debug(f"Closed PSI trigger FD for {resource}")
            except OSError as e:
                logger.warning(f"Error closing PSI FD {fd}: {e}")

    def cleanup_all(self) -> None:
        """Closes all active PSI triggers."""
        # Copy keys to avoid dictionary size change during iteration
        fds = list(self._active_triggers.keys())
        for fd in fds:
            self.cleanup_trigger(fd)

    def __del__(self) -> None:
        self.cleanup_all()

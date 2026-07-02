"""
core/cgroup_manager.py

Provides native interfaces to manage Linux cgroups v2 boundaries.
Used to apply reversible throttling to resource-heavy processes.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class CgroupManager:
    """
    Manages resource limits via the unified cgroup v2 hierarchy.
    """

    CGROUP_ROOT = "/sys/fs/cgroup"

    def __init__(self) -> None:
        self._verify_cgroup_v2()

    def _verify_cgroup_v2(self) -> None:
        """Ensures the system is booted with cgroups v2 unified hierarchy."""
        controllers_path = os.path.join(self.CGROUP_ROOT, "cgroup.controllers")
        if not os.path.exists(controllers_path):
            raise RuntimeError(
                f"cgroup v2 not detected at {self.CGROUP_ROOT}. "
                "SENTRY requires a unified cgroup hierarchy."
            )

    def get_process_cgroup(self, pid: int) -> Optional[str]:
        """
        Resolves the cgroup path for a given PID.
        
        Args:
            pid: The process ID.
            
        Returns:
            The absolute path to the process's cgroup directory, or None if failed.
        """
        cgroup_file = f"/proc/{pid}/cgroup"
        try:
            with open(cgroup_file, "r") as f:
                for line in f:
                    # cgroup v2 format is `0::/path/to/cgroup`
                    if line.startswith("0::"):
                        cgroup_path = line.strip().split("::", 1)[1]
                        # Remove leading slash to join correctly with CGROUP_ROOT
                        if cgroup_path.startswith("/"):
                            cgroup_path = cgroup_path[1:]
                        return os.path.join(self.CGROUP_ROOT, cgroup_path)
        except FileNotFoundError:
            logger.debug(f"PID {pid} no longer exists; cannot resolve cgroup.")
            return None
        except Exception as e:
            logger.warning(f"Failed to read cgroup for PID {pid}: {e}")
            return None
            
        logger.warning(f"No unified cgroup v2 path found for PID {pid}")
        return None

    def read_limit(self, cgroup_path: str, limit_file: str) -> Optional[str]:
        """Reads a specific limit from a cgroup directory."""
        target = os.path.join(cgroup_path, limit_file)
        try:
            with open(target, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return None
        except OSError as e:
            logger.error(f"Failed to read {limit_file} from {cgroup_path}: {e}")
            return None

    def write_limit(self, cgroup_path: str, limit_file: str, value: str) -> bool:
        """
        Writes a value to a cgroup limit file.
        
        Args:
            cgroup_path: The directory of the cgroup.
            limit_file: The specific controller file (e.g., 'memory.high').
            value: The string value to write (e.g., '500M' or 'max').
            
        Returns:
            True if successful, False otherwise.
        """
        target = os.path.join(cgroup_path, limit_file)
        try:
            with open(target, "w") as f:
                f.write(value)
            logger.info(f"Successfully set {limit_file} to '{value}' for {cgroup_path}")
            return True
        except FileNotFoundError:
            logger.debug(f"Cgroup {cgroup_path} no longer exists.")
            return False
        except PermissionError:
            logger.error(f"Permission denied writing to {target}. Does SENTRY have root?")
            return False
        except OSError as e:
            logger.error(f"OS Error writing {value} to {target}: {e}")
            return False

    def throttle_memory(self, pid: int, limit_bytes: int) -> bool:
        """Applies a memory.high throttle to a specific PID's cgroup."""
        cgroup = self.get_process_cgroup(pid)
        if not cgroup:
            return False
        return self.write_limit(cgroup, "memory.high", str(limit_bytes))

    def reset_memory_throttle(self, pid: int) -> bool:
        """Removes the memory.high throttle (sets to 'max')."""
        cgroup = self.get_process_cgroup(pid)
        if not cgroup:
            return False
        return self.write_limit(cgroup, "memory.high", "max")

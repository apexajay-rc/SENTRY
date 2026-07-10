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

    def _delegate_controller(self, cgroup_path: str, controller: str = "cpu") -> None:
        """
        Walks from the cgroup root down to the parent of the target,
        enabling the specified controller in cgroup.subtree_control.
        """
        rel_path = os.path.relpath(cgroup_path, self.CGROUP_ROOT)
        if rel_path == ".":
            return
            
        parts = rel_path.split(os.sep)
        current_path = self.CGROUP_ROOT
        
        # FIX: Iterate through ALL parts (removed [:-1]). 
        # Writing before appending the part perfectly hits every parent directory,
        # ensuring the immediate parent of the target gets the delegation command.
        for part in parts: 
            subtree_file = os.path.join(current_path, "cgroup.subtree_control")
            try:
                with open(subtree_file, "w") as f:
                    f.write(f"+{controller}\n")
            except OSError as e:
                # Systemd locks some internal nodes. We log as debug and continue.
                logger.debug(f"Failed to delegate {controller} at {current_path}: {e}")
            
            current_path = os.path.join(current_path, part)

    def throttle_cpu(self, pid: int, cpu_quota_pct: int = 20) -> bool:
        """
        Clamps the CPU usage of a process using cgroups v2 cpu.max.
        """
        cgroup_path = self.get_process_cgroup(pid)
        if not cgroup_path:
            return False
            
        # 1. Force the kernel to enable the CPU controller for this path
        self._delegate_controller(cgroup_path, "cpu")
        
        cpu_max_file = os.path.join(cgroup_path, "cpu.max")
        
        # 2. Verify the file actually materialized
        if not os.path.exists(cpu_max_file):
            logger.error(f"CPU controller delegation failed. {cpu_max_file} does not exist.")
            return False
            
        quota = int((cpu_quota_pct / 100.0) * 100000)
        
        try:
            with open(cpu_max_file, 'w') as f:
                f.write(f"{quota} 100000\n")
            logger.info(f"Successfully set cpu.max to '{quota} 100000' ({cpu_quota_pct}%) for {cgroup_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to set CPU throttle: {e}")
            return False

    def reset_cpu_throttle(self, pid: int) -> bool:
        """Removes the CPU limit, allowing unlimited CPU access."""
        cgroup_path = self.get_process_cgroup(pid)
        if not cgroup_path:
            return False
            
        cpu_max_file = os.path.join(cgroup_path, "cpu.max")
        if not os.path.exists(cpu_max_file):
            return False
            
        try:
            with open(cpu_max_file, 'w') as f:
                f.write("max 100000\n")
            logger.info(f"Successfully removed CPU throttle for {cgroup_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to reset CPU throttle: {e}")
            return False

    def _verify_cgroup_v2(self) -> None:
        """Ensures the system is booted with cgroups v2 unified hierarchy."""
        controllers_path = os.path.join(self.CGROUP_ROOT, "cgroup.controllers")
        if not os.path.exists(controllers_path):
            raise RuntimeError(
                f"cgroup v2 not detected at {self.CGROUP_ROOT}. "
                "SENTRY requires a unified cgroup hierarchy."
            )

    def get_process_cgroup(self, pid: int) -> Optional[str]:
        """Resolves the cgroup path for a given PID."""
        cgroup_file = f"/proc/{pid}/cgroup"
        try:
            with open(cgroup_file, "r") as f:
                for line in f:
                    if line.startswith("0::"):
                        cgroup_path = line.strip().split("::", 1)[1]
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
        cgroup = self.get_process_cgroup(pid)
        if not cgroup:
            return False
        return self.write_limit(cgroup, "memory.high", str(limit_bytes))

    def reset_memory_throttle(self, pid: int) -> bool:
        cgroup = self.get_process_cgroup(pid)
        if not cgroup:
            return False
        return self.write_limit(cgroup, "memory.high", "max")

"""
core/cgroup_manager.py

Native Cgroups v2 and OS Scheduler manipulator.
Strictly uses safe file I/O and native syscalls to prevent shell injection.
"""

import os
import time

class CgroupManager:
    def __init__(self, logger):
        self.logger = logger
        self.throttled_tasks = {} # Format: {pid: expiration_timestamp}

    def _get_cgroup_v2_path(self, pid: int) -> str:
        """Dynamically locates a process's specific cgroup v2 path."""
        try:
            with open(f"/proc/{pid}/cgroup", "r") as f:
                lines = f.readlines()
                for line in lines:
                    if line.startswith("0::"):
                        cgroup_path = line.strip().split("0::")[1]
                        return f"/sys/fs/cgroup{cgroup_path}"
        except Exception:
            return None
        return None

    def apply_memory_throttle(self, pid: int, limit_bytes: int):
        """Applies a soft memory.high clamp via native file writes."""
        cgroup_path = self._get_cgroup_v2_path(pid)
        if not cgroup_path:
            self.logger.warning(f"Could not resolve cgroup for PID {pid}. Falling back to OS scheduler.")
            self._apply_scheduler_fallback(pid)
            return

        mem_high_path = os.path.join(cgroup_path, "memory.high")
        try:
            with open(mem_high_path, "w") as f:
                f.write(str(limit_bytes))
            self.logger.audit("CLAMP_MEMORY", pid, cgroup_path, f"Limit set to {limit_bytes} bytes")
        except PermissionError:
            self.logger.error(f"Permission denied writing to {mem_high_path}")
        except Exception as e:
            self.logger.warning(f"Cgroup write failed: {e}. Executing fallback.")
            self._apply_scheduler_fallback(pid)

    def release_memory_throttle(self, pid: int):
        """Restores memory to maximum via native file writes."""
        cgroup_path = self._get_cgroup_v2_path(pid)
        if cgroup_path:
            mem_high_path = os.path.join(cgroup_path, "memory.high")
            try:
                with open(mem_high_path, "w") as f:
                    f.write("max")
                self.logger.info(f"Released memory clamp for PID {pid}")
            except Exception:
                pass
        
        # Always release scheduler fallback just in case
        try:
            os.setpriority(os.PRIO_PROCESS, pid, 0)
        except Exception:
            pass

    def _apply_scheduler_fallback(self, pid: int):
        """Native OS syscall fallback if Cgroups are locked by systemd."""
        try:
            os.setpriority(os.PRIO_PROCESS, pid, 19)
            self.logger.audit("CLAMP_CPU_SCHEDULER", pid, "OS", "Priority reduced to +19")
        except ProcessLookupError:
            pass
        except Exception as e:
            self.logger.error(f"Scheduler fallback failed for PID {pid}: {e}")

    def release_all(self):
        """Emergency release for daemon shutdown."""
        for pid in list(self.throttled_tasks.keys()):
            self.release_memory_throttle(pid)
        self.throttled_tasks.clear()

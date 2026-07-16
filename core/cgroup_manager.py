"""
core/cgroup_manager.py

Native Cgroups v2 and OS Scheduler manipulator.
Strictly uses safe file I/O, native syscalls, and Field 22 boot-tick
verification to prevent shell injection and PID recycling auto-immunity.
"""

import os
import time
from typing import Optional, Dict, Tuple, List, Any

class CgroupManager:
    def __init__(self, logger: Any) -> None:
        self.logger = logger
        # Format: {pid: (kernel_start_ticks, expiration_timestamp)}
        self.throttled_tasks: Dict[int, Tuple[int, float]] = {}

    def _get_cgroup_v2_path(self, pid: int) -> Optional[str]:
        """Dynamically locates a process's specific cgroup v2 path."""
        try:
            with open(f"/proc/{pid}/cgroup", "r") as f:
                for line in f:
                    if line.startswith("0::"):
                        cgroup_path = line.strip().split("0::")[1]
                        return f"/sys/fs/cgroup{cgroup_path}"
        except Exception:
            return None
        return None

    def _get_process_start_time(self, pid: int) -> Optional[int]:
        """Reads /proc/[pid]/stat field 22 (starttime) to verify process identity."""
        try:
            with open(f"/proc/{pid}/stat", "r") as f:
                stat_data = f.read()
            comm_end = stat_data.rindex(")")
            fields = stat_data[comm_end + 1:].split()
            return int(fields[19])
        except Exception:
            return None

    def register_throttle(self, pid: int, unlock_time: float) -> bool:
        """Records a throttle event locked to the process's unique kernel boot tick."""
        start_time = self._get_process_start_time(pid)
        if start_time is None:
            return False
        self.throttled_tasks[pid] = (start_time, unlock_time)
        return True

    def is_throttled(self, pid: int) -> bool:
        """Checks if a PID is actively throttled while defending against PID recycling."""
        if pid not in self.throttled_tasks:
            return False
        
        recorded_start_time, _ = self.throttled_tasks[pid]
        current_start_time = self._get_process_start_time(pid)
        
        # If the process exited or the start time mismatched, the PID was recycled!
        if current_start_time is None or current_start_time != recorded_start_time:
            del self.throttled_tasks[pid]
            return False
            
        return True

    def reconcile_cooldowns(self, current_time: float) -> None:
        """Releases expired throttles and purges recycled PIDs automatically."""
        pids_to_release: List[int] = []
        pids_to_purge: List[int] = []
        
        for pid, (start_time, unlock_time) in list(self.throttled_tasks.items()):
            current_start_time = self._get_process_start_time(pid)
            if current_start_time is None or current_start_time != start_time:
                pids_to_purge.append(pid)
                continue
                
            if current_time >= unlock_time:
                pids_to_release.append(pid)
                
        for pid in pids_to_purge:
            if pid in self.throttled_tasks:
                del self.throttled_tasks[pid]
                
        for pid in pids_to_release:
            self.release_memory_throttle(pid)
            self.release_cpu_throttle(pid)
            if pid in self.throttled_tasks:
                del self.throttled_tasks[pid]

    def apply_memory_throttle(self, pid: int, limit_bytes: int) -> None:
        """Applies a soft memory.high clamp via native file writes."""
        cgroup_path = self._get_cgroup_v2_path(pid)
        if not cgroup_path:
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

    def release_memory_throttle(self, pid: int) -> None:
        """Restores memory to maximum via native file writes."""
        cgroup_path = self._get_cgroup_v2_path(pid)
        if cgroup_path:
            mem_high_path = os.path.join(cgroup_path, "memory.high")
            try:
                with open(mem_high_path, "w") as f:
                    f.write("max")
            except Exception:
                pass
        self._release_scheduler_fallback(pid)

    def apply_cpu_throttle(self, pid: int, quota_pct: int = 20) -> None:
        """Applies a hard cpu.max clamp (default 20% of a single core)."""
        cgroup_path = self._get_cgroup_v2_path(pid)
        if not cgroup_path:
            self.logger.warning(f"Could not resolve cgroup for PID {pid}. Falling back to OS scheduler.")
            self._apply_scheduler_fallback(pid)
            return

        cpu_max_path = os.path.join(cgroup_path, "cpu.max")
        # Quota is mapped against a standard 100000 microsecond period
        quota = int(quota_pct * 1000)
        try:
            with open(cpu_max_path, "w") as f:
                f.write(f"{quota} 100000")
            self.logger.audit("CLAMP_CPU", pid, cgroup_path, f"Limit set to {quota_pct}%")
        except Exception as e:
            self.logger.warning(f"Cgroup CPU write failed: {e}. Executing fallback.")
            self._apply_scheduler_fallback(pid)

    def release_cpu_throttle(self, pid: int) -> None:
        """Restores CPU to maximum via native file writes."""
        cgroup_path = self._get_cgroup_v2_path(pid)
        if cgroup_path:
            cpu_max_path = os.path.join(cgroup_path, "cpu.max")
            try:
                with open(cpu_max_path, "w") as f:
                    f.write("max 100000")
                self.logger.info(f"Released CPU clamp for PID {pid}")
            except Exception:
                pass
        self._release_scheduler_fallback(pid)

    def _apply_scheduler_fallback(self, pid: int) -> None:
        """Native OS syscall fallback if Cgroups are locked by systemd."""
        try:
            os.setpriority(os.PRIO_PROCESS, pid, 19)
            self.logger.audit("CLAMP_CPU_SCHEDULER", pid, "OS", "Priority reduced to +19")
        except Exception:
            pass

    def _release_scheduler_fallback(self, pid: int) -> None:
        try:
            os.setpriority(os.PRIO_PROCESS, pid, 0)
        except Exception:
            pass

    def release_all(self) -> None:
        """Emergency release for daemon shutdown."""
        for pid in list(self.throttled_tasks.keys()):
            self.release_memory_throttle(pid)
            self.release_cpu_throttle(pid)
        self.throttled_tasks.clear()

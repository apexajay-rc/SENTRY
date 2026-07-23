"""
core/cgroup_manager.py

Native Cgroups v2 enforcement with PID recycling defense.
Verifies writes and falls back to scheduler priority if cgroups unavailable.
"""

import os
import time
from typing import Optional, Dict, Tuple, List, Any

class CgroupManager:
    def __init__(self, logger: Any) -> None:
        self.logger = logger
        # {pid: (kernel_start_ticks, expiration_timestamp)}
        self.throttled_tasks: Dict[int, Tuple[int, float]] = {}

    def _get_cgroup_v2_path(self, pid: int) -> Optional[str]:
        """Dynamically locate a process's cgroup v2 path."""
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
        """Read /proc/[pid]/stat field 22 (starttime) for PID recycling defense."""
        try:
            with open(f"/proc/{pid}/stat", "r") as f:
                stat_data = f.read()
            comm_end = stat_data.rindex(")")
            fields = stat_data[comm_end + 1:].split()
            return int(fields[19])  # Field 22 (1-indexed) = index 19 (0-indexed after comm)
        except Exception:
            return None

    def register_throttle(self, pid: int, unlock_time: float) -> bool:
        """Record a throttle event locked to the process's unique kernel boot tick."""
        start_time = self._get_process_start_time(pid)
        if start_time is None:
            return False
        self.throttled_tasks[pid] = (start_time, unlock_time)
        return True

    def is_throttled(self, pid: int) -> bool:
        """Check if PID is actively throttled, defending against PID recycling."""
        if pid not in self.throttled_tasks:
            return False

        recorded_start, _ = self.throttled_tasks[pid]
        current_start = self._get_process_start_time(pid)

        # Process exited or PID recycled
        if current_start is None or current_start != recorded_start:
            del self.throttled_tasks[pid]
            return False

        return True

    def reconcile_cooldowns(self, current_time: float) -> None:
        """Release expired throttles and purge recycled PIDs."""
        to_release: List[int] = []
        to_purge: List[int] = []

        for pid, (start_time, unlock_time) in list(self.throttled_tasks.items()):
            current_start = self._get_process_start_time(pid)
            if current_start is None or current_start != start_time:
                to_purge.append(pid)
                continue

            if current_time >= unlock_time:
                to_release.append(pid)

        for pid in to_purge:
            self.throttled_tasks.pop(pid, None)

        for pid in to_release:
            self.release_memory_throttle(pid)
            self.release_cpu_throttle(pid)
            self.throttled_tasks.pop(pid, None)

    def _verify_write(self, path: str, expected: str) -> bool:
        """Verify a cgroup file write by reading it back."""
        try:
            with open(path, "r") as f:
                actual = f.read().strip()
            return actual == expected.strip()
        except Exception:
            return False

    def apply_memory_throttle(self, pid: int, limit_bytes: int) -> None:
        """Apply memory.high clamp via native file writes."""
        cgroup_path = self._get_cgroup_v2_path(pid)
        if not cgroup_path:
            self.logger.warning(f"Could not resolve cgroup for PID {pid}. Falling back to scheduler.")
            self._apply_scheduler_fallback(pid)
            return

        mem_high_path = os.path.join(cgroup_path, "memory.high")
        limit_str = str(limit_bytes)

        try:
            with open(mem_high_path, "w") as f:
                f.write(limit_str)

            if not self._verify_write(mem_high_path, limit_str):
                raise IOError(f"Write verification failed for {mem_high_path}")

            self.logger.audit("CLAMP_MEMORY", pid, cgroup_path, f"Limit set to {limit_bytes} bytes")
        except PermissionError:
            self.logger.error(f"Permission denied writing to {mem_high_path}")
            self._apply_scheduler_fallback(pid)
        except Exception as e:
            self.logger.warning(f"Cgroup memory write failed: {e}. Executing fallback.")
            self._apply_scheduler_fallback(pid)

    def release_memory_throttle(self, pid: int) -> None:
        """Restore memory.high to max."""
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
        """
        Apply cpu.max clamp.
        quota_pct: percentage of ONE CPU core (e.g., 20 = 20% of one core).
        cpu.max format: "quota period" where quota/period = CPU fraction.
        period default = 100000us. quota = quota_pct * 1000.
        """
        cgroup_path = self._get_cgroup_v2_path(pid)
        if not cgroup_path:
            self.logger.warning(f"Could not resolve cgroup for PID {pid}. Falling back to OS scheduler.")
            self._apply_scheduler_fallback(pid)
            return

        cpu_max_path = os.path.join(cgroup_path, "cpu.max")
        period = 100000
        quota = quota_pct * 1000  # 20% -> 20000us per 100000us period
        value = f"{quota} {period}"

        try:
            with open(cpu_max_path, "w") as f:
                f.write(value)

            if not self._verify_write(cpu_max_path, value):
                raise IOError(f"Write verification failed for {cpu_max_path}")

            self.logger.audit("CLAMP_CPU", pid, cgroup_path, f"Limit set to {quota_pct}%")
        except Exception as e:
            self.logger.warning(f"Cgroup CPU write failed: {e}. Executing fallback.")
            self._apply_scheduler_fallback(pid)

    def release_cpu_throttle(self, pid: int) -> None:
        """Restore cpu.max to max."""
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
        """Native OS syscall fallback if cgroups are locked by systemd."""
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
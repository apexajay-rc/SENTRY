import os
import time
from pathlib import Path
from src.sentry_v2.actuator.protocol import ThrottleSpec

PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
CPU_PERIOD_US = 100_000

class CgroupActuator:
    def __init__(self):
        self.sentry_root = Path("/sys/fs/cgroup/system.slice/sentry-v2.service")
        if not self.sentry_root.exists():
            try:
                self.sentry_root.mkdir(parents=True, exist_ok=True)
                with open(self.sentry_root / "cgroup.subtree_control", "w") as f:
                    f.write("+cpu +memory")
            except PermissionError:
                pass # Handled by systemd in production
        
        # Layer 2 Hysteresis: Per-PID cooldown
        self._pid_cooldowns: dict[int, float] = {}
        self.COOLDOWN_SECONDS = 30.0

    def _write_file(self, path: Path, value: str) -> None:
        try:
            with open(path, "w") as f:
                f.write(value)
        except OSError as e:
            print(f"CGROUP ERROR: {e}")

    async def apply_throttle(self, pid: int, spec: ThrottleSpec) -> None:
        # Layer 2 Hysteresis: Per-PID cooldown check
        now = time.monotonic()
        if pid in self._pid_cooldowns and now < self._pid_cooldowns[pid]:
            remaining = self._pid_cooldowns[pid] - now
            print(f"COOLDOWN ACTIVE: PID {pid} ({remaining:.1f}s remaining)")
            return
        self._pid_cooldowns[pid] = now + self.COOLDOWN_SECONDS

        pid_cgroup = self.sentry_root / str(pid)
        if not pid_cgroup.exists():
            try:
                pid_cgroup.mkdir(exist_ok=True)
                self._write_file(pid_cgroup / "cgroup.procs", str(pid))
            except OSError:
                return

        # MODE HANDLING: PROPORTIONAL vs HARD_LIMIT
        mode = getattr(spec, 'mode', 'PROPORTIONAL')
        if mode == "PROPORTIONAL":
            # Proportional: use cpu.weight, no hard quota
            if spec.cpu_weight is not None:
                self._write_file(pid_cgroup / "cpu.weight", str(spec.cpu_weight))
            self._write_file(pid_cgroup / "cpu.max", "max 100000")
        elif mode == "HARD_LIMIT":
            # Hard limit: use cpu.max quota
            if spec.cpu_quota_pct is not None:
                quota = max(1, (spec.cpu_quota_pct * CPU_PERIOD_US) // 100)
                self._write_file(pid_cgroup / "cpu.max", f"{quota} {CPU_PERIOD_US}")
            self._write_file(pid_cgroup / "cpu.weight", "100")
        else:
            # Default: PROPORTIONAL
            if spec.cpu_weight is not None:
                self._write_file(pid_cgroup / "cpu.weight", str(spec.cpu_weight))
            self._write_file(pid_cgroup / "cpu.max", "max 100000")

        # Memory limits with OOM protection
        if spec.memory_limit_bytes is not None:
            # OOM PROTECTION: Set memory.high with headroom
            self._write_file(pid_cgroup / "memory.high", str(spec.memory_limit_bytes))
            # OOM PROTECTION: Set memory.min to 10% of limit (floor at 1 page)
            memory_min = max(PAGE_SIZE, spec.memory_limit_bytes // 10)
            self._write_file(pid_cgroup / "memory.min", str(memory_min))
            # OOM PROTECTION: Lower OOM score to prefer killing other processes
            self._write_file(pid_cgroup / "oom.score", "100")

    async def release_throttle(self, pid: int) -> None:
        pid_cgroup = self.sentry_root / str(pid)
        if pid_cgroup.exists():
            self._write_file(pid_cgroup / "cpu.max", "max 100000")
            self._write_file(pid_cgroup / "memory.high", "max")
            self._write_file(pid_cgroup / "cpu.weight", "100")
            # Restore OOM settings
            self._write_file(pid_cgroup / "memory.min", "0")
            self._write_file(pid_cgroup / "oom.score", "0")
            # The kernel will automatically clean up the directory when the PID exits

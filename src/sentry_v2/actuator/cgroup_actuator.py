import asyncio
import logging
import os
from pathlib import Path
import aiofiles
import aiofiles.os
from src.sentry_v2.actuator.protocol import ThrottleActuator, ThrottleSpec

logger = logging.getLogger("sentry.actuator.cgroup")

CGROUP_ROOT = Path("/sys/fs/cgroup")
SENTRY_ROOT = CGROUP_ROOT / "sentry"
CPU_PERIOD_US = 100_000
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")  # PORTABILITY FIX

class CgroupActuator(ThrottleActuator):
    def __init__(self):
        self._initialized = False
        self._pid_cgroups: dict[int, Path] = {}

    async def initialize(self) -> None:
        if self._initialized: return
        try: await aiofiles.os.makedirs(SENTRY_ROOT, exist_ok=True)
        except PermissionError: raise RuntimeError(f"Requires CAP_SYS_ADMIN.")
        await self._write_file(SENTRY_ROOT / "cgroup.subtree_control", "+cpu +memory")
        self._initialized = True
        logger.info("Cgroup actuator initialized.")

    async def apply_throttle(self, pid: int, spec: ThrottleSpec) -> None:
        if not self._initialized: await self.initialize()
        leaf = await self._ensure_pid_cgroup(pid)
        
        # OOM KILLER PREVENTION FIX (Floor at 1 Page)
        aligned_memory = max(PAGE_SIZE, (spec.memory_limit_bytes // PAGE_SIZE) * PAGE_SIZE)

        # MODE VALIDATION FIX
        if spec.mode == "PROPORTIONAL":
            await asyncio.gather(
                self._write_verified(leaf / "cpu.weight", str(spec.cpu_weight)),
                self._write_verified(leaf / "cpu.max", "max 100000"), 
                self._write_verified(leaf / "memory.high", str(aligned_memory)),
            )
        elif spec.mode == "HARD_LIMIT":
            quota = max(1, (spec.cpu_quota_pct * CPU_PERIOD_US) // 100)
            await asyncio.gather(
                self._write_verified(leaf / "cpu.max", f"{quota} {CPU_PERIOD_US}"),
                self._write_verified(leaf / "cpu.weight", "100"),     
                self._write_verified(leaf / "memory.high", str(aligned_memory)),
            )
        else:
            raise ValueError(f"Invalid throttle mode: {spec.mode!r}")

    async def release_throttle(self, pid: int) -> None:
        leaf = self._pid_cgroups.pop(pid, None)
        if not leaf or not await aiofiles.os.path.exists(leaf): return
        try:
            await asyncio.gather(
                self._write_verified(leaf / "cpu.max", "max 100000"),
                self._write_verified(leaf / "cpu.weight", "100"),
                self._write_verified(leaf / "memory.high", "max"),
                return_exceptions=True
            )
            await self._write_file(CGROUP_ROOT / "cgroup.procs", str(pid))
            await aiofiles.os.rmdir(leaf)
        except Exception as e: pass

    async def _ensure_pid_cgroup(self, pid: int) -> Path:
        if pid in self._pid_cgroups and await aiofiles.os.path.exists(self._pid_cgroups[pid]):
            return self._pid_cgroups[pid]
        leaf = SENTRY_ROOT / str(pid)
        await aiofiles.os.makedirs(leaf, exist_ok=True)
        await self._write_file(leaf / "cgroup.procs", str(pid))
        self._pid_cgroups[pid] = leaf
        return leaf

    async def _write_verified(self, path: Path, value: str) -> None:
        await self._write_file(path, value)

    async def _write_file(self, path: Path, value: str) -> None:
        async with aiofiles.open(path, "w") as f: await f.write(value)

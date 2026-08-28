"""
Sentry-Owned Cgroup v2 Hierarchy Manager.
Creates /sys/fs/cgroup/sentry/, migrates target PIDs into it, enforces limits.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiofiles
import aiofiles.os

logger = logging.getLogger("sentry.cgroup.sentry_hierarchy")
logging.basicConfig(level=logging.INFO)

CGROUP_ROOT = Path("/sys/fs/cgroup")
SENTRY_ROOT = CGROUP_ROOT / "sentry"
CPU_PERIOD_US = 100_000

@dataclass(frozen=True)
class ThrottleSpec:
    cpu_quota_pct: int
    memory_limit_bytes: int

class SentryHierarchyError(Exception):
    def __init__(self, message: str, pid: int = 0, path: Optional[Path] = None):
        super().__init__(message)
        self.pid = pid
        self.path = path

class MigrationError(SentryHierarchyError):
    pass

class SentryCgroupManager:
    """
    Manages SENTRY's private cgroup hierarchy.
    - Creates /sys/fs/cgroup/sentry/ with controllers enabled
    - Migrates target PIDs into dedicated child cgroups
    - Applies limits on owned leaves
    """

    def __init__(self):
        self._initialized = False
        self._pid_cgroups: dict[int, Path] = {}  # pid -> sentry/<pid>/

    async def initialize(self) -> None:
        """Create /sys/fs/cgroup/sentry/ and enable controllers."""
        if self._initialized:
            return

        # 1. Create sentry root
        try:
            await aiofiles.os.makedirs(SENTRY_ROOT, exist_ok=True)
        except PermissionError:
            raise SentryHierarchyError(f"Cannot create {SENTRY_ROOT}. Requires CAP_SYS_ADMIN.")

        # 2. Enable controllers in sentry's subtree_control
        subtree_control = SENTRY_ROOT / "cgroup.subtree_control"
        await self._write_file(subtree_control, "+cpu +memory +io")

        # 3. Verify
        content = await self._read_file(subtree_control)
        if not all(c in content for c in ("cpu", "memory")):
            raise SentryHierarchyError(
                f"Failed to enable controllers in {SENTRY_ROOT}. "
                f"Content: {content}. Systemd may be blocking delegation."
            )

        self._initialized = True
        logger.info("SENTRY cgroup hierarchy initialized", extra={"path": str(SENTRY_ROOT)})

    async def apply_throttle(self, pid: int, spec: ThrottleSpec) -> None:
        """Migrate PID into sentry hierarchy and apply limits."""
        if not self._initialized:
            await self.initialize()

        leaf = await self._ensure_pid_cgroup(pid)

        # Compute cpu.max
        quota = max(1, (spec.cpu_quota_pct * CPU_PERIOD_US) // 100)
        cpu_max_value = f"{quota} {CPU_PERIOD_US}"
        
        # Align memory to kernel page size (4096 bytes)
        PAGE_SIZE = 4096
        aligned_memory = (spec.memory_limit_bytes // PAGE_SIZE) * PAGE_SIZE

        # Apply limits
        await asyncio.gather(
            self._write_verified(leaf / "cpu.max", cpu_max_value),
            self._write_verified(leaf / "memory.high", str(aligned_memory)),
        )

        logger.info(
            "Throttle applied on SENTRY hierarchy",
            extra={"pid": pid, "cgroup": str(leaf), "cpu_max": cpu_max_value}
        )

    async def release_throttle(self, pid: int) -> None:
        """Release limits and move PID back to systemd hierarchy."""
        leaf = self._pid_cgroups.pop(pid, None)
        if not leaf or not await aiofiles.os.path.exists(leaf):
            return

        try:
            # 1. Release limits
            await asyncio.gather(
                self._write_verified(leaf / "cpu.max", "max 100000"),
                self._write_verified(leaf / "memory.high", "max"),
                return_exceptions=True
            )

            # 2. Move PID back to system root
            await self._write_file(CGROUP_ROOT / "cgroup.procs", str(pid))

            # 3. Cleanup empty cgroup
            await aiofiles.os.rmdir(leaf)

            logger.info("Throttle released, PID migrated back", extra={"pid": pid})

        except Exception as e:
            logger.warning("Failed to fully release PID", extra={"pid": pid, "error": str(e)})

    async def verify_throttle(self, pid: int) -> ThrottleSpec:
        leaf = self._pid_cgroups.get(pid)
        if not leaf:
            raise SentryHierarchyError(f"PID {pid} not managed by SENTRY hierarchy", pid=pid)

        cpu_raw, mem_raw = await asyncio.gather(
            self._read_file(leaf / "cpu.max"),
            self._read_file(leaf / "memory.high"),
        )

        quota_str = cpu_raw.split()[0]
        cpu_pct = 100 if quota_str == "max" else max(1, min(100, (int(quota_str) * 100) // CPU_PERIOD_US))
        mem_bytes = 2**64 - 1 if mem_raw.strip() == "max" else int(mem_raw.strip())

        return ThrottleSpec(cpu_quota_pct=cpu_pct, memory_limit_bytes=mem_bytes)

    # ─── Internal: PID Migration ───
    async def _ensure_pid_cgroup(self, pid: int) -> Path:
        """Create sentry/<pid>/ and migrate PID into it."""
        if pid in self._pid_cgroups:
            leaf = self._pid_cgroups[pid]
            if await aiofiles.os.path.exists(leaf):
                return leaf

        leaf = SENTRY_ROOT / str(pid)
        try:
            await aiofiles.os.makedirs(leaf, exist_ok=True)
        except OSError as e:
            raise SentryHierarchyError(f"Failed to create leaf {leaf}: {e}", pid=pid, path=leaf)

        # MIGRATE: Write PID to our cgroup.procs
        try:
            await self._write_file(leaf / "cgroup.procs", str(pid))
        except PermissionError:
            raise MigrationError(
                f"Cannot migrate PID {pid} into {leaf}. Systemd restrictions?",
                pid=pid,
                path=leaf
            )
        except FileNotFoundError:
            raise MigrationError(f"PID {pid} disappeared during migration", pid=pid)

        self._pid_cgroups[pid] = leaf
        return leaf

    # ─── Low-level I/O ───
    async def _write_verified(self, path: Path, value: str) -> None:
        await self._write_file(path, value)
        actual = await self._read_file(path)
        if actual.strip() != value.strip():
            raise SentryHierarchyError(
                f"Write verification failed: expected '{value}', got '{actual}'",
                path=path
            )

    async def _write_file(self, path: Path, value: str) -> None:
        async with aiofiles.open(path, "w") as f:
            await f.write(value)

    async def _read_file(self, path: Path) -> str:
        async with aiofiles.open(path, "r") as f:
            return await f.read()

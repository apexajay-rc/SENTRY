import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Set

from dbus_next.aio import MessageBus
from dbus_next.constants import BusType
from dbus_next.errors import DBusError
from src.sentry_v2.config import ImmunityConfig

logger = logging.getLogger("sentry.immunity")

CGROUP_ROOT = Path("/sys/fs/cgroup")
PROC_ROOT = Path("/proc")
DBUS_TIMEOUT_MS = 50

DESKTOP_PORTAL_BUS = "org.freedesktop.portal.Desktop"
DESKTOP_PORTAL_PATH = "/org/freedesktop/portal/desktop"
DESKTOP_PORTAL_IFACE = "org.freedesktop.portal.Desktop"

@dataclass(frozen=True)
class ImmunityDecision:
    immune: bool
    reason: str
    source: Literal["slice", "portal", "config"]

class SliceImmunity:
    def __init__(self, immune_slices: Set[str], cache_ttl: float):
        self.immune_slices = immune_slices
        self.cache_ttl = cache_ttl
        self._cache: dict[int, tuple[float, ImmunityDecision]] = {}
        self._slice_pattern = re.compile(r"^0::(.+)$")

    def is_immune(self, pid: int) -> ImmunityDecision:
        if pid == 1: return ImmunityDecision(True, "init system (PID 1)", "core")
        now = asyncio.get_event_loop().time()
        cached = self._cache.get(pid)
        if cached and (now - cached[0]) < self.cache_ttl:
            return cached[1]

        decision = self._check_slice_immunity_sync(pid)
        self._cache[pid] = (now, decision)
        return decision

    def _check_slice_immunity_sync(self, pid: int) -> ImmunityDecision:
        try:
            cgroup_file = PROC_ROOT / str(pid) / "cgroup"
            if not cgroup_file.exists():
                return ImmunityDecision(False, "cgroup missing", "slice")

            content = cgroup_file.read_text()
            for line in content.splitlines():
                match = self._slice_pattern.match(line)
                if match:
                    rel_path = match.group(1).strip("/")
                    for immune in self.immune_slices:
                        if rel_path.startswith(immune.strip("/")):
                            return ImmunityDecision(True, f"slice {immune}", "slice")
            return ImmunityDecision(False, "no match", "slice")
        except:
            return ImmunityDecision(False, "read error", "slice")

    def invalidate(self, pid: int) -> None:
        self._cache.pop(pid, None)

class PortalImmunity:
    def __init__(self, enabled: bool, cache_ttl: float):
        self.enabled = enabled
        self.cache_ttl = cache_ttl
        self._cache: tuple[float, Optional[int]] = (0.0, None)
        self._proxy = None

    async def initialize(self) -> None:
        if not self.enabled: return
        try:
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            introspection = await bus.introspect(DESKTOP_PORTAL_BUS, DESKTOP_PORTAL_PATH)
            obj = introspection.get_object(DESKTOP_PORTAL_PATH)
            self._proxy = obj.get_interface(DESKTOP_PORTAL_IFACE)
        except:
            self.enabled = False

    async def get_active_window_pid(self) -> Optional[int]:
        if not self.enabled or not self._proxy: return None
        now = asyncio.get_event_loop().time()
        if (now - self._cache[0]) < self.cache_ttl: return self._cache[1]
        # DBus implementation placeholder. Will require specific Wayland/X11 extension.
        self._cache = (now, None)
        return None

    def is_immune(self, pid: int) -> ImmunityDecision:
        if pid == 1: return ImmunityDecision(True, "init system (PID 1)", "core")
        active_pid = self._cache[1]
        if active_pid and pid == active_pid:
            return ImmunityDecision(True, "active window", "portal")
        return ImmunityDecision(False, "not active", "portal")

class ImmunityEngine:
    def __init__(self, config: ImmunityConfig):
        self.slice_immunity = SliceImmunity(set(config.immune_slices), config.cache_ttl)
        self.portal_immunity = PortalImmunity(config.desktop_portal_enabled, config.cache_ttl)

    async def initialize(self) -> None:
        await self.portal_immunity.initialize()

    def is_immune(self, pid: int) -> ImmunityDecision:
        if pid == 1: return ImmunityDecision(True, "init system (PID 1)", "core")
        sd = self.slice_immunity.is_immune(pid)
        if sd.immune: return sd
        pd = self.portal_immunity.is_immune(pid)
        if pd.immune: return pd
        return ImmunityDecision(False, "no match", "config")

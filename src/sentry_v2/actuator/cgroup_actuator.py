"""
Systemd DBus-based actuator for SENTRY V2 using dbus-next.
Replaces direct cgroup filesystem writes with systemd Manager.SetUnitProperties DBus API.
"""

import os
import time
import logging
from typing import Optional
from src.sentry_v2.actuator.protocol import ThrottleSpec

logger = logging.getLogger("sentry.actuator")

try:
    from dbus_next.aio import MessageBus
    from dbus_next.constants import BusType
    from dbus_next import DBusError, Variant
    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False
    logger.warning("dbus-next not available, systemd DBus actuation disabled")


class SystemdActuator:
    """
    Actuates CPU resource limits via systemd DBus API using dbus-next.
    Uses Manager.SetUnitProperties to dynamically adjust CPUWeight.
    """

    def __init__(self):
        if not DBUS_AVAILABLE:
            raise RuntimeError("dbus-next required for SystemdActuator. Install with: pip install dbus-next")

        self._bus: Optional[MessageBus] = None
        self._manager_iface = None

        # Layer 2 Hysteresis: Per-PID cooldown
        self._pid_cooldowns: dict[int, float] = {}
        self.COOLDOWN_SECONDS = 30.0

        # Cache original CPU weights for restoration
        self._original_weights: dict[str, int] = {}

    async def initialize(self) -> None:
        """Initialize DBus connection to systemd."""
        try:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            introspection = await self._bus.introspect('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
            # Get proxy object WITH introspection
            manager_obj = self._bus.get_proxy_object(
                'org.freedesktop.systemd1',
                '/org/freedesktop/systemd1',
                introspection
            )
            self._manager_iface = manager_obj.get_interface('org.freedesktop.systemd1.Manager')
            logger.info("Systemd DBus actuator initialized")
        except Exception as e:
            logger.error(f"Failed to initialize systemd DBus actuator: {e}")
            raise

    async def _get_unit_name_from_pid(self, pid: int) -> Optional[str]:
        """Resolve systemd unit name from PID via GetUnitByPID, then find leaf scope."""
        try:
            if not self._manager_iface:
                return None

            unit_path = await self._manager_iface.call_get_unit_by_pid(pid)
            if not unit_path or unit_path == '/':
                logger.warning(f"No systemd unit found for PID {pid}")
                return None

            # Get the unit object and read its Id property
            introspection = await self._bus.introspect('org.freedesktop.systemd1', unit_path)
            unit_proxy = self._bus.get_proxy_object('org.freedesktop.systemd1', unit_path, introspection)
            props_iface = unit_proxy.get_interface('org.freedesktop.DBus.Properties')
            unit_name_variant = await props_iface.call_get('org.freedesktop.systemd1.Unit', 'Id')
            unit_name = str(unit_name_variant.value)
            
            # For user@1000.service, we need to find the leaf scope that actually has CPUWeight
            # Check if this is a user service - if so, find the leaf scope from cgroup
            if unit_name.startswith('user@') and unit_name.endswith('.service'):
                # Try to find the actual leaf scope from /proc/PID/cgroup
                try:
                    with open(f'/proc/{pid}/cgroup', 'r') as f:
                        cgroup_path = f.read().strip().split(':')[-1]
                    # Extract the leaf scope name (last component)
                    if cgroup_path and cgroup_path != '/':
                        leaf = cgroup_path.strip('/').split('/')[-1]
                        # Convert systemd escaped path back to unit name
                        leaf_unit = leaf.replace('_2e', '.').replace('_2d', '-')
                        if leaf_unit.endswith('.scope') or leaf_unit.endswith('.slice'):
                            logger.debug(f"Found leaf scope for PID {pid}: {leaf_unit}")
                            return leaf_unit
                except Exception as e:
                    logger.debug(f"Could not read cgroup for PID {pid}: {e}")
            
            return unit_name
        except Exception as e:
            logger.warning(f"Failed to get unit for PID {pid}: {e}")
            return None

    async def _set_cpu_weight(self, unit_name: str, weight: int) -> bool:
        """Set CPUWeight via Manager.SetUnitProperties (runtime=True)."""
        try:
            if not self._manager_iface:
                return False

            # CPUWeight must be 1-10000
            weight = max(1, min(10000, weight))
            await self._manager_iface.call_set_unit_properties(
                unit_name,
                True,  # runtime=True (persist only until reboot)
                [['CPUWeight', Variant('t', weight)]]  # a(sv) format
            )
            logger.debug(f"Set CPUWeight={weight} for {unit_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to set CPUWeight for {unit_name}: {e}")
            return False

    async def _get_current_cpu_weight(self, unit_name: str) -> Optional[int]:
        """Get current CPUWeight from unit properties."""
        try:
            if not self._bus:
                return None

            # systemd unit paths are escaped: . -> _2e, - -> _2d
            escaped_name = unit_name.replace(".", "_2e").replace("-", "_2d")
            unit_path = f'/org/freedesktop/systemd1/unit/{escaped_name}'
            introspection = await self._bus.introspect('org.freedesktop.systemd1', unit_path)
            unit_proxy = self._bus.get_proxy_object('org.freedesktop.systemd1', unit_path, introspection)
            props_iface = unit_proxy.get_interface('org.freedesktop.DBus.Properties')
            weight_variant = await props_iface.call_get('org.freedesktop.systemd1.Unit', 'CPUWeight')
            return int(weight_variant.value)
        except Exception as e:
            logger.debug(f"Could not read CPUWeight for {unit_name}: {e}")
            return None

    async def apply_throttle(self, pid: int, spec: ThrottleSpec) -> None:
        """Apply CPU throttling via systemd CPUWeight."""
        # Layer 2 Hysteresis: Per-PID cooldown check
        now = time.monotonic()
        if pid in self._pid_cooldowns and now < self._pid_cooldowns[pid]:
            remaining = self._pid_cooldowns[pid] - now
            logger.info(f"COOLDOWN ACTIVE: PID {pid} ({remaining:.1f}s remaining)")
            return
        self._pid_cooldowns[pid] = now + self.COOLDOWN_SECONDS

        unit_name = await self._get_unit_name_from_pid(pid)
        if not unit_name:
            logger.warning(f"No systemd unit found for PID {pid}, cannot throttle")
            return

        # Determine target weight from spec
        mode = getattr(spec, 'mode', 'PROPORTIONAL')
        if mode == "PROPORTIONAL":
            target_weight = spec.cpu_weight if spec.cpu_weight is not None else 100
        elif mode == "HARD_LIMIT":
            # Convert quota percentage to weight (approximate)
            target_weight = max(1, (spec.cpu_quota_pct * 100) if spec.cpu_quota_pct else 100)
        else:
            target_weight = spec.cpu_weight if spec.cpu_weight is not None else 100

        # Cache original weight if not already cached
        if unit_name not in self._original_weights:
            current = await self._get_current_cpu_weight(unit_name)
            if current is not None:
                self._original_weights[unit_name] = current
            else:
                self._original_weights[unit_name] = 100  # systemd default

        # Apply new weight
        success = await self._set_cpu_weight(unit_name, target_weight)
        if success:
            logger.info(f"Throttled PID {pid} ({unit_name}): CPUWeight={target_weight}")

    async def release_throttle(self, pid: int) -> None:
        """Restore original CPU weight for a PID."""
        unit_name = await self._get_unit_name_from_pid(pid)
        if not unit_name:
            return

        original_weight = self._original_weights.get(unit_name, 100)
        success = await self._set_cpu_weight(unit_name, original_weight)
        if success:
            logger.info(f"Released PID {pid} ({unit_name}): restored CPUWeight={original_weight}")
            # Clean up cache
            self._original_weights.pop(unit_name, None)
            self._pid_cooldowns.pop(pid, None)


# Factory function for actuator creation
async def create_actuator() -> 'SystemdActuator':
    """Factory function to create the systemd actuator."""
    if not DBUS_AVAILABLE:
        raise RuntimeError("dbus-next not installed. Install with: pip install dbus-next")

    actuator = SystemdActuator()
    await actuator.initialize()
    return actuator
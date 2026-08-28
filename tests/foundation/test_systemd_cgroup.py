import pytest
from unittest.mock import AsyncMock
from dbus_next.errors import DBusError

# Assuming PYTHONPATH=src is used when running tests
from sentry_v2.cgroup.v2 import SystemdCgroupManager, UnitNotFoundError

@pytest.mark.asyncio
async def test_apply_throttle_validates_inputs():
    mgr = SystemdCgroupManager()
    with pytest.raises(ValueError):
        await mgr.apply_throttle(123, 0, 1024)  # cpu_pct < 1
    with pytest.raises(ValueError):
        await mgr.apply_throttle(123, 101, 1024)  # cpu_pct > 100
    with pytest.raises(ValueError):
        await mgr.apply_throttle(123, 50, 0)  # memory <= 0

@pytest.mark.asyncio
async def test_unit_not_found():
    mgr = SystemdCgroupManager()
    mgr._manager_proxy = AsyncMock()
    
    # dbus_next DBusError requires both a type and a message
    mgr._manager_proxy.call_get_unit_by_pid.side_effect = DBusError(
        "org.freedesktop.DBus.Error.Failed", 
        "No such process"
    )
    
    with pytest.raises(UnitNotFoundError):
        await mgr.apply_throttle(999999, 50, 1024)

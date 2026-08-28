from src.sentry_v2.actuator.protocol import ThrottleActuator
from src.sentry_v2.actuator.cgroup_actuator import CgroupActuator
from src.sentry_v2.actuator.userspace_actuator import UserspaceActuator
from src.sentry_v2.actuator.detection import cfs_bandwidth_available

async def create_actuator() -> ThrottleActuator:
    if await cfs_bandwidth_available():
        actuator = CgroupActuator()
        await actuator.initialize()
        return actuator
    else:
        return UserspaceActuator()

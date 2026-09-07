from src.sentry_v2.actuator.protocol import ThrottleActuator
from src.sentry_v2.actuator.cgroup_actuator import CgroupActuator
from src.sentry_v2.actuator.userspace_actuator import UserspaceActuator
from src.sentry_v2.actuator.detection import cfs_bandwidth_available

def create_actuator() -> ThrottleActuator:
    if cfs_bandwidth_available():
        actuator = CgroupActuator()
        return actuator
    else:
        return UserspaceActuator()

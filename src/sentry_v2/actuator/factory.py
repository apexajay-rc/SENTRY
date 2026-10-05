from src.sentry_v2.actuator.protocol import ThrottleActuator
from src.sentry_v2.actuator.cgroup_actuator import SystemdActuator


async def create_actuator() -> SystemdActuator:
    """Factory function to create the systemd actuator."""
    actuator = SystemdActuator()
    await actuator.initialize()
    return actuator
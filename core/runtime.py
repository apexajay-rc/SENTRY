"""Bootstrap SENTRY runtime modules from sentry_config.yaml."""

from typing import Optional

from core.cgroups import setup_cgrou
from core.config import ConfigParser
from core.metrics import configure_metrics
from core.platform_adapter import PLATFORM
from core.policy import configure_policy


def init_runtime(config_file: Optional[str] = None) -> ConfigParser:
    config = load_config(config_file)
    configure_policy(config)
    configure_metrics(config)

    if PLATFORM == "Linux" and config.cgroup_enabled():
        setup_cgroup(config.cgroup_path())

    return config

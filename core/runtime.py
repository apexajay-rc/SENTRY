"""Bootstrap SENTRY runtime modules from sentry_config.yaml."""

from typing import Optional, Any

from core.cgroups import setup_cgroup
from core.config import ConfigParser
from core.metrics import configure_metrics
from core.platform_adapter import PLATFORM
from core.policy import configure_policy


def init_runtime(config_file: Optional[str] = None) -> Any:
    config = ConfigParser.load(config_file)
    
    configure_policy(config)  # type: ignore[arg-type]
    configure_metrics(config)  # type: ignore[arg-type]

    if PLATFORM == "Linux" and config.cgroup_enabled():  # type: ignore[attr-defined]
        setup_cgroup(config.cgroup_path())  # noqa: F821  # type: ignore

    return config

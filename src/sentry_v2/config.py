"""
SENTRY V2 Configuration Loader.
Transforms dynamic YAML into immutable, strictly typed dataclasses.
"""

import yaml
import logging
from dataclasses import dataclass, field
from typing import List
from pathlib import Path

logger = logging.getLogger("sentry.config")

@dataclass(frozen=True)
class ThresholdConfig:
    low: int = 35
    moderate: int = 55
    high: int = 75
    critical: int = 95
    psi_trigger: float = 10.0
    hysteresis: int = 5

@dataclass(frozen=True)
class ThrottleConfig:
    max_hogs: int = 5
    memory_headroom_multiplier: float = 1.5

@dataclass(frozen=True)
class ImmunityConfig:
    immune_slices: list[str] = field(default_factory=lambda: ["system.slice", "init.scope"])
    desktop_portal_enabled: bool = True
    cache_ttl: float = 5.0

@dataclass(frozen=True)
class SentryV2Config:
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    throttle: ThrottleConfig = field(default_factory=ThrottleConfig)
    immunity: ImmunityConfig = field(default_factory=ImmunityConfig)

def load_config(path: str) -> SentryV2Config:
    config_path = Path(path)
    if not config_path.exists():
        logger.warning(f"Config file {path} not found. Using hardcoded safe defaults.")
        return SentryV2Config()

    try:
        with open(config_path, "r") as f:
            raw = yaml.safe_load(f) or {}

        # Validate required sections exist
        for section in ["thresholds", "throttle", "immunity"]:
            if section not in raw:
                raise ValueError(f"Missing required config section: {section}")

        t_raw = raw.get("thresholds", {})
        th_raw = raw.get("throttle", {})
        i_raw = raw.get("immunity", {})

        return SentryV2Config(
            thresholds=ThresholdConfig(**t_raw),
            throttle=ThrottleConfig(**th_raw),
            immunity=ImmunityConfig(**i_raw)
        )
    except Exception as e:
        logger.error(f"Failed to parse {path}: {e}. Falling back to safe defaults.")
        return SentryV2Config()

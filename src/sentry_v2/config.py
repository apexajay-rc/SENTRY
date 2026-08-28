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
class MemoryPolicyConfig:
    mode: str = "RELATIVE_MULTIPLIER"
    value: float = 1.5

@dataclass(frozen=True)
class ImmunityConfig:
    immune_slices: List[str] = field(default_factory=lambda: ["user.slice", "system.slice"])

@dataclass(frozen=True)
class SentryConfig:
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    memory: MemoryPolicyConfig = field(default_factory=MemoryPolicyConfig)
    immunity: ImmunityConfig = field(default_factory=ImmunityConfig)

    @classmethod
    def load(cls, path: str = "sentry-v2.yaml") -> "SentryConfig":
        """Loads YAML config, falling back to safe defaults if missing."""
        config_path = Path(path)
        if not config_path.exists():
            logger.warning(f"Config file {path} not found. Using hardcoded safe defaults.")
            return cls()

        try:
            with open(config_path, 'r') as f:
                raw = yaml.safe_load(f) or {}
                
            t_raw = raw.get("thresholds", {})
            m_raw = raw.get("memory", {})
            i_raw = raw.get("immunity", {})

            return cls(
                thresholds=ThresholdConfig(**t_raw),
                memory=MemoryPolicyConfig(**m_raw),
                immunity=ImmunityConfig(**i_raw)
            )
        except Exception as e:
            logger.error(f"Failed to parse {path}: {e}. Falling back to safe defaults.")
            return cls()

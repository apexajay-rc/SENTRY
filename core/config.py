"""
core/config.py

Strict, fail-safe configuration parser for the SENTRY daemon.
Validates YAML inputs and provides guaranteed fallback defaults 
if the configuration file is missing or malformed.
"""

import os
import logging
import yaml
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class SentryConfig:
    """Strictly typed configuration state."""
    memory_throttle_limit: str = "500M"
    cooldown_period: float = 60.0
    watchdog_interval: float = 5.0

class ConfigParser:
    """Reads and validates the sentry_config.yaml file."""
    
    DEFAULT_PATHS = [
        "/etc/sentry/config.yaml",     # Standard Linux config path
        "/opt/sentry/sentry_config.yaml", # Makefile install path
        "sentry_config.yaml"           # Local dev fallback
    ]

    @classmethod
    def load(cls, custom_path: str | None = None) -> SentryConfig:
        """
        Locates, loads, and validates the configuration.
        Returns a SentryConfig object populated with defaults on failure.
        """
        config_obj = SentryConfig()
        
        target_path = custom_path
        if not target_path:
            for path in cls.DEFAULT_PATHS:
                if os.path.exists(path):
                    target_path = path
                    break
                    
        if not target_path:
            logger.warning("No sentry_config.yaml found. Using fail-safe defaults.")
            return config_obj

        try:
            with open(target_path, "r") as f:
                raw_yaml = yaml.safe_load(f) or {}
                
            logger.info(f"Loaded configuration from {target_path}")
            return cls._validate_and_apply(raw_yaml, config_obj)
            
        except yaml.YAMLError as e:
            logger.error(f"Malformed YAML in {target_path}: {e}. Using defaults.")
            return config_obj
        except Exception as e:
            logger.error(f"Failed to read config {target_path}: {e}. Using defaults.")
            return config_obj

    @staticmethod
    def _validate_and_apply(raw: dict, config: SentryConfig) -> SentryConfig:
        """Safely extracts and type-casts YAML values into the config object."""
        policy = raw.get("policy", {})
        daemon = raw.get("daemon", {})

        # Parse memory limit
        if "memory_throttle_limit" in policy:
            config.memory_throttle_limit = str(policy["memory_throttle_limit"])

        # Parse cooldown
        if "cooldown_period" in policy:
            try:
                config.cooldown_period = float(policy["cooldown_period"])
            except ValueError:
                logger.error("Invalid config: cooldown_period must be a number. Defaulting.")

        # Parse watchdog
        if "watchdog_interval" in daemon:
            try:
                config.watchdog_interval = float(daemon["watchdog_interval"])
            except ValueError:
                logger.error("Invalid config: watchdog_interval must be a number. Defaulting.")

        return config

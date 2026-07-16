"""
core/config.py

Unified Configuration Manager.
Resolves the dual-API technical debt by combining dataclass defaults
with safe YAML loading and legacy dictionary access.
"""
import os
import yaml
from typing import Any, Dict

class SentryConfig:
    def __init__(self, config_path: str = "sentry_config.yaml"):
        # Fallback Defaults
        self.memory_clamp_bytes: int = 52428800  # 50MB
        self.cooldown_seconds: int = 60
        self._raw_config: Dict[str, Any] = {}

        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    loaded = yaml.safe_load(f)
                    if loaded and isinstance(loaded, dict):
                        self._raw_config = loaded
                        self._map_config()
            except Exception as e:
                # Log warning in real implementation; fallback to defaults
                pass

    def _map_config(self) -> None:
        """Safely maps YAML keys to internal properties, handling legacy naming."""
        # 1. Memory mapping (handles old 'memory_throttle_limit' and new 'memory_clamp_bytes')
        mem_val = self._raw_config.get("memory_throttle_limit") or self._raw_config.get("memory_clamp_bytes")
        if mem_val:
            self.memory_clamp_bytes = self._parse_memory(str(mem_val))

        # 2. Cooldown mapping
        cool_val = self._raw_config.get("cooldown_period") or self._raw_config.get("cooldown_seconds")
        if cool_val is not None:
            try:
                self.cooldown_seconds = int(cool_val)
            except ValueError:
                pass

    def _parse_memory(self, mem_str: str) -> int:
        """Deterministically converts memory strings (e.g., '100MB') to raw bytes."""
        mem_str = mem_str.upper().strip()
        try:
            if mem_str.endswith("GB") or mem_str.endswith("G"):
                return int(mem_str.replace("GB", "").replace("G", "")) * 1024**3
            elif mem_str.endswith("MB") or mem_str.endswith("M"):
                return int(mem_str.replace("MB", "").replace("M", "")) * 1024**2
            elif mem_str.endswith("KB") or mem_str.endswith("K"):
                return int(mem_str.replace("KB", "").replace("K", "")) * 1024
            return int(mem_str)
        except ValueError:
            return 52428800  # Fallback to 50MB on parsing failure

    def get(self, key: str, default: Any = None) -> Any:
        """Legacy dictionary access support for core/runtime.py compatibility."""
        return self._raw_config.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._raw_config[key]

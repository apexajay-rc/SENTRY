"""
tests/test_config.py

Validates the unified SentryConfig contract and deterministic memory parsing.
"""
import unittest
import os
import tempfile
from core.config import SentryConfig

class TestSentryConfig(unittest.TestCase):
    def setUp(self):
        # Create a temporary YAML file mirroring legacy config
        self.test_yaml = tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.yaml')
        self.test_yaml.write("memory_throttle_limit: 100MB\ncooldown_period: 120\n")
        self.test_yaml.close()

    def tearDown(self):
        os.unlink(self.test_yaml.name)

    def test_default_config_fallback(self):
        """Ensures defaults apply when YAML is missing."""
        config = SentryConfig("nonexistent.yaml")
        self.assertEqual(config.memory_clamp_bytes, 524288000)
        self.assertEqual(config.cooldown_seconds, 60)

    def test_yaml_load_and_parse(self):
        """Ensures strings like '100MB' map cleanly to raw bytes."""
        config = SentryConfig(self.test_yaml.name)
        self.assertEqual(config.memory_clamp_bytes, 104857600)  # 100MB in bytes
        self.assertEqual(config.cooldown_seconds, 120)
        
    def test_legacy_get_api(self):
        """Ensures the .get() method still functions for downstream modules."""
        config = SentryConfig(self.test_yaml.name)
        self.assertEqual(config.get("cooldown_period"), 120)
        self.assertEqual(config.get("missing_key", "default_val"), "default_val")

if __name__ == '__main__':
    unittest.main()

import tempfile
import unittest
from pathlib import Path

import yaml

from core.config import ConfigManager, load_config, resolve_config_path
from core import policy
from core.metrics import compute_stress, configure_metrics


class ConfigPathTests(unittest.TestCase):
    def test_resolve_config_path_defaults_to_repo_root(self):
        path = resolve_config_path()
        self.assertEqual(path.name, "sentry_config.yaml")
        self.assertTrue(path.parent.name == "SENTRY" or path.exists())


class ConfigManagerTests(unittest.TestCase):
    def test_loads_custom_thresholds_and_escalation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.yaml"
            config_path.write_text(
                yaml.dump(
                    {
                        "thresholds": {
                            "moderate": 0.40,
                            "high": 0.60,
                            "critical": 0.80,
                        },
                        "escalation": {
                            "high": {
                                "cpu_weight": 25,
                                "memory_limit_percent": 70,
                                "io_weight": 25,
                            }
                        },
                        "metrics": {
                            "cpu_weight": 0.6,
                            "memory_weight": 0.3,
                            "io_weight": 0.1,
                        },
                        "critical_processes": ["systemd", "custom-daemon"],
                        "daemon": {"poll_interval_seconds": 5, "cooldown_seconds": 20},
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigManager(str(config_path))
            policy.configure_policy(config)
            configure_metrics(config)

            self.assertEqual(config.poll_interval(), 5)
            self.assertEqual(config.cooldown_seconds(), 20)
            self.assertEqual(config.critical_processes_set(), {"systemd", "custom-daemon"})
            self.assertEqual(policy.THRESHOLDS["MODERATE"], 0.40)
            self.assertEqual(policy.THRESHOLDS["HIGH"], 0.60)
            self.assertEqual(policy.ESCALATION_MATRIX["HIGH"]["cpu_weight"], 25)
            self.assertEqual(policy.classify_basic(0.65), "HIGH")
            self.assertEqual(compute_stress(50.0, 50.0, 50.0), 0.50)

    def test_deep_merge_preserves_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "partial.yaml"
            config_path.write_text("thresholds:\n  high: 0.75\n", encoding="utf-8")

            config = ConfigManager(str(config_path))
            self.assertEqual(config.get_threshold("high"), 0.75)
            self.assertEqual(config.get_threshold("moderate"), 0.50)
            self.assertEqual(config.get_escalation_actions("critical")["cpu_weight"], 10)


class RuntimeConfigTests(unittest.TestCase):
    def test_load_config_helper(self):
        config = load_config()
        self.assertIsInstance(config, ConfigManager)
        self.assertTrue(config.config_file.exists() or config.poll_interval() == 3)


if __name__ == "__main__":
    unittest.main()

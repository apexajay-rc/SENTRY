"""
Tests for FeedbackEngine — action outcome evaluation.
"""

import unittest

from engine.feedback import FeedbackEngine


class TestFeedbackEngine(unittest.TestCase):

    def test_successful_action(self):
        """Action is successful when stress decreases AND pressure improves."""
        engine = FeedbackEngine()

        outcome = engine.evaluate(
            pid=123,
            stress_before=0.90,
            stress_after=0.60,
            pressure_before="CRITICAL",
            pressure_after="HIGH",
        )

        self.assertTrue(outcome.successful)

    def test_failed_action_no_improvement(self):
        """Action fails when stress doesn't decrease enough."""
        engine = FeedbackEngine()

        outcome = engine.evaluate(
            pid=123,
            stress_before=0.90,
            stress_after=0.88,
            pressure_before="CRITICAL",
            pressure_after="CRITICAL",
        )

        self.assertFalse(outcome.successful)

    def test_successful_action_same_level(self):
        """Action succeeds if stress decreases and level stays same."""
        engine = FeedbackEngine()

        outcome = engine.evaluate(
            pid=456,
            stress_before=0.72,
            stress_after=0.71,
            pressure_before="HIGH",
            pressure_after="HIGH",
        )

        self.assertTrue(outcome.successful)

    def test_failed_action_pressure_worsened(self):
        """Action fails if pressure level worsened despite stress decrease."""
        engine = FeedbackEngine()

        outcome = engine.evaluate(
            pid=789,
            stress_before=0.50,
            stress_after=0.45,
            pressure_before="MODERATE",
            pressure_after="HIGH",  # Moved to worse level
        )

        self.assertFalse(outcome.successful)

    def test_successful_action_to_low(self):
        """Action succeeds when reaching LOW level."""
        engine = FeedbackEngine()

        outcome = engine.evaluate(
            pid=999,
            stress_before=0.60,
            stress_after=0.30,
            pressure_before="HIGH",
            pressure_after="LOW",
        )

        self.assertTrue(outcome.successful)


if __name__ == "__main__":
    unittest.main()

import unittest

from engine.feedback import FeedbackEngine


class TestFeedbackEngine(unittest.TestCase):

    def test_successful_action(self):

        engine = FeedbackEngine()

        outcome = engine.evaluate(
            pid=123,
            stress_before=0.90,
            stress_after=0.60,
            pressure_before="CRITICAL",
            pressure_after="HIGH",
        )

        self.assertTrue(outcome.successful)

    def test_failed_action(self):

        engine = FeedbackEngine()

        outcome = engine.evaluate(
            pid=123,
            stress_before=0.90,
            stress_after=0.88,
            pressure_before="CRITICAL",
            pressure_after="CRITICAL",
        )

        self.assertFalse(outcome.successful)

"""Which signal a comparison pill claims on its right-hand side."""
from __future__ import annotations

import unittest

from energy_dashboard.core.alarms import (
    comparison_subject_label,
    comparison_subjects,
)


class ComparisonSubjectTests(unittest.TestCase):
    def test_goes_silent_is_the_tasmota_device(self):
        self.assertEqual(comparison_subject_label("goes silent"), "Tasmota device")
        self.assertEqual(comparison_subjects("goes silent"), ("Tasmota device",))

    def test_stops_covers_more_than_one_feed(self):
        self.assertEqual(comparison_subject_label("stops"), "Multiple")
        self.assertIn("Database writing", comparison_subjects("stops"))
        self.assertIn("Grott feed", comparison_subjects("stops"))

    def test_level_checks_are_multiple_not_all(self):
        self.assertEqual(comparison_subject_label("stays below"), "Multiple")
        self.assertGreater(len(comparison_subjects("stays below")), 1)

    def test_uses_almost_all_is_house_load(self):
        self.assertEqual(comparison_subject_label("uses almost all of"), "House load")


if __name__ == "__main__":
    unittest.main()

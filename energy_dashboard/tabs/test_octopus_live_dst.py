"""UK clock-change night must not crash Octopus Live slot flooring."""
from __future__ import annotations

import unittest

import pandas as pd

from energy_dashboard.tabs.octopus_live_cost import energy_slots_from_frames, floor_to_slot


class DstFloorTests(unittest.TestCase):
    def test_floor_keeps_both_one_oclock_hours(self):
        idx = pd.date_range(
            "2026-10-25 00:00", periods=8, freq="30min", tz="Europe/London",
        )
        floored = floor_to_slot(pd.Series(idx), 30)
        self.assertEqual(len(floored), 8)
        # First 01:00 is still BST (+01); the second is GMT (+00).
        self.assertEqual(str(floored.iloc[2]), "2026-10-25 01:00:00+01:00")
        self.assertEqual(str(floored.iloc[4]), "2026-10-25 01:00:00+00:00")

    def test_cost_slots_survive_the_fall_back_hour(self):
        idx = pd.date_range(
            "2026-10-25 00:00", periods=8, freq="30min", tz="Europe/London",
        )
        imp = pd.DataFrame({
            "interval_start": idx,
            "consumption": [0.1] * 8,
        })
        slots, source = energy_slots_from_frames(imp, None, 30)
        self.assertEqual(source, "meter")
        self.assertEqual(len(slots), 8)
        self.assertAlmostEqual(float(slots["import_kwh"].sum()), 0.8, places=6)


if __name__ == "__main__":
    unittest.main()

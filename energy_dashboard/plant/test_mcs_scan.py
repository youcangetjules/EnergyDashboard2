"""When a scanned certificate has enough figures to stop reading."""
from __future__ import annotations

import unittest

from energy_dashboard.plant.mcs_read import _scan_enough


class ScanStopTests(unittest.TestCase):
    def test_page_one_stops_when_capacity_and_a_module_are_both_printed(self):
        text = (
            "Total Installed Capacity (kW)\n6.60\n"
            "DAH Solar DHM-72X10-550W\n"
        )
        self.assertTrue(_scan_enough(text, 1))

    def test_page_one_continues_when_the_module_row_is_still_missing(self):
        text = "Total Installed Capacity (kW)\n6.60\n"
        self.assertFalse(_scan_enough(text, 1))

    def test_the_second_page_is_the_last_page_read(self):
        self.assertTrue(_scan_enough("nothing useful", 2))


if __name__ == "__main__":
    unittest.main()

"""A module datasheet yields the printed electrical figures, and nothing else."""
from __future__ import annotations

import unittest

from energy_dashboard.plant.datasheet_read import parse_datasheet


_SHEET = """
DAH Solar
Module type DHM72X10-550W
Electrical Characteristics STC
Maximum Power Pmax 550 W
Voltage at Maximum Power Vmp 42.4 V
Current at Maximum Power Imp 12.97 A
Open Circuit Voltage Voc 50.2 V
Short Circuit Current Isc 13.65 A
Temperature Coefficient of Voc -0.28 %/°C
Dimensions 2278×1134×35 mm
"""


class DatasheetParseTests(unittest.TestCase):
    def test_electrical_table_and_size(self):
        found = parse_datasheet(_SHEET)
        self.assertEqual(found["maker"], "DAH")
        self.assertEqual(found["model"], "DHM72X10")
        self.assertEqual(found["wp"], 550)
        self.assertEqual(found["vmp"], 42.4)
        self.assertEqual(found["voc"], 50.2)
        self.assertEqual(found["imp"], 12.97)
        self.assertEqual(found["w_m"], 1.134)
        self.assertEqual(found["h_m"], 2.278)

    def test_temperature_coefficient_is_not_a_voltage(self):
        found = parse_datasheet("Temperature Coefficient of Voc -0.28 %/°C")
        self.assertIsNone(found["voc"])

    def test_a_blank_sheet_stays_blank(self):
        found = parse_datasheet("Installation manual. Do not cover the cells.")
        self.assertIsNone(found["wp"])
        self.assertIsNone(found["vmp"])
        self.assertIsNone(found["voc"])
        self.assertIsNone(found["imp"])


if __name__ == "__main__":
    unittest.main()

"""Geospatial handling, deduplication, and aggregation. No database and no network."""
from __future__ import annotations

import unittest
from pathlib import Path

from energy_dashboard.hegel.aggregate import aggregate
from energy_dashboard.hegel.dedup import deduplicate, prepare_observations
from energy_dashboard.hegel.geo import distance_m, in_radius
from energy_dashboard.hegel.models import (
    CHINNOR_LAT,
    CHINNOR_LON,
    Observation,
    chinnor_pod,
    optional_float,
)
from energy_dashboard.hegel.schema import HEGEL_TABLES


def _pv(**kwargs) -> Observation:
    base = dict(
        source="pvoutput",
        source_record_id="1",
        resource_type="pv",
        location_accuracy="site",
        verification_status="confirmed",
        latitude=CHINNOR_LAT,
        longitude=CHINNOR_LON,
        installed_capacity_kwp=4.0,
    )
    base.update(kwargs)
    return Observation(**base)


class GeoTests(unittest.TestCase):
    def test_chinnor_centre_is_inside_its_circle(self):
        pod = chinnor_pod()
        self.assertTrue(in_radius(
            pod.centre_lat, pod.centre_lon,
            pod.centre_lat, pod.centre_lon, pod.radius_km,
        ))

    def test_a_point_past_five_kilometres_is_outside(self):
        # About 0.05 degrees of latitude is 5.6 km.
        self.assertFalse(in_radius(CHINNOR_LAT + 0.05, CHINNOR_LON, CHINNOR_LAT, CHINNOR_LON, 5))
        self.assertGreater(distance_m(CHINNOR_LAT, CHINNOR_LON, CHINNOR_LAT + 0.05, CHINNOR_LON), 5000)

    def test_one_hundred_metres_links_and_two_hundred_does_not(self):
        # 0.001 degree of latitude is about 111 m.
        near = _pv(source="osm", source_record_id="n1", latitude=CHINNOR_LAT + 0.001,
                   location_accuracy="reported", verification_status="observed")
        far = _pv(source="osm", source_record_id="n2", latitude=CHINNOR_LAT + 0.002,
                  location_accuracy="reported", verification_status="observed",
                  installed_capacity_kwp=4.0)
        self.assertEqual(len(deduplicate([_pv(), near])), 1)
        self.assertEqual(len(deduplicate([_pv(), far])), 2)


class DedupTests(unittest.TestCase):
    def test_shared_reported_pins_become_postcode_centroids_and_stay_unmerged(self):
        rows = prepare_observations([
            _pv(source_record_id="a", location_accuracy="reported", installed_capacity_kwp=3),
            _pv(source_record_id="b", location_accuracy="reported", installed_capacity_kwp=5),
        ])
        self.assertTrue(all(row.location_accuracy == "postcode_centroid" for row in rows))
        linked = deduplicate(rows)
        self.assertEqual(len(linked), 2)

    def test_a_site_pin_is_not_relabelled_when_another_row_shares_it(self):
        rows = prepare_observations([
            _pv(source_record_id="site", location_accuracy="site"),
            _pv(source="osm", source_record_id="map", location_accuracy="reported",
                verification_status="observed"),
        ])
        by_id = {row.source_record_id: row.location_accuracy for row in rows}
        self.assertEqual(by_id["site"], "site")
        self.assertEqual(by_id["map"], "reported")

    def test_solar_and_storage_stay_separate(self):
        battery = _pv(
            source="ssen", source_record_id="b1", resource_type="storage",
            installed_capacity_kwp=None, storage_capacity_kwh=50,
        )
        self.assertEqual(len(deduplicate([_pv(), battery])), 2)

    def test_a_small_roof_does_not_merge_with_a_fifty_kilowatt_site(self):
        farm = _pv(source="ssen", source_record_id="farm", installed_capacity_kwp=50)
        self.assertEqual(len(deduplicate([_pv(installed_capacity_kwp=4), farm])), 2)

    def test_a_district_total_never_joins_a_roof(self):
        district = _pv(
            source="desnz", source_record_id="south-oxfordshire",
            location_accuracy="area", verification_status="statistical",
            latitude=None, longitude=None, installed_capacity_kwp=12000,
        )
        linked = deduplicate([_pv(), district])
        self.assertEqual(len(linked), 2)
        self.assertEqual(
            {row.verification_status for row in linked},
            {"confirmed", "statistical"},
        )

    def test_missing_capacity_can_still_link_and_does_not_become_zero(self):
        unknown = _pv(
            source="osm", source_record_id="n9",
            location_accuracy="reported", verification_status="observed",
            installed_capacity_kwp=None,
        )
        linked = deduplicate([_pv(installed_capacity_kwp=4), unknown])
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0].installed_capacity_kwp, 4.0)
        self.assertIsNone(unknown.storage_capacity_kwh)


class AggregateTests(unittest.TestCase):
    def test_unknown_capacity_is_not_added_as_zero(self):
        rows = deduplicate([
            _pv(source_record_id="a", installed_capacity_kwp=4),
            _pv(source_record_id="b", latitude=CHINNOR_LAT + 0.01, installed_capacity_kwp=None),
        ])
        totals = aggregate(rows)
        self.assertEqual(totals.installed_kwp, 4.0)
        self.assertEqual(totals.installed_known, 1)
        self.assertEqual(totals.installed_unknown, 1)

    def test_no_known_capacity_stays_blank(self):
        totals = aggregate(deduplicate([
            _pv(installed_capacity_kwp=None),
        ]))
        self.assertIsNone(totals.installed_kwp)
        self.assertEqual(totals.installed_unknown, 1)

    def test_a_written_zero_is_kept(self):
        self.assertEqual(optional_float(0), 0.0)
        self.assertEqual(optional_float("0"), 0.0)
        self.assertIsNone(optional_float(""))
        self.assertIsNone(optional_float(None))
        self.assertIsNone(optional_float("unknown"))

    def test_district_capacity_is_not_added_to_roofs(self):
        district = _pv(
            source="desnz", source_record_id="la",
            location_accuracy="area", verification_status="statistical",
            latitude=None, longitude=None, installed_capacity_kwp=8000,
        )
        totals = aggregate(deduplicate([_pv(installed_capacity_kwp=4), district]))
        self.assertEqual(totals.installed_kwp, 4.0)
        self.assertEqual(totals.statistical_installed_kwp, 8000.0)
        self.assertEqual(totals.statistical_count, 1)

    def test_storage_unknown_is_separate_from_solar(self):
        battery = _pv(
            source="ssen", source_record_id="s", resource_type="storage",
            latitude=CHINNOR_LAT + 0.02, installed_capacity_kwp=None,
            storage_capacity_kwh=None,
        )
        totals = aggregate(deduplicate([_pv(installed_capacity_kwp=4), battery]))
        self.assertEqual(totals.installed_kwp, 4.0)
        self.assertIsNone(totals.storage_kwh)
        self.assertEqual(totals.storage_unknown, 1)


class SchemaFileTests(unittest.TestCase):
    def test_owner_script_creates_a_database_named_hegel_and_its_tables(self):
        sql = Path(__file__).resolve().parents[3].joinpath("hegel_postgres.sql").read_text()
        self.assertIn("CREATE DATABASE hegel", sql)
        self.assertNotIn("\\c powermon", sql)
        code = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
        self.assertNotIn("DROP", code.upper())
        for name in HEGEL_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {name}", sql)


if __name__ == "__main__":
    unittest.main()

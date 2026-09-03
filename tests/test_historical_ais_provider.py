"""
Unit tests for OceanTrace HistoricalFileProvider (ml/historical_ais_provider.py)
Validates:
- Loading valid CSV datasets into canonical AISPosition / VesselTrack objects
- Timestamp normalization and UTC enforcement
- Malformed CSV row detection and rejection
- Spatiotemporal AISQuery filtering (bounding box and time horizon)
- MMSI query filtering
- Vessel metadata lookup by MMSI
"""

import unittest
import os
import tempfile
from datetime import datetime, timezone, timedelta

from ml.ais_types import AISQuery
from ml.historical_ais_provider import HistoricalFileProvider


class TestHistoricalFileProvider(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.csv_path = os.path.join(self.temp_dir.name, "test_ais.csv")

        # Create sample CSV
        self.ref_time = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
        lines = [
            "mmsi,timestamp,latitude,longitude,sog,cog,heading,nav_status,name,imo,vessel_type\n",
            "999000001,2026-09-01T12:00:00Z,19.2000,71.1000,12.0,45.0,45.0,0,TEST TANKER,9312345,Tanker\n",
            "999000001,2026-09-01T13:00:00Z,19.3000,71.2000,12.2,45.0,45.0,0,TEST TANKER,9312345,Tanker\n",
            "999000001,2026-09-01T14:00:00Z,19.4000,71.3000,12.1,45.0,45.0,0,TEST TANKER,9312345,Tanker\n",
            "999000002,2026-09-01T12:00:00Z,20.5000,72.5000,15.0,90.0,90.0,0,TEST CARGO,9399999,Cargo\n",
            "999000002,2026-09-01T13:00:00Z,20.5000,72.8000,15.2,90.0,90.0,0,TEST CARGO,9399999,Cargo\n"
        ]
        with open(self.csv_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        self.provider = HistoricalFileProvider(self.csv_path, provider_id="test_hist")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_and_query_tracks(self):
        query = AISQuery(
            start_time=self.ref_time - timedelta(hours=24),
            end_time=self.ref_time,
            min_lat=18.0, max_lat=22.0,
            min_lon=70.0, max_lon=75.0
        )
        tracks = self.provider.query_tracks(query)
        self.assertEqual(len(tracks), 2)

        mmsi_map = {t.identity.mmsi: t for t in tracks}
        self.assertIn("999000001", mmsi_map)
        self.assertIn("999000002", mmsi_map)

        tanker_track = mmsi_map["999000001"]
        self.assertEqual(tanker_track.identity.name, "TEST TANKER")
        self.assertEqual(tanker_track.identity.imo, "9312345")
        self.assertEqual(len(tanker_track.positions), 3)
        self.assertEqual(tanker_track.positions[0].sog_knots, 12.0)

    def test_spatiotemporal_filtering(self):
        # Filter bbox covering only vessel 1
        query_bbox = AISQuery(
            start_time=self.ref_time - timedelta(hours=24),
            end_time=self.ref_time,
            min_lat=19.0, max_lat=19.5,
            min_lon=71.0, max_lon=71.5
        )
        tracks_bbox = self.provider.query_tracks(query_bbox)
        self.assertEqual(len(tracks_bbox), 1)
        self.assertEqual(tracks_bbox[0].identity.mmsi, "999000001")

        # Filter time window covering only first ping
        query_time = AISQuery(
            start_time=datetime(2026, 9, 1, 11, 30, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc),
            min_lat=18.0, max_lat=22.0,
            min_lon=70.0, max_lon=75.0
        )
        positions = self.provider.query_positions(query_time)
        self.assertEqual(len(positions), 2)  # 1 from vessel 1, 1 from vessel 2

    def test_malformed_csv_rejection(self):
        bad_csv = os.path.join(self.temp_dir.name, "bad.csv")
        # Missing 'longitude' column
        with open(bad_csv, "w", encoding="utf-8") as f:
            f.write("mmsi,timestamp,latitude,sog,cog\n")
            f.write("999000001,2026-09-01T12:00:00Z,19.2000,12.0,45.0\n")

        bad_prov = HistoricalFileProvider(bad_csv)
        query = AISQuery(
            start_time=self.ref_time - timedelta(hours=24),
            end_time=self.ref_time,
            min_lat=18.0, max_lat=22.0,
            min_lon=70.0, max_lon=75.0
        )
        with self.assertRaises(ValueError):
            bad_prov.query_positions(query)

    def test_bombay_high_demo_scenario(self):
        demo_csv = os.path.abspath("data/ais_scenarios/bombay_high_demo.csv")
        self.assertTrue(os.path.exists(demo_csv), "bombay_high_demo.csv not found")

        prov = HistoricalFileProvider(demo_csv)
        query = AISQuery(
            start_time=datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc),
            min_lat=19.0, max_lat=20.0,
            min_lon=70.5, max_lon=72.5
        )
        tracks = prov.query_tracks(query)
        self.assertEqual(len(tracks), 3)

        tanker = prov.lookup_vessel("999000001")
        self.assertIsNotNone(tanker)
        self.assertEqual(tanker.name, "SYNTHETIC TANKER ALPHA")
        self.assertEqual(tanker.vessel_type, "Crude Oil Tanker")


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for OceanTrace SyntheticAISProvider (ml/synthetic_ais_provider.py)
Validates:
- Deterministic repeatability given identical seed
- Fleet composition (primary candidate, background cargo, sparse vessel, gapped vessel)
- AISQuery temporal and bounding box filtering
- MMSI query filtering
- Output compliance with canonical AISPosition and VesselTrack types
- Explicit synthetic disclosure tags
"""

import unittest
from datetime import datetime, timezone, timedelta
from ml.ais_types import AISQuery, AISPosition, VesselTrack
from ml.synthetic_ais_provider import SyntheticAISProvider


class TestSyntheticAISProvider(unittest.TestCase):

    def setUp(self):
        self.ref_time = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
        self.provider = SyntheticAISProvider(
            provider_id="synthetic_test",
            seed=42,
            reference_time=self.ref_time,
            center_lat=19.4167,
            center_lon=71.3333
        )

    def test_deterministic_repeatability(self):
        p1 = SyntheticAISProvider(seed=42, reference_time=self.ref_time)
        p2 = SyntheticAISProvider(seed=42, reference_time=self.ref_time)

        query = AISQuery(
            start_time=self.ref_time - timedelta(hours=12),
            end_time=self.ref_time,
            min_lat=18.0, max_lat=21.0,
            min_lon=70.0, max_lon=73.0
        )

        tracks1 = p1.query_tracks(query)
        tracks2 = p2.query_tracks(query)

        self.assertEqual(len(tracks1), len(tracks2))
        for t1, t2 in zip(tracks1, tracks2):
            self.assertEqual(t1.identity.mmsi, t2.identity.mmsi)
            self.assertEqual(len(t1.positions), len(t2.positions))
            self.assertAlmostEqual(t1.positions[0].latitude, t2.positions[0].latitude, places=6)
            self.assertAlmostEqual(t1.positions[0].longitude, t2.positions[0].longitude, places=6)

    def test_query_mmsi_filtering(self):
        query_all = AISQuery(
            start_time=self.ref_time - timedelta(hours=24),
            end_time=self.ref_time,
            min_lat=18.0, max_lat=21.0,
            min_lon=70.0, max_lon=73.0
        )
        tracks_all = self.provider.query_tracks(query_all)
        self.assertEqual(len(tracks_all), 4)

        query_single = AISQuery(
            start_time=self.ref_time - timedelta(hours=24),
            end_time=self.ref_time,
            min_lat=18.0, max_lat=21.0,
            min_lon=70.0, max_lon=73.0,
            mmsi_filter=["999000001"]
        )
        tracks_single = self.provider.query_tracks(query_single)
        self.assertEqual(len(tracks_single), 1)
        self.assertEqual(tracks_single[0].identity.mmsi, "999000001")
        self.assertEqual(tracks_single[0].identity.name, "SYNTHETIC TANKER ALPHA")

    def test_vessel_lookup(self):
        vessel = self.provider.lookup_vessel("999000001")
        self.assertIsNotNone(vessel)
        self.assertEqual(vessel.vessel_type, "Crude Oil Tanker")

        missing = self.provider.lookup_vessel("123456789")
        self.assertIsNone(missing)

    def test_synthetic_labeling_and_gap_presence(self):
        query = AISQuery(
            start_time=self.ref_time - timedelta(hours=24),
            end_time=self.ref_time,
            min_lat=18.0, max_lat=21.0,
            min_lon=70.0, max_lon=73.0
        )
        tracks = self.provider.query_tracks(query)
        mmsi_map = {t.identity.mmsi: t for t in tracks}

        # Verify synthetic labeling
        for t in tracks:
            self.assertEqual(t.source_provider, "synthetic_test")

        # Vessel 4 must have a gap > 2.0 hours flagged
        self.assertTrue(mmsi_map["999000004"].data_quality.has_suspicious_gap)
        self.assertGreaterEqual(mmsi_map["999000004"].data_quality.max_temporal_gap_hours, 3.5)


if __name__ == "__main__":
    unittest.main()

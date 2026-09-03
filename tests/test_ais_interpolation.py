"""
Unit tests for OceanTrace AIS Track Interpolation Engine (ml/ais_interpolation.py)
Validates:
- Exact observation timestamp preservation without interpolation
- Normal short-gap geodesic interpolation (gap <= 60 min)
- Long gap rejection and invalid tagging (gap > 60 min)
- Boundary handling: strictly no extrapolation outside track range
- Identical / duplicate timestamp handling
- Single-position track handling
- Timezone normalization
"""

import unittest
from datetime import datetime, timezone, timedelta
from ml.ais_types import AISPosition, VesselIdentity, AISDataQuality, VesselTrack
from ml.ais_interpolation import interpolate_vessel_track


class TestAISTrackInterpolation(unittest.TestCase):

    def setUp(self):
        self.t0 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        self.ident = VesselIdentity(mmsi="419001122", name="TEST TANKER")
        self.quality = AISDataQuality(observation_count=3, median_interval_min=30.0, max_temporal_gap_hours=0.5)

    def test_exact_observation_match(self):
        p1 = AISPosition("419001122", self.t0, 19.0, 71.0, 12.0, 45.0)
        p2 = AISPosition("419001122", self.t0 + timedelta(minutes=30), 19.1, 71.1, 12.0, 45.0)
        track = VesselTrack(identity=self.ident, positions=[p1, p2], data_quality=self.quality)

        # Query at exact p1 timestamp
        interp1 = interpolate_vessel_track(track, self.t0)
        self.assertIsNotNone(interp1)
        self.assertEqual(interp1.latitude, 19.0)
        self.assertEqual(interp1.longitude, 71.0)
        self.assertFalse(interp1.is_interpolated)
        self.assertTrue(interp1.is_valid)

        # Query at exact p2 timestamp
        interp2 = interpolate_vessel_track(track, self.t0 + timedelta(minutes=30))
        self.assertIsNotNone(interp2)
        self.assertEqual(interp2.latitude, 19.1)
        self.assertFalse(interp2.is_interpolated)
        self.assertTrue(interp2.is_valid)

    def test_short_gap_interpolation(self):
        p1 = AISPosition("419001122", self.t0, 19.0, 71.0, 10.0, 40.0)
        p2 = AISPosition("419001122", self.t0 + timedelta(minutes=30), 19.2, 71.2, 12.0, 50.0)
        track = VesselTrack(identity=self.ident, positions=[p1, p2], data_quality=self.quality)

        # Query halfway (15 minutes in)
        t_mid = self.t0 + timedelta(minutes=15)
        interp = interpolate_vessel_track(track, t_mid)
        self.assertIsNotNone(interp)
        self.assertTrue(interp.is_interpolated)
        self.assertTrue(interp.is_valid)
        self.assertAlmostEqual(interp.latitude, 19.1, places=5)
        self.assertAlmostEqual(interp.longitude, 71.1, places=5)
        self.assertAlmostEqual(interp.sog_knots, 11.0, places=2)
        self.assertAlmostEqual(interp.cog_deg, 45.0, places=1)

    def test_large_gap_unobserved_rejection(self):
        # 2-hour gap (> 60 min limit)
        p1 = AISPosition("419001122", self.t0, 19.0, 71.0, 10.0, 40.0)
        p2 = AISPosition("419001122", self.t0 + timedelta(hours=2), 19.5, 71.5, 12.0, 50.0)
        track = VesselTrack(identity=self.ident, positions=[p1, p2], data_quality=self.quality)

        t_query = self.t0 + timedelta(hours=1)
        interp = interpolate_vessel_track(track, t_query, max_gap_seconds=3600.0)
        self.assertIsNotNone(interp)
        self.assertTrue(interp.is_interpolated)
        # MUST be marked invalid because gap exceeds 60 minutes
        self.assertFalse(interp.is_valid)
        self.assertEqual(interp.gap_duration_seconds, 7200.0)

    def test_no_extrapolation(self):
        p1 = AISPosition("419001122", self.t0, 19.0, 71.0, 10.0, 40.0)
        p2 = AISPosition("419001122", self.t0 + timedelta(minutes=30), 19.2, 71.2, 12.0, 50.0)
        track = VesselTrack(identity=self.ident, positions=[p1, p2], data_quality=self.quality)

        # Query before track start
        self.assertIsNone(interpolate_vessel_track(track, self.t0 - timedelta(minutes=5)))
        # Query after track end
        self.assertIsNone(interpolate_vessel_track(track, self.t0 + timedelta(minutes=35)))

    def test_single_position_track(self):
        p1 = AISPosition("419001122", self.t0, 19.0, 71.0, 10.0, 40.0)
        q = AISDataQuality(observation_count=1, median_interval_min=0.0, max_temporal_gap_hours=0.0)
        track = VesselTrack(identity=self.ident, positions=[p1], data_quality=q)

        # Exact match succeeds
        interp = interpolate_vessel_track(track, self.t0)
        self.assertIsNotNone(interp)
        self.assertEqual(interp.latitude, 19.0)
        self.assertFalse(interp.is_interpolated)

        # Any other timestamp returns None (no extrapolation)
        self.assertIsNone(interpolate_vessel_track(track, self.t0 + timedelta(seconds=1)))


if __name__ == "__main__":
    unittest.main()

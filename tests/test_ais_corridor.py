"""
Unit tests for OceanTrace AIS Corridor Correlation Engine (ml/ais_corridor.py)
Validates:
- Stage 1 coarse bounding box and temporal filtering
- Stage 2 dynamic covariance ellipse intersection & CPA distance calculation
- Bombay High demonstration scenario validation:
  * SYNTHETIC TANKER ALPHA intersects the target corridor with low CPA
  * SYNTHETIC CARGO BRAVO remains outside the search cone
  * SYNTHETIC FISHING CHARLIE operates peripherally
- Gap-near-CPA flag detection for unobserved intervals
"""

import unittest
import os
from datetime import datetime, timezone, timedelta

from ml.ais_types import AISPosition, VesselIdentity, AISDataQuality, VesselTrack, AISQuery
from ml.drift_types import TrajectoryPackage, TrajectoryStep, SearchEllipse
from ml.historical_ais_provider import HistoricalFileProvider
from ml.ais_corridor import AISCorridorCorrelator


class TestAISCorridorCorrelator(unittest.TestCase):

    def setUp(self):
        # Create a synthetic 24-hour backward hindcast corridor centered near Bombay High (19.4167N, 71.3333E)
        self.t0 = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
        self.steps = []

        # 5 steps: t0, -6h, -12h, -18h, -24h
        offsets = [0.0, -6.0, -12.0, -18.0, -24.0]
        for idx, h in enumerate(offsets):
            step_time = self.t0 + timedelta(hours=h)
            # Reconstructed slick advects SW as we step backward into the past; passes (19.4167, 71.3333) at h=-12h
            prog = (h + 12.0) / 12.0  # 0 at -12h, 1 at 0h, -1 at -24h
            lat = 19.4167 + prog * 0.15
            lon = 71.3333 + prog * 0.15
            # Expanding uncertainty radius backward in time
            radius = 2.0 + abs(h) * 0.20  # 2.0 km at t0 -> 6.8 km at -24h

            self.steps.append(TrajectoryStep(
                hours_offset=h,
                timestamp=step_time.isoformat(),
                centroid_lat=lat,
                centroid_lon=lon,
                ellipse=SearchEllipse(
                    semi_major_km=radius * 1.2,
                    semi_minor_km=radius * 0.8,
                    orientation_deg=45.0,
                    uncertainty_radius_km=radius
                ),
                particle_count=250
            ))

        self.hindcast = TrajectoryPackage(
            horizon_hours=24.0,
            direction="hindcast",
            steps=self.steps,
            trajectory_geojson={"type": "Feature", "geometry": {"type": "LineString", "coordinates": []}}
        )

        self.correlator = AISCorridorCorrelator(max_interpolation_gap_minutes=60.0, spatial_padding_km=25.0)

    def test_stage1_coarse_filtering(self):
        # Track 1: Overlaps Bombay High region
        t_start = self.t0 - timedelta(hours=20)
        p1 = AISPosition("999000001", t_start, 19.40, 71.30, 12.0, 45.0)
        p2 = AISPosition("999000001", t_start + timedelta(hours=2), 19.45, 71.35, 12.0, 45.0)
        track1 = VesselTrack(
            identity=VesselIdentity(mmsi="999000001", name="IN CORRIDOR"),
            positions=[p1, p2],
            data_quality=AISDataQuality(2, 120.0, 2.0)
        )

        # Track 2: Distant vessel in Bay of Bengal (lat 12.0, lon 85.0)
        p3 = AISPosition("999000009", t_start, 12.0, 85.0, 12.0, 45.0)
        p4 = AISPosition("999000009", t_start + timedelta(hours=2), 12.1, 85.1, 12.0, 45.0)
        track2 = VesselTrack(
            identity=VesselIdentity(mmsi="999000009", name="FAR AWAY"),
            positions=[p3, p4],
            data_quality=AISDataQuality(2, 120.0, 2.0)
        )

        candidates = self.correlator.filter_candidates_coarse([track1, track2], self.hindcast)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].identity.mmsi, "999000001")

    def test_bombay_high_demo_scenario_correlation(self):
        demo_csv = os.path.abspath("data/ais_scenarios/bombay_high_demo.csv")
        self.assertTrue(os.path.exists(demo_csv))
        prov = HistoricalFileProvider(demo_csv)

        query = AISQuery(
            start_time=self.t0 - timedelta(hours=24),
            end_time=self.t0,
            min_lat=18.0, max_lat=21.0,
            min_lon=70.0, max_lon=73.0
        )
        tracks = prov.query_tracks(query)
        self.assertEqual(len(tracks), 3)

        correlations = self.correlator.correlate_fleet(tracks, self.hindcast)
        self.assertEqual(len(correlations), 3)

        corr_map = {c.mmsi: c for c in correlations}

        # 1. Primary Tanker (SYNTHETIC TANKER ALPHA - MMSI 999000001)
        tanker_corr = corr_map["999000001"]
        self.assertTrue(tanker_corr.intersects_corridor)
        self.assertTrue(tanker_corr.is_cpa_inside_search_cone)
        self.assertLess(tanker_corr.min_cpa_distance_km, 5.0)
        self.assertLessEqual(tanker_corr.min_cpa_normalized_distance, 1.0)
        self.assertGreater(tanker_corr.corridor_overlap_fraction, 0.20)

        # 2. Background Cargo (SYNTHETIC CARGO BRAVO - MMSI 999000002)
        cargo_corr = corr_map["999000002"]
        self.assertFalse(cargo_corr.intersects_corridor)
        self.assertFalse(cargo_corr.is_cpa_inside_search_cone)
        self.assertGreater(cargo_corr.min_cpa_distance_km, 25.0)  # ~35 km East

        # 3. Sparse Fishing Vessel (SYNTHETIC FISHING CHARLIE - MMSI 999000003)
        fishing_corr = corr_map["999000003"]
        self.assertFalse(fishing_corr.intersects_corridor)
        self.assertGreater(fishing_corr.min_cpa_distance_km, 30.0)

    def test_unobserved_gap_near_cpa_detection(self):
        # Vessel with a 3-hour gap crossing near CPA
        t_start = self.t0 - timedelta(hours=14)
        p1 = AISPosition("999000005", t_start, 19.30, 71.20, 12.0, 45.0)
        # 3-hour jump to t0 - 11h
        p2 = AISPosition("999000005", t_start + timedelta(hours=3), 19.45, 71.35, 12.0, 45.0)
        track = VesselTrack(
            identity=VesselIdentity(mmsi="999000005", name="GAPPED SHIP"),
            positions=[p1, p2],
            data_quality=AISDataQuality(2, 180.0, 3.0, has_suspicious_gap=True)
        )

        corr = self.correlator.correlate_vessel(track, self.hindcast)
        self.assertTrue(corr.has_gap_near_cpa)


if __name__ == "__main__":
    unittest.main()

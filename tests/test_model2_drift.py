"""
Unit Test Suite for OceanTrace Model 2 (Lagrangian Drift & Hindcast Engine)
Covers SpillDetection validation, coordinate math, particle seeding, RK2 physics integration,
Coriolis deflection, forward/backward trajectories, uncertainty ellipses, and AIS attribution scoring.
"""

import unittest
import math
import time
from datetime import datetime, timezone, timedelta
import numpy as np

from ml.drift_types import (
    SpillDetection,
    ParticleState,
    SearchEllipse,
    TrajectoryStep,
    TrajectoryPackage,
    DriftResult,
    CandidateVesselTrack,
    VesselAttributionScore,
    parse_utc_iso
)
from ml.environmental_provider import (
    EnvironmentalProvider,
    SyntheticClimatologyProvider,
    OpenMeteoMarineProvider
)
from ml.drift_engine import (
    DriftEngine,
    meters_to_lat_deg,
    meters_to_lon_deg,
    lat_lon_distance_km,
    compute_coriolis_deflection,
    rotate_vector_2d,
    point_in_polygon
)
from ml.forecast import ForwardForecaster, generate_ellipse_geojson_ring
from ml.hindcast import BackwardHindcaster
from ml.ais_correlation import AISAttributionEngine, interpolate_vessel_position_at_time


class TestModel2TypesAndValidation(unittest.TestCase):
    """Test data types, ISO8601 validation, and coordinate bounds."""

    def test_spill_detection_valid(self):
        det = SpillDetection(
            detection_id="spill_001",
            source_scene_id="S1A_TEST_001",
            detection_timestamp="2026-09-02T04:30:00Z",
            centroid_lat=18.924,
            centroid_lon=72.831,
            area_km2=4.5,
            confidence=0.92
        )
        self.assertEqual(det.detection_id, "spill_001")
        self.assertEqual(det.utc_datetime.year, 2026)
        self.assertEqual(det.utc_datetime.tzinfo, timezone.utc)

    def test_spill_detection_invalid_coords(self):
        with self.assertRaises(ValueError):
            SpillDetection("s1", "src", "2026-09-02T04:30:00Z", centroid_lat=95.0, centroid_lon=72.0, area_km2=1.0, confidence=0.9)
        with self.assertRaises(ValueError):
            SpillDetection("s1", "src", "2026-09-02T04:30:00Z", centroid_lat=18.0, centroid_lon=-195.0, area_km2=1.0, confidence=0.9)
        with self.assertRaises(ValueError):
            SpillDetection("s1", "src", "2026-09-02T04:30:00Z", centroid_lat=18.0, centroid_lon=72.0, area_km2=-5.0, confidence=0.9)
        with self.assertRaises(ValueError):
            SpillDetection("s1", "src", "2026-09-02T04:30:00Z", centroid_lat=18.0, centroid_lon=72.0, area_km2=1.0, confidence=1.5)

    def test_timestamp_tz_aware_requirement(self):
        with self.assertRaises(ValueError):
            parse_utc_iso("2026-09-02 04:30:00")  # missing timezone


class TestDriftPhysicsAndEngine(unittest.TestCase):
    """Test coordinate transforms, Coriolis deflection, RK2 step integration, and particle seeding."""

    def setUp(self):
        self.env = SyntheticClimatologyProvider(
            base_u_current=0.30,
            base_v_current=0.0,
            base_u_wind=5.0,
            base_v_wind=0.0
        )
        self.engine = DriftEngine(
            env_provider=self.env,
            default_particle_count=250,
            base_windage_factor=0.030,
            horizontal_diffusion_m2s=5.0,
            timestep_seconds=900.0,
            seed=42
        )

    def test_distance_and_degree_conversions(self):
        lat0, lon0 = 15.0, 70.0
        d_lat_deg = meters_to_lat_deg(111000.0)
        self.assertAlmostEqual(d_lat_deg, 1.0, places=1)

        dist_km = lat_lon_distance_km(15.0, 70.0, 16.0, 70.0)
        self.assertAlmostEqual(dist_km, 111.19, places=0)

    def test_coriolis_deflection(self):
        # Northern Hemisphere (>5°N) should deflect +10°
        def_n = compute_coriolis_deflection(18.0)
        self.assertAlmostEqual(math.degrees(def_n), 10.0, places=1)

        # Southern Hemisphere (<-5°S) should deflect -10°
        def_s = compute_coriolis_deflection(-20.0)
        self.assertAlmostEqual(math.degrees(def_s), -10.0, places=1)

        # Equator should have zero deflection
        def_eq = compute_coriolis_deflection(0.0)
        self.assertAlmostEqual(math.degrees(def_eq), 0.0, places=2)

    def test_polygon_rejection_seeding(self):
        # Create square polygon around (18.0, 72.0)
        poly = {
            "type": "Polygon",
            "coordinates": [[
                [71.9, 17.9],
                [72.1, 17.9],
                [72.1, 18.1],
                [71.9, 18.1],
                [71.9, 17.9]
            ]]
        }
        det = SpillDetection(
            detection_id="spill_poly",
            source_scene_id="S1_TEST",
            detection_timestamp="2026-09-02T00:00:00Z",
            centroid_lat=18.0,
            centroid_lon=72.0,
            area_km2=10.0,
            confidence=0.95,
            polygon_geojson=poly
        )
        particles = self.engine.seed_particles(det)
        self.assertEqual(len(particles), 250)

        # Verify all particles are inside the bounding box
        for p in particles:
            self.assertTrue(17.9 <= p.lat <= 18.1)
            self.assertTrue(71.9 <= p.lon <= 72.1)

    def test_rk2_forward_step_advection(self):
        t0 = datetime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc)
        particles = [ParticleState(lat=15.0, lon=70.0, weight=1.0, windage_factor=0.030)]

        # Step 900 seconds forward
        p_next, u_curr, _ = self.engine.step_particles_rk2(particles, t0, dt_seconds=900.0, apply_diffusion=False)
        self.assertEqual(len(p_next), 1)
        # Expected eastward motion (u > 0)
        self.assertGreater(p_next[0].lon, 70.0)

    def test_uncertainty_ellipse_calculation(self):
        # Construct synthetic circular cloud
        particles = [
            ParticleState(lat=15.0 + 0.01 * math.cos(theta), lon=70.0 + 0.01 * math.sin(theta))
            for theta in np.linspace(0, 2 * math.pi, 50)
        ]
        c_lat, c_lon, ellipse = self.engine.calculate_uncertainty_ellipse(particles)
        self.assertAlmostEqual(c_lat, 15.0, places=2)
        self.assertAlmostEqual(c_lon, 70.0, places=2)
        self.assertGreater(ellipse.semi_major_km, 0.5)
        self.assertGreater(ellipse.uncertainty_radius_km, 0.5)


class TestForwardForecastAndBackwardHindcast(unittest.TestCase):
    """Test 48-hour forward and backward trajectory pipelines."""

    def setUp(self):
        self.env = SyntheticClimatologyProvider(base_u_current=0.20, base_v_current=0.10, base_u_wind=4.0, base_v_wind=2.0)
        self.engine = DriftEngine(env_provider=self.env, default_particle_count=100, seed=42)
        self.detection = SpillDetection(
            detection_id="spill_test_01",
            source_scene_id="S1_TEST",
            detection_timestamp="2026-09-02T06:00:00Z",
            centroid_lat=18.5,
            centroid_lon=72.5,
            area_km2=3.5,
            confidence=0.91
        )

    def test_forward_forecast_48h(self):
        forecaster = ForwardForecaster(self.engine, horizon_hours=48.0, output_interval_hours=6.0)
        pkg = forecaster.forecast(self.detection)

        self.assertEqual(pkg.direction, "forecast")
        self.assertEqual(pkg.horizon_hours, 48.0)
        # Steps: 0h, 6h, 12h, 18h, 24h, 30h, 36h, 42h, 48h -> 9 steps
        self.assertEqual(len(pkg.steps), 9)
        self.assertEqual(pkg.steps[0].hours_offset, 0.0)
        self.assertEqual(pkg.steps[-1].hours_offset, 48.0)

        # Slick should advect north-eastward over 48h
        self.assertGreater(pkg.steps[-1].centroid_lat, self.detection.centroid_lat)
        self.assertGreater(pkg.steps[-1].centroid_lon, self.detection.centroid_lon)

        # Check GeoJSON structures
        self.assertEqual(pkg.trajectory_geojson["type"], "Feature")
        self.assertEqual(pkg.trajectory_geojson["geometry"]["type"], "LineString")
        self.assertEqual(len(pkg.trajectory_geojson["geometry"]["coordinates"]), 9)

    def test_backward_hindcast_48h(self):
        hindcaster = BackwardHindcaster(self.engine, horizon_hours=48.0, output_interval_hours=6.0)
        pkg = hindcaster.hindcast(self.detection)

        self.assertEqual(pkg.direction, "hindcast")
        self.assertEqual(pkg.horizon_hours, 48.0)
        self.assertEqual(len(pkg.steps), 9)
        self.assertEqual(pkg.steps[0].hours_offset, 0.0)
        self.assertEqual(pkg.steps[-1].hours_offset, -48.0)

        # Backward centroid should be south-west of detection
        self.assertLess(pkg.steps[-1].centroid_lat, self.detection.centroid_lat)
        self.assertLess(pkg.steps[-1].centroid_lon, self.detection.centroid_lon)

        # Uncertainty cone should expand backward in time
        r0 = pkg.steps[0].ellipse.uncertainty_radius_km
        r_end = pkg.steps[-1].ellipse.uncertainty_radius_km
        self.assertGreater(r_end, r0 * 2.0)


class TestAISAttribution(unittest.TestCase):
    """Test AIS track interpolation, closest point of approach (CPA), and responsibility scoring."""

    def test_vessel_interpolation_and_scoring(self):
        # Create a hindcast package
        env = SyntheticClimatologyProvider()
        engine = DriftEngine(env, default_particle_count=50, seed=42)
        det = SpillDetection("s1", "src", "2026-09-02T12:00:00Z", 18.0, 72.0, 2.0, 0.95)
        hindcaster = BackwardHindcaster(engine, horizon_hours=24.0, output_interval_hours=6.0)
        hindcast_pkg = hindcaster.hindcast(det)

        # Vessel A: Passes right through the hindcast location at t = -12h
        target_step = hindcast_pkg.steps[2]  # -12h
        vessel_a = CandidateVesselTrack(
            mmsi="123456789",
            vessel_name="Ocean Tanker 1",
            vessel_type="Crude Oil Tanker",
            track_points=[
                {"timestamp": "2026-09-01T22:00:00Z", "lat": target_step.centroid_lat - 0.05, "lon": target_step.centroid_lon - 0.05},
                {"timestamp": "2026-09-02T00:00:00Z", "lat": target_step.centroid_lat, "lon": target_step.centroid_lon},
                {"timestamp": "2026-09-02T02:00:00Z", "lat": target_step.centroid_lat + 0.05, "lon": target_step.centroid_lon + 0.05}
            ]
        )

        # Vessel B: Far away
        vessel_b = CandidateVesselTrack(
            mmsi="987654321",
            vessel_name="Pleasure Yacht",
            vessel_type="Pleasure Craft",
            track_points=[
                {"timestamp": "2026-09-01T22:00:00Z", "lat": 19.5, "lon": 74.0},
                {"timestamp": "2026-09-02T02:00:00Z", "lat": 19.6, "lon": 74.1}
            ]
        )

        ais_engine = AISAttributionEngine()
        ranked = ais_engine.rank_candidate_vessels([vessel_b, vessel_a], hindcast_pkg)

        # Vessel A should be rank 1 with high score
        self.assertEqual(ranked[0].mmsi, "123456789")
        self.assertEqual(ranked[0].attribution_rank, 1)
        self.assertTrue(ranked[0].is_inside_uncertainty_cone)
        self.assertGreater(ranked[0].responsibility_score, 80.0)

        # Vessel B should have near-zero score
        self.assertEqual(ranked[1].mmsi, "987654321")
        self.assertLess(ranked[1].responsibility_score, 5.0)


if __name__ == "__main__":
    unittest.main()

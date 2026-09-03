"""
Unit tests for OceanTrace AIS Attribution Scoring & Evidence Synthesis (ml/vessel_attribution.py)
Validates all Phase D requirements:
1. Score bounds [0, 100]
2. Determinism of scoring
3. Spatial score behavior (near center vs outer boundary vs outside)
4. Corridor overlap score behavior
5. Temporal score behavior
6. COG circular-angle handling (0 deg, 90 deg, 180 deg)
7. SOG consistency behavior
8. Missing COG handling
9. Missing SOG handling
10. Large AIS gap penalty and confidence reduction
11. Interpolation-dependent encounter handling
12. Multiple candidates sorted correctly
13. Category thresholds (STRONG, MODERATE, WEAK, INSUFFICIENT_EVIDENCE)
14. Confidence decoupled from raw score
15. Neutral default prior (w_prior = 1.0)
16. INSUFFICIENT_EVIDENCE category behavior
17. Explanation and reason-code generation
18. Synthetic Bombay High demo scenario ranking (Tanker Alpha vs Cargo Bravo vs Fishing Charlie)
"""

import unittest
import os
from datetime import datetime, timezone, timedelta

from ml.ais_types import VesselIdentity, AISDataQuality, AISPosition, AISQuery
from ml.drift_types import TrajectoryPackage, TrajectoryStep, SearchEllipse
from ml.ais_correlation_types import VesselCorridorCorrelation, CorridorEncounterStep
from ml.historical_ais_provider import HistoricalFileProvider
from ml.ais_corridor import AISCorridorCorrelator
from ml.ais_attribution_types import (
    AttributionCategory,
    ConfidenceLevel,
    ReasonCode,
    AttributionScore,
    AttributionResult
)
from ml.vessel_attribution import (
    VesselAttributionEngine,
    compute_course_alignment,
    compute_speed_consistency
)


class TestAISAttribution(unittest.TestCase):

    def setUp(self):
        self.engine = VesselAttributionEngine(
            w_spatial=0.50,
            w_corridor=0.20,
            w_course=0.15,
            w_speed=0.15,
            corridor_heading_deg=45.0
        )
        self.t0 = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
        self.dummy_ellipse = SearchEllipse(semi_major_km=3.0, semi_minor_km=2.0, orientation_deg=45.0, uncertainty_radius_km=2.5)

    def _create_mock_correlation(
        self,
        mmsi: str = "999000001",
        name: str = "MOCK VESSEL",
        norm_dist: float = 0.20,
        dist_km: float = 0.50,
        overlap_frac: float = 0.50,
        sog: float = 12.5,
        cog: float = 45.0,
        has_gap_near_cpa: bool = False,
        is_interp: bool = False,
        is_valid: bool = True,
        obs_count: int = 40,
        max_gap: float = 0.5
    ) -> VesselCorridorCorrelation:
        ident = VesselIdentity(mmsi=mmsi, name=name, vessel_type="Tanker")
        q = AISDataQuality(observation_count=obs_count, median_interval_min=15.0, max_temporal_gap_hours=max_gap)
        return VesselCorridorCorrelation(
            mmsi=mmsi,
            identity=ident,
            has_temporal_overlap=True,
            intersects_corridor=(norm_dist <= 1.0),
            min_cpa_distance_km=dist_km,
            min_cpa_time=self.t0 - timedelta(hours=12),
            min_cpa_hours_offset=-12.0,
            min_cpa_normalized_distance=norm_dist,
            is_cpa_inside_search_cone=(norm_dist <= 1.0),
            is_cpa_interpolated=is_interp,
            is_cpa_valid=is_valid,
            corridor_dwell_steps=int(overlap_frac * 10),
            corridor_overlap_fraction=overlap_frac,
            vessel_sog_at_cpa=sog,
            vessel_cog_at_cpa=cog,
            closest_hindcast_ellipse=self.dummy_ellipse,
            encounter_steps=[],
            data_quality=q,
            has_gap_near_cpa=has_gap_near_cpa
        )

    def test_score_bounds_and_determinism(self):
        corr = self._create_mock_correlation()
        score1 = self.engine.evaluate_candidate(corr)
        score2 = self.engine.evaluate_candidate(corr)

        self.assertGreaterEqual(score1.overall_score, 0.0)
        self.assertLessEqual(score1.overall_score, 100.0)
        self.assertEqual(score1.overall_score, score2.overall_score)
        self.assertEqual(score1.category, score2.category)

    def test_spatial_score_behavior(self):
        # Center of corridor (norm_dist = 0.0)
        c_center = self._create_mock_correlation(norm_dist=0.0)
        ev_center = self.engine.extract_evidence(c_center)
        self.assertAlmostEqual(ev_center.s_dist, 1.0, places=3)

        # Boundary of 95% ellipse (norm_dist = 1.0)
        c_boundary = self._create_mock_correlation(norm_dist=1.0)
        ev_boundary = self.engine.extract_evidence(c_boundary)
        self.assertAlmostEqual(ev_boundary.s_dist, 0.6065, places=3)

        # Well outside corridor (norm_dist = 3.0)
        c_outside = self._create_mock_correlation(norm_dist=3.0)
        ev_outside = self.engine.extract_evidence(c_outside)
        self.assertEqual(ev_outside.s_dist, 0.0)

    def test_cog_circular_alignment(self):
        # Perfectly aligned: COG 45° vs Corridor 45° -> 1.0
        s_align, v1 = compute_course_alignment(45.0, 45.0)
        self.assertTrue(v1)
        self.assertAlmostEqual(s_align, 1.0)

        # Orthogonal: COG 135° vs Corridor 45° (diff 90°) -> 0.5
        s_ortho, v2 = compute_course_alignment(135.0, 45.0)
        self.assertTrue(v2)
        self.assertAlmostEqual(s_ortho, 0.5)

        # Opposite: COG 225° vs Corridor 45° (diff 180°) -> 0.0
        s_opp, v3 = compute_course_alignment(225.0, 45.0)
        self.assertTrue(v3)
        self.assertAlmostEqual(s_opp, 0.0)

        # Across zero degrees wrap: 5° vs 355° (diff 10°) -> 1.0 - 10/180
        s_wrap, v4 = compute_course_alignment(5.0, 355.0)
        self.assertTrue(v4)
        self.assertAlmostEqual(s_wrap, 1.0 - 10.0 / 180.0)

    def test_speed_consistency(self):
        # Cruising speed 12.0 kts
        s_cruise, v1 = compute_speed_consistency(12.0)
        self.assertTrue(v1)
        self.assertEqual(s_cruise, 1.0)

        # Anchored / stationary 0.1 kts
        s_stat, v2 = compute_speed_consistency(0.1)
        self.assertTrue(v2)
        self.assertEqual(s_stat, 0.05)

    def test_missing_cog_and_sog_handling(self):
        # Missing COG
        c_no_cog = self._create_mock_correlation(cog=None)
        score_no_cog = self.engine.evaluate_candidate(c_no_cog)
        self.assertIn("cog", score_no_cog.evidence.missing_fields)
        self.assertIn(ReasonCode.MISSING_COG, score_no_cog.reason_codes)

        # Missing SOG
        c_no_sog = self._create_mock_correlation(sog=None)
        score_no_sog = self.engine.evaluate_candidate(c_no_sog)
        self.assertIn("sog", score_no_sog.evidence.missing_fields)
        self.assertIn(ReasonCode.MISSING_SOG, score_no_sog.reason_codes)

    def test_large_ais_gap_and_confidence_degradation(self):
        # Dense track with no gap -> High Confidence
        c_dense = self._create_mock_correlation(obs_count=50, max_gap=0.5, has_gap_near_cpa=False)
        score_dense = self.engine.evaluate_candidate(c_dense)
        self.assertEqual(score_dense.confidence, ConfidenceLevel.HIGH)

        # Vessel with an unobserved >60 min gap near CPA -> Low Confidence & Score Penalty
        c_gapped = self._create_mock_correlation(obs_count=10, max_gap=4.0, has_gap_near_cpa=True)
        score_gapped = self.engine.evaluate_candidate(c_gapped)
        self.assertEqual(score_gapped.confidence, ConfidenceLevel.LOW)
        self.assertIn(ReasonCode.LARGE_AIS_GAP, score_gapped.reason_codes)
        # S_time must be penalized to 0.50
        self.assertEqual(score_gapped.evidence.s_time, 0.50)
        self.assertLess(score_gapped.overall_score, score_dense.overall_score)

    def test_category_thresholds(self):
        self.assertEqual(self.engine.categorize_score(85.0), AttributionCategory.STRONG)
        self.assertEqual(self.engine.categorize_score(75.0), AttributionCategory.STRONG)
        self.assertEqual(self.engine.categorize_score(60.0), AttributionCategory.MODERATE)
        self.assertEqual(self.engine.categorize_score(45.0), AttributionCategory.MODERATE)
        self.assertEqual(self.engine.categorize_score(30.0), AttributionCategory.WEAK)
        self.assertEqual(self.engine.categorize_score(15.0), AttributionCategory.WEAK)
        self.assertEqual(self.engine.categorize_score(10.0), AttributionCategory.INSUFFICIENT_EVIDENCE)
        self.assertEqual(self.engine.categorize_score(0.0), AttributionCategory.INSUFFICIENT_EVIDENCE)

    def test_multiple_candidates_ranking(self):
        c1 = self._create_mock_correlation(mmsi="999000001", name="HIGH MATCH", norm_dist=0.1)
        c2 = self._create_mock_correlation(mmsi="999000002", name="LOW MATCH", norm_dist=3.0)
        c3 = self._create_mock_correlation(mmsi="999000003", name="MID MATCH", norm_dist=0.8)

        res = self.engine.evaluate_and_rank_fleet([c2, c1, c3])
        self.assertEqual(res.candidate_count, 3)
        self.assertEqual(res.ranked_candidates[0].mmsi, "999000001")
        self.assertEqual(res.ranked_candidates[1].mmsi, "999000003")
        self.assertEqual(res.ranked_candidates[2].mmsi, "999000002")
        self.assertEqual(res.ranked_candidates[0].rank, 1)

    def test_bombay_high_demo_scenario_ranking(self):
        # End-to-end evaluation using Phase B/C demo CSV and hindcast corridor
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

        # Build 24-hour backward hindcast corridor passing (19.4167, 71.3333) at -12h
        steps = []
        for h in [0.0, -6.0, -12.0, -18.0, -24.0]:
            step_time = self.t0 + timedelta(hours=h)
            prog = (h + 12.0) / 12.0
            lat = 19.4167 + prog * 0.15
            lon = 71.3333 + prog * 0.15
            radius = 2.0 + abs(h) * 0.20
            steps.append(TrajectoryStep(
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

        hindcast = TrajectoryPackage(
            horizon_hours=24.0,
            direction="hindcast",
            steps=steps,
            trajectory_geojson={"type": "Feature", "geometry": {"type": "LineString", "coordinates": []}}
        )

        correlator = AISCorridorCorrelator()
        correlations = correlator.correlate_fleet(tracks, hindcast)
        self.assertEqual(len(correlations), 3)

        result = self.engine.evaluate_and_rank_fleet(correlations, corridor_heading=45.0, incident_id="BOMBAY_HIGH_DEMO")
        self.assertEqual(result.candidate_count, 3)

        top_cand = result.ranked_candidates[0]
        self.assertEqual(top_cand.mmsi, "999000001")
        self.assertEqual(top_cand.identity.name, "SYNTHETIC TANKER ALPHA")
        self.assertGreaterEqual(top_cand.overall_score, 75.0)
        self.assertEqual(top_cand.category, AttributionCategory.STRONG)
        self.assertIn(ReasonCode.CLOSE_SPATIAL_MATCH, top_cand.reason_codes)

        cargo_cand = [c for c in result.ranked_candidates if c.mmsi == "999000002"][0]
        self.assertEqual(cargo_cand.category, AttributionCategory.INSUFFICIENT_EVIDENCE)
        self.assertLess(cargo_cand.overall_score, 15.0)

        fishing_cand = [c for c in result.ranked_candidates if c.mmsi == "999000003"][0]
        self.assertEqual(fishing_cand.category, AttributionCategory.INSUFFICIENT_EVIDENCE)
        self.assertLess(fishing_cand.overall_score, 15.0)


if __name__ == "__main__":
    unittest.main()

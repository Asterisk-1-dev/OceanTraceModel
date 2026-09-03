"""
Unit tests for OceanTrace End-to-End Pipeline Integration (ml/oceantrace_pipeline.py)
Validates Phase F requirements:
1. Model 1 inference can be invoked through the pipeline with frozen V6 E21 checkpoint.
2. Pixel mask reaches geospatial adapter and moment-based centroid calculation.
3. Canonical SpillDetection is produced with valid GeoJSON polygon and UTC timestamp.
4. SpillDetection reaches Model 2 P-LDHE engine.
5. Model 2 produces a 48h backward hindcast result with expanding uncertainty cones.
6. Hindcast produces a usable AIS search corridor envelope.
7. Synthetic AIS provider supplies candidate vessel tracks.
8. Phase C correlates tracks with corridor (two-stage filtering, CPA calculation, gap detection).
9. Phase D ranks candidates into structured AttributionResult (score, confidence, category).
10. Final result contains all pipeline stages, provider identifiers, and forensic timings.
11. Pipeline is deterministic under fixed inputs/seeds.
12. No real network or external internet connection is required.
13. No AISStream API key is required.
14. Model 1 V6 checkpoint SHA256 remains exactly 4de684fa85daf05fa9d5b330103b4e3536450ccaa9d65724f889225c13eef635.
15. Empty mask produces graceful NO_OIL_DETECTED_ABOVE_THRESHOLD without errors.
"""

import unittest
import os
import hashlib
from datetime import datetime, timezone
import numpy as np

from ml.oceantrace_pipeline import OceanTracePipeline, OceanTracePipelineResult
from ml.synthetic_ais_provider import SyntheticAISProvider
from ml.historical_ais_provider import HistoricalFileProvider
from ml.ais_attribution_types import AttributionCategory, ConfidenceLevel


class TestEndToEndPipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ckpt_path = "V6_E21_FINAL/oceantrace_v6_E21_final.pth"
        if not os.path.exists(cls.ckpt_path):
            raise FileNotFoundError(f"Missing required V6 E21 checkpoint at: {cls.ckpt_path}")

        # Initialize pipeline on CPU
        cls.pipeline = OceanTracePipeline(checkpoint_path=cls.ckpt_path, device="cpu")

    def test_checkpoint_hash_integrity(self):
        """Verifies that the frozen Model 1 V6 E21 checkpoint is strictly untouched."""
        hasher = hashlib.sha256()
        with open(self.ckpt_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        expected_sha = "4de684fa85daf05fa9d5b330103b4e3536450ccaa9d65724f889225c13eef635"
        self.assertEqual(hasher.hexdigest(), expected_sha, "Model 1 V6 E21 SHA256 checksum mismatch!")

    def test_end_to_end_pipeline_flow(self):
        """Tests complete mechanical flow: Raster -> Model 1 -> Geo -> SpillDetection -> Model 2 -> AIS -> Attribution."""
        np.random.seed(42)
        # Synthetic dual-pol SAR raster fixture [512, 512, 2]
        raster = np.random.normal(-12.0, 2.0, (512, 512, 2)).astype(np.float32)
        raster[:, :, 1] = raster[:, :, 0] - 7.0

        # Inject dark oil slick patch in center
        raster[230:280, 230:280, 0] -= 10.0
        raster[230:280, 230:280, 1] -= 8.0

        bounds = {"min_lat": 19.3167, "max_lat": 19.5167, "min_lon": 71.2333, "max_lon": 71.4333}
        ts_utc = "2026-09-02T00:00:00Z"

        result = self.pipeline.run_pipeline(
            raster_input=raster,
            scene_bounds=bounds,
            source_scene_id="SYNTHETIC_PIPELINE_FIXTURE_001",
            detection_timestamp_utc=ts_utc,
            incident_id="INC_TEST_001"
        )

        # 1. Pipeline Result Container
        self.assertIsInstance(result, OceanTracePipelineResult)
        self.assertEqual(result.incident_id, "INC_TEST_001")

        # 2. Model 1 Summary
        self.assertIn("scene_classification", result.model1_summary)
        self.assertGreater(result.model1_summary["peak_probability"], 0.28)

        # 3. Geospatial SpillDetection
        det = result.spill_detection
        self.assertIsNotNone(det)
        self.assertEqual(det.source_scene_id, "SYNTHETIC_PIPELINE_FIXTURE_001")
        self.assertGreater(det.area_km2, 0.0)
        self.assertTrue(19.3167 <= det.centroid_lat <= 19.5167)
        self.assertTrue(71.2333 <= det.centroid_lon <= 71.4333)
        self.assertEqual(det.polygon_geojson["type"], "Polygon")
        self.assertEqual(len(det.polygon_geojson["coordinates"][0]), 5)

        # 4. Model 2 Drift Result
        drift = result.drift_result
        self.assertIsNotNone(drift)
        self.assertEqual(drift.hindcast.direction, "hindcast")
        self.assertEqual(drift.hindcast.horizon_hours, 48.0)
        self.assertEqual(len(drift.hindcast.steps), 9)  # 0h, -6h, ..., -48h
        self.assertEqual(drift.forecast.direction, "forecast")
        self.assertEqual(len(drift.forecast.steps), 9)   # 0h, +6h, ..., +48h

        # Uncertainty expansion check backward in time
        r0 = drift.hindcast.steps[0].ellipse.uncertainty_radius_km
        r_end = drift.hindcast.steps[-1].ellipse.uncertainty_radius_km
        self.assertGreater(r_end, r0 * 2.0)

        # 5. AIS Candidates & Attribution
        self.assertGreaterEqual(len(result.ais_correlations), 1)
        self.assertIsNotNone(result.attributions)
        self.assertEqual(result.attributions.incident_id, "INC_TEST_001")
        self.assertEqual(result.attributions.candidate_count, len(result.ais_correlations))

        # Check rankings
        for idx, cand in enumerate(result.attributions.ranked_candidates, start=1):
            self.assertEqual(cand.rank, idx)
            self.assertTrue(0.0 <= cand.overall_score <= 100.0)
            self.assertIn(cand.confidence, [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW])

        # 6. Timings & Providers
        self.assertIn("model1_ms", result.timings_ms)
        self.assertIn("model2_drift_ms", result.timings_ms)
        self.assertIn("total_pipeline_ms", result.timings_ms)
        self.assertIn("ais", result.providers)

        # 7. Serialization
        as_dict = result.to_dict()
        self.assertTrue(as_dict["spill_detected"])
        self.assertEqual(as_dict["candidate_count"], len(result.ais_correlations))

    def test_pipeline_determinism(self):
        """Validates that running the pipeline twice with identical inputs yields identical numerical results."""
        np.random.seed(123)
        raster = np.random.normal(-12.0, 2.0, (512, 512, 2)).astype(np.float32)
        raster[:, :, 1] = raster[:, :, 0] - 7.0
        raster[230:280, 230:280, 0] -= 10.0
        raster[230:280, 230:280, 1] -= 8.0

        bounds = {"min_lat": 19.3, "max_lat": 19.5, "min_lon": 71.2, "max_lon": 71.4}
        ts_utc = "2026-09-02T00:00:00Z"

        res1 = self.pipeline.run_pipeline(raster, bounds, "DET_TEST", ts_utc, incident_id="INC_DETERM")
        res2 = self.pipeline.run_pipeline(raster, bounds, "DET_TEST", ts_utc, incident_id="INC_DETERM")

        self.assertIsNotNone(res1.spill_detection)
        self.assertIsNotNone(res2.spill_detection)
        self.assertAlmostEqual(res1.spill_detection.centroid_lat, res2.spill_detection.centroid_lat, places=6)
        self.assertAlmostEqual(res1.spill_detection.centroid_lon, res2.spill_detection.centroid_lon, places=6)
        self.assertAlmostEqual(res1.spill_detection.area_km2, res2.spill_detection.area_km2, places=4)

        for c1, c2 in zip(res1.attributions.ranked_candidates, res2.attributions.ranked_candidates):
            self.assertEqual(c1.mmsi, c2.mmsi)
            self.assertAlmostEqual(c1.overall_score, c2.overall_score, places=4)

    def test_empty_raster_handling(self):
        """Validates that a clean sea scene (no oil pixels) gracefully halts without errors."""
        # Clean sea backscatter (no oil slick)
        clean_raster = np.full((512, 512, 2), -10.0, dtype=np.float32)
        clean_raster[:, :, 1] = -17.0

        bounds = {"min_lat": 19.3, "max_lat": 19.5, "min_lon": 71.2, "max_lon": 71.4}
        result = self.pipeline.run_pipeline(
            raster_input=clean_raster,
            scene_bounds=bounds,
            source_scene_id="CLEAN_SEA_001",
            detection_timestamp_utc="2026-09-02T00:00:00Z"
        )

        self.assertIsNone(result.spill_detection)
        self.assertIsNone(result.drift_result)
        self.assertEqual(len(result.ais_correlations), 0)
        self.assertIn("NO_OIL_DETECTED_ABOVE_THRESHOLD", result.warnings)

    def test_bombay_high_aligned_scenario(self):
        """
        Validates pipeline correlation against an aligned synthetic AIS scenario
        where a candidate tanker crosses near the hindcast corridor.
        """
        t0 = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
        # Position synthetic fleet centered near the 12h hindcast point
        aligned_ais = SyntheticAISProvider(
            provider_id="synthetic_aligned_provider",
            reference_time=t0,
            center_lat=19.3553,
            center_lon=71.1233
        )
        custom_pipe = OceanTracePipeline(
            checkpoint_path=self.ckpt_path,
            ais_provider=aligned_ais,
            device="cpu"
        )

        raster = np.random.normal(-12.0, 2.0, (512, 512, 2)).astype(np.float32)
        raster[:, :, 1] = raster[:, :, 0] - 7.0
        raster[230:280, 230:280, 0] -= 10.0
        raster[230:280, 230:280, 1] -= 8.0

        bounds = {"min_lat": 19.3167, "max_lat": 19.5167, "min_lon": 71.2333, "max_lon": 71.4333}
        result = custom_pipe.run_pipeline(
            raster_input=raster,
            scene_bounds=bounds,
            source_scene_id="ALIGNED_BH_SCENE",
            detection_timestamp_utc="2026-09-02T00:00:00Z"
        )

        self.assertIsNotNone(result.attributions)
        self.assertGreater(result.attributions.candidate_count, 0)

        # Primary tanker must be ranked #1
        top_cand = result.attributions.ranked_candidates[0]
        self.assertEqual(top_cand.mmsi, "999000001")
        self.assertEqual(top_cand.identity.name, "SYNTHETIC TANKER ALPHA")
        self.assertGreaterEqual(top_cand.overall_score, 60.0)
        self.assertIn(top_cand.category, [AttributionCategory.STRONG, AttributionCategory.MODERATE])

        # Background vessel must receive Insufficient Evidence
        cargo_cand = [c for c in result.attributions.ranked_candidates if c.mmsi == "999000002"][0]
        self.assertEqual(cargo_cand.category, AttributionCategory.INSUFFICIENT_EVIDENCE)
        self.assertLess(cargo_cand.overall_score, 10.0)


if __name__ == "__main__":
    unittest.main()

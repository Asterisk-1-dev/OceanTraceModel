"""
OceanTrace — End-to-End Pipeline Performance Benchmark (Phase F)
Measures execution latencies across 3 deterministic offline repetitions:
- Model 1 V6 E21 neural network inference
- Geospatial conversion and moment analysis
- Model 2 P-LDHE 48h backward hindcasting & 48h forward forecasting
- AIS candidate spatial query & Phase C corridor correlation
- Phase D composite attribution scoring and ranking
- Total pipeline latency (mean, min, max)

Clearly labels synthetic datasets and offline environmental providers.
"""

import os
import sys
import time
import numpy as np
from datetime import datetime, timezone
from typing import Optional

from ml.oceantrace_pipeline import OceanTracePipeline, OceanTracePipelineResult
from ml.synthetic_ais_provider import SyntheticAISProvider
from ml.environmental_provider import SyntheticClimatologyProvider


def run_end_to_end_benchmark(num_runs: int = 3):
    print("=" * 90)
    print(" OCEANTRACE END-TO-END PIPELINE PERFORMANCE BENCHMARK (PHASE F)")
    print("=" * 90)
    print("Pipeline Stages:")
    print("  1. S1 SAR Raster [512x512x2 dB]")
    print("  2. Model 1: SARDeepLabV3Plus_MultiTask_scSE (Frozen V6 E21 Final Checkpoint)")
    print("  3. Geospatial Adapter: Moment Centroid & WGS84 GeoJSON Polygonizer")
    print("  4. Canonical SpillDetection Validation")
    print("  5. Model 2: P-LDHE Lagrangian Drift Engine (48h Hindcast + 48h Forecast, RK2, 250 particles)")
    print("  6. AIS Data Layer: Synthetic Bombay High Scenario (SYNTHETIC AIS — TEST DATA ONLY)")
    print("  7. Phase C: AIS Corridor Correlator (Dynamic CPA & Covariance Ellipse Intersections)")
    print("  8. Phase D: Vessel Attribution Engine (Composite Evidence Scoring 0-100 & Confidence)")
    print("=" * 90)

    # Deterministic inputs
    t0 = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
    env = SyntheticClimatologyProvider()
    ais = SyntheticAISProvider(
        provider_id="synthetic_benchmark_provider",
        reference_time=t0,
        center_lat=19.3553,
        center_lon=71.1233
    )

    print("\nInitializing OceanTrace End-to-End Pipeline...")
    t_init_start = time.perf_counter()
    pipeline = OceanTracePipeline(
        checkpoint_path="V6_E21_FINAL/oceantrace_v6_E21_final.pth",
        detection_threshold=0.28,
        device="cpu",
        env_provider=env,
        ais_provider=ais
    )
    t_init_ms = (time.perf_counter() - t_init_start) * 1000.0
    print(f"Pipeline initialized in {t_init_ms:.2f} ms (CPU)")

    # Construct deterministic synthetic SAR raster fixture [512, 512, 2] in dB
    np.random.seed(42)
    raster = np.random.normal(-12.0, 2.0, (512, 512, 2)).astype(np.float32)
    raster[:, :, 1] = raster[:, :, 0] - 7.0
    # Add dark oil slick patch in center
    raster[230:280, 230:280, 0] -= 10.0
    raster[230:280, 230:280, 1] -= 8.0

    bounds = {"min_lat": 19.3167, "max_lat": 19.5167, "min_lon": 71.2333, "max_lon": 71.4333}
    ts_utc = "2026-09-02T00:00:00Z"

    runs_data = []

    print(f"\nExecuting {num_runs} consecutive benchmark runs...")
    print("-" * 90)

    last_result: Optional[OceanTracePipelineResult] = None
    for run_idx in range(1, num_runs + 1):
        t0_run = time.perf_counter()
        res = pipeline.run_pipeline(
            raster_input=raster,
            scene_bounds=bounds,
            source_scene_id=f"BENCHMARK_FIXTURE_RUN_{run_idx}",
            detection_timestamp_utc=ts_utc,
            incident_id=f"INC_BENCH_{run_idx}"
        )
        total_wall_ms = (time.perf_counter() - t0_run) * 1000.0
        last_result = res

        runs_data.append({
            "model1_ms": res.timings_ms["model1_ms"],
            "geospatial_ms": res.timings_ms["geospatial_ms"],
            "model2_drift_ms": res.timings_ms["model2_drift_ms"],
            "ais_query_and_correlate_ms": res.timings_ms["ais_query_and_correlate_ms"],
            "attribution_ms": res.timings_ms["attribution_ms"],
            "total_ms": total_wall_ms
        })
        print(f"Run #{run_idx:d}: Total = {total_wall_ms:7.2f} ms | M1 = {res.timings_ms['model1_ms']:6.2f} ms | Geo = {res.timings_ms['geospatial_ms']:5.2f} ms | Drift = {res.timings_ms['model2_drift_ms']:6.2f} ms | AIS = {res.timings_ms['ais_query_and_correlate_ms']:5.2f} ms | Attr = {res.timings_ms['attribution_ms']:5.2f} ms")

    # Metrics aggregation
    print("-" * 90)
    print(" BENCHMARK LATENCY BREAKDOWN (Across 3 Runs)")
    print("-" * 90)
    stages = [
        ("Model 1 Inference (CPU)", "model1_ms"),
        ("Geospatial Conversion", "geospatial_ms"),
        ("Model 2 Drift (48h Hindcast+Forecast)", "model2_drift_ms"),
        ("AIS Query & Phase C Correlation", "ais_query_and_correlate_ms"),
        ("Phase D Attribution Scoring", "attribution_ms"),
        ("End-to-End Pipeline Latency", "total_ms")
    ]

    print(f"{'Pipeline Stage':<42} | {'Mean (ms)':<10} | {'Min (ms)':<10} | {'Max (ms)':<10}")
    print("-" * 80)
    for label, key in stages:
        vals = [r[key] for r in runs_data]
        mean_v = float(np.mean(vals))
        min_v = float(np.min(vals))
        max_v = float(np.max(vals))
        print(f"{label:<42} | {mean_v:9.2f}  | {min_v:9.2f}  | {max_v:9.2f}")

    print("=" * 90)
    print(" SAMPLE FORENSIC INCIDENT DOSSIER SUMMARY")
    print("=" * 90)
    det = last_result.spill_detection
    print(f"Incident Identifier:   {last_result.incident_id}")
    print(f"Spill Centroid:        {det.centroid_lat:.6f}°N, {det.centroid_lon:.6f}°E")
    print(f"Detected Area:         {det.area_km2:.4f} km²")
    print(f"Estimated Volume:      {det.estimated_volume_m3:.2f} m³")
    print(f"Scene Classification:  {det.scene_classification}")
    print(f"Model 1 Confidence:    {det.confidence:.4f}")
    print(f"Hindcast Horizon:      {last_result.drift_result.hindcast.horizon_hours:.0f} hours backward (9 output steps)")
    print(f"Candidates Evaluated:  {last_result.attributions.candidate_count}")

    print("\nRanked Vessel Suspects:")
    for cand in last_result.attributions.ranked_candidates:
        print(f"  Rank #{cand.rank} | MMSI: {cand.mmsi} | Name: {cand.identity.name:<25} | Score: {cand.overall_score:5.1f} | Category: {cand.category.value:<22} | Conf: {cand.confidence.value}")
        print(f"    CPA: {cand.evidence.min_cpa_distance_km:.2f} km | Overlap: {cand.evidence.corridor_overlap_fraction*100:.1f}% | SOG: {cand.evidence.vessel_sog_at_cpa} kts | Norm Dist: {cand.evidence.min_cpa_normalized_distance:.2f}")
        print(f"    Reason Codes: {[r.value for r in cand.reason_codes]}")

    print("\nDisclaimer & Safety Notice:")
    print("  - Environmental Forcing: SYNTHETIC ENVIRONMENT — OFFLINE TEST ONLY")
    print("  - Vessel Tracking:       SYNTHETIC AIS — NOT REAL VESSEL EVIDENCE")
    print("  - Attribution Score:     Attribution Evidence Score (0-100 scale), NOT a probability.")
    print("=" * 90)


if __name__ == "__main__":
    run_end_to_end_benchmark()

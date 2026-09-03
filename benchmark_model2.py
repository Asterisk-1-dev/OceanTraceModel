"""
OceanTrace Model 2 — End-to-End Integration & Performance Benchmark
Executes a complete simulated 48-hour incident:
SpillDetection -> Particle Seeding -> 48h Hindcast -> 48h Forecast -> DriftResult -> AIS Ranking
Measures actual runtime, memory consumption, particle counts, and verifies GeoJSON serialization.
"""

import time
import json
import tracemalloc
from datetime import datetime, timezone

from ml.drift_types import (
    SpillDetection,
    DriftResult,
    CandidateVesselTrack
)
from ml.environmental_provider import SyntheticClimatologyProvider
from ml.drift_engine import DriftEngine
from ml.forecast import ForwardForecaster
from ml.hindcast import BackwardHindcaster
from ml.ais_correlation import AISAttributionEngine


def run_model2_benchmark():
    print("=" * 85)
    print(" OCEANTRACE MODEL 2: END-TO-END INTEGRATION & PERFORMANCE BENCHMARK")
    print("=" * 85)

    # 1. Setup Environmental Engine & Drift Models
    env = SyntheticClimatologyProvider(
        base_u_current=0.25,
        base_v_current=0.12,
        base_u_wind=5.5,
        base_v_wind=2.1
    )
    engine = DriftEngine(
        env_provider=env,
        default_particle_count=250,
        base_windage_factor=0.030,
        horizontal_diffusion_m2s=5.0,
        timestep_seconds=900.0,  # 15 min
        seed=42
    )

    forecaster = ForwardForecaster(engine, horizon_hours=48.0, output_interval_hours=6.0)
    hindcaster = BackwardHindcaster(engine, horizon_hours=48.0, output_interval_hours=6.0)
    ais_engine = AISAttributionEngine()

    # 2. Define Sample SpillDetection (Emitted from Model 1 + polygonize.py)
    spill_poly = {
        "type": "Polygon",
        "coordinates": [[
            [72.810, 18.910],
            [72.852, 18.915],
            [72.848, 18.938],
            [72.805, 18.932],
            [72.810, 18.910]
        ]]
    }

    detection = SpillDetection(
        detection_id="incident_sih_2026_0902",
        source_scene_id="S1A_IW_GRDH_1SDV_20260902T043000_BOMBAY_HIGH",
        detection_timestamp="2026-09-02T04:30:00Z",
        centroid_lat=18.9240,
        centroid_lon=72.8310,
        area_km2=5.24,
        confidence=0.942,
        polygon_geojson=spill_poly,
        estimated_volume_m3=34.06
    )

    # 3. Benchmark Execution
    tracemalloc.start()
    t_start = time.perf_counter()

    # Seed Particles
    particles = engine.seed_particles(detection)

    # Run 48h Hindcast (Backward Source Estimation)
    hindcast_pkg = hindcaster.hindcast(detection, initial_particles=particles)

    # Run 48h Forecast (Forward Spill Dispersion)
    forecast_pkg = forecaster.forecast(detection, initial_particles=particles)

    # Package into Unified DriftResult
    drift_result = DriftResult(
        incident_id=detection.detection_id,
        detection=detection,
        hindcast=hindcast_pkg,
        forecast=forecast_pkg,
        metadata={
            "environmental_provider": "SyntheticClimatologyProvider (Test Benchmark)",
            "integration_scheme": "2nd-Order Runge-Kutta (RK2 Midpoint)",
            "timestep_seconds": 900.0,
            "particle_count": len(particles)
        }
    )

    # 4. Run AIS Attribution on 10 Candidate Vessels
    candidate_vessels = []
    # Vessel 1: Culprit tanker crossing hindcast path at t = -18h
    target_18h_step = hindcast_pkg.steps[3]  # -18h
    candidate_vessels.append(CandidateVesselTrack(
        mmsi="419001122",
        vessel_name="MT Arabian Pioneer",
        vessel_type="Crude Oil Tanker",
        track_points=[
            {"timestamp": "2026-09-01T09:00:00Z", "lat": target_18h_step.centroid_lat - 0.08, "lon": target_18h_step.centroid_lon - 0.08},
            {"timestamp": "2026-09-01T10:30:00Z", "lat": target_18h_step.centroid_lat + 0.005, "lon": target_18h_step.centroid_lon - 0.005},
            {"timestamp": "2026-09-01T12:00:00Z", "lat": target_18h_step.centroid_lat + 0.09, "lon": target_18h_step.centroid_lon + 0.09}
        ]
    ))

    # Vessels 2-10: Background traffic
    for v_idx in range(2, 11):
        candidate_vessels.append(CandidateVesselTrack(
            mmsi=f"4190099{v_idx:02d}",
            vessel_name=f"Cargo Carrier {v_idx}",
            vessel_type="Cargo",
            track_points=[
                {"timestamp": "2026-09-01T08:00:00Z", "lat": 19.8 + v_idx * 0.1, "lon": 73.5},
                {"timestamp": "2026-09-01T16:00:00Z", "lat": 19.9 + v_idx * 0.1, "lon": 73.6}
            ]
        ))

    ranked_vessels = ais_engine.rank_candidate_vessels(candidate_vessels, hindcast_pkg)

    t_elapsed = time.perf_counter() - t_start
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # 5. Output Verification
    json_output = drift_result.to_json(indent=2)
    parsed_json = json.loads(json_output)

    print(f"\n[BENCHMARK RESULTS]")
    print(f"Total Incident Processing Time: {t_elapsed * 1000:.2f} ms ({t_elapsed:.4f} seconds)")
    print(f"Peak RAM Memory Allocated:      {peak_mem / 1024:.2f} KB ({peak_mem / (1024*1024):.4f} MB)")
    print(f"Total Particles Tracked:        {len(particles)}")
    print(f"Hindcast Steps Generated:       {len(hindcast_pkg.steps)} (0h to -48h)")
    print(f"Forecast Steps Generated:       {len(forecast_pkg.steps)} (0h to +48h)")
    print(f"GeoJSON Output Size:            {len(json_output):,} characters")

    print(f"\n[FORENSIC AIS ATTRIBUTION RANKING]")
    print(f"{'Rank':4s} | {'Vessel Name':22s} | {'Type':18s} | {'CPA (km)':9s} | {'Time Match':20s} | {'Inside Cone':11s} | {'Resp Score':10s}")
    print("-" * 110)
    for v in ranked_vessels[:5]:
        print(f"#{v.attribution_rank:<3d} | {v.vessel_name:22s} | {v.vessel_type:18s} | {v.closest_approach_distance_km:9.3f} | {v.closest_approach_time:20s} | {str(v.is_inside_uncertainty_cone):11s} | {v.responsibility_score:9.2f}%")

    assert ranked_vessels[0].mmsi == "419001122", "Attribution failed: Top ranked vessel is not the culprit!"
    assert ranked_vessels[0].responsibility_score > 90.0, "Culprit responsibility score below 90%!"
    print("\n[VERIFICATION STATUS]: ALL INTEGRATION ASSERTIONS PASSED (100% OK)")


if __name__ == "__main__":
    run_model2_benchmark()

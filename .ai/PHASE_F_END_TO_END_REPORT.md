# OceanTrace Phase F: End-to-End Pipeline Integration & Offline Benchmark Report

**Project:** OceanTrace — Maritime Oil Spill Intelligence  
**Problem Statement:** SIH26143 — Leveraging satellite imagery to determine oil spills at sea along with AIS data correlations to identify the vessel responsible for the spill.  
**Subsystem:** End-to-End Orchestrator, Geospatial Adapter, and Forensic Benchmark  
**Phase:** Phase F (Full Pipeline Integration & Offline Verification)  
**Date:** 2026-09-03  
**Status:** IMPLEMENTED & VALIDATED (67/67 Tests Passing)

---

## 1. Executive Summary

Phase F connects the previously developed and approved subsystems of OceanTrace into a unified, deterministic, end-to-end software pipeline:

$$\text{Satellite Raster} \longrightarrow \text{Model 1 (V6 E21)} \longrightarrow \text{Geospatial Adapter} \longrightarrow \text{SpillDetection} \longrightarrow \text{Model 2 (P-LDHE)} \longrightarrow \text{AIS Corridor Correlation} \longrightarrow \text{Phase D Attribution} \longrightarrow \text{Ranked Suspects}$$

All stages execute in memory on CPU with zero external API dependencies, zero network requests, zero live AISStream API keys required, and strictly zero modification to Model 1 weights, architecture, or Model 2 physics.

### Primary Deliverables:
1. **[`ml/geospatial_adapter.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/geospatial_adapter.py):** Geospatial output adapter converting Model 1 2D segmentation probability masks into WGS84 coordinates, computing area ($km^2$), volume ($m^3$), second-order central moment centroids, axes, orientation, and producing canonical `SpillDetection` objects.
2. **[`ml/oceantrace_pipeline.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/oceantrace_pipeline.py):** End-to-end orchestrator (`OceanTracePipeline`) encapsulating the frozen `SARDeepLabV3Plus_MultiTask_scSE` architecture, Model 2 `BackwardHindcaster` / `ForwardForecaster`, `AISCorridorCorrelator`, and `VesselAttributionEngine`.
3. **[`tests/test_end_to_end_pipeline.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/tests/test_end_to_end_pipeline.py):** Automated test suite (5 tests) verifying end-to-end pipeline flow, strict checkpoint SHA256 integrity, determinism under fixed inputs, graceful handling of clean sea scenes, and Bombay High scenario correlation.
4. **[`benchmark_end_to_end.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/benchmark_end_to_end.py):** Performance benchmark measuring latencies across 3 consecutive offline runs.

---

## 2. Existing Interfaces Discovered & Integrated

Phase F directly reused canonical domain types across all boundaries:
* **Model 1 $\to$ Geospatial Adapter:** Consumes 2D NumPy probability mask `prob_patch [H, W]` from `torch.sigmoid(seg_logits)`.
* **Geospatial Adapter $\to$ Model 2:** Emits canonical `SpillDetection` (`ml/drift_types.py`) validated for coordinate bounds $[-90, 90] \times [-180, 180]$, timezone-aware UTC ISO8601 string, non-negative area, and GeoJSON polygon ring.
* **Model 2 $\to$ AIS Phase C:** Emits `TrajectoryPackage` (`ml/drift_types.py`) containing discrete `TrajectoryStep` instances with 95% covariance covariance ellipses (`SearchEllipse`) over a 48-hour backward window.
* **AIS Provider $\to$ Phase C:** `SyntheticAISProvider` / `HistoricalFileProvider` queries emit canonical `VesselTrack` lists with attached `VesselIdentity` and `AISDataQuality` metrics.
* **Phase C $\to$ Phase D:** `AISCorridorCorrelator.correlate_fleet()` produces `VesselCorridorCorrelation` objects with Closest Point of Approach (CPA), normalized covariance distance, overlap fraction, and unobserved gap flags.
* **Phase D $\to$ Final Output:** `VesselAttributionEngine.evaluate_and_rank_fleet()` produces `AttributionResult` with ranked `AttributionScore` objects (0–100 scale), decoupled confidence levels (`HIGH`, `MEDIUM`, `LOW`), reason codes, and natural language explanations.

---

## 3. Files Created & Modified

| File Path | Action | Description |
| :--- | :--- | :--- |
| [`ml/geospatial_adapter.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/geospatial_adapter.py) | **CREATED** | Converts 2D segmentation masks into WGS84 GeoJSON and builds canonical `SpillDetection`. |
| [`ml/oceantrace_pipeline.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/oceantrace_pipeline.py) | **CREATED** | Master pipeline orchestrator connecting Model 1, Geo Adapter, Model 2, and AIS attribution. |
| [`tests/test_end_to_end_pipeline.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/tests/test_end_to_end_pipeline.py) | **CREATED** | 5 comprehensive offline integration unit tests. |
| [`benchmark_end_to_end.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/benchmark_end_to_end.py) | **CREATED** | Standalone benchmark script measuring stage latencies and printing sample dossier. |
| `.ai/PHASE_F_END_TO_END_REPORT.md` | **CREATED** | Phase F verification and compliance deliverable report. |
| Existing Core Files | **UNTOUCHED** | `ml/models.py`, `ml/dataset.py`, `ml/drift_engine.py`, `ml/forecast.py`, `ml/hindcast.py`, `ml/ais_*.py`, `ml/vessel_attribution.py`, `V6_E21_FINAL/oceantrace_v6_E21_final.pth`. |

---

## 4. End-to-End Performance Benchmark Results

Executed on local CPU environment across 3 consecutive deterministic repetitions:

```text
==========================================================================================
 OCEANTRACE END-TO-END PIPELINE PERFORMANCE BENCHMARK (PHASE F)
==========================================================================================
Pipeline Stages:
  1. S1 SAR Raster [512x512x2 dB]
  2. Model 1: SARDeepLabV3Plus_MultiTask_scSE (Frozen V6 E21 Final Checkpoint)
  3. Geospatial Adapter: Moment Centroid & WGS84 GeoJSON Polygonizer
  4. Canonical SpillDetection Validation
  5. Model 2: P-LDHE Lagrangian Drift Engine (48h Hindcast + 48h Forecast, RK2, 250 particles)
  6. AIS Data Layer: Synthetic Bombay High Scenario (SYNTHETIC AIS — TEST DATA ONLY)
  7. Phase C: AIS Corridor Correlator (Dynamic CPA & Covariance Ellipse Intersections)
  8. Phase D: Vessel Attribution Engine (Composite Evidence Scoring 0-100 & Confidence)
==========================================================================================
Pipeline initialized in 64.32 ms (CPU)

Run #1: Total = 1392.20 ms | M1 = 540.72 ms | Geo =  1.99 ms | Drift = 844.76 ms | AIS =  2.90 ms | Attr =  0.22 ms
Run #2: Total = 1410.23 ms | M1 = 533.37 ms | Geo =  1.43 ms | Drift = 872.51 ms | AIS =  0.86 ms | Attr =  0.13 ms
Run #3: Total = 1280.38 ms | M1 = 506.29 ms | Geo =  1.48 ms | Drift = 770.13 ms | AIS =  0.69 ms | Attr =  0.13 ms
------------------------------------------------------------------------------------------
 BENCHMARK LATENCY BREAKDOWN (Across 3 Runs)
------------------------------------------------------------------------------------------
Pipeline Stage                             | Mean (ms)  | Min (ms)   | Max (ms)  
--------------------------------------------------------------------------------
Model 1 Inference (CPU)                    |    526.79  |    506.29  |    540.72
Geospatial Conversion                      |      1.63  |      1.43  |      1.99
Model 2 Drift (48h Hindcast+Forecast)      |    829.13  |    770.13  |    872.51
AIS Query & Phase C Correlation            |      1.48  |      0.69  |      2.90
Phase D Attribution Scoring                |      0.16  |      0.13  |      0.22
End-to-End Pipeline Latency                |   1360.94  |   1280.38  |   1410.23
==========================================================================================
```

### Forensic Incident Dossier Output:
```text
Incident Identifier:   INC_BENCH_3
Spill Centroid:        19.417499°N, 71.333153°E
Detected Area:         0.2119 km²
Estimated Volume:      1.38 m³
Scene Classification:  Lookalike
Model 1 Confidence:    0.4307
Hindcast Horizon:      48 hours backward (9 output steps)
Candidates Evaluated:  3

Ranked Vessel Suspects:
  Rank #1 | MMSI: 999000001 | Name: SYNTHETIC TANKER ALPHA    | Score:  72.0 | Category: MODERATE               | Conf: HIGH
    CPA: 0.12 km | Overlap: 25.0% | SOG: 12.13 kts | Norm Dist: 0.03
    Reason Codes: ['CLOSE_SPATIAL_MATCH', 'CORRIDOR_OVERLAP', 'STRONG_TEMPORAL_ALIGNMENT', 'SPEED_CONSISTENCY']
  Rank #2 | MMSI: 999000004 | Name: SYNTHETIC BULKER DELTA    | Score:  33.9 | Category: WEAK                   | Conf: MEDIUM
    CPA: 8.19 km | Overlap: 0.0% | SOG: 11.0 kts | Norm Dist: 1.56
    Reason Codes: ['WEAK_SPATIAL_MATCH', 'STRONG_TEMPORAL_ALIGNMENT', 'SPEED_CONSISTENCY']
  Rank #3 | MMSI: 999000002 | Name: SYNTHETIC CARGO BRAVO     | Score:   0.0 | Category: INSUFFICIENT_EVIDENCE  | Conf: HIGH
    CPA: 30.57 km | Overlap: 0.0% | SOG: 15.88 kts | Norm Dist: 5.81
    Reason Codes: ['WEAK_SPATIAL_MATCH', 'STRONG_TEMPORAL_ALIGNMENT', 'SPEED_CONSISTENCY', 'INSUFFICIENT_EVIDENCE']
```

---

## 5. Full Test Suite & Regression Verification

Executed the complete unit test suite across all subsystems:

```text
python -m unittest discover tests
................................Malformed JSON frame received: Expecting value: line 1 column 1 (char 0)
...................................
----------------------------------------------------------------------
Ran 67 tests in 8.363s

OK
```

### Complete Breakdown (67 Tests Total):
* `tests/test_model2_drift.py`: 11 tests (RK2 numerical physics, Coriolis deflection, polygon seeding, uncertainty ellipses, correlation stub) — **PASS**
* `tests/test_model2_validation.py`: 5 tests (analytical velocity match, source containment, diffusion scaling, dateline handling, windage sensitivity) — **PASS**
* `tests/test_ais_types.py`: 7 tests (domain model validation, UTC constraints, track ordering, query checks) — **PASS**
* `tests/test_ais_provider.py`: 2 tests (abstract interface compliance, registry operations) — **PASS**
* `tests/test_synthetic_ais_provider.py`: 4 tests (deterministic repeatability, bounding box queries, MMSI filters, synthetic labeling) — **PASS**
* `tests/test_historical_ais_provider.py`: 4 tests (CSV loading, malformed row rejection, spatiotemporal filtering, demo benchmark loading) — **PASS**
* `tests/test_ais_interpolation.py`: 5 tests (exact match, short gap interpolation, $>60\text{ min}$ gap rejection, no extrapolation, single ping) — **PASS**
* `tests/test_ais_corridor.py`: 3 tests (Stage 1 coarse filter, Bombay High scenario correlation, gap-near-CPA detection) — **PASS**
* `tests/test_ais_attribution.py`: 9 tests (bounds, determinism, spatial decay, circular COG, speed consistency, missing fields, gap penalties, category thresholds, ranking) — **PASS**
* `tests/test_ais_storage.py`: 6 tests (WAL initialization, position insertion, duplicate suppression, identity upsert, bbox/MMSI queries, 72h retention purge) — **PASS**
* `tests/test_aisstream_provider.py`: 6 tests (timestamp parsing, position/static normalization, malformed frame handling, subscription generation, storage integration) — **PASS**
* `tests/test_end_to_end_pipeline.py`: 5 tests (**NEW Phase F**) (Model 1 checksum check, full pipeline flow, determinism, clean sea handling, aligned Bombay High scenario) — **PASS**

---

## 6. Checkpoint Integrity & System Governance

* **Model 1 Checkpoint Path:** `V6_E21_FINAL/oceantrace_v6_E21_final.pth`
* **Verified SHA256 Checksum:**
  ```text
  4de684fa85daf05fa9d5b330103b4e3536450ccaa9d65724f889225c13eef635
  ```
  *(Confirmed 100% bit-for-bit identical)*
* **Git Status:** Clean with respect to tracked files. Zero modifications to `ml/models.py`, `ml/dataset.py`, or existing physics models.
* **Held-Out Benchmark Safety:** Part 3 dataset was **not touched, not mounted, and not used for integration testing**.

---

## 7. Known Limitations & Explicit Disclaimers

1. **Software Integration vs Real-World Attribution:**
   * The offline benchmark proves **software pipeline integration, deterministic execution, and mechanical correctness**.
   * It does **NOT** prove that any real vessel discharged oil or is liable under maritime law.
2. **Attribution Score Semantics:**
   * The composite score ($0\text{--}100$) is strictly an **"Attribution Evidence Score"**.
   * It is **NOT** a probability of guilt, probability of occurrence, or statistically calibrated Bayesian posterior.
3. **Synthetic Data Provenance:**
   * The offline scenarios (`SYNTHETIC_AIS`) are mathematically simulated test fixtures designed for air-gapped CI/CD and offline demonstrations. They do not correspond to real vessels.

---

## 8. Freezing Status

Phase F is **COMPLETE**, fully tested (67/67 tests passing), verified against frozen checkpoint SHA256, and **SAFE TO FREEZE**.

# OceanTrace AIS Subsystem: Phase C Implementation Report

**Project:** OceanTrace — Maritime Oil Spill Intelligence  
**Problem Statement:** SIH26143 — Leveraging satellite imagery to determine oil spills at sea along with AIS data correlations to identify the vessel responsible for the spill.  
**Subsystem:** AIS Data Acquisition, Spatiotemporal Correlation & Attribution Engine  
**Phase:** Phase C (Track Interpolation & Corridor Correlation)  
**Date:** 2026-09-03  
**Status:** IMPLEMENTED & TESTED (41/41 Tests Passing)

---

## 1. Executive Summary

Phase C establishes the core deterministic spatiotemporal bridge between **Model 2**'s time-varying backward hindcast corridor (`TrajectoryPackage` from `ml/hindcast.py`) and **VesselTrack** trajectories. It provides:
1. **Deterministic Track Interpolation:** Geodesic-compatible position and kinematic interpolation for short intervals with a **strict 60-minute maximum interpolation limit** ($\Delta t_{\text{max}} = 3600\text{s}$). Gaps $>60\text{ minutes}$ are explicitly flagged as unobserved data voids and never fictitiously dead-reckoned.
2. **Two-Stage Corridor Filtering & Correlation:**
   * **Stage 1 (Coarse Filter):** Temporal overlap checking with investigation window $[t_0 - 48\text{h}, t_0]$ and spatial pruning against an expanded bounding box ($\text{max\_radius} + 25\text{ km}$ margin).
   * **Stage 2 (Precise Correlation):** Time-indexed Closest Point of Approach (CPA) calculation against dynamic 95% covariance search ellipses, corridor dwell counting, course alignment recording, and tracking void detection near CPA.
3. **Structured Intermediate Outputs:** Data classes (`InterpolatedPosition`, `CorridorEncounterStep`, `VesselCorridorCorrelation`) containing all physical features required for Phase D attribution scoring.

---

## 2. File Implementation Breakdown

| File Path | Component | Description |
| :--- | :--- | :--- |
| [`ml/ais_correlation_types.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/ais_correlation_types.py) | Correlation Data Types | Canonical data structures for intermediate interpolation states, step encounters, and comprehensive vessel corridor correlation summaries. |
| [`ml/ais_interpolation.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/ais_interpolation.py) | Track Interpolation Engine | Geodesic-compatible lat/lon interpolation, shortest-path angle interpolation for COG, and strict $>60\text{ min}$ unobserved gap thresholding. |
| [`ml/ais_corridor.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/ais_corridor.py) | Corridor Correlation Engine | Two-stage candidate filtering and time-indexed CPA correlation against Model 2 dynamic uncertainty search ellipses. |
| [`tests/test_ais_interpolation.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/tests/test_ais_interpolation.py) | Interpolation Tests | 5 unit tests verifying exact ping preservation, short-gap interpolation, $>60\text{ min}$ gap rejection, zero extrapolation, and single-ping tracks. |
| [`tests/test_ais_corridor.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/tests/test_ais_corridor.py) | Corridor Correlation Tests | 3 unit tests verifying Stage 1 filtering, Bombay High scenario discrimination, and gap-near-CPA detection. |

---

## 3. Interpolation & Gap Handling Behavior

* **Authentic Observations:** Original AIS pings matching target timestamps are strictly preserved (`is_interpolated = False`).
* **Short-Gap Geodesic Interpolation ($\Delta t_{\text{gap}} \le 60\text{ minutes}$):**
  * Linear geographic interpolation with antimeridian wrapping protection ($[-180.0, 180.0]$).
  * Kinematic interpolation of Speed Over Ground (SOG).
  * Course Over Ground (COG) circular interpolation taking the shortest angular path across $0^\circ / 360^\circ$.
  * Tagged with `is_interpolated = True` and `is_valid = True`.
* **Large Gap Rejection ($\Delta t_{\text{gap}} > 60\text{ minutes}$):**
  * Gaps exceeding 1 hour are **not silently dead-reckoned**.
  * Tagged with `is_interpolated = True` and `is_valid = False`.
  * The actual gap duration is recorded (`gap_duration_seconds`), and if an unobserved gap occurs within $\pm 2\text{ hours}$ of CPA, `has_gap_near_cpa` is flagged.
* **No Extrapolation:** Timestamps outside the vessel's recorded observation window return `None`.

---

## 4. Corridor Correlation Algorithm

1. **Stage 1 — Coarse Envelope Pruning:**
   * Extracts maximum uncertainty radius $r_{\text{max}} = \max_k(r_k)$ across all $K$ hindcast steps.
   * Defines spatial bounding box margin: $\text{Margin}_{\text{deg}} = (r_{\text{max}} + 25.0\text{ km}) / 111.0$.
   * Discards vessels with zero temporal overlap in $[t_0 - 48\text{h}, t_0]$ or whose recorded positions fall entirely outside the bounding box.
2. **Stage 2 — Precise Spatiotemporal Correlation:**
   * At each discrete hindcast step $k$ ($t_k, \text{lat}_k, \text{lon}_k, \mathbf{\Sigma}_k, r_k$):
     * Evaluates interpolated vessel coordinates $( \text{lat}_v(t_k), \text{lon}_v(t_k) )$.
     * Computes great-circle distance $d_k$ to the hindcast centroid.
     * Computes normalized distance: $d_{\text{norm}} = d_k / \max(0.50, r_k)$.
     * Tests if position lies inside the 95% search ellipse ($d_{\text{norm}} \le 1.0$).
   * Determines global Closest Point of Approach (CPA):
     $$d_{\text{CPA}} = \min_k (d_k)$$
   * Computes corridor dwell count $N_{\text{inside}}$ and overlap fraction $f_{\text{overlap}} = N_{\text{inside}} / N_{\text{valid}}$.

---

## 5. Synthetic Scenario Validation: Bombay High

Evaluated against [`data/ais_scenarios/bombay_high_demo.csv`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/data/ais_scenarios/bombay_high_demo.csv) with a 24-hour backward hindcast corridor passing near Bombay High platform coordinates ($19.4167^\circ\text{N}, 71.3333^\circ\text{E}$) at $t_0 - 12\text{h}$:

| Vessel Name | MMSI | Vessel Type | Min CPA (km) | Normalized CPA | Inside 95% Cone? | Corridor Overlap Fraction | Correlation Assessment |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **SYNTHETIC TANKER ALPHA** | `999000001` | Crude Oil Tanker | **$3.955\text{ km}$** | **$0.899$** | **YES** | **$40.0\%$** | **Corridor Intersection Confirmed** (High proximity at $t_0 - 12\text{h}$) |
| **SYNTHETIC CARGO BRAVO** | `999000002` | Container Ship | **$34.918\text{ km}$** | **$7.936$** | **NO** | **$0.0\%$** | **Outside Corridor** (Parallel transit $35\text{ km}$ East) |
| **SYNTHETIC FISHING CHARLIE** | `999000003` | Fishing | **$37.042\text{ km}$** | **$8.419$** | **NO** | **$0.0\%$** | **Outside Corridor** (Operating $37\text{ km}$ North) |

### Scientific Disclosure Statement:
> *"CRITICAL: These synthetic scenario results are technical machinery tests only. They do NOT assert or establish real-world vessel liability, operational oil discharge, or maritime fault."*

---

## 6. Test Suite & Regression Verification

The complete unit test suite was executed across all existing Model 2 physics, validation suites, AIS Phase A domain models, AIS Phase B file providers, and new AIS Phase C modules:

```text
python -m unittest discover tests
.........................................
----------------------------------------------------------------------
Ran 41 tests in 0.523s

OK
```

### Complete Test Breakdown (41 Tests Total):
* `tests/test_model2_drift.py`: 11 tests (RK2 physics, Coriolis, polygon seeding, hindcast/forecast) — **PASS**
* `tests/test_model2_validation.py`: 5 tests (analytical velocity match, source containment, diffusion scaling, dateline handling, windage sensitivity) — **PASS**
* `tests/test_ais_types.py`: 7 tests (domain model validation, UTC constraints, track ordering, query checks) — **PASS**
* `tests/test_ais_provider.py`: 2 tests (abstract interface compliance, registry operations) — **PASS**
* `tests/test_synthetic_ais_provider.py`: 4 tests (deterministic repeatability, bounding box queries, MMSI filters, synthetic labeling) — **PASS**
* `tests/test_historical_ais_provider.py`: 4 tests (CSV loading, malformed row rejection, spatiotemporal filtering, demo benchmark loading) — **PASS**
* `tests/test_ais_interpolation.py`: 5 tests (exact match, short gap interpolation, $>60\text{ min}$ gap rejection, no extrapolation, single ping) — **PASS**
* `tests/test_ais_corridor.py`: 3 tests (Stage 1 coarse filter, Bombay High scenario correlation, gap-near-CPA detection) — **PASS**

---

## 7. Model Integrity Verification

* **Model 1 Checkpoint:** `V6_E21_FINAL/oceantrace_v6_E21_final.pth`
* **Verified Checkpoint SHA256:** `4de684fa85daf05fa9d5b330103b4e3536450ccaa9d65724f889225c13eef635` *(Strictly unchanged)*
* **Model 1 Source Code:** `ml/models.py`, `ml/dataset.py` *(Strictly untouched)*
* **Model 2 Core Physics:** `ml/drift_engine.py`, `ml/forecast.py`, `ml/hindcast.py` *(Strictly untouched)*
* **Part 3 Test Data:** Untouched and unmounted.

---

**STOPPED.** Phase C is complete. Ready for Phase D (Attribution Scoring & Evidence Synthesis).

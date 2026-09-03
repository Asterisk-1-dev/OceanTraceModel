# OceanTrace AIS Subsystem: Phase B Implementation Report

**Project:** OceanTrace — Maritime Oil Spill Intelligence  
**Problem Statement:** SIH26143 — Leveraging satellite imagery to determine oil spills at sea along with AIS data correlations to identify the vessel responsible for the spill.  
**Subsystem:** AIS Data Acquisition, Spatiotemporal Correlation & Attribution Engine  
**Phase:** Phase B (Historical & Synthetic Providers)  
**Date:** 2026-09-03  
**Status:** IMPLEMENTED & TESTED (33/33 Tests Passing)

---

## 1. Executive Summary & Deliverables

Phase B implements the offline, deterministic AIS provider architecture designed in [`.ai/AIS_ARCHITECTURE.md`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/.ai/AIS_ARCHITECTURE.md). It allows OceanTrace to ingest, normalize, and query vessel tracking data with **zero network dependencies**, zero cloud cost, and complete air-gapped repeatability for SIH evaluation.

### Key Deliverables Completed:
1. **`SyntheticAISProvider` (`ml/synthetic_ais_provider.py`):**
   * Deterministic, seed-controlled vessel track generator implementing `AISProvider`.
   * Generates a realistic multi-vessel fleet (primary candidate tanker, background cargo vessel, sparse fishing vessel, and a vessel with an intentional 4-hour tracking gap).
2. **`HistoricalFileProvider` (`ml/historical_ais_provider.py`):**
   * High-performance CSV file reader implementing `AISProvider`.
   * Enforces canonical column mapping, ISO8601 UTC timestamp normalization, coordinate and kinematic bounds checks, and automatic track reconstruction grouped by MMSI.
3. **Demo Scenario Benchmark (`data/ais_scenarios/`):**
   * Packaged `bombay_high_demo.csv` with 108 position reports covering 24 hours of navigation across the Bombay High offshore platform region ($19.42^\circ\text{N}, 71.33^\circ\text{E}$).
   * Packaged `bombay_high_demo_metadata.json` documenting scenario bounds, vessel roles, and **explicit synthetic data disclosure**.
4. **Unit Test Suites (`tests/test_synthetic_ais_provider.py`, `tests/test_historical_ais_provider.py`):**
   * 8 new tests verifying deterministic repeatability, CSV parsing, malformed row rejection, spatiotemporal bounding box filtering, MMSI filtering, and demo scenario loading.

---

## 2. File Implementation Breakdown

| File Path | Component | Description |
| :--- | :--- | :--- |
| [`ml/synthetic_ais_provider.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/synthetic_ais_provider.py) | `SyntheticAISProvider` | Deterministic fleet generator implementing `query_positions`, `query_tracks`, and `lookup_vessel`. |
| [`ml/historical_ais_provider.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/historical_ais_provider.py) | `HistoricalFileProvider` | Local CSV file provider with row-by-row validation, UTC normalization, and MMSI track grouping. |
| [`ml/ais_types.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/ais_types.py) | Domain Model Update | Added `has_suspicious_gap: bool` field to `AISDataQuality` to audit tracking voids $>2.0\text{h}$. |
| [`data/ais_scenarios/bombay_high_demo.csv`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/data/ais_scenarios/bombay_high_demo.csv) | Scenario Dataset | 108 position reports across 3 vessels in the Bombay High offshore region over 24 hours. |
| [`data/ais_scenarios/bombay_high_demo_metadata.json`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/data/ais_scenarios/bombay_high_demo_metadata.json) | Scenario Manifest | Provenance metadata explicitly documenting synthetic origin, coordinate bounds, and disclaimers. |
| [`tests/test_synthetic_ais_provider.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/tests/test_synthetic_ais_provider.py) | Unit Tests | Tests for deterministic seed repeatability, bounding box queries, MMSI filters, and synthetic labeling. |
| [`tests/test_historical_ais_provider.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/tests/test_historical_ais_provider.py) | Unit Tests | Tests for CSV parsing, malformed row rejection, coordinate filtering, and demo benchmark loading. |

---

## 3. Canonical CSV Schema & Validation Rules

The `HistoricalFileProvider` expects CSV files conforming to the canonical schema:

| Column Name | Type | Mandatory? | Validation & Normalization Rules |
| :--- | :---: | :---: | :--- |
| **`mmsi`** | String | **Yes** | Must resolve to a clean 9-digit numeric string (e.g. `"999000001"`). Whitespace stripped. |
| **`timestamp`** | String / ISO8601 | **Yes** | Converted to timezone-aware UTC datetime. Naive datetimes (without timezone) are rejected. |
| **`latitude`** | Float | **Yes** | Validated to $[-90.0, 90.0]$. NaN / Inf rejected. |
| **`longitude`** | Float | **Yes** | Validated to $[-180.0, 180.0]$. NaN / Inf rejected. |
| **`sog`** | Float | **Yes** | Speed Over Ground in knots; validated to $[0.0, 102.2\text{ knots}]$. |
| **`cog`** | Float | **Yes** | Course Over Ground in degrees; validated and normalized to $[0.0, 360.0^\circ)$. |
| **`heading`** | Float | Optional | True heading ($0.0\text{--}359.0^\circ$ or $511.0$ for unavailable). |
| **`nav_status`** | Integer | Optional | Navigational status code ($0\text{--}15$). |
| **`name`** / **`vessel_name`** | String | Optional | Vessel name string for display. |
| **`imo`** | String | Optional | 7-digit IMO number (stripped of any `"IMO"` prefix). |
| **`vessel_type`** | String | Optional | Vessel type string (e.g. `"Crude Oil Tanker"`, `"Container Ship"`). |

---

## 4. Demonstration Scenario Provenance & Scientific Honesty

The demo dataset `data/ais_scenarios/bombay_high_demo.csv` is explicitly declared as:
* **Data Provenance:** `SYNTHETIC_AIS`
* **Is Synthetic:** `True`
* **Scientific Disclosure Statement:**
  > *"CRITICAL: This dataset contains SYNTHETIC AIS TEST DATA ONLY. It does NOT assert or imply real-world vessel identity, operational discharge, or environmental liability."*

### Fleet Roles in the Bombay High Demo Scenario:
1. **Primary Candidate (`999000001`, `SYNTHETIC TANKER ALPHA`):**
   * Crude Oil Tanker cruising NE at $12.4\text{ knots}$ ($45^\circ\text{ COG}$).
   * Navigates directly through the Bombay High offshore corridor ($19.4167^\circ\text{N}, 71.3333^\circ\text{E}$) at $t_0 - 12\text{h}$.
2. **Background Transit Vessel (`999000002`, `SYNTHETIC CARGO BRAVO`):**
   * Container Ship cruising NE at $15.8\text{ knots}$ ($42^\circ\text{ COG}$).
   * Navigates along a parallel corridor $35\text{ km}$ East of the spill corridor.
3. **Sparse Fishing Vessel (`999000003`, `SYNTHETIC FISHING CHARLIE`):**
   * Commercial fishing vessel operating $45\text{ km}$ North of the platform area with 2-hour reporting intervals.

---

## 5. Test Suite Verification & Regression Protection

The complete unit test suite was executed across all Model 2 physics, validation, AIS Phase A domain types, and new AIS Phase B providers:

```text
python -m unittest discover tests
.................................
----------------------------------------------------------------------
Ran 33 tests in 0.689s

OK
```

### Test Suite Breakdown (33 Tests Total):
* `tests/test_model2_drift.py`: 11 tests (RK2 numerical advection, Coriolis deflection, polygon rejection seeding, uncertainty ellipses, AIS correlation stub) — **PASS**
* `tests/test_model2_validation.py`: 5 tests (analytical velocity match, source containment, diffusion scaling, dateline crossing, windage sensitivity) — **PASS**
* `tests/test_ais_types.py`: 7 tests (MMSI validation, UTC datetime enforcement, coordinate bounds, SOG/COG ranges, IMO checks, chronological ordering) — **PASS**
* `tests/test_ais_provider.py`: 2 tests (abstract interface compliance, registry operations) — **PASS**
* `tests/test_synthetic_ais_provider.py`: 4 tests (deterministic seed repeatability, bounding box queries, MMSI filters, synthetic labeling) — **PASS**
* `tests/test_historical_ais_provider.py`: 4 tests (CSV loading, malformed row rejection, spatiotemporal filtering, demo benchmark loading) — **PASS**

---

## 6. Model & Data Integrity Verification

* **Model 1 Checkpoint:** `V6_E21_FINAL/oceantrace_v6_E21_final.pth`
* **Verified Checkpoint SHA256:** `4de684fa85daf05fa9d5b330103b4e3536450ccaa9d65724f889225c13eef635` *(Strictly unchanged)*
* **Model 1 Source Code:** `ml/models.py`, `ml/dataset.py` *(Strictly untouched)*
* **Model 2 Core Physics:** `ml/drift_engine.py`, `ml/forecast.py`, `ml/hindcast.py` *(Strictly untouched)*
* **Untouched Part 3 Test Data:** Untouched and unmounted.

---

**STOPPED.** Phase B implementation complete. All 33 unit tests passing in $<0.7\text{ seconds}$. Ready for Phase C (Track Interpolation & Corridor Correlation).

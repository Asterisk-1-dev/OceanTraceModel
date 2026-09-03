# OceanTrace AIS Subsystem: Phase E Implementation Report

**Project:** OceanTrace — Maritime Oil Spill Intelligence  
**Problem Statement:** SIH26143 — Leveraging satellite imagery to determine oil spills at sea along with AIS data correlations to identify the vessel responsible for the spill.  
**Subsystem:** AIS Data Acquisition, Spatiotemporal Correlation & Attribution Engine  
**Phase:** Phase E (Live AISStream Ingestion & Local SQLite Storage)  
**Date:** 2026-09-03  
**Status:** IMPLEMENTED & TESTED (62/62 Tests Passing)

---

## 1. Executive Summary & Deliverables

Phase E establishes the real-time data ingestion and local persistence layer of OceanTrace. It bridges live crowdsourced maritime transponder feeds with the analytical correlation engine developed in Phases A–D:

1. **`AISStorage` (`ml/ais_storage.py`):**
   * Robust SQLite persistence engine running in **Write-Ahead Logging (WAL)** mode (`PRAGMA journal_mode=WAL;`, `PRAGMA synchronous=NORMAL;`).
   * Schema enforcing relational uniqueness on `(mmsi, timestamp_epoch)` to eliminate duplicate reception pings.
   * High-speed composite indexes: `(mmsi, timestamp_epoch ASC)` for linear track reconstruction and `(timestamp_epoch, latitude, longitude)` for spatial bounding box filtering.
   * **Rolling 72-Hour Retention Purge:** Deterministic cleanup deleting position reports older than 72 hours relative to a supplied reference time.
2. **`AISStreamProvider` (`ml/aisstream_provider.py`):**
   * Conforms strictly to the abstract `AISProvider` interface.
   * Connects via secure WebSocket (`wss://stream.aisstream.io/v0/stream`) with immediate JSON subscription frame transmission ($\le 3\text{s}$ contract).
   * Decodes and normalizes AISStream JSON envelopes (`PositionReport`, `ShipStaticData`) into canonical `AISPosition` and `VesselIdentity` domain objects.
   * Thread-safe background daemon execution with bounded exponential backoff ($1\text{s} \to 30\text{s}$) upon network interruption.
   * **Strict Secret Management:** Reads credentials strictly from `OCEANTRACE_AISSTREAM_API_KEY`. Never logs, prints, or exposes the key.
3. **Comprehensive Offline Test Suite (`tests/test_ais_storage.py`, `tests/test_aisstream_provider.py`):**
   * 12 new automated unit tests validating table creation, WAL configuration, position insertion, duplicate suppression, static identity upsert, bounding box queries, MMSI filters, track ordering, retention purge, timestamp parsing, message normalization, and subscription payload generation.
   * **Zero Live Dependency:** Automated tests execute entirely offline against temporary databases using mock envelopes with zero API key requirement.

---

## 2. File Implementation Breakdown

| File Path | Component | Description |
| :--- | :--- | :--- |
| [`ml/ais_storage.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/ais_storage.py) | `AISStorage` | SQLite local database manager with WAL mode, parameterized SQL, composite indexes, track grouping, and rolling 72h retention. |
| [`ml/aisstream_provider.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/aisstream_provider.py) | `AISStreamProvider` | Live WebSocket provider with normalization, retry/backoff, and thread-safe persistence to `AISStorage`. |
| [`tests/test_ais_storage.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/tests/test_ais_storage.py) | Unit Tests | Tests for SQLite initialization, WAL mode, unique constraint, spatiotemporal queries, identity upsert, and 72h retention purge. |
| [`tests/test_aisstream_provider.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/tests/test_aisstream_provider.py) | Unit Tests | Tests for timestamp normalization, `PositionReport` / `ShipStaticData` normalization, malformed frame handling, and subscription creation. |

---

## 3. Database Schema & Indexing Design

### Tables:
```sql
-- 1. Vessel Static Metadata Table
CREATE TABLE IF NOT EXISTS vessel_identities (
    mmsi TEXT PRIMARY KEY,
    imo TEXT,
    name TEXT,
    callsign TEXT,
    vessel_type TEXT,
    vessel_type_code INTEGER,
    length_m REAL,
    beam_m REAL,
    last_updated_epoch INTEGER NOT NULL
);

-- 2. Dynamic Position Reports Table
CREATE TABLE IF NOT EXISTS ais_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mmsi TEXT NOT NULL,
    timestamp_epoch INTEGER NOT NULL,  -- Unix epoch in seconds for fast range filtering
    timestamp_iso TEXT NOT NULL,       -- ISO8601 UTC string for forensic auditability
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    sog_knots REAL NOT NULL,
    cog_deg REAL NOT NULL,
    heading_deg REAL,
    nav_status INTEGER,
    source_provider TEXT NOT NULL DEFAULT 'aisstream',
    received_at_epoch INTEGER NOT NULL,
    UNIQUE(mmsi, timestamp_epoch)     -- Prevents duplicate pings from multi-receiver reception
);
```

### Indexes:
* `idx_positions_mmsi_time ON ais_positions(mmsi, timestamp_epoch ASC)`: Enables single-pass retrieval of chronologically ordered vessel trajectories.
* `idx_positions_spatiotemporal ON ais_positions(timestamp_epoch, latitude, longitude)`: Maximizes query efficiency when filtering candidate vessels across Model 2's $48\text{h}$ backward search envelope.

---

## 4. Message Normalization & Canonical Domain Mapping

| AISStream Source Field | Canonical Target | Validation / Transformation |
| :--- | :--- | :--- |
| `MetaData.MMSI` / `PositionReport.UserID` | `AISPosition.mmsi` | Converted to standard 9-digit numeric string (`str(mmsi).zfill(9)`). |
| `MetaData.time_utc` | `AISPosition.timestamp` | Parsed to timezone-aware UTC datetime (handles subsecond nanoseconds). |
| `PositionReport.Latitude` | `AISPosition.latitude` | Validated float in $[-90.0, 90.0]$. Rejects default invalid value $91.0$. |
| `PositionReport.Longitude` | `AISPosition.longitude` | Validated float in $[-180.0, 180.0]$. Rejects default invalid value $181.0$. |
| `PositionReport.Sog` | `AISPosition.sog_knots` | Float in $[0.0, 102.2]$. Value $102.3$ (unavailable) normalized to $0.0$. |
| `PositionReport.Cog` | `AISPosition.cog_deg` | Float in $[0.0, 360.0)$. Value $360.0$ (unavailable) normalized to $0.0$. |
| `PositionReport.TrueHeading` | `AISPosition.heading_deg` | Float in $[0.0, 359.0]$. Value $511$ (unavailable) mapped to `None`. |
| `PositionReport.NavigationalStatus` | `AISPosition.nav_status` | Integer in $[0, 15]$. Default / undefined mapped to `None`. |
| `ShipStaticData.ImoNumber` | `VesselIdentity.imo` | Cleaned 7-digit string. Value $0$ (unavailable) mapped to `None`. |
| `MetaData.ShipName` / `ShipStaticData.Name`| `VesselIdentity.name` | Stripped UTF-8 string. Empty mapped to `None`. |
| `ShipStaticData.Type` | `VesselIdentity.vessel_type` | Code converted to descriptive name (`70` Cargo, `80` Tanker, `30` Fishing, etc.). |
| `ShipStaticData.Dimension` | `VesselIdentity.length_m` / `beam_m` | Derived from GPS antenna offset dimensions $A+B$ and $C+D$. |

---

## 5. Rolling 72-Hour Retention Purge

* **Formula & Window:** 48-hour Model 2 hindcast + 24-hour operational buffer = **72 hours total retention**.
* **Purge Execution:**
  ```sql
  DELETE FROM ais_positions WHERE timestamp_epoch < :cutoff_epoch;
  PRAGMA incremental_vacuum;
  ```
* **Performance:** Deletes all expired position pings in a single atomic transaction without disturbing static vessel identity metadata.

---

## 6. Resilience & Failure Handling

* **Handshake Compliance:** Emits JSON subscription frame within $3\text{ seconds}$ of WebSocket connection.
* **Network Interruption:** Background thread catches socket closures and initiates bounded exponential backoff ($1\text{s}, 2\text{s}, 4\text{s}, \dots, 30\text{s}$).
* **Authentication Failure:** `SecurityOptionsError` or `InvalidStatusCode` aborts reconnection immediately with an explicit error log, preventing infinite connection loops.
* **Malformed Messages:** Discarded gracefully with a warning log; ingestion thread never crashes.
* **Offline Operation:** The entire provider hierarchy (`AISStreamProvider`, `HistoricalFileProvider`, `SyntheticAISProvider`) conforms to `AISProvider`, allowing OceanTrace to run air-gapped without live internet access.

---

## 7. Test Suite Verification & Regression Protection

Executed the entire unit test suite across all subsystems:

```text
python -m unittest discover tests
................................Malformed JSON frame received: Expecting value: line 1 column 1 (char 0)
..............................
----------------------------------------------------------------------
Ran 62 tests in 1.280s

OK
```

### Complete Test Breakdown (62 Tests Total):
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

---

## 8. Model & System Integrity Verification

* **Model 1 Checkpoint:** `V6_E21_FINAL/oceantrace_v6_E21_final.pth`
* **Verified Checkpoint SHA256:** `4de684fa85daf05fa9d5b330103b4e3536450ccaa9d65724f889225c13eef635` *(Strictly unchanged)*
* **Model 1 Source Code:** `ml/models.py`, `ml/dataset.py` *(Strictly untouched)*
* **Model 2 Core Physics:** `ml/drift_engine.py`, `ml/forecast.py`, `ml/hindcast.py` *(Strictly untouched)*
* **Phases A–D Modules:** `ml/ais_types.py`, `ml/ais_provider.py`, `ml/historical_ais_provider.py`, `ml/synthetic_ais_provider.py`, `ml/ais_interpolation.py`, `ml/ais_corridor.py`, `ml/vessel_attribution.py` *(Strictly untouched)*
* **Part 3 Test Data:** Untouched and unmounted.

---

**STOPPED.** Phase E implementation and testing is complete. Ready for Phase F (End-to-End Pipeline Integration & Benchmark).

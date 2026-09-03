# OceanTrace AIS Acquisition, Correlation & Vessel Attribution Architecture

**Project:** OceanTrace — Maritime Oil Spill Intelligence  
**Problem Statement:** SIH26143 — Leveraging satellite imagery to determine oil spills at sea along with AIS data correlations to identify the vessel responsible for the spill.  
**Subsystem:** AIS Data Acquisition, Spatiotemporal Trajectory Correlation & Vessel Attribution Engine  
**Author:** OceanTrace Architect  
**Date:** 2026-09-03  
**Status:** ARCHITECTURE SPECIFICATION (Pre-Implementation)

---

## 1. Executive Summary

This document specifies the architecture of the **OceanTrace AIS Subsystem**, the downstream component responsible for acquiring vessel tracking data, correlating historical ship trajectories with Model 2's time-varying backward hindcast corridor, and computing transparent, defensible vessel attribution metrics.

### System Boundaries & Guiding Principles:
1. **Upstream Decoupling:** The subsystem begins strictly at the boundary of Model 2 (`TrajectoryPackage` from `ml/hindcast.py`). It does not alter Model 1 segmentation weights or Model 2 hydrodynamic advection physics.
2. **Provider-Agnostic Core:** The attribution engine is completely agnostic of the underlying AIS data provider. AIS data flows into a standardized, canonical domain model whether sourced from live WebSockets (`AISStream.io`), local historical files (`Parquet` / `SQLite` / `CSV`), research repositories (`Global Fishing Watch`), or offline test suites.
3. **Transparent & Deterministic Scoring:** The vessel attribution metric is formulated as an **Attribution Score (0–100 scale)** derived from explicit, verifiable physical criteria (spatiotemporal proximity, trajectory alignment, operational speed underway, and vessel prior risk). **It is never represented as a probability**, nor does it assert legal guilt.
4. **Decoupled Evidence Confidence:** A distinct **Data Confidence Level (`HIGH` / `MEDIUM` / `LOW`)** is generated alongside the attribution score to reflect AIS observation density, temporal interpolation extent, and provider coverage quality.
5. **Hackathon Feasibility & Offline Resilience:** Designed to run with zero cloud infrastructure overhead on standard hardware (Python 3.12, local SQLite/file storage, $<20\text{ MB}$ memory footprint) while supporting fully offline demonstration through pre-packaged maritime scenarios.

---

## 2. End-to-End Pipeline & System Boundary

```text
┌────────────────────────────────────────────────────────────────────────┐
│  SENTINEL-1 SAR GeoTIFF (VV, VH)                                      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  MODEL 1 (V6 E21 — Frozen Multi-Task DeepLabV3+ Checkpoint)            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 2D Binary / Probability Mask
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  GEOSPATIAL CONVERSION LAYER (ml/polygonize.py)                        │
│  - Raster -> Vector Polygon Extraction (WGS84 Coordinates)             │
│  - Emits: SpillDetection Schema (Centroid, Area, GeoJSON)              │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ SpillDetection
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  MODEL 2 (Physics-Informed Lagrangian Drift & Hindcast Engine)         │
│  - Forward Forecast (+48h) & Backward Hindcast (-48h)                  │
│  - Emits: TrajectoryPackage (Time-Varying Centroids & Covariance Cones)│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Hindcast TrajectoryPackage
                                    ▼
==========================================================================
              OCEANTRACE AIS SUBSYSTEM BOUNDARY (THIS SYSTEM)
==========================================================================
                                    │
        ┌───────────────────────────┴───────────────────────────┐
        ▼                                                       ▼
┌───────────────────────────────┐       ┌───────────────────────────────┐
│   AIS PROVIDER ABSTRACTION    │       │     MODEL 2 QUERY BUILDER     │
│ - AISStream (WebSocket Stream)│       │ - Time Horizon: [t0 - 48h, t0]│
│ - Historical File (SQLite/CSV)│       │ - Dynamic Convex Hull Envelope│
│ - GFW / Research Archives     │       │ - Spatial Query Padding       │
│ - Synthetic Unit Test Provider│       └───────────────┬───────────────┘
└───────────────┬───────────────┘                       │
                │ Canonical AISPositions                │ AISQuery
                ▼                                       ▼
┌───────────────────────────────────────────────────────────────────────┐
│  STAGE 1: COARSE CANDIDATE FILTERING (Spatiotemporal Bounding Box)   │
│  Filters AOI traffic (e.g. 500 ships -> 15 candidate vessels)         │
└───────────────────────────────────┬───────────────────────────────────┘
                                    │ Candidate Vessel Tracks
                                    ▼
┌───────────────────────────────────────────────────────────────────────┐
│  STAGE 2: SPATIOTEMPORAL TRACK INTERPOLATION & CORRELATION ENGINE      │
│  - Geodesic Interpolation across short gaps (< 60 min)                │
│  - Gapped / Dark-Period Flagging (> 120 min)                          │
│  - Dynamic CPA to Hindcast Core & Covariance Ellipses                 │
│  - Track Alignment vs. Spill Trail Orientation                        │
│  - Underway Speed Plausibility Verification (8 - 18 knots)             │
└───────────────────────────────────┬───────────────────────────────────┘
                                    │ Correlation Metrics
                                    ▼
┌───────────────────────────────────────────────────────────────────────┐
│  FORENSIC ATTRIBUTION & CONFIDENCE ENGINE                             │
│  - Computes Attribution Score (0 - 100)                               │
│  - Computes Data Confidence (HIGH / MEDIUM / LOW)                     │
│  - Generates Structured Evidence Summary for Forensic Reports & UI    │
└───────────────────────────────────┬───────────────────────────────────┘
                                    │ Ranked CandidateVesselResult[]
                                    ▼
┌───────────────────────────────────────────────────────────────────────┐
│  DOWNSTREAM FORENSIC DASHBOARD / REPORT (React UI Baseline)          │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 3. Canonical AIS Domain Model

All AIS data—regardless of origin—must be parsed and normalized into canonical dataclasses defined in `ml/ais_types.py`.

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import math

@dataclass
class AISPosition:
    """Canonical position report for an individual AIS transponder ping."""
    mmsi: str                           # Exactly 9 digits
    timestamp: datetime                 # Timezone-aware UTC datetime
    latitude: float                     # Decimal degrees [-90.0, 90.0]
    longitude: float                    # Decimal degrees [-180.0, 180.0]
    sog_knots: float                    # Speed over ground in knots [0.0, 102.2]
    cog_deg: float                      # Course over ground in degrees [0.0, 360.0)
    heading_deg: Optional[float] = None # True heading [0.0, 359.0] (511 = unavailable)
    nav_status: Optional[int] = None    # Navigational status (0=underway, 1=anchored, etc.)
    source_provider: str = "unknown"

    def __post_init__(self):
        if not (isinstance(self.mmsi, str) and len(self.mmsi.strip()) == 9 and self.mmsi.strip().isdigit()):
            raise ValueError(f"Invalid MMSI: '{self.mmsi}'. Must be a 9-digit numerical string.")
        if self.timestamp.tzinfo is None:
            raise ValueError(f"Timestamp {self.timestamp} must be timezone-aware (UTC).")
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(f"Invalid latitude: {self.latitude}")
        # Normalize longitude to [-180, 180]
        self.longitude = (self.longitude + 180.0) % 360.0 - 180.0
        if not (0.0 <= self.sog_knots <= 102.2):
            self.sog_knots = max(0.0, min(102.2, self.sog_knots))
        self.cog_deg = self.cog_deg % 360.0

@dataclass
class VesselIdentity:
    """Static vessel metadata (typically from AIS Message Type 5)."""
    mmsi: str
    name: Optional[str] = None
    imo: Optional[str] = None           # 7-digit IMO ship number
    callsign: Optional[str] = None
    vessel_type: str = "Unknown"        # e.g., "Crude Oil Tanker", "Cargo", "Fishing"
    vessel_type_code: Optional[int] = None # Raw IMO/ITU numeric code (e.g., 80-89)
    flag_country: Optional[str] = None
    length_m: Optional[float] = None
    beam_m: Optional[float] = None

@dataclass
class AISDataQuality:
    """Data quality and completeness audit for an evaluated vessel track."""
    observation_count: int
    time_span_hours: float
    median_reporting_interval_min: float
    max_temporal_gap_hours: float
    has_suspicious_gap: bool            # True if gap > 2.0 hours during transit near corridor
    interpolation_fraction: float       # Fraction of evaluated track points that are interpolated
    missing_fields: List[str] = field(default_factory=list)

@dataclass
class VesselTrack:
    """Ordered chronological track for a candidate vessel across an investigation window."""
    identity: VesselIdentity
    positions: List[AISPosition]        # Strictly ordered ascending by timestamp
    quality: AISDataQuality

@dataclass
class AISQuery:
    """Structured query contract passed to any AISProvider."""
    start_time: datetime
    end_time: datetime
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    mmsi_filter: Optional[List[str]] = None
```

---

## 4. Provider Abstraction (`AISProvider`)

To ensure OceanTrace is decoupled from any single commercial or free API, providers implement a common interface defined in `ml/ais_provider.py`:

```python
from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
from ml.ais_types import AISPosition, VesselIdentity, VesselTrack, AISQuery

class AISProvider(ABC):
    """Abstract base provider for all AIS data sources."""

    @abstractmethod
    def query_positions(self, query: AISQuery) -> List[AISPosition]:
        """Fetches raw, normalized position reports matching spatiotemporal bounds."""
        pass

    @abstractmethod
    def query_tracks(self, query: AISQuery) -> List[VesselTrack]:
        """Fetches pre-grouped, chronologically sorted tracks with data-quality audits."""
        pass

    @abstractmethod
    def lookup_vessel(self, mmsi: str) -> Optional[VesselIdentity]:
        """Resolves static vessel metadata (name, IMO, ship type) by MMSI."""
        pass
```

### Supported Concrete Provider Implementations:
1. **`AISStreamProvider` (`ml/providers/aisstream_provider.py`):**
   * Connects to `wss://stream.aisstream.io/v0/stream`.
   * Subscribes using dynamic bounding boxes; filters Message Types 1, 2, 3 (Position Reports) and Message Type 5 (Static Data).
   * Streamed messages are parsed into `AISPosition` and persisted to the local rolling SQLite database.
2. **`HistoricalFileProvider` (`ml/providers/historical_provider.py`):**
   * Ingests local CSV, Parquet, or SQLite scenario databases.
   * Performs zero network queries; 100% offline; ideal for verified incident demonstration.
3. **`GlobalFishingWatchProvider` (`ml/providers/gfw_provider.py`):**
   * Connects to GFW BigQuery public tables or REST API where available; provides historical background context and apparent vessel activity.
4. **`SyntheticAISProvider` (`ml/providers/synthetic_provider.py`):**
   * Deterministic, mathematical vessel track generator for microsecond unit testing without file dependencies.

---

## 5. Live Ingestion & Storage Architecture

### Prototype Storage Decision: Embedded SQLite (`ais_local.db`)
For an SIH hackathon demonstration, running heavy enterprise databases (PostgreSQL/PostGIS, TimescaleDB) introduces fragile environment dependencies. **SQLite** (standard in Python) provides:
* Embedded zero-configuration storage ($<1\text{ ms}$ local query latency).
* Support for indexing on `(mmsi, timestamp)` and `(latitude, longitude)`.
* Spatial querying via standard R-Tree extension (`rtree`) or bounding box coordinate filters.
* Capable of handling $100,000+$ vessel pings per hour with $<15\text{ MB}$ RAM.

```text
┌────────────────────────────────────────────────────────────┐
│                    ais_local.db Schema                     │
├────────────────────────────────────────────────────────────┤
│ TABLE raw_positions (                                      │
│     mmsi TEXT NOT NULL,                                    │
│     timestamp_epoch INTEGER NOT NULL,                      │
│     timestamp_iso TEXT NOT NULL,                           │
│     latitude REAL NOT NULL,                                │
│     longitude REAL NOT NULL,                               │
│     sog REAL NOT NULL,                                     │
│     cog REAL NOT NULL,                                     │
│     heading REAL,                                          │
│     nav_status INTEGER,                                    │
│     source TEXT,                                           │
│     PRIMARY KEY (mmsi, timestamp_epoch)                    │
│ );                                                         │
│ CREATE INDEX idx_pos_spatiotemporal                        │
│     ON raw_positions(timestamp_epoch, latitude, longitude);│
│                                                            │
│ TABLE vessel_identities (                                  │
│     mmsi TEXT PRIMARY KEY,                                 │
│     imo TEXT,                                              │
│     vessel_name TEXT,                                      │
│     vessel_type TEXT,                                      │
│     vessel_type_code INTEGER,                              │
│     updated_epoch INTEGER                                  │
│ );                                                         │
└────────────────────────────────────────────────────────────┘
```

### Ingestion Lifecycle & Rolling Buffer:
* **Retention Window:** Fixed rolling window of **72 hours** (covers maximum 48h Model 2 hindcast $+ 24\text{h}$ safety buffer). A lightweight purge query runs every hour:
  `DELETE FROM raw_positions WHERE timestamp_epoch < (strftime('%s', 'now') - 259200);`
* **Deduplication:** Enforced via composite primary key `(mmsi, timestamp_epoch)`.
* **Reconnect Logic:** Exponential backoff ($1\text{s}, 2\text{s}, 4\text{s}, \dots, 30\text{s}$) with automated reconnect on WebSocket drop.
* **Credentials:** API keys read strictly from environment variable `OCEANTRACE_AISSTREAM_API_KEY`. Never hard-coded.

---

## 6. Model 2 → AIS Query Interface

Model 2 emits a `TrajectoryPackage` containing $K$ backward steps from $t_0$ to $t_0 - 48\text{h}$. The AIS subsystem converts this time-varying path into an optimized spatial query:

### Spatiotemporal Corridor Envelope:
1. **Query Time Bounds:**
   * $t_{\text{start}} = t_0 - 48\text{h} - \Delta t_{\text{pad}}$ (where $\Delta t_{\text{pad}} = 60\text{ minutes}$)
   * $t_{\text{end}} = t_0 + \Delta t_{\text{pad}}$
2. **Spatial Bounding Box with Adaptive Margin:**
   * Compute bounding box encompassing all $K$ hindcast step centroids $(\text{lat}_k, \text{lon}_k)$.
   * Expand boundaries by the maximum uncertainty radius $+ 25\text{ km}$ buffer margin:
     $$\text{Margin}_{\text{deg}} = \frac{\max_k (r_k) + 25.0}{111.0}$$
     $$\text{BBox} = [\min_k(\text{lat}_k) - \text{Margin}, \max_k(\text{lat}_k) + \text{Margin}, \min_k(\text{lon}_k) - \text{Margin}, \max_k(\text{lon}_k) + \text{Margin}]$$

---

## 7. Track Interpolation & Gap Analysis

AIS broadcasts are irregular (transponder intervals vary from 2 seconds to 3 minutes when underway, up to 15 minutes when anchored or shadowed).

### Interpolation Rules:
* **Step Synchronization:** For each discrete hindcast step timestamp $t_k$, compute the vessel's interpolated position $(\text{lat}_v(t_k), \text{lon}_v(t_k), \text{sog}_v(t_k), \text{cog}_v(t_k))$.
* **Short-Gap Linear Interpolation ($\Delta t_{\text{gap}} \le 60\text{ minutes}$):**
  $$\text{frac} = \frac{t_k - t_1}{t_2 - t_1}$$
  $$\text{lat}_{\text{interp}} = \text{lat}_1 + \text{frac} \cdot (\text{lat}_2 - \text{lat}_1)$$
  $$\text{lon}_{\text{interp}} = \text{lon}_1 + \text{frac} \cdot (\text{lon}_2 - \text{lon}_1)$$
* **Maximum Interpolation Horizon ($\Delta t_{\text{max\_interp}} = 60\text{ minutes}$):**
  * **Rule:** If the gap between recorded observations exceeds 60 minutes, **do NOT perform continuous spatial interpolation**. Instead, flag that step as `unobserved`.
* **Dark-Period / Suspicious Gap Indicator ($\Delta t_{\text{gap}} > 120\text{ minutes}$):**
  * If an unobserved gap occurs while the vessel was projected to intersect the hindcast search cone, flag `has_suspicious_gap = True`.
  * *Important Constraint:* **An AIS gap does NOT prove guilt or intentional transponder shutdown.** Gaps commonly result from VHF propagation loss, terrestrial antenna shading, or satellite footprint handoffs. It is recorded strictly as a contextual feature.

---

## 8. Two-Stage Candidate Filtering Pipeline

To avoid evaluating thousands of irrelevant vessels across the entire sea basin, processing follows a rigorous two-stage funnel:

```text
  [ All AIS Traffic in Database ] (~500 to 2,000 vessels in regional EEZ)
                 │
                 ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ STAGE 1: COARSE SPATIOTEMPORAL BOUNDING BOX FILTER                    │
  │ • Temporal overlap with [t0 - 48h, t0]                                 │
  │ • At least 2 pings within expanded corridor BBox                       │
  │ • Vessel type exclusion (Exclude tugboats/dredgers in port if far)     │
  └──────────────────────────────────┬─────────────────────────────────────┘
                                     │ Filtered to ~10 - 25 Candidates
                                     ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ STAGE 2: PRECISE SPATIOTEMPORAL CORRELATION                           │
  │ • Calculate time-indexed CPA to dynamic hindcast covariance ellipses   │
  │ • Compute minimum corridor distance d_norm(t)                          │
  │ • Compute course alignment and underway speed plausibility             │
  │ • Calculate composite Attribution Score & Data Confidence              │
  └──────────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
  [ Final Ranked Suspect List ] (Top 3 - 5 Candidates with Evidence)
```

---

## 9. Attribution Scoring Formulation

The Attribution Score ($R_v \in [0.0, 100.0]$) is a **transparent, multi-criteria forensic compatibility score**. It evaluates how strongly a vessel's physical navigation history coincides with the reconstructed oil spill corridor.

$$R_v = \Big( w_{\text{spatial}} \cdot S_{\text{dist}} + w_{\text{corridor}} \cdot S_{\text{overlap}} + w_{\text{course}} \cdot S_{\text{cog}} + w_{\text{speed}} \cdot S_{\text{sog}} \Big) \cdot S_{\text{time}} \cdot w_{\text{prior}} \times 100$$

### Sub-Score Formulations:

1. **Spatial Proximity to Hindcast Centerline ($S_{\text{dist}} \in [0.0, 1.0]$):**
   Measures distance at the Closest Point of Approach (CPA) normalized by the 95% search radius $\sigma_k$ at that specific historical hour:
   $$d_{\text{norm}} = \frac{d_{\text{CPA}}}{\max(0.50, \sigma_k)}$$
   $$S_{\text{dist}} = \exp\left( -0.5 \cdot d_{\text{norm}}^2 \right)$$
   * If vessel passes through the center of the slick: $d_{\text{norm}} \approx 0 \implies S_{\text{dist}} \approx 1.0$.
   * If vessel passes at the 95% ellipse boundary ($d = 2\sigma$): $d_{\text{norm}} = 2 \implies S_{\text{dist}} = \exp(-2) \approx 0.135$.
   * If vessel is far outside ($d > 3\sigma$): $S_{\text{dist}} \to 0$.

2. **Corridor Overlap & Dwell Fraction ($S_{\text{overlap}} \in [0.0, 1.0]$):**
   Measures what fraction of the vessel's trajectory points occurred inside the time-varying 95% uncertainty cone:
   $$S_{\text{overlap}} = \frac{N_{\text{inside\_cone}}}{N_{\text{total\_in\_window}}}$$

3. **Track Course Alignment ($S_{\text{cog}} \in [0.0, 1.0]$):**
   Illegal operational discharges (tank washing / bilge dumping) form linear trails parallel to the ship's course:
   $$S_{\text{cog}} = \left| \cos\left( \text{COG}_v(t^*) - \phi_{\text{slick}} \right) \right|$$
   * $\phi_{\text{slick}}$ is the major orientation angle of the Model 1 slick polygon or hindcast advection corridor.

4. **Speed Over Ground Underway Plausibility ($S_{\text{sog}} \in [0.0, 1.0]$):**
   MARPOL Annex I operational bilge/slop discharges are legally defined and mechanically executed only while the ship is en route at cruising speed:
   $$S_{\text{sog}} = \begin{cases}
   1.00 & \text{if } 8.0 \le \text{SOG} \le 18.0 \text{ knots (Standard cruising discharge underway)} \\
   0.65 & \text{if } 4.0 \le \text{SOG} < 8.0 \text{ or } 18.0 < \text{SOG} \le 24.0 \text{ knots} \\
   0.20 & \text{if } 0.5 \le \text{SOG} < 4.0 \text{ knots (Slow steaming / maneuvering)} \\
   0.05 & \text{if } \text{SOG} < 0.5 \text{ knots (Anchored or moored)}
   \end{cases}$$

5. **Temporal Synchronization Penalty ($S_{\text{time}} \in [0.0, 1.0]$):**
   Penalizes vessel tracks where the closest approach occurred during a large unobserved gap ($\Delta t_{\text{gap}} > 60\text{ min}$):
   $$S_{\text{time}} = \exp\left( - \frac{\Delta t_{\text{gap\_at\_cpa}}}{120.0} \right)$$

6. **Vessel Risk Prior ($w_{\text{prior}} \in [0.30, 1.00]$):**
   Empirical MARPOL risk weighting based on cargo capacity and discharge history:
   * Crude Oil Tanker / Product Tanker: $1.00$
   * Chemical Tanker: $0.90$
   * Container Ship / Bulk Cargo: $0.75$
   * Offshore Supply / Tug: $0.60$
   * Commercial Fishing: $0.50$
   * Passenger Ship / Yacht: $0.30$
   * Unknown / Unidentified: $0.65$

### Recommended Default Feature Weights:
* **$w_{\text{spatial}} = 0.50$** (Spatial proximity dominates)
* **$w_{\text{corridor}} = 0.20$** (Dwell time inside corridor)
* **$w_{\text{course}} = 0.15$** (Directional alignment with trail)
* **$w_{\text{speed}} = 0.15$** (Underway operational speed)
* *(Sum of baseline weights $= 1.00$)*

### Graceful Degradation for Missing Fields:
If optional fields (such as `cog` or `vessel_type`) are missing from the AIS feed, their weights are automatically redistributed proportionally across the remaining available features so vessels are never artificially penalized for provider data limitations.

---

## 10. Decoupled Data Confidence Model

A critical architectural distinction is established between **Attribution Score** and **Data Confidence**:
* A vessel may achieve an Attribution Score of $85\%$ simply because its single recorded ping coincided with the corridor. However, if that vessel has only 1 ping in 48 hours, the **Data Confidence** is `LOW`.
* Conversely, a vessel with 500 continuous pings passing $8\text{ km}$ outside the cone receives an Attribution Score of $10\%$ with a Data Confidence of `HIGH` (exonerated with high certainty).

### Confidence Metric:
$$\text{Confidence Score} = \Big( 0.40 \cdot C_{\text{density}} + 0.30 \cdot C_{\text{continuity}} + 0.30 \cdot C_{\text{static}} \Big) \times 100$$
Where:
* $C_{\text{density}} = \min(1.0, N_{\text{pings}} / 20)$
* $C_{\text{continuity}} = 1.0 - (\text{Max Gap Hours} / 48.0)$
* $C_{\text{static}} = 1.0$ if IMO, name, and vessel type are verified; $0.5$ if only MMSI is known.

### Confidence Tier Thresholds:
* **`HIGH CONFIDENCE` ($\ge 75\%$):** Dense reporting, continuous track coverage, verified vessel identity.
* **`MEDIUM CONFIDENCE` ($45\text{--}74\%$):** Moderate reporting frequency with minor interpolation gaps.
* **`LOW CONFIDENCE` ($< 45\%$):** Sparse pings, large tracking voids, or unverified ship type.

---

## 11. Candidate Output Schema (`CandidateVesselResult`)

The correlation engine produces a structured result package for each candidate vessel:

```json
{
  "mmsi": "419001122",
  "vessel_name": "MT Arabian Pioneer",
  "imo": "9312345",
  "vessel_type": "Crude Oil Tanker",
  "attribution_rank": 1,
  "attribution_category": "Strong Candidate",
  "attribution_score": 92.4,
  "data_confidence": "HIGH",
  "metrics": {
    "min_cpa_km": 0.85,
    "time_of_cpa": "2026-09-02T01:30:00Z",
    "hours_before_detection": 3.0,
    "hindcast_search_radius_km": 3.82,
    "is_inside_search_cone": true,
    "corridor_overlap_fraction": 0.83,
    "mean_sog_knots": 12.4,
    "course_alignment_deg": 8.2,
    "max_ais_gap_hours": 0.45,
    "suspicious_gap_detected": false
  },
  "sub_scores": {
    "spatial_proximity": 0.975,
    "corridor_dwell": 0.830,
    "course_alignment": 0.990,
    "speed_plausibility": 1.000,
    "vessel_risk_prior": 1.000
  },
  "evidence_summary": "Crude Oil Tanker MT Arabian Pioneer crossed the reconstructed spill corridor 3.0h prior to satellite detection at cruising speed (12.4 kts) with a CPA of 0.85 km inside the 95% confidence corridor. Track course was aligned within 8.2° of the slick elongation axis with continuous high-density AIS reporting."
}
```

---

## 12. Multiple-Candidate Handling & Attribution Categories

OceanTrace **does not artificially force a single guilty culprit**. Depending on traffic density and maritime corridor intersections, the system outputs one of four descriptive attribution categories:

| Attribution Score Range | Category Classification | Forensic Interpretation |
| :---: | :---: | :--- |
| **$75.0\text{--}100.0\%$** | **Strong Candidate** | High spatiotemporal coincidence within the 1-sigma core, cruising underway speed, and favorable track alignment. Priority for port state control inspection. |
| **$45.0\text{--}74.9\%$** | **Moderate Candidate** | Vessel navigated near or through the outer corridor bounds ($1\sigma\text{--}2\sigma$), but with course divergence, lower risk vessel type, or minor timing mismatches. |
| **$15.0\text{--}44.9\%$** | **Weak Candidate** | Peripheral proximity ($2\sigma\text{--}3\sigma$); unlikely primary source but within broader regional traffic envelope. |
| **$< 15.0\%$** | **Insufficient Evidence / Exonerated** | Vessel track remains outside the 95% dispersion corridor throughout the 48-hour investigation window. |

---

## 13. Offline & Historical Demonstration Strategy

To ensure dependable, repeatable live demonstrations for SIH evaluators without risking API rate limits, WebSocket drops, or offshore coverage voids:

### Directory Structure: `data/ais_scenarios/`
Each scenario is stored as a self-contained JSON/SQLite bundle with an explicit provenance manifest:

```json
{
  "scenario_id": "bombay_high_offloading_01",
  "data_provenance": "REAL_AIS_RECENTERED",
  "is_synthetic": false,
  "description": "Authentic crude tanker transit off Mumbai High North platform with 8 background cargo vessels",
  "bounding_box": [19.10, 19.65, 71.00, 71.60],
  "start_time": "2026-09-01T00:00:00Z",
  "end_time": "2026-09-02T12:00:00Z",
  "vessel_count": 9,
  "incident_metadata": {
    "simulated_spill_scene_id": "S1A_IW_GRDH_BOMBAY_HIGH_SCENARIO",
    "primary_suspect_mmsi": "419001122"
  }
}
```

* **Strict Truth Labeling:** Scenarios are explicitly tagged as `REAL_AIS_RECENTERED` or `SYNTHETIC_AIS`. The system never misrepresents synthetic tracks as live satellite intelligence.

---

## 14. Existing Code Migration Plan (`ml/ais_correlation.py`)

The prototype implementation in [`ml/ais_correlation.py`](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/ml/ais_correlation.py) provides an initial proof-of-concept. The architecture reorganizes and upgrades it as follows:

| Component in `ml/ais_correlation.py` | Architecture Disposition | Rationale |
| :--- | :--- | :--- |
| `VESSEL_TYPE_PRIORS` dict | **RETAIN & EXPAND** | Move to `ml/ais_types.py`; add IMO numerical code mappings. |
| `interpolate_vessel_position_at_time()` | **REFACTOR** | Move to `ml/ais_interpolation.py`; add maximum gap thresholds ($60\text{ min}$) and unobserved flags. |
| `CandidateVesselTrack` dataclass | **DEPRECATE & REPLACE** | Replace with canonical `VesselTrack` and `AISPosition` in `ml/ais_types.py`. |
| `VesselAttributionScore` dataclass | **REPLACE** | Replace with `CandidateVesselResult` supporting sub-scores, confidence, and text explanation. |
| `AISAttributionEngine` | **REFACTOR** | Modularize into `AISCorrelationEngine` and `VesselAttributionScorer`. |

---

## 15. Proposed Repository File Structure

Integrating cleanly into the existing OceanTrace codebase:

```text
ml/
├── __init__.py
├── models.py                     # [FROZEN] Model 1 DeepLabV3+ MultiTask
├── dataset.py                    # [FROZEN] Model 1 Dataset utilities
├── polygonize.py                 # Geospatial Conversion (Mask -> SpillDetection)
├── drift_types.py                # Model 2 Drift Types
├── environmental_provider.py     # Model 2 Hydrodynamic Providers
├── drift_engine.py               # Model 2 Lagrangian Physics Engine
├── forecast.py                   # Model 2 Forward Forecast
├── hindcast.py                   # Model 2 Backward Hindcast
│
├── ais_types.py                  # [NEW] Canonical AIS types & query contracts
├── ais_provider.py               # [NEW] Abstract base provider & registry
├── ais_store.py                  # [NEW] Local SQLite rolling buffer manager
├── ais_interpolation.py          # [NEW] Geodesic interpolation & gap analysis
├── ais_correlation.py            # [REFACTORED] Spatiotemporal corridor matching
├── vessel_attribution.py         # [NEW] Multi-factor scoring & evidence synthesis
│
└── providers/
    ├── __init__.py
    ├── aisstream_provider.py     # [NEW] Live WebSocket client for AISStream.io
    ├── historical_provider.py    # [NEW] Local SQLite/JSON/CSV file provider
    └── synthetic_provider.py     # [NEW] Unit-test synthetic track generator

tests/
├── test_model2_drift.py          # [EXISTING] Model 2 tests
├── test_model2_validation.py     # [EXISTING] Model 2 validation tests
├── test_ais_types.py             # [NEW] AIS validation tests
├── test_ais_store.py             # [NEW] SQLite buffer tests
├── test_ais_interpolation.py     # [NEW] Track interpolation & gap tests
├── test_ais_correlation.py       # [NEW] Corridor matching tests
└── test_vessel_attribution.py    # [NEW] Multi-criteria scoring & confidence tests
```

---

## 16. Phased Implementation Roadmap

* **Phase A: Canonical AIS Types & Provider Abstraction**
  * Implement `ml/ais_types.py` and `ml/ais_provider.py`.
  * Unit tests for MMSI validation, coordinate bounds, and query schema.
* **Phase B: Historical & Synthetic Providers**
  * Implement `ml/providers/synthetic_provider.py` and `ml/providers/historical_provider.py`.
  * Create `data/ais_scenarios/` with Bombay High demonstration benchmarks.
* **Phase C: Track Interpolation & Corridor Correlation Engine**
  * Implement `ml/ais_interpolation.py` and refactor `ml/ais_correlation.py`.
  * Verify time-indexed CPA calculations against dynamic Model 2 hindcast ellipses.
* **Phase D: Multi-Factor Attribution Scoring & Evidence Generation**
  * Implement `ml/vessel_attribution.py` with decoupled Attribution Score and Data Confidence.
  * Unit tests for weight redistribution and missing field tolerance.
* **Phase E: Live AISStream WebSocket Provider & Local Rolling Store**
  * Implement `ml/ais_store.py` (SQLite) and `ml/providers/aisstream_provider.py`.
  * Add automatic reconnection and rolling 72h purge maintenance.
* **Phase F: End-to-End Integration & Benchmark**
  * Execute full pipeline integration test: `Sentinel-1 -> Model 1 -> Model 2 -> AIS Ingestion -> Attribution Ranking -> Report JSON`.
  * Verify runtime and memory performance.

---

## 17. Scientific Honesty & Risk Matrix

| Risk / Limitation | Impact | Architectural Mitigation |
| :--- | :--- | :--- |
| **Incomplete Offshore AIS Coverage** | High-seas spills like Bombay High may lack real-time terrestrial VHF AIS pings. | Architecture is provider-agnostic. Supports pre-packaged historical scenarios for offshore cases, with live AISStream.io for coastal traffic. |
| **AIS Gaps Misinterpreted as Guilt** | Unjustly accusing vessels that suffered antenna shadowing or atmospheric ducting. | AIS gaps are strictly treated as an unobserved state and data-confidence penalty, never as an indicator of guilt. |
| **Legal Admissibility Constraints** | Attribution scores mistaken for proof of an illegal oil discharge. | Outputs are explicitly classified as "Forensic Correlation Scores" based on physical trajectory coincidence, generating technical investigative leads for port authorities. |
| **WebSocket Stream Rate Limits / Drops** | Real-time connection severed during live evaluation. | Automatic exponential backoff reconnection, local SQLite ping persistence, and fallback to local scenario benchmarks. |

---

## 18. Architectural Review & Next Steps

This architecture delivers a **production-clean, scientifically honest, and hackathon-feasible** AIS intelligence engine. It directly fulfills the attribution mandate of **SIH26143** while preserving strict modular isolation from Model 1 and Model 2.

**STOPPED.** Awaiting user approval of `.ai/AIS_ARCHITECTURE.md` before proceeding to Phase A implementation.

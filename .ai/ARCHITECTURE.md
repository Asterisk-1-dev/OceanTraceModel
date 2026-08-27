# OceanTrace — Revised System Architecture Specification

## 1. Architectural Synthesis & Product Evaluation

This document defines the comprehensive system architecture for **SIH26143**, synthesizing:
1. The **Teammate Core Architecture Proposal** (Spill Detection, OpenDrift, AIS attribution, FastAPI, React UX baseline).
2. The **Researcher Findings** in [RESEARCH_REPORT_SAR_DATASETS.md](file:///c:/Users/user/OneDrive/Desktop/SIH/OceanTrace-main/.ai/RESEARCH_REPORT_SAR_DATASETS.md).
3. The **Product & UX Recommendations** (Slick geometry/age, explainable scoring, funnel filtering, hash chains, repeat-offender lookup, response readiness).

### Core Architectural Principle
**Primary Directive**: Deliver an end-to-end, scientifically grounded, fully functional oil-spill detection and vessel attribution platform powered by **our own trained machine learning model**. Infrastructure complexity, distributed queues, database scaling, and premature optimizations are strictly phased into higher tiers.

---

## 2. Classification of Product & UX Recommendations

| Feature Recommendation | Classification | Rationale & Architectural Impact |
| :--- | :---: | :--- |
| **1. Visible Slick Age & Geometry** | **TIER 1 (MVP REQUIRED)** | Essential for spill characterization and drift initialization. Directly computed from polygon contour moments ($km^2$, major/minor axes, orientation) and hindcast temporal offset $\Delta t$. Already present in `Report.jsx` baseline. |
| **2. Explainable Vessel Scoring** | **TIER 1 (MVP REQUIRED)** | Core requirement of SIH26143 attribution. Deconstructs composite score ($0\text{--}100\%$) into explicit sub-scores ($S_{\text{prox}}, S_{\text{time}}, S_{\text{dark}}, S_{\text{anom}}, S_{\text{type}}$) to provide transparent, defensible evidence. |
| **3. Traffic Filtering Funnel** | **TIER 1 (MVP REQUIRED)** | Visualizes the algorithmic filtering progression: Total AOI Traffic ($N \approx 250$) $\rightarrow$ Spatial/Temporal Envelope ($N=17$) $\rightarrow$ Anomaly Candidates ($N=5$) $\rightarrow$ Top Ranked Suspects ($N=3$). Supported by stat cards in `App.jsx`. |
| **4. Tamper-Evident Report Hash Chain** | **TIER 2 (ADVANCED FEATURE)** | Computes SHA-256 linear hash chain across pipeline artifacts (Raw Scene $\rightarrow$ Mask $\rightarrow$ Drift Envelope $\rightarrow$ Ranked Attribution $\rightarrow$ Forensic JSON/PDF) for data integrity and provenance tracking. |
| **5. Repeat-Offender Analysis** | **TIER 2 (ADVANCED FEATURE)** | Cross-references candidate MMSIs with historical incident logs to flag repeat environmental offenders. Implemented as a clean lookup table. |
| **6. Response-Readiness ETA** | **TIER 2 (ADVANCED FEATURE)** | Calculates distance and transit ETA for nearest coast guard response vessels/stations based on projected drift vector. |

---

## 3. Three-Tier Architectural Hierarchy

```
┌────────────────────────────────────────────────────────────────────────┐
│                        TIER 1: SIH MVP (REQUIRED)                      │
│  • Trained PyTorch SAR Segmentation Model (U-Net / DeepLabV3+)        │
│  • SAR Normalization, Saliency Thresholding, GeoJSON Polygonizer       │
│  • Slick Age, Area (km²), Estimated Volume (m³), and Morphology        │
│  • Vectorized Lagrangian Drift Engine (Hindcast Origin & 36h Forecast) │
│  • Spatio-Temporal AIS Correlator & Dark-Period Gap Detector           │
│  • Transparent Traffic Filtering Funnel (Total -> Envelope -> Suspects)│
│  • Explainable 5-Factor Vessel Responsibility Scoring Breakdown        │
│  • Lightweight In-Process FastAPI Backend (REST & GeoJSON Endpoints)   │
│  • Approved React 19 Frontend Baseline (Full UI & Scrubber Integration)│
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ (Extends to)
┌────────────────────────────────────▼───────────────────────────────────┐
│                     TIER 2: ADVANCED CAPABILITIES                      │
│  • Sentinel-2 Optical False-Positive Cross-Validation (Cloud-Gated)    │
│  • SAR Hard-Target Point Reflector Ship Detection                     │
│  • Cryptographic Provenance Hash Chain for Forensic Reports            │
│  • Repeat-Offender Historical Anomaly Lookup Table                     │
│  • Marine Response Asset Routing & Transit ETA Calculations           │
│  • Comprehensive Oil Weathering Model (Evaporation / Emulsification)  │
│  • PostgreSQL + PostGIS Persistent Incident & AIS Database             │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ (Scales to)
┌────────────────────────────────────▼───────────────────────────────────┐
│                     TIER 3: OPTIMIZATIONS & SCALE                      │
│  • ONNX Runtime / TensorRT Inference Acceleration                      │
│  • Celery + Redis Distributed Ingestion Worker Pool                    │
│  • TimescaleDB Spatio-Temporal Hypertables for Live Global AIS Feeds   │
│  • Full Copernicus CDSE Automated Satellite Polling Daemon             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Detailed Tier 1 (MVP) Dataflow & Specifications

```
[ Sentinel-1 SAR Dual-Pol GRD ]      [ Hydrodynamic & Wind Grids ]     [ Regional AIS Trajectories ]
 (Zenodo / Kaggle SOS Corpus)             (CMEMS / ERA5 NetCDF)               (GeoJSON / CSV)
              │                                    │                                 │
              ▼                                    ▼                                 │
┌───────────────────────────┐            ┌───────────────────┐                       │
│  1. SAR ML VISION ENGINE  │            │  2. DRIFT ENGINE  │                       │
│  • VV/VH normalization    │            │  • Lagrangian     │                       │
│  • DeepLabV3+ / U-Net     │──(Slick)──▶│    particle model │                       │
│  • Slick Area & Geometry  │            │  • Hindcasting    │                       │
│  • GeoJSON Polygonizer    │            │    origin (t0,p0) │                       │
└───────────────────────────┘            └─────────┬─────────┘                       │
                                                   │ (Spill Origin Envelope)         │
                                                   ▼                                 ▼
                                         ┌───────────────────────────────────────────────┐
                                         │  3. AIS CORRELATION & ATTRIBUTION ENGINE      │
                                         │  • Traffic Funnel: Total -> Envelope -> Ranked│
                                         │  • AIS dark-period / gap detector (>15 min)  │
                                         │  • Kinematic course/speed anomaly analyzer   │
                                         │  • Explainable 5-Factor Score (0-100%)       │
                                         └───────────────────────┬───────────────────────┘
                                                                 │
                                                                 ▼
                                         ┌───────────────────────────────────────────────┐
                                         │  4. FASTAPI SERVICE LAYER (IN-PROCESS ASYNC)  │
                                         │  • /api/incidents  • /api/layers/geojson      │
                                         │  • /api/vessels    • /api/drift/timeline      │
                                         └───────────────────────┬───────────────────────┘
                                                                 │
                                                                 ▼
                                         ┌───────────────────────────────────────────────┐
                                         │  5. APPROVED REACT 19 FRONTEND BASELINE       │
                                         │  • Operations Dashboard (App.jsx)             │
                                         │  • Forensic Incident Report (Report.jsx)      │
                                         └───────────────────────────────────────────────┘
```

---

## 5. Algorithmic Formulations

### 5.1 Slick Geometry & Estimated Age
* **Area ($A$)**: Computed from contour integration over calibrated pixel spacing:
  $$A = N_{\text{pixels}} \times (\text{pixel\_res}_x \times \text{pixel\_res}_y) \times 10^{-6} \text{ km}^2$$
* **Estimated Volume ($V$)**: Derived from standard Bonn Agreement oil appearance thickness matrix ($d_{\text{slick}} \approx 0.1\text{--}1.0\ \mu\text{m}$ for sheen, $1.0\text{--}50\ \mu\text{m}$ for true dark oil):
  $$V = A \times \bar{d}_{\text{slick}} \quad (\text{m}^3)$$
* **Slick Age ($t_{\text{age}}$)**: Calculated as the backward drift integration time required to regress particle dispersion back to a minimal point-source radius ($r_0 \le 500\text{ m}$):
  $$t_{\text{age}} = t_{\text{detect}} - t_0$$

### 5.2 Traffic Filtering Funnel Data Model
The backend API exposes explicit funnel progression metrics:
```json
{
  "traffic_funnel": {
    "total_aoi_traffic": 248,
    "vessels_in_envelope": 17,
    "anomaly_candidates": 5,
    "high_priority_suspects": 3
  }
}
```

### 5.3 Explainable 5-Factor Vessel Scoring
Every candidate vessel returns both a composite culpability score $S \in [0, 100]$ and its component breakdown:
$$S = 0.30 S_{\text{prox}} + 0.25 S_{\text{time}} + 0.25 S_{\text{dark}} + 0.10 S_{\text{anom}} + 0.10 S_{\text{type}}$$

```json
{
  "name": "SEA ORCHID",
  "mmsi": "477981200",
  "flag": "SG",
  "total_score": 92,
  "score_breakdown": {
    "proximity_score": 96.5,
    "temporal_score": 94.0,
    "dark_period_penalty": 100.0,
    "kinematic_anomaly_penalty": 75.0,
    "vessel_type_risk": 90.0
  },
  "anomaly_detail": "18 min AIS dark period during origin transit",
  "dark_period_confirmed": true
}
```

---

## 6. Tier 2 Specifications: Cryptographic Provenance Hash Chain

To ensure verifiable report integrity, Tier 2 produces a lightweight SHA-256 hash chain:
1. $H_1 = \text{SHA256}(\text{Raw SAR GeoTIFF bytes})$
2. $H_2 = \text{SHA256}(H_1 + \text{Segmentation Binary Mask bytes})$
3. $H_3 = \text{SHA256}(H_2 + \text{Lagrangian Particles Hindcast JSON})$
4. $H_4 = \text{SHA256}(H_3 + \text{AIS Candidate Attribution Array})$
5. $H_{\text{final}} = \text{SHA256}(H_4 + \text{Report Metadata Timestamp})$

This root hash is embedded into the forensic report header (`Report.jsx`) and exported GeoJSON properties, guaranteeing tamper-evident provenance without requiring third-party blockchain dependencies.

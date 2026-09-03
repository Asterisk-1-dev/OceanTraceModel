# OceanTrace — Maritime Oil Spill Detection, Drift Tracking & Vessel Attribution

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10--3.12](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![React: 19](https://img.shields.io/badge/Frontend-React%2019%20%2B%20Vite-61dafb)](https://react.dev/)
[![Tests: Passing](https://img.shields.io/badge/Tests-78%2F78%20Passing-brightgreen)](tests/)

**OceanTrace** (AquaVigil) is an end-to-end maritime intelligence platform engineered to detect oil slicks in satellite Synthetic Aperture Radar (SAR) imagery, model their historical ocean drift, correlate trajectories against Automatic Identification System (AIS) vessel traffic, and provide decision-ready attribution evidence for maritime authorities.

---

## Problem Statement

> **Smart India Hackathon (SIH26143):**  
> *"Leveraging satellite imagery to determine Oil spills at sea along with AIS data correlations to identify vessel responsible for the spill."*

Satellite SAR imagery captures high-resolution snapshots of marine oil slicks across vast swaths, but cannot identify the discharging vessel because slicks drift and disperse over hours or days before satellite overpasses. Simultaneously, AIS vessel logs record movements but provide no physical proof of discharge. 

Matching instantaneous slick detections directly against simultaneous vessel locations causes severe errors: innocent passing vessels are falsely implicated, while the true culprit—having steamed 20–80 km away—escapes detection. OceanTrace bridges this spatiotemporal gap by coupling deep learning SAR segmentation with time-reversed hydrodynamic drift physics to identify the candidate release corridor and rank intersecting vessels.

---

## System Architecture

```text
Sentinel-1 SAR Scene (VV / VH dB)
              ↓
SAR Preprocessing & Dual-Pol Normalization [B, 3, 512, 512]
              ↓
Model 1: DeepLabV3+ Multi-Task with scSE Gating (Frozen V6 E21 Checkpoint)
              ↓
Geospatial Adapter (Raster Contours → WGS84 GeoJSON Polygon + Moments Centroid)
              ↓
Model 2: P-LDHE Lagrangian Drift Engine (250 Particles, RK2 Midpoint Scheme)
              ↓
48-Hour Backward Hindcast Corridor (95% Search Covariance Ellipses)
              ↓
AIS Ingestion & Normalization (AISStream WebSocket / Historical File / Synthetic)
              ↓
Spatiotemporal Correlation & Dynamic CPA Intersection
              ↓
Explainable Attribution Engine (Proximity, Overlap, Heading, Speed)
              ↓
FastAPI Backend (REST & GeoJSON) → React 19 Operations Dashboard & Forensic Report
```

---

## Model 1 — Oil Spill Detection

Model 1 is a multi-task deep learning architecture based on DeepLabV3+ with Spatial and Channel Squeeze-and-Excitation (`scSE`) context gating.

* **Input:** 3-channel radiometrically normalized floating-point tensor `[B, 3, 512, 512]`:
  1. `VV_norm`: Calibrated vertical co-polarization backscatter in dB.
  2. `VH_norm`: Calibrated cross-polarization backscatter in dB.
  3. `(VV - VH)_norm`: Polarization difference channel distinguishing capillary wave dampening from volumetric depolarization.
* **Multi-Task Heads:**
  * **Segmentation Head:** Pixel-level binary oil slick probability mask trained via Focal Tversky Loss ($\alpha=0.60, \beta=0.40, \gamma=1.33$).
  * **Auxiliary Classification Head:** Predicts scene-level category (**Clean Sea**, **Oil Spill**, or **Lookalike**) to penalize false alarms on low-wind calm sea patches.
* **Production Checkpoint:** [`V6_E21_FINAL/oceantrace_v6_E21_final.pth`](V6_E21_FINAL/oceantrace_v6_E21_final.pth)  
* **Checkpoint SHA-256:**  
  `4de684fa85daf05fa9d5b330103b4e3536450ccaa9d65724f889225c13eef635`

---

## Model 2 — Drift & Hindcast

The **P-LDHE** (Physics-Informed Lagrangian Drift & Hindcast Engine) models slick transport and diffusion across the ocean surface:

$$\vec{U}_{\text{drift}} = \vec{U}_{\text{current}} + \alpha_{\text{wind}} \mathbf{R}(\theta_{\text{Coriolis}}) \vec{U}_{\text{wind}} + \vec{U}_{\text{diffusion}}'$$

* **Surface Ocean Current ($\vec{U}_{\text{current}}$):** Background advection from ocean current velocity fields.
* **Windage ($\alpha_{\text{wind}}$):** Aerodynamic momentum transfer calibrated to **3.0%** of 10 m surface wind velocity.
* **Coriolis Deflection ($\mathbf{R}(\theta_{\text{Coriolis}})$):** Empirical Ekman deflection rotating the windage vector to the right of the wind in the Northern Hemisphere ($0^\circ\text{--}15^\circ$).
* **Stochastic Diffusion ($\vec{U}_{\text{diffusion}}'$):** Wiener random-walk parameterization representing sub-mesoscale horizontal turbulent dispersion ($K_h \approx 10\text{--}50\text{ m}^2/\text{s}$).
* **Numerical Solver:** Vectorized 2nd-order Runge-Kutta (RK2 Midpoint) scheme integrating 250 Lagrangian particles over a **48-hour backward hindcast** (origin reconstruction) and **48-hour forward forecast** (coastal containment).
* **Uncertainty Ellipses:** Computes 95% spatial covariance search ellipses at each 6-hour step to define the candidate release corridor.

---

## AIS Correlation & Attribution

The AIS subsystem ingests regional vessel traffic, normalizes trajectories, and correlates them against the time-varying hindcast corridor.

* **Provider Abstraction:** Supports live streaming via `AISStreamProvider` (WebSocket), historical voyage logs via `HistoricalFileProvider` (CSV/SQLite), and offline validation via `SyntheticAISProvider`.
* **Track Preprocessing:** Great-circle geodesic interpolation across gaps $\le 60\text{ minutes}$. Gaps $>60\text{ minutes}$ are explicitly marked as unobserved (no speculative dead-reckoning).
* **Attribution Evidence Scoring ($0\text{--}100$):**
  $$S_{\text{attr}} = 100 \times \left( 0.50 \cdot S_{\text{dist}} + 0.20 \cdot S_{\text{overlap}} + 0.15 \cdot S_{\text{cog}} + 0.15 \cdot S_{\text{sog}} \right)$$
  * **Spatial Proximity ($50\%$):** Gaussian decay of distance to closest hindcast centroid relative to covariance radius.
  * **Corridor Overlap ($20\%$):** Dwell fraction within the 95% dispersion envelope.
  * **Heading Alignment ($15\%$):** Angular alignment between vessel course and slick drift axis.
  * **Speed Consistency ($15\%$):** Assessment of operational speed vs. low-speed discharge profiles.
* **Confidence Categories:** Ranked as `STRONG` ($\ge 75$), `MODERATE` ($50\text{--}74$), `WEAK` ($20\text{--}49$), or `INSUFFICIENT_EVIDENCE` ($<20$), paired with a decoupled data quality rating (`HIGH`, `MEDIUM`, `LOW`).

> [!IMPORTANT]
> The Attribution Score is a physical evidence ranking metric for investigative decision support. It is **not** a legal determination or mathematical probability of guilt.

---

## Backend & Frontend

* **FastAPI Backend (`backend/app/`):** Exposes modular REST endpoints for active incidents, slick geometries, ranked candidate vessels, and GeoJSON exports. In-memory indexing is backed by local SQLite storage (`ais_local.db`) with automated rolling TTL purging.
* **React 19 Frontend (`src/`):** Single-page operations dashboard with an interactive Leaflet map canvas, satellite SAR/slick/current layer toggles, 48-hour timeline playback scrubber, priority suspect queue, and an exportable forensic intelligence brief (`/report`).

---

## Datasets & Evaluation

Models were trained and evaluated using the open-access Zenodo Sentinel-1 SAR Oil Spill Benchmark:

| Dataset Partition | Zenodo Record | Contents | Role in Project |
|---|---|---|---|
| **Part I** | [8346860](https://zenodo.org/records/8346860) | 1,200 Verified Oil Spill scenes (2048×2048×2 VV/VH dB) | Training & Validation |
| **Part II** | [8253899](https://zenodo.org/records/8253899) | 685 Clean Sea + 685 Lookalike scenes | Hard-Negative Training |
| **Part III** | [13761290](https://zenodo.org/records/13761290) | 150 Oil + 150 Clean Sea + 150 Lookalike (450 scenes) | **Untouched Held-Out Test Set** |

---

## Verified Results

The frozen V6 E21 checkpoint was evaluated across all 450 scenes of the untouched official Part III dataset at operational threshold $\tau = 0.28$ (zero Test-Time Augmentation):

| Metric | Part III Held-Out Benchmark | Significance |
|---|:---:|---|
| **Oil Global IoU** | **76.91%** | Overall pixel intersection-over-union across oil scenes |
| **Oil Macro IoU** | **78.68%** | Mean per-scene IoU |
| **Oil Dice Coefficient** | **86.95%** | Harmonic mean of precision and recall |
| **Oil Recall** | **83.48%** | Detection sensitivity on genuine oil slicks |
| **Oil Precision** | **90.72%** | Delineation accuracy on segmented slick boundaries |
| **Clean Sea False Positives** | **14 / 150** | Specificity of 90.7% on clean ocean imagery |
| **Lookalike False Positives** | **94 / 150** | Lookalike rejection rate (improved over earlier models) |

### System Performance
* **Automated Unit & Integration Tests:** **78 / 78 passing** (`python -m unittest discover tests`).
* **End-to-End Latency:** **~1.12 seconds on standard CPU** (`benchmark_end_to_end.py`), covering SAR segmentation, geospatial conversion, 48h particle tracking, and AIS corridor attribution.

---

## Offline Demo

To guarantee deterministic, reproducible evaluations without external network dependencies, OceanTrace includes an air-gapped test fixture:
* **Synthetic SAR Patch:** A 512×512 dual-polarization radar raster patch with an embedded slick signature centered in the Arabian Sea off Bombay High ($19.417^\circ\text{N}, 71.333^\circ\text{E}$).
* **Synthetic Vessel Scenario:** Three simulated candidate vessels:
  1. `SYNTHETIC TANKER ALPHA` (MMSI: 999000001): Intersects release corridor at CPA $0.12\text{ km}$ ($S_{\text{attr}} = 72$, `MODERATE`).
  2. `SYNTHETIC BULKER DELTA` (MMSI: 999000004): Distant transit at CPA $8.19\text{ km}$ ($S_{\text{attr}} = 34$, `WEAK`).
  3. `SYNTHETIC CARGO BRAVO` (MMSI: 999000002): Unrelated transit at CPA $30.57\text{ km}$ ($S_{\text{attr}} = 0$, `INSUFFICIENT_EVIDENCE`).

*Note: Simulated vessel identities and AIS tracks are strictly synthetic test artifacts.*

---

## Running Locally

### Prerequisites
* Python 3.10 – 3.12
* Node.js (v18+) and npm

### 1. Start FastAPI Backend
```powershell
$env:PYTHONPATH="backend;."
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
* API Health Check: `http://127.0.0.1:8000/health`
* Swagger Documentation: `http://127.0.0.1:8000/docs`

### 2. Start React Frontend
```powershell
npm.cmd run dev -- --host localhost --port 5173
```
* Operations Dashboard: `http://localhost:5173/`
* Forensic Incident Brief: `http://localhost:5173/report`

### 3. Run Test Suite & Benchmarks
```powershell
# Run full automated regression suite (78 tests)
python -m unittest discover tests

# Run end-to-end CPU performance benchmark
python benchmark_end_to_end.py

# Build frontend production bundle
npm.cmd run build
```

---

## Dynamic Operational Workflow

```text
Copernicus CDSE Catalog Polling → Sentinel-1 GRD Download → Dual-Pol Normalization
                                        ↓
                         Model 1 Multi-Task Inference
                                        ↓
                 ┌──────────────────────┴──────────────────────┐
                 ▼ (Score < 0.28)                              ▼ (Score ≥ 0.28)
           Scene Archived                            Incident Initialized
                                                               ↓
                                             WGS84 Vector Polygonization
                                                               ↓
                                             Model 2 P-LDHE Drift Hindcast
                                                               ↓
                                             Spatio-Temporal AIS Extraction
                                                               ↓
                                             Multi-Factor Vessel Ranking
                                                               ↓
                                             Interactive Alert & Brief Export
```

* **Implemented & Validated:** Local end-to-end pipeline execution, neural network inference, geospatial vector extraction, P-LDHE hindcast/forecast, AIS correlation, multi-factor attribution, and live dashboard rendering.
* **Intended Production Architecture:** Automated cloud daemon for continuous Copernicus Sentinel-1 catalog polling and real-time CMEMS / NOAA GFS API fetching.

---

## Limitations

* **Satellite Revisit Interval:** Constrained by Sentinel-1 constellation orbital tracks (1 to 6 days revisit), precluding real-time continuous video monitoring.
* **Oceanic Lookalikes:** Severe low-wind calm patches ($<3\text{ m/s}$) and biogenic surface films dampen capillary waves and can cause false detections.
* **AIS Non-Compliance:** Discharging vessels may disable transponders ("dark ships") or spoof positions.
* **Empirical Drift Approximations:** Standard 3.0% windage factor and Coriolis deflection are empirical approximations subject to localized wind-wave conditions.

---

## Future Work

1. **Copernicus CDSE Cloud Polling:** Deploy automated polling daemons to trigger the pipeline immediately upon new Sentinel-1 acquisitions.
2. **Sentinel-2 Multispectral Fusion:** Optical cloud-gated cross-validation (NDVI / Infrared) to filter biogenic algal blooms.
3. **Live MetOcean APIs:** Direct integration with Copernicus Marine Service (CMEMS) and NOAA GFS for real-time hydrodynamic fields.
4. **Database Migration:** Scale local SQLite storage to PostgreSQL + PostGIS with TimescaleDB hypertables for global fleet coverage.

---

## Project Structure

```text
OceanTrace/
├── backend/app/                     # FastAPI backend (main, routers, schemas, services)
├── ml/                              # Core ML, physics drift & AIS modules
│   ├── models.py                    # Multi-Task scSE DeepLabV3+ architecture
│   ├── geospatial_adapter.py        # Raster-to-WGS84 vector polygonizer
│   ├── drift_engine.py              # Lagrangian drift advection engine
│   ├── hindcast.py / forecast.py    # 48h backward hindcast & forward forecast
│   ├── ais_corridor.py              # Spatiotemporal AIS corridor correlator
│   ├── vessel_attribution.py        # Multi-factor attribution scoring engine
│   └── oceantrace_pipeline.py       # Master pipeline orchestrator
├── src/                             # React 19 + Vite frontend (App.jsx, Report.jsx, api/)
├── tests/                           # 78 automated Python unit and integration tests
├── V6_E21_FINAL/                    # Authoritative frozen model checkpoint
├── data/ais_scenarios/              # Deterministic offline AIS scenario data
├── benchmark_end_to_end.py          # End-to-end CPU performance benchmark
├── package.json / vite.config.js    # Node package & build configuration
└── README.md                        # Master project documentation
```

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details. Dataset benchmarks are governed by their respective [Zenodo CC-BY 4.0 licenses](https://zenodo.org/records/8346860).

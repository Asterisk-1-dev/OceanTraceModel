# OceanTrace Model 2 — Drift & Prediction Architecture

**Project:** OceanTrace — Maritime Oil Spill Intelligence  
**Problem Statement:** SIH26143 — Leveraging satellite imagery to determine oil spills at sea along with AIS data correlations to identify the vessel responsible for the spill.  
**Component:** Model 2 (Oil Spill Drift, Hindcasting, Forecasting, and Attribution Engine)  
**Status:** Architecture Specification & Engineering Blueprint (Pre-Implementation)

---

## 1. Objective

OceanTrace Model 2 takes a validated, geographic oil spill detection produced by Model 1 (`SARDeepLabV3Plus_MultiTask_scSE`, V6 E21) and models its dynamic transport across the ocean surface over time.

### Core Functions:
1. **Backward Hindcasting (Forensic Source Estimation):** Advects the spill backward in time from detection timestamp $t_0$ to $t_0 - 48\text{h}$ to reconstruct the candidate release path and generate an expanding spatio-temporal search cone for AIS vessel track intersection.
2. **Forward Forecasting (Containment & Trajectory Prediction):** Advects the spill forward in time from $t_0$ to $t_0 + 48\text{h}$ to predict future slick spread, center-of-mass trajectory, and shoreline encounter risk.
3. **Probabilistic Uncertainty Modeling:** Represents physical advection uncertainty (windage variance, current model resolution limits, sub-mesoscale turbulence) using a multi-particle Lagrangian cloud and time-expanding covariance ellipses.
4. **AIS Correlation Handover:** Emits a standardized, machine-readable JSON/GeoJSON trajectory package consumed directly by the AIS responsibility scoring module.

---

## 2. Model 1 → Model 2 Interface

Model 2 operates strictly in the **geographic coordinate space (WGS84 / EPSG:4326)**. It is decoupled from raw Sentinel-1 GeoTIFF rasters, affine matrices, and bounding boxes via an intermediate geospatial conversion layer (`ml/polygonize.py`).

```text
┌────────────────────────────────────────────────────────┐
│  SENTINEL-1 SAR GeoTIFF (VV, VH)                      │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│  MODEL 1 (V6 E21 — Frozen Multi-Task DeepLabV3+)       │
│  - Output: 2D Probability Mask [H, W] in [0.0, 1.0]   │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│  GEOSPATIAL CONVERSION LAYER (ml/polygonize.py)        │
│  - Raster -> Vector Polygon Extraction (Contour/Geo)   │
│  - Calculates: Area, Centroid, Bounding GeoJSON       │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ emits SpillDetection Schema
┌────────────────────────────────────────────────────────┐
│  MODEL 2 (Lagrangian Drift & Hindcast Engine)          │
│  - Consumes: Geographic Coordinates & Timestamp Only   │
│  - Produces: Hindcast Search Cone + Forward Forecast  │
└────────────────────────────────────────────────────────┘
```

### Input Contract: `SpillDetection` Schema
```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class SpillDetection:
    detection_id: str                      # Unique UUID for incident
    source_scene_id: str                   # Sentinel-1 Scene ID (e.g. S1A_IW_GRDH_...)
    detection_timestamp: str               # ISO8601 UTC (e.g. "2026-09-02T04:30:00Z")
    centroid_lat: float                    # Latitude in decimal degrees [-90.0, 90.0]
    centroid_lon: float                    # Longitude in decimal degrees [-180.0, 180.0]
    area_km2: float                        # Estimated slick area in km²
    confidence: float                      # Model 1 segmentation confidence score [0.0, 1.0]
    scene_classification: str              # "Oil Spill" (from Model 1 auxiliary head)
    polygon_geojson: Dict[str, Any]        # GeoJSON Polygon / MultiPolygon geometry
    estimated_volume_m3: Optional[float] = None
```

---

## 3. Inputs & Environmental Forcing Specification

To advect Lagrangian particles across the sea surface, Model 2 requires temporal forcing fields covering the bounding region $\mathcal{B} = [\text{lat} \pm 1.5^\circ, \text{lon} \pm 1.5^\circ]$ over time window $[t_0 - 48\text{h}, t_0 + 48\text{h}]$.

### Required Environmental Variables:
1. **Surface Ocean Currents ($0\text{--}1\text{m}$ depth):**
   * $u_{\text{curr}}(\text{lat}, \text{lon}, t)$: Eastward ocean current velocity ($\text{m/s}$).
   * $v_{\text{curr}}(\text{lat}, \text{lon}, t)$: Northward ocean current velocity ($\text{m/s}$).
2. **$10\text{m}$ Sea Surface Wind:**
   * $u_{\text{wind}}(\text{lat}, \text{lon}, t)$: $10\text{m}$ Eastward wind component ($\text{m/s}$).
   * $v_{\text{wind}}(\text{lat}, \text{lon}, t)$: $10\text{m}$ Northward wind component ($\text{m/s}$).

### Modular Provider Architecture:
To ensure the system is not hard-coded to a single API, environmental data is accessed through an abstract interface:

```python
from abc import ABC, abstractmethod

class EnvironmentalProvider(ABC):
    @abstractmethod
    def fetch_forcing_grid(self, bounds: dict, start_time: str, end_time: str) -> dict:
        """Fetches and caches spatiotemporal grids of u_curr, v_curr, u_wind, v_wind."""
        pass

    @abstractmethod
    def get_velocity(self, lat: float, lon: float, timestamp: float) -> tuple[float, float, float, float]:
        """Returns bilinearly/temporally interpolated (u_curr, v_curr, u_wind, v_wind) at (lat, lon, t)."""
        pass
```

* **Primary Production Provider:** `OpenMeteoMarineProvider` (Real-time & Reanalysis REST API combining Copernicus Marine / Mercator currents and ERA5 / GFS winds; zero authentication required, sub-second response).
* **High-Precision Provider:** `CopernicusCMEMSProvider` (Native NetCDF/xarray subsetting via `copernicusmarine` client).
* **Fallback Climatology Provider:** `SyntheticClimatologyProvider` (Offline fallback using regional seasonal current vectors + default windage when external network is unavailable).

---

## 4. Drift Physics & Governing Equations

The drift of an oil slick on the ocean surface is modeled using the standard vector superposition law established by NOAA GNOME and EMSA CleanSeaNet:

$$\vec{V}_{\text{particle}}(\vec{x}, t) = \vec{U}_{\text{current}}(\vec{x}, t) + \alpha_{\text{wind}} \cdot \mathbf{R}(\theta_{\text{deflection}}) \vec{U}_{\text{wind}}(\vec{x}, t) + \vec{U}'_{\text{turb}}$$

### 1. Ocean Current Advection ($\vec{U}_{\text{current}}$)
Direct 100% Eulerian advection by surface layer ($0\text{--}1\text{m}$) current velocities:
$$\vec{U}_{\text{current}} = (u_{\text{curr}}, v_{\text{curr}})$$

### 2. Direct Wind Drag / Windage ($\alpha_{\text{wind}}$ & Coriolis Deflection)
* **Windage Factor ($\alpha_{\text{wind}}$):** Standard empirical marine value $\alpha_{\text{wind}} = 0.030$ ($3.0\%$ of $10\text{m}$ wind speed).
* **Windage Variability:** Modeled across particles as a uniform physical ensemble:
  $$\alpha_i \sim \mathcal{U}(0.025, 0.035)$$
* **Coriolis Deflection Angle ($\theta_{\text{deflection}}$):** In deep open water, wind-driven surface shear deflects relative to the wind direction due to Earth's rotation (Ekman drift):
  $$\theta_{\text{deflection}} = \begin{cases} +10^\circ \text{ (to the right)} & \text{if } \text{lat} > 5^\circ\text{N} \\ -10^\circ \text{ (to the left)} & \text{if } \text{lat} < -5^\circ\text{S} \\ 0^\circ & \text{if } |\text{lat}| \le 5^\circ \text{ (Equatorial zone)} \end{cases}$$
  The rotation matrix is:
  $$\mathbf{R}(\theta) = \begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix}$$

### 3. Turbulent Random Walk Diffusion ($\vec{U}'_{\text{turb}}$)
Horizontal turbulent diffusion is represented as an isotropic Wiener process:
$$\delta \vec{x}_{\text{diff}} = \sqrt{2 K_h \Delta t} \cdot \vec{\mathcal{N}}(0, \mathbf{I})$$
where $K_h = 5.0\text{ m}^2/\text{s}$ is the horizontal turbulent diffusion coefficient.

### 4. Numerical Time Integrator: 2nd-Order Runge-Kutta (RK2 / Midpoint)
* *Integrator Decision:* While 4th-order Runge-Kutta (RK4) was initially proposed, **2nd-Order Runge-Kutta (RK2 / Midpoint)** is selected as optimal.
* *Justification:* Environmental forcing data is typically resolved hourly on an $8\text{--}25\text{ km}$ grid. 4th-order integration provides mathematically fictitious sub-millimeter precision over low-frequency interpolated fields while doubling API interpolation overhead. RK2 provides second-order convergence with $\Delta t = 15\text{ minutes}$ ($900\text{s}$), achieving sub-meter physical accuracy at $2\times$ faster execution speed ($<0.05\text{s}$ for $N=250$ particles).

---

## 5. Particle Seeding Model

Rather than collapsing the entire slick into a single mathematical point, Model 2 initializes **$N = 250$ Lagrangian particles** sampled directly from the geometry of the Model 1 polygon:

```text
Spill Polygon GeoJSON (Model 1)
         │
         ▼
[ Bounding Box Filtering ]
         │
         ▼
[ Uniform Random Rejection Sampling inside Polygon ]
         │
         ▼
250 Dispersed Particles (lat_i, lon_i, weight_i = 1/N, alpha_i ~ U(0.025, 0.035))
```

* **Why Polygon Seeding Matters:** An elongated $15\text{km}$ slick drifting in a shear zone experiences differential current velocities across its length. Seeding across the true polygon captures realistic elongation, rotation, and shear dispersion.

---

## 6. Forward Forecasting ($t_0 \to t_0 + 48\text{h}$)

### Integration Protocol:
1. Step forward in positive time steps $\Delta t = +900\text{s}$ ($15\text{ min}$).
2. Sample environmental velocities $\vec{u}_{\text{curr}}, \vec{u}_{\text{wind}}$ at particle position $(x_i, y_i, t)$.
3. Update particle coordinate:
   $$\vec{x}_i(t + \Delta t) = \vec{x}_i(t) + \vec{V}_{\text{particle}}(\vec{x}_i, t) \cdot \Delta t + \delta \vec{x}_{\text{diff}}$$
4. Record summary states at target reporting intervals ($+6\text{h}, +12\text{h}, +24\text{h}, +36\text{h}, +48\text{h}$).

### Forward Outputs:
* Time-stamped centroid $\vec{X}_{\text{fore}}(t_k) = \frac{1}{N} \sum_{i=1}^N \vec{x}_i(t_k)$.
* Coordinate array of all $N=250$ particles representing the dispersing slick envelope.
* 95% Confidence Ellipse (Major Axis, Minor Axis, Orientation Angle $\phi$).

---

## 7. Backward Hindcasting ($t_0 \to t_0 - 48\text{h}$) — Forensic Engine

The backward hindcast reconstructs where the slick was located prior to satellite detection.

```text
                   BACKWARD HINDCAST SEARCH CONE OVER TIME
  
  [ t = t0 - 24h ]             [ t = t0 - 12h ]             [ t = t0 (Detection) ]
  Uncertainty: ±7.5 km         Uncertainty: ±3.8 km         Uncertainty: ±0.5 km
  
      (  ·  ·  )                   ( · · )                     (·)
    (  ·  ·  ·  )                 ( · · · )                 [Slick Mask]
      (  ·  ·  )                   ( · · )                     (·)
          ▲                           ▲                         ▲
          │                           │                         │
          └───────────────────────────┴─────────────────────────┘
                       Reverse Advection Path (dt < 0)
```

### Physical Time-Inversion Formulation:
For backward integration, the velocity vector is inverted:
$$\frac{d\vec{x}_{\text{hind}}}{dt} = -\left[ \vec{U}_{\text{current}}(\vec{x}, t) + \alpha_i \cdot \mathbf{R}(\theta) \vec{U}_{\text{wind}}(\vec{x}, t) \right]$$

### The Irreversibility of Diffusion:
* **Critical Physical Rule:** Stochastic diffusion cannot be "subtracted" backward in time (negative diffusion is mathematically unstable and non-physical).
* **Correct Mathematical Formulation:** Advect particles backward deterministically along inverse velocity streamlines while **expanding the spatial uncertainty envelope** forward in uncertainty time $\tau = |t - t_0|$:
  $$\sigma^2_{\text{hind}}(\tau) = \sigma^2_0 + \left(\sigma_{\text{env}}^2 + \sigma_\alpha^2 |\vec{u}_{\text{wind}}|^2\right) \tau^2 + 2 K_h \tau$$
* This guarantees that as we search further into the past, the **confidence search cone widens rigorously**, preventing false exoneration of culprit vessels.

---

## 8. AIS Integration & Forensic Attribution Protocol

Model 2 produces a time-indexed sequence of candidate source regions. The downstream AIS module queries vessel tracks in this spacetime volume to rank suspect vessels.

```text
========================================================================================
                      AIS SPATIOTEMPORAL ATTRIBUTION PIPELINE
========================================================================================

  [ Model 2 Hindcast Output: (lat_k, lon_k, radius_k, timestamp_k) ]
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  1. AIS Bounding Box Query                                  │
  │     Filter vessel positions within spatial envelope         │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  2. Interpolate Vessel Positions at Hindcast Timestamps     │
  │     For each vessel v, calculate position X_v(t_k)          │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  3. Compute Closest Point of Approach (CPA)                 │
  │     d_CPA = min || X_v(t_k) - X_hind(t_k) ||                │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  4. Calculate Forensic Responsibility Score                 │
  │     R_v = S_distance * S_time * W_vessel_type               │
  └─────────────────────────────────────────────────────────────┘
```

### Responsibility Scoring Formula:
$$R_v = \underbrace{\exp\left(-\frac{d_{\text{CPA}}^2}{2 \sigma_{\text{hind}}^2(t_{\text{CPA}})}\right)}_{\text{Spatial Proximity within Cone}} \cdot \underbrace{\exp\left(-\frac{|\Delta t_{\text{match}}|^2}{2 \tau_{\text{tol}}^2}\right)}_{\text{Temporal Coincidence}} \cdot \underbrace{w_{\text{type}}}_{\text{Vessel Prior}}$$

Where:
* $d_{\text{CPA}}$ is the minimum distance (km) between vessel track and hindcast centroid.
* $\sigma_{\text{hind}}(t_{\text{CPA}})$ is the hindcast search cone radius at that exact historical timestamp.
* $w_{\text{type}} \in [0.5, 1.0]$: Tankers/Cargo = $1.0$, Fishing/Tugs = $0.7$, Passenger/Yachts = $0.5$.

---

## 9. Complete Output Schema (`DriftResult`)

Model 2 returns a standard Python dictionary / Pydantic dataclass easily serialized to JSON and GeoJSON:

```json
{
  "incident_id": "spill_20260902_001",
  "detection": {
    "scene_id": "S1A_IW_GRDH_1SDV_20260902T043000",
    "timestamp": "2026-09-02T04:30:00Z",
    "centroid": [18.9240, 72.8310],
    "area_km2": 4.82,
    "confidence": 0.942
  },
  "hindcast": {
    "horizon_hours": 48,
    "steps": [
      {
        "hours_offset": -6.0,
        "timestamp": "2026-09-01T22:30:00Z",
        "centroid": [18.8812, 72.7951],
        "uncertainty_radius_km": 2.15,
        "search_ellipse": {
          "semi_major_km": 2.45,
          "semi_minor_km": 1.85,
          "angle_deg": 42.0
        },
        "particle_count": 250
      },
      {
        "hours_offset": -12.0,
        "timestamp": "2026-09-01T16:30:00Z",
        "centroid": [18.8395, 72.7420],
        "uncertainty_radius_km": 4.30,
        "search_ellipse": {
          "semi_major_km": 4.90,
          "semi_minor_km": 3.70,
          "angle_deg": 44.5
        },
        "particle_count": 250
      }
    ],
    "search_cone_geojson": {
      "type": "Feature",
      "geometry": { "type": "Polygon", "coordinates": [[...]] },
      "properties": { "description": "48h Backward Source Probability Cone" }
    }
  },
  "forecast": {
    "horizon_hours": 48,
    "steps": [
      {
        "hours_offset": 12.0,
        "timestamp": "2026-09-02T16:30:00Z",
        "centroid": [18.9850, 72.8950],
        "uncertainty_radius_km": 3.10
      }
    ],
    "trajectory_geojson": {
      "type": "Feature",
      "geometry": { "type": "LineString", "coordinates": [[72.8310, 18.9240], [72.8950, 18.9850]] },
      "properties": { "description": "48h Forward Drift Forecast" }
    }
  },
  "metadata": {
    "environmental_provider": "Open-Meteo Marine / Copernicus ERA5",
    "advection_engine": "Lagrangian RK2 Midpoint",
    "particle_count": 250,
    "execution_time_seconds": 0.42
  }
}
```

---

## 10. Error & Edge-Case Handling

| Edge Case | Failure Mode | Architectural Mitigation |
| :--- | :--- | :--- |
| **API Timeout / Network Loss** | External weather/marine API fails to respond within $3\text{s}$. | Built-in timeout (3.0s) triggering automatic fallback to `SyntheticClimatologyProvider` (regional seasonal current + 3% wind default), with an explicit warning flag in metadata. |
| **Spill Near Coastline / Island** | Particles drift onto terrestrial land mass. | Simple land-mask polygon intersection test: if particle enters land polygon, particle velocity is set to $0$ (beached / shoreline retention). |
| **Invalid / Zero Mask Input** | Model 1 returns no detected pixels. | Geospatial layer intercepts empty masks and returns `detected: false` without triggering Model 2 execution. |
| **Tiny (<0.01 km²) or Huge (>100 km²) Spill** | Numerical instability in particle sampling. | Dynamic particle clamp: for $A < 0.1\text{ km}^2$, collapse initial seed to centroid $+ \text{Gaussian jitter}$; for $A > 50\text{ km}^2$, sample $N=500$ particles to ensure adequate density. |
| **Antimeridian Crossing (Lon ±180°)** | Longitude wrap-around discontinuities. | Angular modular arithmetic on longitude steps: `(lon + 180) % 360 - 180`. |

---

## 11. Proposed Project File Structure

Integrating cleanly with the existing codebase:

```text
ml/
├── __init__.py
├── models.py                     # Frozen Model 1 (DeepLabV3+ MultiTask)
├── dataset.py                    # Model 1 Dataset utilities
├── evaluate.py                   # Model 1 Evaluation utilities
├── polygonize.py                 # Geospatial Conversion Layer (Mask -> SpillDetection)
│
├── drift_types.py                # Data classes: SpillDetection, DriftResult, Particle, Ellipse
├── environmental_provider.py     # Base EnvironmentalProvider + OpenMeteoMarineProvider
├── drift_engine.py               # Core Lagrangian RK2 Advection & Seeder Engine
├── hindcast.py                   # Backward search cone & trajectory builder
├── forecast.py                   # Forward prediction & shoreline encounter builder
└── ais_correlation.py            # AIS track ingestion, CPA calculation, & Responsibility Scorer
```

---

## 12. Computational Feasibility Analysis

* **Hardware Target:** Intel Core i5 12th Gen, RTX 3050 4GB / standard Colab CPU.
* **Algorithm:** Vectorized NumPy operations for all $N=250$ particles simultaneously.
* **Step Count:** $48\text{ hours} \times 4\text{ steps/hour} = 192\text{ integration steps}$.
* **Benchmark Estimation:**
  * Environmental Grid Fetch (REST API): $\approx 0.80\text{--}1.50\text{ seconds}$
  * Particle Sampling ($N=250$): $\approx 0.005\text{ seconds}$
  * 192-step RK2 Integration (NumPy Vectorized): $\mathbf{\approx 0.035\text{ seconds}}$
  * AIS Track Interpolation & CPA Scoring ($100$ vessels): $\mathbf{\approx 0.015\text{ seconds}}$
  * **Total Incident Processing Time:** $\mathbf{< 1.6\text{ seconds}}$
* **Memory Footprint:** $<15\text{ MB}$ RAM (zero GPU memory required).

---

## 13. Validation Strategy

Validation will be partitioned into two distinct, rigorous tiers:

### Tier 1: Physical Advection Validation (Drifter Ground Truth)
* **Dataset:** NOAA Global Drifter Program (GDP) surface drifter tracks ($15\text{m}$ drogued/undrogued buoys).
* **Metric:** **Separation Distance Error (SDE)** after 24h and 48h:
  $$\text{SDE}(t) = \|\vec{X}_{\text{pred}}(t) - \vec{X}_{\text{buoy}}(t)\|$$
* **Acceptance Criterion:** Median $\text{SDE}_{24\text{h}} < 15\text{ km}$ under standard ERA5 forcing.

### Tier 2: End-to-End AIS Forensic Validation (Synthetic & Historical Scenarios)
* **Validation Benchmark:** Construct 5 verified maritime incident test benches (known vessel path + artificial release point + simulated forward drift to satellite detection $t_0$).
* **Metric:** **Attribution Recall @ Top-1 / Top-3**:
  * Does the true culprit vessel achieve the #1 ranked Responsibility Score $R_v$?
  * Is the true release point contained inside the 95% Hindcast Search Cone?
* **Acceptance Criterion:** $100\%$ containment of true release coordinates within estimated $\Sigma_{\text{hindcast}}(t_{\text{release}})$.

---

## 14. Summary & Architecture Decision

### Final Decision:
Deploy a **Physics-Informed Lagrangian Drift & Hindcast Engine (P-LDHE)** driven by dynamic marine environmental forcing (Open-Meteo / Copernicus), 2nd-order Runge-Kutta advection, empirical 3.0% windage with Coriolis deflection, and probabilistic search cone generation for AIS forensic attribution.

This architecture is **scientifically robust, computationally instantaneous, requires zero unavailable multi-frame training sets**, and perfectly completes Problem Statement **SIH26143**.

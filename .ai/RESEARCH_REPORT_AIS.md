# OceanTrace AIS Data Layer: Comprehensive Research Report

**Project:** OceanTrace — Maritime Oil Spill Intelligence  
**Problem Statement:** SIH26143 — Leveraging satellite imagery to determine oil spills at sea along with AIS data correlations to identify the vessel responsible for the spill.  
**Component:** AIS Data Acquisition, Geospatial Corridor Matching, and Forensic Vessel Responsibility Attribution  
**Author:** OceanTrace Researcher  
**Date:** 2026-09-03  
**Status:** COMPLETE RESEARCH REPORT (Pre-Architecture & Pre-Implementation)

---

## 1. Executive Summary

OceanTrace combines Sentinel-1 SAR oil-spill detection (**Model 1: V6 E21 DeepLabV3+**) with a hydrodynamic Lagrangian drift and reverse advection engine (**Model 2: P-LDHE**) to predict forward slick movement and backward forensic source corridors. To satisfy **SIH26143**, the downstream attribution module must cross-reference this spacetime search cone against Automatic Identification System (AIS) vessel tracking data to identify and rank candidate discharge vessels.

### Key Research Findings:
1. **AIS Data Availability Landscape:**
   * **Global Real-Time AIS:** Commercial providers (MarineTraffic/Kpler, Spire Maritime, exactEarth) charge enterprise pricing ($1,000s/month) for live S-AIS (Satellite AIS). However, **AISStream.io** provides a **100% free, developer-friendly WebSocket stream** of real-time terrestrial and satellite-relayed AIS data filtered by bounding box.
   * **Historical AIS Data:** NOAA Marine Cadastre provides massive free open-access historical AIS CSVs, but is geographically constrained to US EEZ waters. For global/Indian waters, open raw historical AIS is heavily commercialized. **Global Fishing Watch (GFW)** offers free BigQuery public access, but focuses on fishing vessels and aggregates raw pings.
   * **India / Bombay High Feasibility:** India's DGLL (Directorate General of Lighthouses and Lightships) operates 87 National AIS (NAIS) coastal shore stations. While government feeds are restricted, Bombay High ($19.42^\circ\text{N}, 71.33^\circ\text{E}$, $\sim 160\text{ km}$ offshore) is monitored via coastal/offshore platform relays and satellite AIS, accessible in real-time via AISStream.io and community aggregators.
2. **Attribution Methodology:**
   * Forensic attribution requires a **deterministic, multi-criteria mathematical scoring engine** rather than an ungrounded black-box ML model. The score integrates:
     * Spatial Proximity to Hindcast Corridor ($d_{\text{CPA}}$ relative to dynamic $\sigma_{\text{hindcast}}(t)$)
     * Temporal Alignment ($\Delta t_{\text{match}}$)
     * Track Directional Consistency (vessel COG vs. spill elongation axis)
     * Vessel Prior Risk Weight ($w_{\text{type}}$: Crude Tankers > Chemical Tankers > Cargo > Fishing)
     * Operational Speed Anomaly (tanker slop/bilge discharge typically occurs underway at $8\text{--}15\text{ knots}$, whereas anchoring or maneuvering indicates differing risk profiles).
3. **Recommended Demonstration Strategy for SIH Prototype:**
   * **Primary Live Source:** `AISStreamProvider` via `AISStream.io` WebSocket client (free API key, bounding box filtering).
   * **Demo & Historical Ground Truth:** Pre-packaged, verified scenario SQLite/JSON datasets featuring authentic tanker trajectories paired with synthetic discharge incident scenarios off the Mumbai coast / Bombay High.
   * **Test Source:** Deterministic synthetic track generator in `tests/test_ais_correlation.py`.

---

## 2. AIS Data Source Comparison Matrix

| Provider / Source | Access Model | Real-Time | Historical | Geographic Coverage | Temporal Resolution | Auth / Cost | Suitability for OceanTrace Prototype |
| :--- | :--- | :---: | :---: | :--- | :--- | :--- | :--- |
| **AISStream.io** | WebSocket Stream | **Yes** | No (Stream only) | Global (Coastal + High Traffic Offshore) | Real-time (seconds) | Free API Key required | **HIGHEST (Primary Live Source)** — Zero cost, bounding box subscription, standard JSON schema. |
| **AISHub.net** | REST / Raw UDP | **Yes** | No | Global Community Network | 1–5 min | Free "give-to-get" (Requires running receiver) | **LOW** — Demands operating an active physical AIS receiver. |
| **Datalastic / VesselAPI** | REST API | **Yes** | Limited (Past 7–30 days) | Global (Terrestrial + S-AIS) | Variable | Freemium (Free tier ~50–100 calls/mo) | **MODERATE (Backup Live REST)** — Strict request caps, good for one-off ping checks. |
| **NOAA Marine Cadastre** | Direct CSV Download | No | **Yes (2009–2024)** | US EEZ Only | 1 min downsampled | Free Open Access (No auth) | **HIGH (Physics / Algorithm Validation)** — Large, verified raw data, but wrong geography. |
| **Global Fishing Watch (GFW)** | Google BigQuery | No | **Yes (2012–2024)** | Global | Daily / Hourly Aggregates | Free Google Cloud tier (1TB/mo query) | **LOW/MODERATE** — Primarily fishing vessels, pre-aggregated, non-tanker focus. |
| **EMODnet Physics (Europe)** | WFS / REST API | Near Real-Time | **Yes** | European Waters | 6 min | Free (EU login) | **LOW** — Geographically limited to European regional seas. |
| **India DGLL NAIS Network** | Government Internal | Yes | Yes | Indian Coastline & Island Territories | High | Restricted (Navy/Coast Guard/DG Shipping) | **RESTRICTED** — Authoritative Indian source; public access unavailable. |
| **Spire / MarineTraffic (Kpler)** | REST API / S-AIS | Yes | Yes | Global (Full Satellite AIS) | Real-time (10–30s) | Enterprise ($1,000s/year) | **COMMERCIAL BENCHMARK ONLY** — Prohibitive for hackathon prototype. |

---

## 3. Required AIS Data Fields

AIS messages originate from transponders emitting maritime VHF messages (predominantly Message Types 1, 2, 3 for dynamic position reports, and Message Type 5 for static/voyage data).

### Minimum Required Schema:

| Field Name | Type | Mandatory? | Source Message | Description & OceanTrace Usage |
| :--- | :---: | :---: | :---: | :--- |
| **`mmsi`** | `str` (9 digits) | **MANDATORY** | Msg 1, 2, 3, 5 | Maritime Mobile Service Identity — Unique vessel identifier. |
| **`timestamp`** | `str` (ISO8601 UTC) | **MANDATORY** | Transponder / Gateway | Exact UTC timestamp of position ping. Required for temporal corridor matching. |
| **`latitude`** | `float` ($[-90, 90]$) | **MANDATORY** | Msg 1, 2, 3 | WGS84 decimal latitude degrees. |
| **`longitude`** | `float` ($[-180, 180]$) | **MANDATORY** | Msg 1, 2, 3 | WGS84 decimal longitude degrees. |
| **`sog`** | `float` (knots) | **MANDATORY** | Msg 1, 2, 3 | Speed Over Ground ($0.0\text{--}102.2\text{ knots}$). Verifies vessel underway status. |
| **`cog`** | `float` (degrees) | **MANDATORY** | Msg 1, 2, 3 | Course Over Ground ($0.0^\circ\text{--}359.9^\circ$). Tests directional alignment with slick trail. |
| **`vessel_name`** | `str` | OPTIONAL | Msg 5 | Ship name for operator UI display. |
| **`vessel_type`** | `str` / `int` | OPTIONAL | Msg 5 | IMO ship type code (e.g., Tanker=80-89, Cargo=70-79). Governs discharge prior weight. |
| **`imo`** | `str` (7 digits) | OPTIONAL | Msg 5 | International Maritime Organization number (permanent ship hull ID). |
| **`nav_status`** | `int` | OPTIONAL | Msg 1, 2, 3 | Navigational status (0=Under way using engine, 1=At anchor, 5=Moored). |
| **`heading`** | `float` (degrees) | OPTIONAL | Msg 1, 2, 3 | True heading ($0\text{--}359^\circ$, 511=not available). |

---

## 4. OceanTrace Model 2 → AIS Interface Mapping

Model 2 provides a continuous spacetime hindcast package:
$$\mathcal{H} = \left\{ \big(t_k, \vec{x}_k, \mathbf{\Sigma}_k, r_k\big) \;\Big|\; k = 0, \dots, K; \; t_0 \ge t_k \ge t_0 - 48\text{h} \right\}$$
where:
* $t_k$ is the historical timestamp step.
* $\vec{x}_k = (\text{lat}_k, \text{lon}_k)$ is the hindcast slick centroid.
* $\mathbf{\Sigma}_k$ is the 2D covariance search ellipse (semi-major axis $a_k$, semi-minor axis $b_k$, orientation $\phi_k$).
* $r_k$ is the equivalent 95% search cone radius ($r_k \approx \sqrt{a_k b_k}$).

```text
========================================================================================
                      MODEL 2 TO AIS ATTRIBUTION PIPELINE
========================================================================================

  [ MODEL 2 HINDCAST CONE ]                     [ AIS VESSEL TRACK STORE ]
  Steps: t0, -6h, -12h, ..., -48h               Historical Tracks for All Vessels
  Centroids: x_hind(t_k)                        Track: { (t_v, lat_v, lon_v, sog_v, cog_v) }
  Search Radius: r_hind(t_k)
          │                                                  │
          │                                                  │
          ▼                                                  ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  1. SPATIOTEMPORAL BOUNDING BOX QUERY                                       │
  │     Query Window: Lat/Lon envelope of entire search cone over [t0-48h, t0]   │
  │     Returns: Set of N candidate vessels passing through region              │
  └──────────────────────────────────────┬──────────────────────────────────────┘
                                         │
                                         ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  2. TEMPORAL SYNCHRONIZATION & INTERPOLATION                                │
  │     For each vessel v and each hindcast timestamp t_k:                     │
  │     Linearly interpolate vessel position: X_v(t_k)                          │
  └──────────────────────────────────────┬──────────────────────────────────────┘
                                         │
                                         ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  3. CLOSEST POINT OF APPROACH (CPA) COMPUTATION                             │
  │     d_CPA(v) = min_k || X_v(t_k) - x_hind(t_k) ||                           │
  │     Find step k* yielding minimum spatial separation                        │
  └──────────────────────────────────────┬──────────────────────────────────────┘
                                         │
                                         ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  4. MULTI-CRITERIA FORENSIC RESPONSIBILITY SCORING                          │
  │     Compute: Spatial Gaussian Decay + Temporal Match + Directional          │
  │     Alignment + Speed Plausibility + Vessel Risk Prior                      │
  └──────────────────────────────────────┬──────────────────────────────────────┘
                                         │
                                         ▼
  [ RANKED CANDIDATE TABLE (MMSI, Vessel Name, CPA, Responsibility Score %) ]
```

---

## 5. Transparent Attribution Scoring Proposal

To ensure complete explainability for maritime authorities and port state control inspectors, we propose a **fully transparent, multi-factor attribution formulation**:

$$R_v = \Big( w_{\text{spatial}} \cdot S_{\text{dist}} + w_{\text{cog}} \cdot S_{\text{cog}} + w_{\text{sog}} \cdot S_{\text{sog}} \Big) \cdot S_{\text{time}} \cdot w_{\text{prior}} \times 100\%$$

### Component Formulations:

1. **Spatial Proximity Score ($S_{\text{dist}} \in [0.0, 1.0]$):**
   $$S_{\text{dist}} = \exp\left( -\frac{1}{2} \left(\frac{d_{\text{CPA}}}{\sigma_{\text{hind}}(t^*)}\right)^2 \right)$$
   * $d_{\text{CPA}}$ is the great-circle distance between interpolated vessel position and hindcast centroid at optimal step $t^*$.
   * $\sigma_{\text{hind}}(t^*)$ is the estimated 95% search radius at step $t^*$.
   * If vessel is inside the 1-sigma core, $S_{\text{dist}} \ge 0.60$; at the 2-sigma edge, $S_{\text{dist}} \approx 0.135$; beyond 3-sigma, $S_{\text{dist}} \to 0$.

2. **Course / Track Alignment Score ($S_{\text{cog}} \in [0.0, 1.0]$):**
   Spills from moving vessels form linear "trails" or elongated slicks aligned with vessel heading and prevailing drift.
   $$S_{\text{cog}} = \left| \cos\left( \text{COG}_v - \phi_{\text{trail}} \right) \right|$$
   * $\phi_{\text{trail}}$ is the orientation angle of the Model 1 polygon major axis or the hindcast advection corridor.
   * Vessels traveling parallel or anti-parallel to the slick elongation receive high alignment ($1.0$), while orthogonal cross-traffic receives low alignment ($0.0$).

3. **Speed Over Ground Plausibility Score ($S_{\text{sog}} \in [0.0, 1.0]$):**
   Illegal operational discharges (MARPOL Annex I violations, e.g., oily bilge discharge or tank washing) almost exclusively occur when vessels are en route at cruising speed:
   $$S_{\text{sog}} = \begin{cases} 
   1.0 & \text{if } 8.0 \le \text{SOG} \le 18.0 \text{ knots (Cruising discharge underway)} \\
   0.6 & \text{if } 4.0 \le \text{SOG} < 8.0 \text{ or } 18.0 < \text{SOG} \le 24.0 \text{ knots} \\
   0.2 & \text{if } 0.5 \le \text{SOG} < 4.0 \text{ knots (Maneuvering / slow steaming)} \\
   0.05 & \text{if } \text{SOG} < 0.5 \text{ knots (Anchored / moored — discharge unlikely unless catastrophic spill)}
   \end{cases}$$

4. **Temporal Synchronization Penalty ($S_{\text{time}} \in \{0.0, 1.0\}$):**
   * $S_{\text{time}} = 1.0$ if an authentic interpolated vessel ping exists within $\pm 45\text{ minutes}$ of the hindcast step $t^*$.
   * Decreases exponentially if the vessel has significant AIS ping gaps ($>2\text{ hours}$).

5. **Vessel Risk Prior ($w_{\text{prior}} \in [0.30, 1.00]$):**
   * Crude Oil Tankers / Product Tankers: $1.00$
   * Chemical / Liquid Bulk Carriers: $0.90$
   * Container Ships / General Cargo: $0.75$
   * Offshore Supply / Tugs: $0.60$
   * Fishing Vessels: $0.50$
   * Passenger Ships / Yachts: $0.30$
   * Unknown Vessel Type: $0.65$

### Recommended Weightings:
* $w_{\text{spatial}} = 0.55$
* $w_{\text{cog}} = 0.25$
* $w_{\text{sog}} = 0.20$

---

## 6. India / Bombay High Feasibility Analysis

### Geographic Characteristics:
* **Coordinates:** $19.4167^\circ\text{N}, 71.3333^\circ\text{E}$
* **Distance to Shore:** $\sim 160\text{ km}$ ($86\text{ nautical miles}$) West-Northwest of Mumbai, Maharashtra.
* **Environment:** Offshore oil extraction field operated by ONGC, characterized by intense platform supply vessel (PSV) traffic, high-density international tanker lanes linking the Persian Gulf to East Asia, and seasonal South-West monsoon winds.

### Real-World AIS Coverage Assessment:
1. **Terrestrial VHF AIS Limitations:**
   * Line-of-sight propagation for terrestrial VHF antennas (mounted at $30\text{--}50\text{m}$ elevation at Mumbai/Luhara Point lighthouses) has a practical radar horizon:
     $$D_{\text{horizon}} \approx 3.57 \left( \sqrt{h_{\text{station}}} + \sqrt{h_{\text{ship}}} \right) \approx 3.57 (\sqrt{45} + \sqrt{15}) \approx 37.8\text{ km} \approx 20.4\text{ NM}$$
   * Terrestrial coastal receivers located on the Mumbai mainland **cannot reliably receive direct VHF AIS pings at Bombay High ($160\text{ km}$ offshore)** due to Earth curvature.
2. **Offshore Platform Relays & Satellite AIS:**
   * Offshore production platforms at Bombay High (e.g., Mumbai High North, South) host internal radar and AIS repeater stations integrated into the Indian Coast Guard Coastal Surveillance Network (CSN Phase-II).
   * Free global aggregators like **AISStream.io** rely on a mix of coastal community receivers and volunteer vessel repeaters. In active tanker transit corridors off Mumbai, coverage is intermittent to moderate. Deep offshore coverage ($>50\text{ NM}$) is strictly reliant on Satellite-AIS (S-AIS).
3. **Feasibility Conclusion for OceanTrace Prototype:**
   * For live demonstration in high-seas regions like Bombay High, a prototype cannot rely solely on 24/7 uninterrupted free terrestrial AIS feeds without risking dropouts.
   * **Defensible Strategy:** The prototype must support **AISStream.io** for real-time coastal tracking ($<40\text{ NM}$) while providing a robust **Pre-Packaged Historical Cache / Scenario Injector** for offshore test cases like Bombay High.

---

## 7. Historical Demonstration Strategy

To ensure dependable demonstration during SIH hackathon evaluations without risking API downtime, rate limits, or offshore data voids:

### Strategy 1: The Pre-Packaged Incident Benchmark (Recommended)
* Extract authentic historical vessel traffic from open AIS datasets (such as NOAA Marine Cadastre or Danish Maritime Authority) and translate coordinate offsets to the Arabian Sea / Bombay High grid.
* Package 3 verified incident scenarios in local SQLite / JSON storage:
  * **Scenario 1 (Bombay High Offloading Incident):** 1 culprit crude tanker + 8 background cargo/fishing vessels passing through the 48h hindcast corridor.
  * **Scenario 2 (Gulf of Kutch Tanker Lane Transit):** High-density tanker lane with intersecting trajectories; tests multi-candidate ranking discrimination.
  * **Scenario 3 (Exoneration Case):** Detected slick where closest vessel passed 30 km outside the uncertainty cone; model correctly reports $0\%$ attribution.

### Strategy 2: Live AIS Stream Tap
* Integrate a background listener connecting to `wss://stream.aisstream.io/v0/stream`.
* Filter messages to the Mumbai Port / Jawaharlal Nehru Port Trust (JNPT) coastal bounding box:
  * Latitude: $[18.60^\circ\text{N}, 19.20^\circ\text{N}]$
  * Longitude: $[72.60^\circ\text{E}, 73.00^\circ\text{E}]$
* Demonstrates live streaming vessel ingestion, coordinate decoding, and real-time corridor monitoring.

---

## 8. Final Source Recommendations

1. **PRIMARY LIVE SOURCE:** **`AISStream.io` (WebSocket Stream API)**
   * *Rationale:* 100% free, developer-friendly, provides real-time JSON events with bounding-box spatial filtering, zero billing setup required.
2. **BACKUP LIVE SOURCE:** **`Datalastic` / `VesselAPI` (REST Freemium)**
   * *Rationale:* Provides standard HTTP GET snapshots of vessels within a radius when streaming WebSockets are constrained by local firewall environments.
3. **DEMO & BENCHMARK SOURCE:** **Local Scenario SQLite Database (`data/ais_scenarios/`)**
   * *Rationale:* Guaranteed deterministic evaluation for judges; zero internet latency; pre-verified tanker tracks with ground-truth discharge timestamps.
4. **SYNTHETIC UNIT TEST SOURCE:** **`SyntheticAISTrackGenerator` (Already implemented in `ml/ais_correlation.py`)**
   * *Rationale:* Fully offline, microsecond unit testing of CPA math and Gaussian scoring.

---

## 9. Key Questions for Architect & Next Steps

1. **Storage Choice:** Should candidate AIS tracks be stored in lightweight local SQLite files, or should the existing in-memory dictionary representation in `ml/ais_correlation.py` be retained for prototype simplicity?
2. **WebSocket Threading:** Does the application architecture support an asynchronous background listener daemon (e.g., `asyncio` / `websockets`) for continuous AISStream ingestion, or should ingestion be on-demand per incident?
3. **AIS Data Retention Policy:** What temporal retention window (e.g., past 72 hours) should be maintained for raw pings in the local database?

---

**STOPPED.** Research report complete. Awaiting user review.

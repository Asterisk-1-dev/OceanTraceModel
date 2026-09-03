# OceanTrace — Technical Issues, Risks & Mitigation Log

## Known Challenges & Risk Registry

### 1. SAR Lookalikes & False Positive Discrimination
* **Issue**: Low wind zones ($< 3\text{ m/s}$), natural biogenic slicks (organic films), grease ice, internal ocean waves, and rain cells create low-backscatter dark patches on SAR imagery that mimic mineral oil spills.
* **Risk**: High false alarm rates leading to wasted enforcement resources.
* **Mitigation Strategy**:
  - Integrate multi-channel feature extraction (texture analysis, Gray-Level Co-occurrence Matrix / GLCM, gradient analysis).
  - Train segmentation models on multi-class datasets (Oil Spill vs Lookalike vs Land vs Sea).
  - Cross-validate SAR detections with co-located ERA5 wind speed fields (reject detections in zero-wind calm zones).

### 2. AIS Dark Vessels & Intentional Transponder Shutdown
* **Issue**: Culprit vessels engaging in illicit bilge discharge or tank cleaning often deliberately power down their Class A/B AIS transponders prior to dumping.
* **Risk**: Candidate vessel list might omit the primary perpetrator if purely relying on continuous AIS track intersections.
* **Mitigation Strategy**:
  - Implement AIS gap detection / trajectory interpolation: flag vessels entering a dark zone before the incident and reappearing downstream.
  - Correlate SAR ship detection (bright hard-target point reflectors) with reported AIS positions to detect uncooperative / dark vessels directly from the satellite scene.

### 3. MetOcean Hydrodynamic Resolution & Latency
* **Issue**: Global ocean current models (HYCOM / CMEMS) may have coarse spatial resolution ($1/12^\circ \approx 8\text{--}9\text{ km}$) and daily temporal updates, missing fine-scale sub-mesoscale coastal eddies.
* **Risk**: Drift hindcasting trajectory error margins expand over long simulation time horizons ($> 48\text{ hours}$).
* **Mitigation Strategy**:
  - Implement Monte Carlo Lagrangian particle dispersion incorporating stochastic diffusion components to generate confidence ellipses rather than a single deterministic point.
  - Fuse surface wind drift (leeway coefficient typically $3\text{--}3.5\%$ with $0\text{--}20^\circ$ deflection angle) with surface current vectors.

### 4. Satellite Revisit Cadence & Latency
* **Issue**: Sentinel-1 SAR constellation revisit time over specific maritime corridors ranges from 6 to 12 days.
* **Risk**: Spills may disperse or weather significantly before the next satellite pass.
* **Mitigation Strategy**:
  - Support multi-sensor ingestion (Sentinel-1A/B, Sentinel-2 optical, Landsat-8/9, PlanetScope where available).
  - Model oil weathering (evaporation, emulsification, natural dispersion) based on API gravity and sea surface temperature to estimate age of slick at detection time.

# OceanTrace — Engineering Backlog & Task Breakdown

## Phase 1: Research, Datasets & Scientific Specifications
- [x] **TASK-RES-01**: Catalog benchmark satellite SAR oil spill datasets (e.g., Zenodo Sentinel-1 SAR Dataset, Kaggle SOS, CERTH-ITI evaluation) — *Completed in `.ai/RESEARCH_REPORT_SAR_DATASETS.md`*.
- [ ] **TASK-RES-02**: Research SAR preprocessing techniques (radiometric calibration, Lee/Refined-Lee speckle filtering, thermal noise removal, terrain correction, land masking).
- [ ] **TASK-RES-03**: Evaluate state-of-the-art semantic segmentation architectures for SAR oil spill detection (U-Net with ResNet/EfficientNet backbones, DeepLabV3+, SegFormer, Mask R-CNN).
- [ ] **TASK-RES-04**: Survey hydrodynamic ocean current & surface wind datasets (Copernicus Marine Service - CMEMS, NOAA HYCOM, ECMWF ERA5 reanalysis).
- [ ] **TASK-RES-05**: Review open-source marine drift simulation engines (OpenDrift / PyGNOME) and Lagrangian particle tracking physics (windage factor, leeway drift, Stokes drift, weathering/evaporation).
- [ ] **TASK-RES-06**: Survey AIS data sources, schemas (AIVDM/AIVDO, MarineCadastre, Spire/AISHub API formats), and trajectory reconstruction techniques.

---

## Phase 2: System Architecture, Data Contracts & Interfaces
- [x] **TASK-ARC-01**: Define data schemas and GeoJSON contracts for satellite scene metadata, detected slick polygons, and candidate vessel tracks — *Specified in `.ai/ARCHITECTURE.md`*.
- [x] **TASK-ARC-02**: Draft REST API specifications bridging the ML pipeline, drift engine, and the approved React frontend — *Specified in `.ai/ARCHITECTURE.md`*.
- [x] **TASK-ARC-03**: Create Architecture Decision Records (ADRs) for 3-tier system, model benchmarking, and lightweight backend — *ADR-001 through ADR-011 in `.ai/DECISIONS.md`*.
- [ ] **TASK-ARC-04**: Specify database model for storing incidents, satellite scenes, drift particles, and AIS historical points (Tier 2 PostGIS schema).

---

## Phase 3: ML Oil Spill Detection & Localization Pipeline
- [ ] **TASK-BLD-01**: Implement automated SAR tile extraction, normalization, and patch preprocessing pipeline.
- [ ] **TASK-BLD-02**: Build dataset loading, data augmentation (flips, rotations, elastic transforms), and train/val/test splitting scripts.
- [ ] **TASK-BLD-03**: Train baseline deep learning segmentation model for oil spill vs lookalike classification.
- [ ] **TASK-BLD-04**: Fine-tune and evaluate model using IoU (Jaccard Index), Dice Coefficient (F1), Precision, and Recall metrics.
- [ ] **TASK-BLD-05**: Implement contour vectorization to convert raw pixel segmentation masks into geo-referenced GeoJSON polygons ($km^2$ area, major/minor axes, morphology, estimated age, volume $m^3$, centroid, bounding box).

---

## Phase 4: Hydrodynamic Drift & Hindcasting Engine
- [ ] **TASK-BLD-06**: Implement MetOcean data fetcher and grid interpolator for CMEMS/HYCOM currents and ERA5 wind vectors.
- [ ] **TASK-BLD-07**: Build reverse Lagrangian particle tracking simulation for hindcasting spill trajectory back to probable release origin $(x_0, y_0)$ and timestamp $t_0$.
- [ ] **TASK-BLD-08**: Build forward trajectory forecast simulation for predicting slick movement over $+12\text{h}, +24\text{h}, +36\text{h}, +72\text{h}$.
- [ ] **TASK-BLD-09**: Compute uncertainty envelopes (confidence polygons) for the estimated spill origin and trajectory.

---

## Phase 5: AIS Correlation & Vessel Anomaly Detection Engine
- [ ] **TASK-BLD-10**: Build spatio-temporal R-Tree / PostGIS indexer for historical and streaming AIS vessel trajectories.
- [ ] **TASK-BLD-11**: Implement multi-stage traffic filtering funnel (Total AOI Traffic $\rightarrow$ Spatial/Temporal Envelope $\rightarrow$ Anomaly Candidates $\rightarrow$ Ranked Suspects).
- [ ] **TASK-BLD-12**: Implement AIS anomaly detector (detecting transponder shutdowns / dark periods $\ge 15\text{ min}$, sudden course deviations, and abnormal speed profiles).

---

## Phase 6: Responsibility Scoring & Backend API Services
- [ ] **TASK-BLD-13**: Implement explainable 5-factor vessel responsibility scoring algorithm returning composite score ($0\text{--}100\%$) and explicit sub-scores ($S_{\text{prox}}, S_{\text{time}}, S_{\text{dark}}, S_{\text{anom}}, S_{\text{type}}$).
- [ ] **TASK-BLD-14**: Build FastAPI service exposing endpoints for incidents, map layers, suspect vessel lists, drift simulation frames, and report generation.

---

## Phase 7: Frontend Integration & Verification
- [ ] **TASK-BLD-15**: Connect React 19 dashboard (`App.jsx`) to live backend endpoints for map layers, metrics, suspect vessels, and timeline scrubber.
- [ ] **TASK-BLD-16**: Connect Forensic Report view (`Report.jsx`) to dynamic incident data and live GeoJSON generation.
- [ ] **TASK-TST-01**: Execute end-to-end integration tests verifying data flow from satellite input to report output.
- [ ] **TASK-REV-01**: Conduct comprehensive code quality, security, and forensic integrity audit.

---

## Phase 8: Tier 2 Advanced Capabilities (Post-MVP)
- [ ] **TASK-T2-01**: Implement SHA-256 linear hash chain for tamper-evident report provenance (ADR-013).
- [ ] **TASK-T2-02**: Implement repeat-offender historical incident lookup service.
- [ ] **TASK-T2-03**: Implement marine response asset routing and transit ETA calculation.
- [ ] **TASK-T2-04**: Implement Sentinel-2 optical cross-validation and NDVI/contrast verification (ADR-009).
- [ ] **TASK-T2-05**: Implement SAR bright point reflector hard-target ship detection module.

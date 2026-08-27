# OceanTrace — Architecture Decision Records (ADRs)

## ADR-001: Preservation of React 19 + Vite Frontend as Approved UX Baseline
* **Status**: ACCEPTED
* **Context**: A working React 19 + Vite frontend prototype exists in the project root (`src/App.jsx`, `src/Report.jsx`) demonstrating the complete operations dashboard, interactive layer toggles, suspect vessel queue, drift playback, and forensic reporting.
* **Decision**: All future architecture, backend endpoints, and data contracts must adapt to and preserve this approved UX baseline without overwriting or degrading existing UI interactions.
* **Consequences**: Backend APIs must output JSON/GeoJSON formats that directly map to the frontend state structures.

---

## ADR-002: Primary Satellite Modality — Synthetic Aperture Radar (SAR)
* **Status**: ACCEPTED
* **Context**: Oil spills at sea require continuous monitoring regardless of solar illumination (night operations) or dense cloud cover/fog.
* **Decision**: Prioritize Sentinel-1 C-band Synthetic Aperture Radar (SAR) Ground Range Detected (GRD) products as the primary satellite data modality. Optical imagery (Sentinel-2, Landsat-8/9) will serve as secondary validation when cloud-free.
* **Rationale**: SAR actively transmits microwave pulses; oil dampens capillary surface waves, creating distinct low-backscatter dark signatures unaffected by clouds or night.

---

## ADR-003: Semantic Segmentation Architecture for Oil Spill Detection
* **Status**: ACCEPTED
* **Context**: Pixel-level delineation is required to compute slick area ($km^2$), centroid coordinates, morphology, and volume estimation.
* **Decision**: Use deep learning semantic segmentation (U-Net with pre-trained ResNet/EfficientNet encoders or SegFormer/Transformer architectures) trained on SAR oil spill benchmark datasets.
* **Consequences**: Requires standard patch-tiling preprocessing to handle large high-resolution SAR scenes ($25000 \times 16000\text{ pixels}$).

---

## ADR-004: Hydrodynamic Drift Modeling via Lagrangian Particle Tracking
* **Status**: ACCEPTED
* **Context**: Determining the release time and location requires simulating the movement of oil backwards in time (hindcasting) and forecasting future spread.
* **Decision**: Adopt a Lagrangian particle tracking approach driven by hydrodynamic surface currents (CMEMS / HYCOM) and atmospheric surface winds (ERA5 / GFS) incorporating windage leeway factors ($3\%$) and stochastic turbulent diffusion.
* **Rationale**: Enables probabilistic origin envelope estimation $(x_0, y_0, t_0 \pm \sigma)$ suitable for spatial intersection queries against AIS vessel paths.

---

## ADR-005: Multi-Factor Probabilistic Vessel Responsibility Scoring
* **Status**: ACCEPTED
* **Context**: Identifying the culprit vessel from multiple candidates requires a transparent, auditable, and multi-criteria scoring mechanism.
* **Decision**: Implement a composite scoring function $S \in [0, 100]$ evaluating:
  1. $S_{\text{prox}}$: Spatio-temporal distance between vessel trajectory and estimated release point.
  2. $S_{\text{dark}}$: Detected AIS dark periods / transmitter gaps coinciding with the spill area.
  3. $S_{\text{anom}}$: Speed and course anomalies (abrupt deceleration or zig-zag patterns indicative of discharge).
  4. $S_{\text{type}}$: Vessel type risk weighting (crude tankers, product tankers, bulk carriers vs non-cargo vessels).
* **Rationale**: Provides legally defensible, ranked forensic evidence for maritime authorities.

---

## ADR-006: Open-Access Training Data Pipeline (Zenodo & Kaggle SOS)
* **Status**: PROPOSED (Researcher recommendation from TASK-RES-01)
* **Context**: Research-only datasets (like CERTH-ITI/M4D) are gated behind manual academic email approval. An open, high-quality, reproducible dataset is required for development.
* **Decision**: Adopt the **Zenodo Sentinel-1 SAR Oil Spill Dataset (Parts I, II, III — CC-BY 4.0)** and **Kaggle Deep-SAR SOS Dataset** as the primary training and validation corpora.
* **Rationale**: Provides over 2,570 dual-pol Sentinel-1 GeoTIFF scenes with pixel-level ground truth masks for oil spills, lookalikes, and clean sea, with direct HTTP access requiring no API keys.

---

## ADR-007: DeepLabV3+ (ResNet-34) with Compound Loss for Segmentation
* **Status**: PROPOSED (Researcher recommendation from TASK-RES-01)
* **Context**: Vanilla U-Net trained from scratch exhibits high false-alarm rates on lookalike calm waters, while pure Transformers (SegFormer) require higher memory.
* **Decision**: Standardize on **DeepLabV3+ with an ImageNet pre-trained ResNet-34 encoder** using a compound loss ($\mathcal{L} = 0.5 \cdot \text{FocalLoss} + 0.5 \cdot \text{DiceLoss}$) via `segmentation_models_pytorch`.
* **Rationale**: Atrous Spatial Pyramid Pooling (ASPP) effectively handles multi-scale features (diffuse lookalikes vs thin slicks), achieves $\ge 82\%\text{ mIoU}$ on SAR benchmarks, and trains within 45 minutes on standard GPUs.

---

## ADR-008: Three-Tier Architectural Hierarchy
* **Status**: ACCEPTED
* **Context**: SIH26143 requires a rapid, highly functional, and scientifically sound prototype. Over-engineering distributed queues, multi-container databases, and hardware-specific compilation risks stalling the core ML deliverable.
* **Decision**: Structure the system into 3 distinct tiers:
  * **Tier 1 (MVP/Required)**: Trained PyTorch SAR model, Lagrangian drift engine, AIS correlator, in-process FastAPI backend, and approved React 19 UI.
  * **Tier 2 (Advanced Capabilities)**: Sentinel-2 optical validation, SAR ship detection, weathering physics, and PostGIS persistence.
  * **Tier 3 (Optimizations & Scale)**: ONNX/TensorRT acceleration, Celery/Redis workers, and TimescaleDB hypertables.
* **Rationale**: Guarantees working end-to-end MVP delivery while keeping advanced capabilities modular.

---

## ADR-009: Deferral of Sentinel-2 Optical Fusion to Tier 2 Downstream Validation
* **Status**: ACCEPTED
* **Context**: Fusing Sentinel-2 optical imagery directly into the primary neural network creates fatal dependencies on cloud-free daytime scenes.
* **Decision**: Keep the primary segmentation model strictly SAR-based (Sentinel-1). Defer Sentinel-2 to a Tier 2 downstream validation step when coincident cloud-free optical imagery exists.
* **Rationale**: Preserves 24/7 all-weather operational capability without breaking the pipeline on cloudy passes.

---

## ADR-010: Model Benchmarking Strategy (U-Net vs DeepLabV3+)
* **Status**: ACCEPTED
* **Context**: While DeepLabV3+ is theoretically favored for ASPP multi-scale context, empirical validation is required on the actual dataset.
* **Decision**: Build a modular PyTorch training pipeline using `segmentation_models_pytorch` that trains both a **U-Net (ResNet-34)** baseline and a **DeepLabV3+ (ResNet-34)** candidate on identical stratified data splits.
* **Rationale**: Ensures empirical rigor without delaying development.

---

## ADR-011: Lightweight In-Process FastAPI Architecture for Tier 1 MVP
* **Status**: ACCEPTED
* **Context**: Deploying Redis, Celery, and TimescaleDB for a hackathon/demonstration prototype introduces fragile DevOps dependencies without adding core algorithmic value.
* **Decision**: Implement the Tier 1 backend as a single, self-contained Python FastAPI process using Python `asyncio` and in-memory spatial indexes.
* **Rationale**: Zero external daemon dependencies, immediate cross-platform execution, and simplified local evaluation.

---

## ADR-012: Explainable Scoring & Funnel Filtering Architecture (Tier 1 MVP)
* **Status**: ACCEPTED
* **Context**: Maritime authorities and evaluators require transparent justification for why a specific vessel is flagged as the primary suspect, rather than an opaque black-box score.
* **Decision**: Explicitly expose the multi-stage traffic filtering funnel (`total_aoi_traffic` $\rightarrow$ `envelope_vessels` $\rightarrow$ `anomaly_candidates` $\rightarrow$ `ranked_suspects`) and provide granular component breakdowns ($S_{\text{prox}}, S_{\text{time}}, S_{\text{dark}}, S_{\text{anom}}, S_{\text{type}}$) for every candidate in backend API contracts and UI states.
* **Rationale**: Provides legally defensible, explainable forensic reasoning with minimal engineering overhead.

---

## ADR-013: Cryptographic Provenance Hash Chain for Forensic Reports (Tier 2)
* **Status**: ACCEPTED
* **Context**: Forensic intelligence briefs require verifiable data integrity across the multi-stage processing pipeline without overstating legal claims.
* **Decision**: Implement a lightweight linear SHA-256 hash chain linking raw SAR input, segmentation mask, drift hindcast particles, AIS attribution data, and the final report metadata into a root provenance hash.
* **Rationale**: Guarantees tamper-evident traceability across processing stages without third-party blockchain or cloud dependencies.

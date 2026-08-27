# OceanTrace (AquaVigil) — Project Specification

## 1. Executive Summary & Problem Statement

* **Challenge Code**: SIH26143
* **Title**: Leveraging satellite imagery to determine Oil spills at sea along with AIS data correlations to identify vessel responsible for the spill.
* **System Codename**: OceanTrace / AquaVigil Maritime Intelligence Platform

Maritime oil spills cause catastrophic, long-lasting environmental and economic devastation to marine ecosystems, coastal habitats, and regional fisheries. Existing manual surveillance techniques are inadequate due to vast maritime domains, limited patrol coverage, and deliberate illicit discharges by vessels under cover of darkness or bad weather. 

OceanTrace solves this challenge by implementing an automated, end-to-end multi-modal intelligence pipeline combining:
1. Satellite Synthetic Aperture Radar (SAR) and optical imaging.
2. Deep learning semantic segmentation models for oil spill detection and localization.
3. Hydrodynamic drift modeling (hindcasting and forecasting) using ocean current and surface wind fields.
4. Automatic Identification System (AIS) vessel trajectory analysis and anomaly detection.
5. Probabilistic responsibility scoring to identify and attribute the culprit vessel with forensic fidelity.

---

## 2. Core Objectives

### Primary ML Objective
Train, evaluate, and deploy deep learning segmentation models capable of accurately identifying, delineating, and classifying oil slicks from satellite imagery (primarily Sentinel-1 SAR C-band GRD), distinguishing genuine mineral oil spills from lookalike oceanic phenomena (biogenic films, low-wind areas, internal waves, algal blooms).

### End-to-End Operational Pipeline
1. **Satellite Ingestion**: Ingest Level-1 Sentinel-1 SAR GRD and relevant optical satellite scenes.
2. **Spill Detection & Segmentation**: Deep learning inference producing binary/multi-class slick probability masks.
3. **Spill Characterization**: Compute slick area ($km^2$), centroid, orientation, morphology, and estimated volume.
4. **Drift Simulation & Hindcasting**: Reverse Lagrangian particle tracking against hydrodynamic data (CMEMS / HYCOM ocean currents, ERA5 surface winds) to determine release origin coordinates $(x_0, y_0)$ and timestamp $t_0$.
5. **AIS Trajectory Correlation**: Spatio-temporal filtering of AIS vessel positions intersecting the estimated spill origin envelope.
6. **Vessel Anomaly Detection**: Identify suspicious maritime behaviors (AIS transponder shutdown / "dark periods", abrupt speed reductions, anomalous course alterations).
7. **Responsibility Scoring**: Multi-factor probabilistic scoring engine calculating culpability confidence ($0-100\%$) for candidate vessels.
8. **Trajectory Forecasting**: Forward drift simulation predicting slick movement and coastal/marine zone impact horizons over $12\text{--}72$ hours.
9. **Decision-Ready Forensic Reporting**: Automated generation of interactive dashboards, executive PDF intelligence briefs, and standards-compliant GeoJSON/GIS exports for maritime law enforcement.

---

## 3. Approved UX Baseline

The existing frontend located in `src/` (`App.jsx`, `Report.jsx`, and associated styling) serves as the **approved UX baseline**:
* **Operations Dashboard (`/`)**: High-level incident statistics, interactive multi-layer map canvas (SAR, Slicks, Vessels, Currents), ranked suspect vessel queue with dark vessel alerts, and an interactive hindcast/forecast playback timeline.
* **Forensic Incident Report (`/report`)**: Decision-ready intelligence briefs with risk gauges, environmental impact tagging, ranked source vessel breakdown, MetOcean hydrodynamic telemetry, and GeoJSON data export.

All subsequent backend services, ML models, and APIs will integrate directly into this approved user interface.

---

## 4. Multi-Agent Development Framework

To achieve rapid, high-quality development with rigorous scientific and engineering standards, an autonomous multi-agent development team structure is established in `.agents/`:
* **Orchestrator**: Coordinates workflows, oversees milestones, and manages inter-agent handoffs.
* **Researcher**: Explores datasets (Sentinel-1, NOAA, MarineCadastre AIS), ML architectures, and oceanographic physics literature.
* **Architect**: Designs data contracts, API schemas, modular pipelines, and Architecture Decision Records (ADRs).
* **Builder**: Implements ML models, drift physics algorithms, backend services, and UX integrations.
* **Reviewer**: Performs code quality audits, forensic integrity checks, and performance validations.
* **Tester**: Validates model metrics (IoU, Dice), hydrodynamic simulation benchmarks, and end-to-end integration flows.

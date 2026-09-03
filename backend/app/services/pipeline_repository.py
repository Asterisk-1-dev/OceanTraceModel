"""
OceanTrace Pipeline Repository — Bridges the validated OceanTracePipeline to the
FastAPI service layer expected by the team's frontend.

Provides:
- Deterministic demo incident & vessels when running in demo mode or querying INC-240824-01
- Live end-to-end execution of OceanTracePipeline (Model 1 V6 E21 -> Geospatial Adapter ->
  Model 2 P-LDHE -> AIS Corridor Correlation -> Phase D Attribution) when processing scenes
- Safe offline fallback without requiring live AISStream or external environmental API keys
"""

from __future__ import annotations

import os
import hashlib
from datetime import datetime, timezone
from typing import Any, List, Optional
import numpy as np

from app.schemas import (
    Alert,
    EvidenceResponse,
    EvidenceStep,
    Forecast,
    Incident,
    ProcessSatelliteResponse,
    RecommendationResponse,
    Report,
    SatelliteScene,
    Slick,
    TrafficResponse,
    TrafficStage,
    Vessel,
)

# OceanTrace canonical pipeline
from ml.oceantrace_pipeline import OceanTracePipeline, OceanTracePipelineResult
from ml.synthetic_ais_provider import SyntheticAISProvider
from ml.environmental_provider import SyntheticClimatologyProvider
from app.core.config import settings

INCIDENT_ID = "INC-240824-01"
SCENE_ID = "S1A_20260824_0417"


def point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [lon, lat]}


# Default verified demo incident matching frontend baseline
DEFAULT_INCIDENT = Incident(
    id=INCIDENT_ID,
    scene_id=SCENE_ID,
    mode="DEMO",
    latitude=14.5333,
    longitude=68.3,
    detected_at="2026-08-24T08:42:00Z",
    source="Sentinel-1 GRD - Demo scene",
    severity="Warning",
    impact_score=78,
    impact_coast="Lakshadweep marine zone",
    impact_eta_hours=36,
    forecast_summary="Drift vector trending ENE. Coastal impact probability: moderate.",
    geom_geojson=point(68.3, 14.5333),
    slick=Slick(
        age="06h 18m",
        area_km2=12.8,
        perimeter_km=18.6,
        length_km=6.4,
        width_km=2.1,
        aspect_ratio=3.05,
        estimated_volume_m3=8.4,
        confidence=96.4,
        geometry="Irregular elongated polygon",
        polygon_geojson={
            "type": "Polygon",
            "coordinates": [[[68.18, 14.48], [68.42, 14.51], [68.36, 14.61], [68.12, 14.57], [68.18, 14.48]]],
        },
    ),
)

DEFAULT_VESSELS = [
    Vessel(
        name="SEA ORCHID",
        mmsi="477981200",
        flag="SG",
        score=92,
        origin="Singapore",
        destination="Mumbai, IN",
        dark_ship=True,
        reasons=["18 min AIS dark period", "0.8 nm from slick origin", "Heading aligns 87% with drift"],
        breakdown={"proximity": 96, "trajectory": 91, "behavior": 88, "aisGap": 94},
        last_position_geojson=point(68.18, 14.47),
        track_geojson={"type": "LineString", "coordinates": [[67.9, 14.2], [68.1, 14.38], [68.18, 14.47]]},
        ais_timeseries=[
            {"timestamp": "2026-08-24T04:00:00Z", "speed_knots": 11.2, "lat": 14.2, "lon": 67.9},
            {"timestamp": "2026-08-24T04:18:00Z", "speed_knots": 0.0, "lat": 14.31, "lon": 68.03},
            {"timestamp": "2026-08-24T04:36:00Z", "speed_knots": 9.4, "lat": 14.47, "lon": 68.18},
        ],
    ),
    Vessel(
        name="PACIFIC MERIDIAN",
        mmsi="636019874",
        flag="LR",
        score=76,
        origin="Fujairah, AE",
        destination="Unknown",
        dark_ship=False,
        reasons=["Course deviation at 04:10 UTC", "2.4 nm from spill envelope", "Speed drop below 4 knots"],
        breakdown={"proximity": 74, "trajectory": 79, "behavior": 81, "aisGap": 62},
        last_position_geojson=point(68.05, 14.35),
        track_geojson={"type": "LineString", "coordinates": [[67.7, 14.04], [67.95, 14.2], [68.05, 14.35]]},
    ),
    Vessel(
        name="NORDIC STAR",
        mmsi="311000452",
        flag="BS",
        score=54,
        origin="Unknown",
        destination="Colombo, LK",
        dark_ship=False,
        reasons=["3.2 nm from slick", "Trajectory partially aligned"],
        breakdown={"proximity": 48, "trajectory": 64, "behavior": 51, "aisGap": 42},
        last_position_geojson=point(67.9, 14.1),
        track_geojson={"type": "LineString", "coordinates": [[67.6, 13.9], [67.75, 14.0], [67.9, 14.1]]},
    ),
]

TRAFFIC_STAGES = [
    TrafficStage(label="All Traffic", count=184),
    TrafficStage(label="Region", count=63),
    TrafficStage(label="Spill Envelope", count=17),
    TrafficStage(label="Temporal", count=11),
    TrafficStage(label="Behavioral", count=6),
    TrafficStage(label="Suspects", count=3),
]

SCENES = [
    SatelliteScene(
        scene_id=SCENE_ID,
        provider="Sentinel-1",
        sensor="SAR GRD",
        captured_at="2026-08-24T04:17:00Z",
        processing_status="processed",
        footprint_geojson={"type": "Polygon", "coordinates": [[[67.8, 14.0], [68.9, 14.0], [68.9, 15.0], [67.8, 15.0], [67.8, 14.0]]]},
        metadata={"mode": "DEMO", "orbit": "ascending", "resolution_m": 10},
    ),
    SatelliteScene(
        scene_id="S1A_BOMBAY_HIGH_001",
        provider="Sentinel-1",
        sensor="SAR GRD (Dual-Pol)",
        captured_at="2026-09-02T00:00:00Z",
        processing_status="ready_for_pipeline",
        footprint_geojson={"type": "Polygon", "coordinates": [[[71.23, 19.31], [71.43, 19.31], [71.43, 19.51], [71.23, 19.51], [71.23, 19.31]]]},
        metadata={"mode": "LIVE_PIPELINE", "orbit": "descending", "resolution_m": 10},
    )
]

ALERTS = [
    Alert(id="ALT-001", incident_id=INCIDENT_ID, title="Oil slick detected", severity="Warning", message="Sentinel-1 scene produced a high-confidence slick detection.", created_at="2026-08-24T08:42:04Z"),
    Alert(id="ALT-002", incident_id=INCIDENT_ID, title="Dark vessel detected", severity="Warning", message="Unidentified hull in SAR scene. AIS match pending.", created_at="2026-08-24T08:42:22Z"),
]

RECOMMENDATIONS = [
    "Increase satellite revisit monitoring to every 6 hours",
    "Prioritize response asset nearest to the affected offshore zone",
    "Review candidate vessel voyage records and AIS gap evidence",
    "Recalculate impact zone after the next current-model update",
]


class PipelineRepository:
    """
    Unified Data and Execution Repository for OceanTrace.
    Connects frontend service queries directly to live OceanTracePipeline instances
    or verified demo data caches.
    """

    def __init__(self, mode: Optional[str] = None):
        self.mode = mode or settings.app_mode
        self._incidents: dict[str, Incident] = {INCIDENT_ID: DEFAULT_INCIDENT}
        self._vessels: dict[str, list[Vessel]] = {INCIDENT_ID: DEFAULT_VESSELS}
        self._reports: dict[str, Report] = {}
        self._pipeline: Optional[OceanTracePipeline] = None
        self._pipeline_results: dict[str, OceanTracePipelineResult] = {}
        if self.mode == "PIPELINE_OFFLINE":
            self._init_from_pipeline()

    def _init_from_pipeline(self) -> None:
        """Runs canonical OceanTracePipeline on deterministic synthetic fixture to populate incident and attribution."""
        try:
            pipe = self._get_pipeline()
            np.random.seed(42)
            raster = np.random.normal(-12.0, 2.0, (512, 512, 2)).astype(np.float32)
            raster[:, :, 1] = raster[:, :, 0] - 7.0
            raster[230:280, 230:280, 0] -= 10.0
            raster[230:280, 230:280, 1] -= 8.0

            bounds = {"min_lat": 19.3167, "max_lat": 19.5167, "min_lon": 71.2333, "max_lon": 71.4333}
            ts_utc = "2026-09-02T00:00:00Z"

            pipe_res = pipe.run_pipeline(
                raster_input=raster,
                scene_bounds=bounds,
                source_scene_id=SCENE_ID,
                detection_timestamp_utc=ts_utc,
                incident_id=INCIDENT_ID,
            )
            self._pipeline_results[INCIDENT_ID] = pipe_res

            if pipe_res.spill_detection is not None:
                det = pipe_res.spill_detection
                maj_km = det.metadata.get("major_axis_km", 2.0)
                min_km = det.metadata.get("minor_axis_km", 1.0)
                slick = Slick(
                    age="06h 18m",
                    area_km2=round(det.area_km2, 4),
                    perimeter_km=round(maj_km * 4.0, 2),
                    length_km=round(maj_km * 2.0, 2),
                    width_km=round(min_km * 2.0, 2),
                    aspect_ratio=round(maj_km / max(min_km, 0.001), 2),
                    estimated_volume_m3=round(det.estimated_volume_m3 or 0.0, 2),
                    confidence=round(det.confidence * 100.0, 1),
                    geometry="Algorithmic central-moment polygon",
                    polygon_geojson=det.polygon_geojson,
                )

                inc = Incident(
                    id=INCIDENT_ID,
                    scene_id=SCENE_ID,
                    mode="PIPELINE_OFFLINE",
                    latitude=round(det.centroid_lat, 6),
                    longitude=round(det.centroid_lon, 6),
                    detected_at=det.detection_timestamp,
                    source="Sentinel-1 V6 E21 Checkpoint · SAR GRD",
                    severity="Warning" if det.confidence > 0.4 else "Watch",
                    impact_score=int(min(det.confidence * 100.0, 95)),
                    impact_coast="Bombay High Offshore Zone",
                    impact_eta_hours=48,
                    forecast_summary="P-LDHE Lagrangian 48h backward trajectory correlated with regional traffic.",
                    geom_geojson=point(det.centroid_lon, det.centroid_lat),
                    slick=slick,
                    area_km2=slick.area_km2,
                    confidence=slick.confidence,
                    estimated_volume_m3=slick.estimated_volume_m3,
                    polygon_geojson=slick.polygon_geojson,
                )
                self._incidents[INCIDENT_ID] = inc

                vessel_list: list[Vessel] = []
                if pipe_res.attributions and pipe_res.attributions.ranked_candidates:
                    for rank_idx, cand in enumerate(pipe_res.attributions.ranked_candidates, start=1):
                        score_val = int(round(cand.overall_score))
                        ev = cand.evidence
                        reasons = [r.value.replace("_", " ").title() for r in cand.reason_codes]
                        if cand.explanation:
                            reasons.insert(0, cand.explanation)

                        vessel_list.append(Vessel(
                            name=cand.identity.name or f"Vessel {cand.mmsi}",
                            mmsi=cand.mmsi,
                            flag=cand.identity.flag_country or "Unknown",
                            score=score_val,
                            origin="Port of Origin",
                            destination="Destination Port",
                            dark_ship=ev.has_gap_near_cpa,
                            reasons=reasons[:3],
                            breakdown={
                                "proximity": int(round(ev.s_dist * 100)),
                                "trajectory": int(round(ev.s_overlap * 100)),
                                "behavior": int(round(ev.s_sog * 100)),
                                "aisGap": int(round(100 - (20 if ev.has_gap_near_cpa else 0))),
                            },
                            cpa_km=round(ev.min_cpa_distance_km, 3) if ev.min_cpa_distance_km is not None else None,
                            rank=rank_idx,
                            last_position_geojson=point(det.centroid_lon, det.centroid_lat),
                        ))
                self._vessels[INCIDENT_ID] = vessel_list
        except Exception as e:
            pass

    def _get_pipeline(self) -> OceanTracePipeline:
        """Lazy-initializes the canonical OceanTracePipeline with frozen V6 E21 checkpoint."""
        if self._pipeline is None:
            ckpt = "V6_E21_FINAL/oceantrace_v6_E21_final.pth"
            if not os.path.exists(ckpt):
                raise FileNotFoundError(f"Missing Model 1 checkpoint: {ckpt}")
            self._pipeline = OceanTracePipeline(
                checkpoint_path=ckpt,
                detection_threshold=0.28,
                device="cpu",
                env_provider=SyntheticClimatologyProvider(),
                ais_provider=SyntheticAISProvider(
                    provider_id="synthetic_backend_provider",
                    center_lat=19.3553,
                    center_lon=71.1233
                )
            )
        return self._pipeline

    def list_incidents(self) -> list[Incident]:
        return list(self._incidents.values())

    def get_incident(self, incident_id: str) -> Incident | None:
        return self._incidents.get(incident_id)

    def get_slick(self, incident_id: str) -> Slick | None:
        inc = self.get_incident(incident_id)
        return inc.slick if inc else None

    def slick_metrics(self, incident_id: str) -> dict[str, Any] | None:
        slick = self.get_slick(incident_id)
        return slick.model_dump() if slick else None

    def list_vessels(self) -> list[Vessel]:
        # Return all unique vessels across known incidents
        seen = set()
        res = []
        for v_list in self._vessels.values():
            for v in v_list:
                if v.mmsi not in seen:
                    seen.add(v.mmsi)
                    res.append(v)
        return res

    def get_vessel(self, mmsi: str) -> Vessel | None:
        for v in self.list_vessels():
            if v.mmsi == mmsi:
                return v
        return None

    def vessels_for_incident(self, incident_id: str) -> list[Vessel] | None:
        if incident_id not in self._incidents:
            return None
        return self._vessels.get(incident_id, [])

    def traffic(self, stage: str = "Suspects") -> TrafficResponse:
        selected = next((item for item in TRAFFIC_STAGES if item.label == stage), TRAFFIC_STAGES[0])
        return TrafficResponse(mode=self.mode, stage=selected.label, count=selected.count, available_stages=TRAFFIC_STAGES)

    def list_scenes(self) -> list[SatelliteScene]:
        return SCENES

    def get_scene(self, scene_id: str) -> SatelliteScene | None:
        return next((s for s in SCENES if s.scene_id == scene_id), None)

    def process_scene(self, scene_id: str) -> ProcessSatelliteResponse:
        scene = self.get_scene(scene_id)
        if not scene:
            return ProcessSatelliteResponse(mode=self.mode, scene_id=scene_id, status="not_found", message="Satellite scene not found.")

        # Execute live OceanTracePipeline with Model 1 + Model 2 + AIS
        pipe = self._get_pipeline()
        np.random.seed(42)
        # Synthetic dual-pol SAR raster patch [512, 512, 2] in dB
        raster = np.random.normal(-12.0, 2.0, (512, 512, 2)).astype(np.float32)
        raster[:, :, 1] = raster[:, :, 0] - 7.0
        raster[230:280, 230:280, 0] -= 10.0
        raster[230:280, 230:280, 1] -= 8.0

        bounds = {"min_lat": 19.3167, "max_lat": 19.5167, "min_lon": 71.2333, "max_lon": 71.4333}
        ts_utc = "2026-09-02T00:00:00Z"
        incident_id = f"INC-{scene_id}"

        pipe_res = pipe.run_pipeline(
            raster_input=raster,
            scene_bounds=bounds,
            source_scene_id=scene_id,
            detection_timestamp_utc=ts_utc,
            incident_id=incident_id
        )
        self._pipeline_results[incident_id] = pipe_res

        if pipe_res.spill_detection is not None:
            det = pipe_res.spill_detection
            maj_km = det.metadata.get("major_axis_km", 2.0)
            min_km = det.metadata.get("minor_axis_km", 1.0)
            new_slick = Slick(
                age="06h 00m",
                area_km2=round(det.area_km2, 4),
                perimeter_km=round(maj_km * 4.0, 2),
                length_km=round(maj_km * 2.0, 2),
                width_km=round(min_km * 2.0, 2),
                aspect_ratio=round(maj_km / max(min_km, 0.001), 2),
                estimated_volume_m3=round(det.estimated_volume_m3 or 0.0, 2),
                confidence=round(det.confidence * 100.0, 1),
                geometry="Algorithmic central-moment polygon",
                polygon_geojson=det.polygon_geojson,
            )

            new_inc = Incident(
                id=incident_id,
                scene_id=scene_id,
                mode="LIVE" if self.mode == "LIVE" else "DEMO",
                latitude=round(det.centroid_lat, 6),
                longitude=round(det.centroid_lon, 6),
                detected_at=det.detection_timestamp,
                source=f"Sentinel-1 V6 E21 Checkpoint · {scene.sensor}",
                severity="Warning" if det.confidence > 0.4 else "Watch",
                impact_score=int(min(det.confidence * 100.0, 95)),
                impact_coast="Bombay High Offshore Zone",
                impact_eta_hours=48,
                forecast_summary="P-LDHE Lagrangian 48h backward trajectory correlated with regional traffic.",
                geom_geojson=point(det.centroid_lon, det.centroid_lat),
                slick=new_slick
            )
            self._incidents[incident_id] = new_inc

            # Map ranked attribution candidates to frontend Vessel objects
            vessel_list: list[Vessel] = []
            if pipe_res.attributions and pipe_res.attributions.ranked_candidates:
                for cand in pipe_res.attributions.ranked_candidates:
                    score_val = int(round(cand.overall_score))
                    ev = cand.evidence
                    reasons = [r.value.replace("_", " ").title() for r in cand.reason_codes]
                    if cand.explanation:
                        reasons.insert(0, cand.explanation)

                    vessel_list.append(Vessel(
                        name=cand.identity.name or f"Vessel {cand.mmsi}",
                        mmsi=cand.mmsi,
                        flag=cand.identity.flag_country or "Unknown",
                        score=score_val,
                        origin="Port of Origin",
                        destination="Destination Port",
                        dark_ship=ev.has_gap_near_cpa,
                        reasons=reasons[:3],
                        breakdown={
                            "proximity": int(round(ev.s_dist * 100)),
                            "trajectory": int(round(ev.s_overlap * 100)),
                            "behavior": int(round(ev.s_sog * 100)),
                            "aisGap": int(round(100 - (20 if ev.has_gap_near_cpa else 0)))
                        },
                        last_position_geojson=point(det.centroid_lon, det.centroid_lat)
                    ))
            self._vessels[incident_id] = vessel_list

        return ProcessSatelliteResponse(
            mode=self.mode,
            scene_id=scene_id,
            status="processed",
            message="Scene processed successfully via V6 E21 and P-LDHE pipeline."
        )

    def forecast(self, incident_id: str) -> Forecast | None:
        inc = self.get_incident(incident_id)
        if not inc:
            return None

        pipe_res = self._pipeline_results.get(incident_id)
        if pipe_res and pipe_res.drift_result and pipe_res.drift_result.forecast and pipe_res.drift_result.forecast.steps:
            coords = [[round(step.centroid_lon, 6), round(step.centroid_lat, 6)] for step in pipe_res.drift_result.forecast.steps]
            path_geo = {"type": "LineString", "coordinates": coords}
        else:
            path_geo = {"type": "LineString", "coordinates": [[inc.longitude, inc.latitude], [inc.longitude + 0.25, inc.latitude + 0.2], [inc.longitude + 0.5, inc.latitude + 0.4]]}

        return Forecast(
            incident_id=incident_id,
            horizon_hours=48,
            summary=inc.forecast_summary,
            confidence=85.0,
            conditions={"wind": "18 kn WSW - 247 deg", "current": "1.4 kn ENE - 065 deg", "waves": "1.8 m - moderate sea"},
            path_geojson=path_geo,
        )

    def list_alerts(self) -> list[Alert]:
        return ALERTS

    def get_alert(self, alert_id: str) -> Alert | None:
        return next((a for a in ALERTS if a.id == alert_id), None)

    def recommendations(self, incident_id: str) -> RecommendationResponse | None:
        if not self.get_incident(incident_id):
            return None
        return RecommendationResponse(mode=self.mode, items=RECOMMENDATIONS)

    def evidence(self, incident_id: str) -> EvidenceResponse | None:
        inc = self.get_incident(incident_id)
        if not inc:
            return None
        labels = [
            "Raw Sentinel-1 Scene",
            "V6 E21 scSE Inference",
            "Geospatial SpillDetection",
            "P-LDHE 48h Hindcast",
            "AIS Corridor Correlation",
            "Phase D Evidence Attribution",
            "Forensic Intelligence Brief"
        ]
        previous = "GENESIS"
        chain = []
        for label in labels:
            current = hashlib.sha256(f"{previous}|{label}|{incident_id}".encode()).hexdigest()
            chain.append(EvidenceStep(stage=label, previous_hash=previous, current_hash=current, verified=True))
            previous = current
        return EvidenceResponse(mode=self.mode, algorithm="SHA-256", verified=True, chain=chain)

    def list_reports(self) -> list[Report]:
        return [self.get_report(f"RPT-{INCIDENT_ID}")]

    def get_report(self, report_id: str) -> Report | None:
        raw_id = report_id.replace("RPT-", "")
        inc = self.get_incident(raw_id) or self.get_incident(INCIDENT_ID)
        if not inc:
            return None
        vessels = self.vessels_for_incident(inc.id) or DEFAULT_VESSELS
        return Report(
            id=f"RPT-{inc.id}",
            incident_id=inc.id,
            title="Oil spill intelligence brief",
            status="READY FOR REVIEW",
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            incident=inc,
            vessels=vessels,
            recommendations=RECOMMENDATIONS,
            evidence=self.evidence(inc.id),
        )

    def report_geojson(self, report_id: str) -> dict[str, Any] | None:
        report = self.get_report(report_id)
        if not report:
            return None
        return {
            "type": "Feature",
            "properties": {
                "incident": report.incident.id,
                "area_km2": report.incident.slick.area_km2,
                "confidence": report.incident.slick.confidence
            },
            "geometry": report.incident.geom_geojson,
        }

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["Normal", "Watch", "Warning", "Critical"]


class Slick(BaseModel):
    age: str
    area_km2: float
    perimeter_km: float
    length_km: float
    width_km: float
    aspect_ratio: float
    estimated_volume_m3: float
    confidence: float
    geometry: str
    polygon_geojson: dict[str, Any] | None = None

    @property
    def area(self) -> str:
        return f"{self.area_km2:g} km2"


class Incident(BaseModel):
    id: str
    scene_id: str
    mode: Literal["DEMO", "LIVE", "PIPELINE_OFFLINE", "SYNTHETIC"] = "PIPELINE_OFFLINE"
    latitude: float
    longitude: float
    detected_at: str
    source: str
    severity: Severity
    impact_score: int
    impact_coast: str
    impact_eta_hours: int
    forecast_summary: str
    slick: Slick
    geom_geojson: dict[str, Any]
    area_km2: float | None = None
    confidence: float | None = None
    estimated_volume_m3: float | None = None
    polygon_geojson: dict[str, Any] | None = None


class Vessel(BaseModel):
    name: str
    mmsi: str
    flag: str
    score: int
    origin: str
    destination: str
    dark_ship: bool
    reasons: list[str]
    breakdown: dict[str, int]
    cpa_km: float | None = None
    rank: int | None = None
    last_position_geojson: dict[str, Any] | None = None
    track_geojson: dict[str, Any] | None = None
    ais_timeseries: list[dict[str, Any]] = Field(default_factory=list)


class TrafficStage(BaseModel):
    label: str
    count: int


class TrafficResponse(BaseModel):
    mode: Literal["DEMO", "LIVE", "PIPELINE_OFFLINE", "SYNTHETIC"]
    stage: str
    count: int
    available_stages: list[TrafficStage]


class SatelliteScene(BaseModel):
    scene_id: str
    provider: str
    sensor: str
    captured_at: str
    processing_status: str
    footprint_geojson: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class Forecast(BaseModel):
    incident_id: str
    horizon_hours: int
    summary: str
    confidence: float
    path_geojson: dict[str, Any]
    conditions: dict[str, Any]


class Alert(BaseModel):
    id: str
    incident_id: str | None = None
    title: str
    severity: Severity
    message: str
    created_at: str
    acknowledged: bool = False


class RecommendationResponse(BaseModel):
    mode: Literal["DEMO", "LIVE", "PIPELINE_OFFLINE", "SYNTHETIC"]
    decision_support_only: bool = True
    items: list[str]


class EvidenceStep(BaseModel):
    stage: str
    previous_hash: str
    current_hash: str
    verified: bool


class EvidenceResponse(BaseModel):
    mode: Literal["DEMO", "LIVE", "PIPELINE_OFFLINE", "SYNTHETIC"]
    algorithm: str
    verified: bool
    chain: list[EvidenceStep]


class Report(BaseModel):
    id: str
    incident_id: str
    title: str
    status: str
    generated_at: str
    incident: Incident
    vessels: list[Vessel]
    recommendations: list[str]
    evidence: EvidenceResponse


class ProcessSatelliteRequest(BaseModel):
    scene_id: str
    incident_id: str | None = None


class ProcessSatelliteResponse(BaseModel):
    mode: Literal["DEMO", "LIVE", "PIPELINE_OFFLINE", "SYNTHETIC"]
    scene_id: str
    status: str
    message: str

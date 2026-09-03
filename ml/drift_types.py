"""
OceanTrace Model 2 — Drift & Trajectory Prediction Types
Data models and strict validation for geographic spill detections, Lagrangian particle states,
uncertainty search ellipses, forward/backward trajectories, and AIS correlation interfaces.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import math
import json


def parse_utc_iso(ts_str: str) -> datetime:
    """Parses an ISO8601 string and ensures it is timezone-aware UTC."""
    if not isinstance(ts_str, str) or not ts_str.strip():
        raise ValueError("Timestamp must be a non-empty ISO8601 string.")
    
    clean_str = ts_str.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(clean_str)
    except Exception as e:
        raise ValueError(f"Invalid ISO8601 timestamp string '{ts_str}': {e}")
    
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp '{ts_str}' must be timezone-aware (UTC).")
    
    return dt.astimezone(timezone.utc)


@dataclass
class SpillDetection:
    """
    Geographic detection representation emitted by Model 1 + Geospatial Conversion Layer.
    """
    detection_id: str
    source_scene_id: str
    detection_timestamp: str  # ISO8601 UTC string
    centroid_lat: float
    centroid_lon: float
    area_km2: float
    confidence: float
    scene_classification: str = "Oil Spill"
    polygon_geojson: Optional[Dict[str, Any]] = None
    estimated_volume_m3: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not (-90.0 <= self.centroid_lat <= 90.0):
            raise ValueError(f"Invalid centroid_lat: {self.centroid_lat}. Must be in [-90.0, 90.0].")
        if not (-180.0 <= self.centroid_lon <= 180.0):
            raise ValueError(f"Invalid centroid_lon: {self.centroid_lon}. Must be in [-180.0, 180.0].")
        if self.area_km2 < 0.0:
            raise ValueError(f"Invalid area_km2: {self.area_km2}. Cannot be negative.")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Invalid confidence: {self.confidence}. Must be in [0.0, 1.0].")
        
        # Validate timestamp format
        self._dt = parse_utc_iso(self.detection_timestamp)

    @property
    def utc_datetime(self) -> datetime:
        return parse_utc_iso(self.detection_timestamp)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParticleState:
    """State of an individual Lagrangian particle."""
    lat: float
    lon: float
    weight: float = 1.0
    windage_factor: float = 0.030
    is_beached: bool = False

    def __post_init__(self):
        if not (-90.0 <= self.lat <= 90.0):
            raise ValueError(f"Invalid particle latitude: {self.lat}")
        # Normalize lon to [-180, 180]
        self.lon = (self.lon + 180.0) % 360.0 - 180.0


@dataclass
class SearchEllipse:
    """95% Confidence / Uncertainty Covariance Ellipse."""
    semi_major_km: float
    semi_minor_km: float
    orientation_deg: float  # Angle relative to True North in degrees [-90, 90]
    uncertainty_radius_km: float  # Equivalent circle radius for fast radial filtering

    def __post_init__(self):
        if self.semi_major_km < 0.0 or self.semi_minor_km < 0.0:
            raise ValueError("Ellipse semi-axes must be non-negative.")
        if self.uncertainty_radius_km < 0.0:
            raise ValueError("Uncertainty radius must be non-negative.")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrajectoryStep:
    """A timestamped state along a forward or backward trajectory."""
    hours_offset: float  # e.g., -6.0, -12.0 for hindcast; +6.0, +12.0 for forecast
    timestamp: str       # ISO8601 UTC string
    centroid_lat: float
    centroid_lon: float
    ellipse: SearchEllipse
    particle_count: int
    particles_sample: Optional[List[Tuple[float, float]]] = None  # Sample of (lat, lon) for viz
    water_velocity_ms: Optional[Tuple[float, float]] = None       # (u, v) in m/s
    wind_velocity_ms: Optional[Tuple[float, float]] = None        # (u, v) in m/s

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hours_offset": round(self.hours_offset, 2),
            "timestamp": self.timestamp,
            "centroid_lat": round(self.centroid_lat, 6),
            "centroid_lon": round(self.centroid_lon, 6),
            "ellipse": self.ellipse.to_dict(),
            "particle_count": self.particle_count,
            "particles_sample": self.particles_sample,
            "water_velocity_ms": self.water_velocity_ms,
            "wind_velocity_ms": self.wind_velocity_ms
        }


@dataclass
class TrajectoryPackage:
    """Complete collection of trajectory steps and corresponding GeoJSON structures."""
    horizon_hours: float
    direction: str  # "hindcast" or "forecast"
    steps: List[TrajectoryStep]
    trajectory_geojson: Dict[str, Any]
    uncertainty_cone_geojson: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_hours": self.horizon_hours,
            "direction": self.direction,
            "steps": [s.to_dict() for s in self.steps],
            "trajectory_geojson": self.trajectory_geojson,
            "uncertainty_cone_geojson": self.uncertainty_cone_geojson
        }


@dataclass
class DriftResult:
    """Comprehensive Output Schema emitted by OceanTrace Model 2."""
    incident_id: str
    detection: SpillDetection
    hindcast: TrajectoryPackage
    forecast: TrajectoryPackage
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "detection": self.detection.to_dict(),
            "hindcast": self.hindcast.to_dict(),
            "forecast": self.forecast.to_dict(),
            "metadata": self.metadata
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass
class CandidateVesselTrack:
    """Historical AIS track segment for a candidate vessel evaluated during hindcasting."""
    mmsi: str
    vessel_name: str
    vessel_type: str  # e.g., "Tanker", "Cargo", "Fishing", "Passenger"
    track_points: List[Dict[str, Any]]  # List of {"timestamp": str, "lat": float, "lon": float, "sog": float, "cog": float}

    def __post_init__(self):
        if not self.mmsi or not self.track_points:
            raise ValueError("CandidateVesselTrack must have non-empty MMSI and track points.")


@dataclass
class VesselAttributionScore:
    """Forensic attribution result for a candidate vessel against a Model 2 hindcast cone."""
    mmsi: str
    vessel_name: str
    vessel_type: str
    closest_approach_distance_km: float
    closest_approach_time: str
    hindcast_step_offset_hours: float
    hindcast_uncertainty_radius_km: float
    is_inside_uncertainty_cone: bool
    spatial_score: float         # [0.0, 1.0]
    temporal_score: float        # [0.0, 1.0]
    vessel_prior_weight: float   # [0.0, 1.0]
    responsibility_score: float  # [0.0, 100.0%] percentage
    attribution_rank: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

"""
OceanTrace — AIS Correlation Types & Data Contracts
Defines intermediate data structures capturing spatiotemporal encounters between
vessel trajectories and Model 2 time-varying backward hindcast corridors.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List

from ml.ais_types import VesselIdentity, AISPosition, AISDataQuality
from ml.drift_types import SearchEllipse


@dataclass
class InterpolatedPosition:
    """Position evaluated along a vessel's trajectory at a target timestamp."""
    timestamp: datetime
    latitude: float
    longitude: float
    sog_knots: float
    cog_deg: float
    is_interpolated: bool       # False if timestamp matches an original AIS observation
    is_valid: bool              # False if target falls in an unobserved gap > max_gap_seconds
    gap_duration_seconds: float # Elapsed time between surrounding observations
    preceding_position: Optional[AISPosition] = None
    following_position: Optional[AISPosition] = None


@dataclass
class CorridorEncounterStep:
    """Encounter evaluation at a discrete Model 2 hindcast timestamp."""
    hours_offset: float         # e.g. 0.0, -6.0, -12.0 ... -48.0
    timestamp: datetime
    hindcast_centroid_lat: float
    hindcast_centroid_lon: float
    hindcast_ellipse: SearchEllipse
    vessel_lat: Optional[float]
    vessel_lon: Optional[float]
    vessel_sog: Optional[float]
    vessel_cog: Optional[float]
    distance_km: Optional[float]
    normalized_distance: Optional[float] # distance / uncertainty_radius_km
    is_inside_ellipse: bool
    is_valid_observation: bool           # True if vessel has valid observation or valid short-gap interpolation
    is_interpolated: bool


@dataclass
class VesselCorridorCorrelation:
    """
    Comprehensive corridor correlation assessment for a candidate vessel.
    Contains all physical spatiotemporal metrics required for Phase D attribution scoring.
    """
    mmsi: str
    identity: VesselIdentity
    has_temporal_overlap: bool
    intersects_corridor: bool             # True if vessel was inside 95% search ellipse at any point
    min_cpa_distance_km: float            # Minimum distance to hindcast centerline
    min_cpa_time: datetime                # Timestamp of closest point of approach
    min_cpa_hours_offset: float           # Hindcast step offset at CPA (e.g. -12.0h)
    min_cpa_normalized_distance: float    # CPA distance / uncertainty_radius_km
    is_cpa_inside_search_cone: bool       # True if CPA is within the 95% uncertainty envelope
    is_cpa_interpolated: bool             # True if CPA was evaluated on an interpolated segment
    is_cpa_valid: bool                    # False if CPA fell in a data void > 60 min
    corridor_dwell_steps: int             # Number of discrete hindcast steps vessel was inside the cone
    corridor_overlap_fraction: float      # Fraction of evaluated valid steps inside the cone
    vessel_sog_at_cpa: Optional[float]    # Speed Over Ground at CPA
    vessel_cog_at_cpa: Optional[float]    # Course Over Ground at CPA
    closest_hindcast_ellipse: SearchEllipse
    encounter_steps: List[CorridorEncounterStep]
    data_quality: AISDataQuality
    has_gap_near_cpa: bool = False        # True if a >60 min gap occurred within +/- 2h of CPA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mmsi": self.mmsi,
            "identity": self.identity.to_dict(),
            "has_temporal_overlap": self.has_temporal_overlap,
            "intersects_corridor": self.intersects_corridor,
            "min_cpa_distance_km": round(self.min_cpa_distance_km, 3),
            "min_cpa_time": self.min_cpa_time.isoformat(),
            "min_cpa_hours_offset": round(self.min_cpa_hours_offset, 2),
            "min_cpa_normalized_distance": round(self.min_cpa_normalized_distance, 3),
            "is_cpa_inside_search_cone": self.is_cpa_inside_search_cone,
            "is_cpa_interpolated": self.is_cpa_interpolated,
            "is_cpa_valid": self.is_cpa_valid,
            "corridor_dwell_steps": self.corridor_dwell_steps,
            "corridor_overlap_fraction": round(self.corridor_overlap_fraction, 3),
            "vessel_sog_at_cpa": round(self.vessel_sog_at_cpa, 2) if self.vessel_sog_at_cpa is not None else None,
            "vessel_cog_at_cpa": round(self.vessel_cog_at_cpa, 1) if self.vessel_cog_at_cpa is not None else None,
            "closest_hindcast_ellipse": self.closest_hindcast_ellipse.to_dict(),
            "has_gap_near_cpa": self.has_gap_near_cpa,
            "data_quality": self.data_quality.to_dict()
        }

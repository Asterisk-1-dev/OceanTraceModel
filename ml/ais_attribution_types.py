"""
OceanTrace — AIS Attribution Types & Data Contracts
Defines canonical dataclasses and enums for transparent, explainable vessel attribution evidence scoring,
confidence classification, reason codes, and ranked incident results.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime
from typing import List, Optional, Dict, Any

from ml.ais_types import VesselIdentity, AISDataQuality
from ml.drift_types import SearchEllipse


class AttributionCategory(str, Enum):
    """Categorical heuristic classification based on final Attribution Evidence Score."""
    STRONG = "STRONG"                       # 75.0 - 100.0
    MODERATE = "MODERATE"                   # 45.0 - 74.9
    WEAK = "WEAK"                           # 15.0 - 44.9
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"  # < 15.0


class ConfidenceLevel(str, Enum):
    """Data and observation confidence level separate from attribution evidence score."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ReasonCode(str, Enum):
    """Stable, machine-readable reason codes explaining attribution evidence."""
    CLOSE_SPATIAL_MATCH = "CLOSE_SPATIAL_MATCH"
    CORRIDOR_OVERLAP = "CORRIDOR_OVERLAP"
    STRONG_TEMPORAL_ALIGNMENT = "STRONG_TEMPORAL_ALIGNMENT"
    COG_ALIGNMENT = "COG_ALIGNMENT"
    SPEED_CONSISTENCY = "SPEED_CONSISTENCY"
    LARGE_AIS_GAP = "LARGE_AIS_GAP"
    SPARSE_AIS = "SPARSE_AIS"
    INTERPOLATION_DEPENDENT = "INTERPOLATION_DEPENDENT"
    WEAK_SPATIAL_MATCH = "WEAK_SPATIAL_MATCH"
    WEAK_TEMPORAL_ALIGNMENT = "WEAK_TEMPORAL_ALIGNMENT"
    MISSING_COG = "MISSING_COG"
    MISSING_SOG = "MISSING_SOG"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass
class AttributionEvidence:
    """Measurable, bounded evidence features extracted from vessel corridor correlation."""
    mmsi: str
    identity: VesselIdentity
    # Feature scores [0.0, 1.0]
    s_dist: float
    s_overlap: float
    s_cog: float
    s_sog: float
    s_time: float
    # Weights applied
    w_spatial: float = 0.50
    w_corridor: float = 0.20
    w_course: float = 0.15
    w_speed: float = 0.15
    w_prior: float = 1.00  # Default neutral prior
    # Physical encounter metrics
    min_cpa_distance_km: float = 0.0
    min_cpa_normalized_distance: float = 0.0
    min_cpa_time: Optional[datetime] = None
    min_cpa_hours_offset: float = 0.0
    corridor_overlap_fraction: float = 0.0
    corridor_dwell_steps: int = 0
    vessel_sog_at_cpa: Optional[float] = None
    vessel_cog_at_cpa: Optional[float] = None
    closest_hindcast_ellipse: Optional[SearchEllipse] = None
    # Quality and gap flags
    is_cpa_interpolated: bool = False
    is_cpa_valid: bool = True
    has_gap_near_cpa: bool = False
    missing_fields: List[str] = field(default_factory=list)
    data_quality: Optional[AISDataQuality] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mmsi": self.mmsi,
            "identity": self.identity.to_dict(),
            "features": {
                "s_dist": round(self.s_dist, 4),
                "s_overlap": round(self.s_overlap, 4),
                "s_cog": round(self.s_cog, 4),
                "s_sog": round(self.s_sog, 4),
                "s_time": round(self.s_time, 4),
                "w_prior": round(self.w_prior, 2)
            },
            "metrics": {
                "min_cpa_distance_km": round(self.min_cpa_distance_km, 3),
                "min_cpa_normalized_distance": round(self.min_cpa_normalized_distance, 3),
                "min_cpa_time": self.min_cpa_time.isoformat() if self.min_cpa_time else None,
                "min_cpa_hours_offset": round(self.min_cpa_hours_offset, 2),
                "corridor_overlap_fraction": round(self.corridor_overlap_fraction, 3),
                "corridor_dwell_steps": self.corridor_dwell_steps,
                "vessel_sog_at_cpa": round(self.vessel_sog_at_cpa, 2) if self.vessel_sog_at_cpa is not None else None,
                "vessel_cog_at_cpa": round(self.vessel_cog_at_cpa, 1) if self.vessel_cog_at_cpa is not None else None,
                "is_cpa_interpolated": self.is_cpa_interpolated,
                "is_cpa_valid": self.is_cpa_valid,
                "has_gap_near_cpa": self.has_gap_near_cpa
            }
        }


@dataclass
class AttributionScore:
    """Evaluated attribution result for an individual candidate vessel."""
    mmsi: str
    identity: VesselIdentity
    overall_score: float              # [0.0, 100.0] Attribution Evidence Score
    confidence: ConfidenceLevel
    category: AttributionCategory
    evidence: AttributionEvidence
    reason_codes: List[ReasonCode]
    explanation: str
    rank: int = 0

    def __post_init__(self):
        if not (0.0 <= self.overall_score <= 100.0):
            raise ValueError(f"overall_score must be in [0.0, 100.0], got {self.overall_score}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mmsi": self.mmsi,
            "vessel_name": self.identity.name,
            "vessel_type": self.identity.vessel_type,
            "imo": self.identity.imo,
            "rank": self.rank,
            "overall_score": round(self.overall_score, 2),
            "confidence": self.confidence.value,
            "category": self.category.value,
            "reason_codes": [r.value for r in self.reason_codes],
            "explanation": self.explanation,
            "evidence": self.evidence.to_dict()
        }


@dataclass
class AttributionResult:
    """Complete ranked incident result for a spill correlation investigation."""
    incident_id: str
    scoring_timestamp: datetime
    scoring_version: str
    candidate_count: int
    ranked_candidates: List[AttributionScore]
    methodology: Dict[str, Any]
    disclaimer: str = (
        "CRITICAL LEGAL & SCIENTIFIC NOTICE: The Attribution Evidence Score is an analytical "
        "decision-support metric representing physical trajectory and temporal coincidence with "
        "reconstructed slick drift models. It is NOT a mathematical probability of guilt, legal "
        "proof of discharge, or liability determination."
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "scoring_timestamp": self.scoring_timestamp.isoformat(),
            "scoring_version": self.scoring_version,
            "candidate_count": self.candidate_count,
            "ranked_candidates": [c.to_dict() for c in self.ranked_candidates],
            "methodology": self.methodology,
            "disclaimer": self.disclaimer
        }

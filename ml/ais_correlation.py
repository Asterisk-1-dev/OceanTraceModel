"""
OceanTrace Model 2 — AIS Correlation & Forensic Attribution Module
Calculates spatial/temporal proximity between historical vessel AIS tracks and Model 2 hindcast search cones,
producing ranked responsibility scores for suspected discharge vessels.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import math

from ml.drift_types import (
    CandidateVesselTrack,
    VesselAttributionScore,
    TrajectoryPackage,
    TrajectoryStep,
    parse_utc_iso
)
from ml.drift_engine import lat_lon_distance_km


# Standard vessel type prior weights for oil discharge probability
VESSEL_TYPE_PRIORS = {
    "crude oil tanker": 1.00,
    "oil products tanker": 0.95,
    "chemical tanker": 0.90,
    "cargo": 0.80,
    "container ship": 0.75,
    "bulk carrier": 0.75,
    "tug": 0.60,
    "fishing": 0.55,
    "passenger": 0.40,
    "pleasure craft": 0.30,
    "unknown": 0.65
}


def interpolate_vessel_position_at_time(
    track_points: List[Dict[str, Any]],
    target_utc: datetime
) -> Optional[Tuple[float, float, float]]:
    """
    Linearly interpolates vessel (lat, lon, sog) at a specific target datetime.
    Returns None if target_utc is outside the vessel's recorded track time span.
    """
    if not track_points:
        return None

    # Parse and sort track points by timestamp
    parsed_points = []
    for pt in track_points:
        try:
            t_dt = parse_utc_iso(pt["timestamp"])
            parsed_points.append((t_dt, float(pt["lat"]), float(pt["lon"]), float(pt.get("sog", 0.0))))
        except Exception:
            continue

    parsed_points.sort(key=lambda x: x[0])
    if len(parsed_points) == 0:
        return None

    # Check boundaries
    t_start, t_end = parsed_points[0][0], parsed_points[-1][0]
    if target_utc < t_start or target_utc > t_end:
        # Outside temporal range
        return None

    # Find bounding bracket
    for i in range(len(parsed_points) - 1):
        t1, lat1, lon1, sog1 = parsed_points[i]
        t2, lat2, lon2, sog2 = parsed_points[i + 1]

        if t1 <= target_utc <= t2:
            dt_total = (t2 - t1).total_seconds()
            if dt_total <= 0.0:
                return lat1, lon1, sog1
            fraction = (target_utc - t1).total_seconds() / dt_total
            interp_lat = lat1 + fraction * (lat2 - lat1)
            interp_lon = lon1 + fraction * (lon2 - lon1)
            interp_sog = sog1 + fraction * (sog2 - sog1)
            return interp_lat, interp_lon, interp_sog

    return parsed_points[-1][1], parsed_points[-1][2], parsed_points[-1][3]


class AISAttributionEngine:
    """
    Computes spatiotemporal correlation between candidate vessel tracks and Model 2 hindcast search cones.
    """

    def __init__(
        self,
        max_search_radius_factor: float = 2.0,  # Query bracket multiple of uncertainty radius
        temporal_tolerance_minutes: float = 30.0
    ):
        self.max_radius_factor = max_search_radius_factor
        self.time_tol_sec = temporal_tolerance_minutes * 60.0

    def evaluate_vessel(
        self,
        vessel: CandidateVesselTrack,
        hindcast: TrajectoryPackage
    ) -> VesselAttributionScore:
        """
        Evaluates a single candidate vessel against all hindcast steps.
        Calculates the Closest Point of Approach (CPA) and forensic responsibility score.
        """
        best_distance_km = float("inf")
        best_step: Optional[TrajectoryStep] = None
        best_match_time = ""
        is_inside = False

        v_type_clean = vessel.vessel_type.lower().strip()
        v_prior = VESSEL_TYPE_PRIORS.get(v_type_clean, 0.65)

        for step in hindcast.steps:
            step_dt = parse_utc_iso(step.timestamp)
            interp = interpolate_vessel_position_at_time(vessel.track_points, step_dt)

            if interp is not None:
                v_lat, v_lon, _ = interp
                dist_km = lat_lon_distance_km(v_lat, v_lon, step.centroid_lat, step.centroid_lon)

                if dist_km < best_distance_km:
                    best_distance_km = dist_km
                    best_step = step
                    best_match_time = step.timestamp
                    is_inside = (dist_km <= step.ellipse.uncertainty_radius_km)

        if best_step is None:
            # Fallback: Compare against earliest/closest point
            best_distance_km = 999.0
            best_step = hindcast.steps[-1]
            best_match_time = best_step.timestamp

        # Compute Gaussian decay spatial score based on hindcast uncertainty radius
        sigma_km = max(0.5, best_step.ellipse.uncertainty_radius_km)
        spatial_score = math.exp(-0.5 * ((best_distance_km / sigma_km) ** 2))

        # Temporal score is 1.0 for synchronized step evaluation
        temporal_score = 1.0

        # Normalized Responsibility Score [0.0, 100.0%]
        raw_score = spatial_score * temporal_score * v_prior
        responsibility_pct = round(float(raw_score * 100.0), 2)

        return VesselAttributionScore(
            mmsi=vessel.mmsi,
            vessel_name=vessel.vessel_name,
            vessel_type=vessel.vessel_type,
            closest_approach_distance_km=round(best_distance_km, 3),
            closest_approach_time=best_match_time,
            hindcast_step_offset_hours=best_step.hours_offset,
            hindcast_uncertainty_radius_km=round(best_step.ellipse.uncertainty_radius_km, 3),
            is_inside_uncertainty_cone=is_inside,
            spatial_score=round(spatial_score, 4),
            temporal_score=round(temporal_score, 4),
            vessel_prior_weight=round(v_prior, 2),
            responsibility_score=responsibility_pct
        )

    def rank_candidate_vessels(
        self,
        candidate_vessels: List[CandidateVesselTrack],
        hindcast: TrajectoryPackage
    ) -> List[VesselAttributionScore]:
        """
        Ranks all candidate vessels by responsibility score descending.
        """
        scores = [self.evaluate_vessel(v, hindcast) for v in candidate_vessels]
        scores.sort(key=lambda s: s.responsibility_score, reverse=True)

        for rank_idx, score in enumerate(scores, start=1):
            score.attribution_rank = rank_idx

        return scores

"""
OceanTrace — AIS Corridor Correlation Engine
Implements two-stage candidate filtering and spatiotemporal correlation
against Model 2 dynamic backward hindcast search corridors.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
import math

from ml.ais_types import VesselTrack, AISPosition, parse_utc_timestamp
from ml.drift_types import TrajectoryPackage, TrajectoryStep, SearchEllipse
from ml.drift_engine import lat_lon_distance_km
from ml.ais_correlation_types import (
    CorridorEncounterStep,
    VesselCorridorCorrelation,
    InterpolatedPosition
)
from ml.ais_interpolation import interpolate_vessel_track


def is_point_inside_ellipse(
    pt_lat: float,
    pt_lon: float,
    center_lat: float,
    center_lon: float,
    ellipse: SearchEllipse
) -> Tuple[bool, float]:
    """
    Evaluates whether (pt_lat, pt_lon) is within the 95% confidence covariance ellipse.
    Returns (is_inside, normalized_distance).
    """
    dist_km = lat_lon_distance_km(pt_lat, pt_lon, center_lat, center_lon)
    radius_km = max(0.50, ellipse.uncertainty_radius_km)
    normalized_dist = dist_km / radius_km
    is_inside = (normalized_dist <= 1.0)
    return is_inside, normalized_dist


class AISCorridorCorrelator:
    """
    Two-stage Spatiotemporal Correlator:
    Stage 1: Coarse bounding box and temporal overlap filter.
    Stage 2: Precise correlation against dynamic Model 2 search ellipses with gap tracking.
    """

    def __init__(
        self,
        max_interpolation_gap_minutes: float = 60.0,
        spatial_padding_km: float = 25.0
    ):
        self.max_gap_sec = max_interpolation_gap_minutes * 60.0
        self.padding_km = spatial_padding_km

    def _compute_hindcast_envelope(self, hindcast: TrajectoryPackage) -> Tuple[datetime, datetime, float, float, float, float]:
        """Calculates temporal window and expanded spatial bounding box covering the entire hindcast."""
        steps = hindcast.steps
        if not steps:
            raise ValueError("Hindcast steps list cannot be empty.")

        timestamps = [parse_utc_timestamp(s.timestamp) for s in steps]
        t_start = min(timestamps)
        t_end = max(timestamps)

        lats = [s.centroid_lat for s in steps]
        lons = [s.centroid_lon for s in steps]
        max_radius = max([s.ellipse.uncertainty_radius_km for s in steps])

        deg_margin = (max_radius + self.padding_km) / 111.0
        min_lat = min(lats) - deg_margin
        max_lat = max(lats) + deg_margin
        min_lon = min(lons) - deg_margin
        max_lon = max(lons) + deg_margin

        return t_start, t_end, min_lat, max_lat, min_lon, max_lon

    def filter_candidates_coarse(
        self,
        tracks: List[VesselTrack],
        hindcast: TrajectoryPackage
    ) -> List[VesselTrack]:
        """
        Stage 1: Discards vessels that have no temporal overlap or whose recorded pings
        fall entirely outside the expanded spatial bounding envelope.
        """
        t_start, t_end, min_lat, max_lat, min_lon, max_lon = self._compute_hindcast_envelope(hindcast)
        candidates: List[VesselTrack] = []

        for track in tracks:
            # Check temporal overlap between track [t_v_start, t_v_end] and hindcast [t_start, t_end]
            if track.end_time < t_start or track.start_time > t_end:
                continue

            # Check if any observation enters the expanded spatial envelope
            has_spatial_overlap = any(
                (min_lat <= p.latitude <= max_lat and min_lon <= p.longitude <= max_lon)
                for p in track.positions
            )
            if has_spatial_overlap:
                candidates.append(track)

        return candidates

    def correlate_vessel(
        self,
        track: VesselTrack,
        hindcast: TrajectoryPackage
    ) -> VesselCorridorCorrelation:
        """
        Stage 2: Evaluates a candidate vessel's track against all discrete hindcast steps.
        """
        steps = hindcast.steps
        encounter_steps: List[CorridorEncounterStep] = []

        min_cpa_distance = float("inf")
        best_encounter: Optional[CorridorEncounterStep] = None
        dwell_count = 0
        valid_eval_count = 0

        # Evaluate at each discrete hindcast timestamp
        for step in steps:
            step_dt = parse_utc_timestamp(step.timestamp)
            interp = interpolate_vessel_track(track, step_dt, max_gap_seconds=self.max_gap_sec)

            if interp is None:
                # Outside vessel track lifespan
                enc = CorridorEncounterStep(
                    hours_offset=step.hours_offset,
                    timestamp=step_dt,
                    hindcast_centroid_lat=step.centroid_lat,
                    hindcast_centroid_lon=step.centroid_lon,
                    hindcast_ellipse=step.ellipse,
                    vessel_lat=None,
                    vessel_lon=None,
                    vessel_sog=None,
                    vessel_cog=None,
                    distance_km=None,
                    normalized_distance=None,
                    is_inside_ellipse=False,
                    is_valid_observation=False,
                    is_interpolated=False
                )
            else:
                dist_km = lat_lon_distance_km(interp.latitude, interp.longitude, step.centroid_lat, step.centroid_lon)
                is_inside, norm_dist = is_point_inside_ellipse(
                    interp.latitude, interp.longitude,
                    step.centroid_lat, step.centroid_lon,
                    step.ellipse
                )

                enc = CorridorEncounterStep(
                    hours_offset=step.hours_offset,
                    timestamp=step_dt,
                    hindcast_centroid_lat=step.centroid_lat,
                    hindcast_centroid_lon=step.centroid_lon,
                    hindcast_ellipse=step.ellipse,
                    vessel_lat=interp.latitude,
                    vessel_lon=interp.longitude,
                    vessel_sog=interp.sog_knots,
                    vessel_cog=interp.cog_deg,
                    distance_km=round(dist_km, 3),
                    normalized_distance=round(norm_dist, 3),
                    is_inside_ellipse=is_inside,
                    is_valid_observation=interp.is_valid,
                    is_interpolated=interp.is_interpolated
                )

                if interp.is_valid:
                    valid_eval_count += 1
                    if is_inside:
                        dwell_count += 1

                if dist_km < min_cpa_distance:
                    min_cpa_distance = dist_km
                    best_encounter = enc

            encounter_steps.append(enc)

        # Fallback if track had zero temporal overlap with any hindcast step
        if best_encounter is None or best_encounter.distance_km is None:
            # Fallback to earliest step
            best_encounter = encounter_steps[-1]
            min_cpa_distance = 999.0
            norm_cpa = 999.0
            is_cpa_inside = False
            is_cpa_interp = False
            is_cpa_valid = False
            sog_cpa = None
            cog_cpa = None
        else:
            norm_cpa = best_encounter.normalized_distance
            is_cpa_inside = best_encounter.is_inside_ellipse
            is_cpa_interp = best_encounter.is_interpolated
            is_cpa_valid = best_encounter.is_valid_observation
            sog_cpa = best_encounter.vessel_sog
            cog_cpa = best_encounter.vessel_cog

        overlap_fraction = (dwell_count / valid_eval_count) if valid_eval_count > 0 else 0.0

        # Check if an invalid gap > 60 min occurred within +/- 2 hours of CPA
        cpa_dt = best_encounter.timestamp
        has_gap_near_cpa = False
        for pos_idx in range(len(track.positions) - 1):
            p1 = track.positions[pos_idx]
            p2 = track.positions[pos_idx + 1]
            gap_dur = (p2.timestamp - p1.timestamp).total_seconds()
            if gap_dur > 3600.0:
                # Check proximity of gap interval [p1.ts, p2.ts] to CPA timestamp
                if (p1.timestamp - timedelta(hours=2)) <= cpa_dt <= (p2.timestamp + timedelta(hours=2)):
                    has_gap_near_cpa = True
                    break

        return VesselCorridorCorrelation(
            mmsi=track.identity.mmsi,
            identity=track.identity,
            has_temporal_overlap=(valid_eval_count > 0),
            intersects_corridor=(dwell_count > 0),
            min_cpa_distance_km=round(min_cpa_distance, 3),
            min_cpa_time=best_encounter.timestamp,
            min_cpa_hours_offset=best_encounter.hours_offset,
            min_cpa_normalized_distance=round(norm_cpa, 3),
            is_cpa_inside_search_cone=is_cpa_inside,
            is_cpa_interpolated=is_cpa_interp,
            is_cpa_valid=is_cpa_valid,
            corridor_dwell_steps=dwell_count,
            corridor_overlap_fraction=round(overlap_fraction, 3),
            vessel_sog_at_cpa=sog_cpa,
            vessel_cog_at_cpa=cog_cpa,
            closest_hindcast_ellipse=best_encounter.hindcast_ellipse,
            encounter_steps=encounter_steps,
            data_quality=track.data_quality,
            has_gap_near_cpa=has_gap_near_cpa
        )

    def correlate_fleet(
        self,
        tracks: List[VesselTrack],
        hindcast: TrajectoryPackage
    ) -> List[VesselCorridorCorrelation]:
        """Executes Stage 1 filtering followed by Stage 2 correlation for all candidate vessels."""
        candidates = self.filter_candidates_coarse(tracks, hindcast)
        correlations = [self.correlate_vessel(c, hindcast) for c in candidates]
        # Sort by minimum CPA ascending
        correlations.sort(key=lambda c: c.min_cpa_distance_km)
        return correlations

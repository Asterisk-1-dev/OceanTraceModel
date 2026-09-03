"""
OceanTrace — AIS Track Interpolation Engine
Interpolates vessel positions along chronological VesselTrack trajectories.
Preserves authentic observations, applies geodesic-compatible interpolation for short gaps,
and strictly enforces a 60-minute maximum interpolation limit.
"""

from datetime import datetime, timezone
from typing import List, Optional
import math

from ml.ais_types import AISPosition, VesselTrack, parse_utc_timestamp
from ml.ais_correlation_types import InterpolatedPosition


def interpolate_angle_deg(a1: float, a2: float, fraction: float) -> float:
    """Interpolates circular angles in degrees taking the shortest angular path."""
    diff = (a2 - a1 + 180.0) % 360.0 - 180.0
    return (a1 + fraction * diff) % 360.0


def interpolate_vessel_track(
    track: VesselTrack,
    target_time: datetime,
    max_gap_seconds: float = 3600.0  # 60 minutes
) -> Optional[InterpolatedPosition]:
    """
    Evaluates a vessel's position and kinematics at target_time.

    Rules:
    1. Timestamps outside the observed track range are NOT extrapolated (returns None).
    2. Exact observation matches are preserved without interpolation.
    3. Duplicate observations at the same timestamp are deduplicated deterministically.
    4. Gaps <= max_gap_seconds (default 60 min) are interpolated using geodesic-compatible linear scaling.
    5. Gaps > max_gap_seconds are flagged as invalid (is_valid=False) to prevent fictitious dead reckoning.
    """
    target_utc = parse_utc_timestamp(target_time)
    positions = track.positions

    if not positions:
        return None

    # Boundary check: strictly no extrapolation outside track range
    t_start = positions[0].timestamp
    t_end = positions[-1].timestamp
    if target_utc < t_start or target_utc > t_end:
        return None

    # Check for exact matches
    for pos in positions:
        if pos.timestamp == target_utc:
            return InterpolatedPosition(
                timestamp=target_utc,
                latitude=pos.latitude,
                longitude=pos.longitude,
                sog_knots=pos.sog_knots,
                cog_deg=pos.cog_deg,
                is_interpolated=False,
                is_valid=True,
                gap_duration_seconds=0.0,
                preceding_position=pos,
                following_position=pos
            )

    # Find bracket [p1, p2] where p1.timestamp < target_utc < p2.timestamp
    for i in range(len(positions) - 1):
        p1 = positions[i]
        p2 = positions[i + 1]

        if p1.timestamp <= target_utc <= p2.timestamp:
            gap_sec = (p2.timestamp - p1.timestamp).total_seconds()
            if gap_sec <= 0.0:
                # Handle identical timestamps deterministically by returning p1
                return InterpolatedPosition(
                    timestamp=target_utc,
                    latitude=p1.latitude,
                    longitude=p1.longitude,
                    sog_knots=p1.sog_knots,
                    cog_deg=p1.cog_deg,
                    is_interpolated=False,
                    is_valid=True,
                    gap_duration_seconds=0.0,
                    preceding_position=p1,
                    following_position=p2
                )

            # Check if gap exceeds maximum allowable interpolation horizon (60 minutes)
            if gap_sec > max_gap_seconds:
                return InterpolatedPosition(
                    timestamp=target_utc,
                    latitude=p1.latitude,
                    longitude=p1.longitude,
                    sog_knots=p1.sog_knots,
                    cog_deg=p1.cog_deg,
                    is_interpolated=True,
                    is_valid=False,  # Flagged invalid due to unobserved data void
                    gap_duration_seconds=gap_sec,
                    preceding_position=p1,
                    following_position=p2
                )

            # Valid short gap (<= 60 min): perform linear interpolation
            fraction = (target_utc - p1.timestamp).total_seconds() / gap_sec

            # Latitude interpolation
            lat_interp = p1.latitude + fraction * (p2.latitude - p1.latitude)

            # Longitude interpolation handling antimeridian wrapping
            d_lon = (p2.longitude - p1.longitude + 180.0) % 360.0 - 180.0
            lon_interp = (p1.longitude + fraction * d_lon + 180.0) % 360.0 - 180.0

            # Kinematics interpolation
            sog_interp = p1.sog_knots + fraction * (p2.sog_knots - p1.sog_knots)
            cog_interp = interpolate_angle_deg(p1.cog_deg, p2.cog_deg, fraction)

            return InterpolatedPosition(
                timestamp=target_utc,
                latitude=round(lat_interp, 6),
                longitude=round(lon_interp, 6),
                sog_knots=round(sog_interp, 2),
                cog_deg=round(cog_interp, 1),
                is_interpolated=True,
                is_valid=True,
                gap_duration_seconds=gap_sec,
                preceding_position=p1,
                following_position=p2
            )

    return None

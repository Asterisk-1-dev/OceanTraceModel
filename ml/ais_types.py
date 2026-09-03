"""
OceanTrace — Canonical AIS Domain Types & Data Contracts
Implements standardized data structures for AIS position reports, vessel identity,
data quality audits, ordered vessel tracks, and spatiotemporal AIS queries.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import math


def parse_utc_timestamp(ts: Any) -> datetime:
    """
    Parses a timestamp input and guarantees a timezone-aware UTC datetime.
    Rejects naive datetimes and malformed strings.
    """
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            raise ValueError(f"Naive datetime {ts} is not allowed; must be timezone-aware (UTC).")
        return ts.astimezone(timezone.utc)
    elif isinstance(ts, str):
        if not ts.strip():
            raise ValueError("Timestamp string cannot be empty.")
        clean_str = ts.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(clean_str)
        except Exception as e:
            raise ValueError(f"Invalid ISO8601 timestamp string '{ts}': {e}")
        if dt.tzinfo is None:
            raise ValueError(f"Timestamp '{ts}' lacks timezone offset; must be timezone-aware (UTC).")
        return dt.astimezone(timezone.utc)
    elif isinstance(ts, (int, float)):
        # Epoch timestamp in seconds
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        raise TypeError(f"Unsupported timestamp type: {type(ts)}")


def validate_mmsi(mmsi: str) -> str:
    """
    Validates that MMSI is a standard 9-digit maritime numerical string.
    """
    if not isinstance(mmsi, str):
        raise TypeError(f"MMSI must be a string, got {type(mmsi).__name__}")
    clean_mmsi = mmsi.strip()
    if len(clean_mmsi) != 9 or not clean_mmsi.isdigit():
        raise ValueError(f"Invalid MMSI: '{mmsi}'. Must be exactly 9 numeric digits.")
    return clean_mmsi


@dataclass
class AISPosition:
    """
    Canonical position report for an individual AIS transponder transmission (Messages 1, 2, 3).
    """
    mmsi: str
    timestamp: datetime
    latitude: float
    longitude: float
    sog_knots: float
    cog_deg: float
    heading_deg: Optional[float] = None
    nav_status: Optional[int] = None
    source_provider: str = "unknown"

    def __post_init__(self):
        # 1. MMSI validation
        self.mmsi = validate_mmsi(self.mmsi)

        # 2. Timestamp validation (must be timezone-aware UTC)
        self.timestamp = parse_utc_timestamp(self.timestamp)

        # 3. Coordinate validation
        if not isinstance(self.latitude, (int, float)) or math.isnan(self.latitude):
            raise ValueError(f"Invalid latitude value: {self.latitude}")
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(f"Latitude out of bounds [-90, 90]: {self.latitude}")

        if not isinstance(self.longitude, (int, float)) or math.isnan(self.longitude):
            raise ValueError(f"Invalid longitude value: {self.longitude}")
        if not (-180.0 <= self.longitude <= 180.0):
            # Normalize longitude to [-180, 180] if slightly offset, but reject extreme values
            if -360.0 <= self.longitude <= 360.0:
                self.longitude = (self.longitude + 180.0) % 360.0 - 180.0
            else:
                raise ValueError(f"Longitude out of bounds [-180, 180]: {self.longitude}")

        # 4. SOG validation (Knots)
        if not isinstance(self.sog_knots, (int, float)) or math.isnan(self.sog_knots):
            raise ValueError(f"Invalid SOG value: {self.sog_knots}")
        if not (0.0 <= self.sog_knots <= 102.2):
            raise ValueError(f"SOG out of standard range [0.0, 102.2 knots]: {self.sog_knots}")

        # 5. COG validation (Degrees)
        if not isinstance(self.cog_deg, (int, float)) or math.isnan(self.cog_deg):
            raise ValueError(f"Invalid COG value: {self.cog_deg}")
        if not (0.0 <= self.cog_deg < 360.0):
            if 0.0 <= self.cog_deg <= 360.0:
                self.cog_deg = self.cog_deg % 360.0
            else:
                raise ValueError(f"COG out of valid range [0, 360 degrees): {self.cog_deg}")

        # 6. Optional Heading validation (0 - 359, 511 = unavailable)
        if self.heading_deg is not None:
            if not isinstance(self.heading_deg, (int, float)) or math.isnan(self.heading_deg):
                raise ValueError(f"Invalid heading value: {self.heading_deg}")
            if not (0.0 <= self.heading_deg <= 359.0 or self.heading_deg == 511.0):
                raise ValueError(f"Heading out of standard range [0, 359] (or 511 for unavailable): {self.heading_deg}")

        # 7. Optional Nav Status (0 - 15)
        if self.nav_status is not None:
            if not isinstance(self.nav_status, int) or not (0 <= self.nav_status <= 15):
                raise ValueError(f"Navigational status must be integer in [0, 15], got {self.nav_status}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mmsi": self.mmsi,
            "timestamp": self.timestamp.isoformat(),
            "latitude": round(self.latitude, 6),
            "longitude": round(self.longitude, 6),
            "sog_knots": round(self.sog_knots, 2),
            "cog_deg": round(self.cog_deg, 1),
            "heading_deg": round(self.heading_deg, 1) if self.heading_deg is not None else None,
            "nav_status": self.nav_status,
            "source_provider": self.source_provider
        }


@dataclass
class VesselIdentity:
    """
    Static vessel metadata and voyage information (Messages 5, 24).
    """
    mmsi: str
    imo: Optional[str] = None
    name: Optional[str] = None
    callsign: Optional[str] = None
    vessel_type: str = "Unknown"
    vessel_type_code: Optional[int] = None
    flag_country: Optional[str] = None
    length_m: Optional[float] = None
    beam_m: Optional[float] = None

    def __post_init__(self):
        self.mmsi = validate_mmsi(self.mmsi)

        if self.imo is not None:
            clean_imo = str(self.imo).strip().upper().replace("IMO", "").strip()
            if not (len(clean_imo) == 7 and clean_imo.isdigit()):
                raise ValueError(f"Invalid IMO number: '{self.imo}'. Must be a 7-digit number.")
            self.imo = clean_imo

        if self.name is not None:
            self.name = self.name.strip()

        if self.length_m is not None and self.length_m < 0.0:
            raise ValueError(f"Vessel length cannot be negative: {self.length_m}")
        if self.beam_m is not None and self.beam_m < 0.0:
            raise ValueError(f"Vessel beam cannot be negative: {self.beam_m}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AISDataQuality:
    """
    Data quality metrics and integrity audit for an evaluated vessel track.
    """
    observation_count: int
    median_interval_min: float
    max_temporal_gap_hours: float
    has_suspicious_gap: bool = False
    interpolation_fraction: float = 0.0
    missing_fields: List[str] = field(default_factory=list)
    source_provider: str = "unknown"

    def __post_init__(self):
        if self.observation_count < 0:
            raise ValueError("observation_count cannot be negative.")
        if self.median_interval_min < 0.0:
            raise ValueError("median_interval_min cannot be negative.")
        if self.max_temporal_gap_hours < 0.0:
            raise ValueError("max_temporal_gap_hours cannot be negative.")
        if not (0.0 <= self.interpolation_fraction <= 1.0):
            raise ValueError(f"interpolation_fraction must be in [0.0, 1.0], got {self.interpolation_fraction}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VesselTrack:
    """
    Chronologically ordered sequence of AIS position reports for a specific vessel.
    """
    identity: VesselIdentity
    positions: List[AISPosition]
    data_quality: AISDataQuality
    source_provider: str = "unknown"

    def __post_init__(self):
        if not self.positions:
            raise ValueError("VesselTrack positions list cannot be empty.")

        # Validate that all positions match the vessel MMSI
        for idx, pos in enumerate(self.positions):
            if pos.mmsi != self.identity.mmsi:
                raise ValueError(f"Position at index {idx} MMSI '{pos.mmsi}' does not match track identity MMSI '{self.identity.mmsi}'.")

        # Enforce strict chronological ordering (ascending by timestamp)
        for i in range(len(self.positions) - 1):
            if self.positions[i].timestamp > self.positions[i + 1].timestamp:
                raise ValueError(
                    f"VesselTrack positions are out of chronological order: "
                    f"index {i} ({self.positions[i].timestamp}) > index {i+1} ({self.positions[i+1].timestamp})"
                )

    @property
    def start_time(self) -> datetime:
        return self.positions[0].timestamp

    @property
    def end_time(self) -> datetime:
        return self.positions[-1].timestamp

    @property
    def duration_hours(self) -> float:
        return (self.end_time - self.start_time).total_seconds() / 3600.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "positions": [p.to_dict() for p in self.positions],
            "data_quality": self.data_quality.to_dict(),
            "source_provider": self.source_provider,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_hours": round(self.duration_hours, 2)
        }


@dataclass
class AISQuery:
    """
    Structured spatiotemporal query contract passed to any AISProvider.
    """
    start_time: datetime
    end_time: datetime
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    mmsi_filter: Optional[List[str]] = None

    def __post_init__(self):
        # 1. Parse and validate timestamps
        self.start_time = parse_utc_timestamp(self.start_time)
        self.end_time = parse_utc_timestamp(self.end_time)

        if self.start_time >= self.end_time:
            raise ValueError(f"start_time ({self.start_time}) must be strictly before end_time ({self.end_time})")

        # 2. Coordinate bounds validation
        if not (-90.0 <= self.min_lat <= 90.0 and -90.0 <= self.max_lat <= 90.0):
            raise ValueError(f"Latitude bounds must be in [-90, 90]. Got [{self.min_lat}, {self.max_lat}]")
        if self.min_lat > self.max_lat:
            raise ValueError(f"min_lat ({self.min_lat}) cannot exceed max_lat ({self.max_lat})")

        if not (-180.0 <= self.min_lon <= 180.0 and -180.0 <= self.max_lon <= 180.0):
            raise ValueError(f"Longitude bounds must be in [-180, 180]. Got [{self.min_lon}, {self.max_lon}]")
        if self.min_lon > self.max_lon:
            raise ValueError(f"min_lon ({self.min_lon}) cannot exceed max_lon ({self.max_lon})")

        # 3. Optional MMSI filter validation
        if self.mmsi_filter is not None:
            self.mmsi_filter = [validate_mmsi(m) for m in self.mmsi_filter]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "bbox": [self.min_lat, self.max_lat, self.min_lon, self.max_lon],
            "mmsi_filter": self.mmsi_filter
        }

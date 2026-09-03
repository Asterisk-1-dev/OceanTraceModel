"""
OceanTrace — Historical File AIS Data Provider
Loads, validates, and queries historical AIS tracks from local CSV files or SQLite databases.
Supports spatiotemporal bounding box querying, MMSI filtering, and automated track grouping.
"""

import os
import csv
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from ml.ais_types import (
    AISPosition,
    VesselIdentity,
    AISDataQuality,
    VesselTrack,
    AISQuery,
    parse_utc_timestamp,
    validate_mmsi
)
from ml.ais_provider import AISProvider


class HistoricalFileProvider(AISProvider):
    """
    Provider for reading and querying local historical AIS datasets (CSV or SQLite).
    Ensures strict validation, canonical normalization, and zero network dependency.
    """

    def __init__(self, file_path: str, provider_id: Optional[str] = None):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"AIS data file not found: {file_path}")
        self.file_path = os.path.abspath(file_path)
        self._provider_id = provider_id or f"historical_file_{os.path.basename(file_path)}"
        self._positions_cache: Optional[List[AISPosition]] = None
        self._identities_cache: Dict[str, VesselIdentity] = {}

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def _load_csv(self) -> List[AISPosition]:
        """Parses canonical AIS CSV file with strict validation."""
        positions: List[AISPosition] = []
        identities: Dict[str, VesselIdentity] = {}

        with open(self.file_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            # Normalize column names to lowercase stripped strings
            if not reader.fieldnames:
                raise ValueError(f"CSV file '{self.file_path}' has no header row.")

            field_map = {col.strip().lower(): col for col in reader.fieldnames}
            req_cols = ["mmsi", "timestamp", "latitude", "longitude", "sog", "cog"]
            for col in req_cols:
                if col not in field_map:
                    raise ValueError(f"Missing required AIS column '{col}' in '{self.file_path}'. Found: {reader.fieldnames}")

            for line_no, row in enumerate(reader, start=2):
                try:
                    mmsi_raw = row[field_map["mmsi"]]
                    ts_raw = row[field_map["timestamp"]]
                    lat_raw = float(row[field_map["latitude"]])
                    lon_raw = float(row[field_map["longitude"]])
                    sog_raw = float(row[field_map["sog"]])
                    cog_raw = float(row[field_map["cog"]])

                    # Optional fields
                    heading_raw = None
                    if "heading" in field_map and row[field_map["heading"]].strip():
                        heading_raw = float(row[field_map["heading"]])

                    nav_raw = None
                    if "nav_status" in field_map and row[field_map["nav_status"]].strip():
                        nav_raw = int(row[field_map["nav_status"]])

                    pos = AISPosition(
                        mmsi=mmsi_raw,
                        timestamp=parse_utc_timestamp(ts_raw),
                        latitude=lat_raw,
                        longitude=lon_raw,
                        sog_knots=sog_raw,
                        cog_deg=cog_raw,
                        heading_deg=heading_raw,
                        nav_status=nav_raw,
                        source_provider=self._provider_id
                    )
                    positions.append(pos)

                    # Extract identity metadata if present and not yet saved
                    clean_mmsi = pos.mmsi
                    if clean_mmsi not in identities:
                        imo_val = row.get(field_map.get("imo", ""), None)
                        name_val = row.get(field_map.get("vessel_name", field_map.get("name", "")), None)
                        type_val = row.get(field_map.get("vessel_type", ""), "Unknown")
                        identities[clean_mmsi] = VesselIdentity(
                            mmsi=clean_mmsi,
                            imo=imo_val.strip() if (imo_val and imo_val.strip()) else None,
                            name=name_val.strip() if (name_val and name_val.strip()) else None,
                            vessel_type=type_val.strip() if (type_val and type_val.strip()) else "Unknown"
                        )

                except Exception as e:
                    raise ValueError(f"Error parsing row {line_no} in '{self.file_path}': {e}")

        self._identities_cache.update(identities)
        return positions

    def _get_all_positions(self) -> List[AISPosition]:
        if self._positions_cache is None:
            if self.file_path.endswith(".csv"):
                self._positions_cache = self._load_csv()
            else:
                raise NotImplementedError(f"Unsupported file format for '{self.file_path}'. Supported: .csv")
        return self._positions_cache

    def query_positions(self, query: AISQuery) -> List[AISPosition]:
        all_positions = self._get_all_positions()
        filtered: List[AISPosition] = []

        for p in all_positions:
            if query.mmsi_filter and p.mmsi not in query.mmsi_filter:
                continue
            if query.start_time <= p.timestamp <= query.end_time:
                if query.min_lat <= p.latitude <= query.max_lat:
                    if query.min_lon <= p.longitude <= query.max_lon:
                        filtered.append(p)

        filtered.sort(key=lambda p: p.timestamp)
        return filtered

    def query_tracks(self, query: AISQuery) -> List[VesselTrack]:
        matching_positions = self.query_positions(query)
        if not matching_positions:
            return []

        # Group by MMSI
        by_mmsi: Dict[str, List[AISPosition]] = {}
        for p in matching_positions:
            by_mmsi.setdefault(p.mmsi, []).append(p)

        tracks: List[VesselTrack] = []
        for mmsi, positions in by_mmsi.items():
            positions.sort(key=lambda p: p.timestamp)
            identity = self.lookup_vessel(mmsi) or VesselIdentity(mmsi=mmsi)

            obs_count = len(positions)
            gaps = [
                (positions[i+1].timestamp - positions[i].timestamp).total_seconds() / 3600.0
                for i in range(obs_count - 1)
            ]
            max_gap = max(gaps) if gaps else 0.0
            median_interval = (sorted(gaps)[len(gaps)//2] * 60.0) if gaps else 0.0

            quality = AISDataQuality(
                observation_count=obs_count,
                median_interval_min=median_interval,
                max_temporal_gap_hours=max_gap,
                has_suspicious_gap=(max_gap > 2.0),
                interpolation_fraction=0.0,
                source_provider=self._provider_id
            )

            tracks.append(VesselTrack(
                identity=identity,
                positions=positions,
                data_quality=quality,
                source_provider=self._provider_id
            ))

        return tracks

    def lookup_vessel(self, mmsi: str) -> Optional[VesselIdentity]:
        self._get_all_positions()  # ensure cache is populated
        clean_mmsi = validate_mmsi(mmsi)
        return self._identities_cache.get(clean_mmsi)

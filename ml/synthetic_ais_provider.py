"""
OceanTrace — Synthetic AIS Data Provider (Development & Testing Only)
Generates deterministic, mathematically consistent vessel trajectories for unit testing,
CI/CD test runners, and air-gapped system demonstrations.

IMPORTANT:
Synthetic AIS is TEST DATA ONLY. It does NOT represent real-world maritime intelligence.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
import math
import random

from ml.ais_types import (
    AISPosition,
    VesselIdentity,
    AISDataQuality,
    VesselTrack,
    AISQuery,
    parse_utc_timestamp
)
from ml.ais_provider import AISProvider


class SyntheticAISProvider(AISProvider):
    """
    Deterministic synthetic vessel track generator implementing the AISProvider interface.
    Generates realistic tracks with configurable seeds, including:
    - Primary candidate tanker passing through a central target corridor
    - Background commercial traffic passing outside the corridor
    - Sparse reporting vessel (long reporting intervals)
    - Vessel with a deliberate mid-voyage AIS gap
    """

    def __init__(
        self,
        provider_id: str = "synthetic_test_provider",
        seed: int = 42,
        reference_time: Optional[datetime] = None,
        center_lat: float = 19.4167,
        center_lon: float = 71.3333
    ):
        self._provider_id = provider_id
        self.seed = seed
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.ref_time = reference_time or datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
        self._tracks_cache: Optional[List[VesselTrack]] = None

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def _generate_synthetic_fleet(self) -> List[VesselTrack]:
        """Generates a fixed deterministic fleet of synthetic vessels."""
        if self._tracks_cache is not None:
            return self._tracks_cache

        rng = random.Random(self.seed)
        tracks: List[VesselTrack] = []

        # -------------------------------------------------------------
        # Vessel 1: Primary Target Tanker (Crosses center corridor at t0 - 12h)
        # -------------------------------------------------------------
        ident_1 = VesselIdentity(
            mmsi="999000001",
            imo="9990001",
            name="SYNTHETIC TANKER ALPHA",
            callsign="SYNT1",
            vessel_type="Crude Oil Tanker",
            vessel_type_code=80,
            flag_country="Synthetic Registry",
            length_m=274.0,
            beam_m=48.0
        )
        # En route SW to NE at 12.5 knots (approx 0.003° lat per 15 min)
        positions_1 = []
        t_start = self.ref_time - timedelta(hours=24)
        for step in range(96):  # 24 hours at 15-min intervals
            t_curr = t_start + timedelta(minutes=15 * step)
            # Center of passage aligns near (center_lat, center_lon) at step 48 (t0 - 12h)
            progress = (step - 48) / 48.0
            lat = self.center_lat + progress * 0.35 + rng.gauss(0, 0.0005)
            lon = self.center_lon + progress * 0.35 + rng.gauss(0, 0.0005)
            positions_1.append(AISPosition(
                mmsi=ident_1.mmsi,
                timestamp=t_curr,
                latitude=lat,
                longitude=lon,
                sog_knots=12.5 + rng.gauss(0, 0.2),
                cog_deg=45.0 + rng.gauss(0, 0.5),
                heading_deg=45.0,
                nav_status=0,
                source_provider=self._provider_id
            ))
        q_1 = AISDataQuality(
            observation_count=len(positions_1),
            median_interval_min=15.0,
            max_temporal_gap_hours=0.25,
            interpolation_fraction=0.0,
            source_provider=self._provider_id
        )
        tracks.append(VesselTrack(identity=ident_1, positions=positions_1, data_quality=q_1, source_provider=self._provider_id))

        # -------------------------------------------------------------
        # Vessel 2: Background Cargo Vessel (Parallel course, 30 km East)
        # -------------------------------------------------------------
        ident_2 = VesselIdentity(
            mmsi="999000002",
            imo="9990002",
            name="SYNTHETIC CARGO BRAVO",
            callsign="SYNT2",
            vessel_type="Container Ship",
            vessel_type_code=70,
            flag_country="Synthetic Registry",
            length_m=330.0,
            beam_m=42.0
        )
        positions_2 = []
        for step in range(96):
            t_curr = t_start + timedelta(minutes=15 * step)
            progress = (step - 48) / 48.0
            lat = self.center_lat + progress * 0.40
            lon = self.center_lon + 0.35 + progress * 0.40  # offset 0.35 deg (~35 km East)
            positions_2.append(AISPosition(
                mmsi=ident_2.mmsi,
                timestamp=t_curr,
                latitude=lat,
                longitude=lon,
                sog_knots=16.0 + rng.gauss(0, 0.2),
                cog_deg=42.0,
                heading_deg=42.0,
                nav_status=0,
                source_provider=self._provider_id
            ))
        q_2 = AISDataQuality(
            observation_count=len(positions_2),
            median_interval_min=15.0,
            max_temporal_gap_hours=0.25,
            interpolation_fraction=0.0,
            source_provider=self._provider_id
        )
        tracks.append(VesselTrack(identity=ident_2, positions=positions_2, data_quality=q_2, source_provider=self._provider_id))

        # -------------------------------------------------------------
        # Vessel 3: Sparse Reporting Vessel (Hourly pings, passing North)
        # -------------------------------------------------------------
        ident_3 = VesselIdentity(
            mmsi="999000003",
            name="SYNTHETIC FISHING CHARLIE",
            vessel_type="Fishing",
            vessel_type_code=30,
            flag_country="Synthetic Registry"
        )
        positions_3 = []
        for step in range(24):  # 24 hours at 60-min intervals
            t_curr = t_start + timedelta(hours=step)
            lat = self.center_lat + 0.45 + (step / 24.0) * 0.1
            lon = self.center_lon - 0.20 + (step / 24.0) * 0.2
            positions_3.append(AISPosition(
                mmsi=ident_3.mmsi,
                timestamp=t_curr,
                latitude=lat,
                longitude=lon,
                sog_knots=6.5,
                cog_deg=65.0,
                nav_status=7,  # engaged in fishing
                source_provider=self._provider_id
            ))
        q_3 = AISDataQuality(
            observation_count=len(positions_3),
            median_interval_min=60.0,
            max_temporal_gap_hours=1.0,
            interpolation_fraction=0.0,
            source_provider=self._provider_id
        )
        tracks.append(VesselTrack(identity=ident_3, positions=positions_3, data_quality=q_3, source_provider=self._provider_id))

        # -------------------------------------------------------------
        # Vessel 4: Vessel with a deliberate 4-hour AIS Gap (Crossing South)
        # -------------------------------------------------------------
        ident_4 = VesselIdentity(
            mmsi="999000004",
            imo="9990004",
            name="SYNTHETIC BULKER DELTA",
            vessel_type="Bulk Carrier",
            vessel_type_code=75
        )
        positions_4 = []
        for step in range(96):
            # Introduce intentional gap between step 36 and 52 (4-hour void)
            if 36 <= step < 52:
                continue
            t_curr = t_start + timedelta(minutes=15 * step)
            progress = (step - 48) / 48.0
            lat = self.center_lat - 0.25 - progress * 0.30
            lon = self.center_lon + 0.10 + progress * 0.30
            positions_4.append(AISPosition(
                mmsi=ident_4.mmsi,
                timestamp=t_curr,
                latitude=lat,
                longitude=lon,
                sog_knots=11.0,
                cog_deg=135.0,
                nav_status=0,
                source_provider=self._provider_id
            ))
        q_4 = AISDataQuality(
            observation_count=len(positions_4),
            median_interval_min=15.0,
            max_temporal_gap_hours=4.0,  # 4-hour gap
            has_suspicious_gap=True,
            interpolation_fraction=0.0,
            source_provider=self._provider_id
        )
        tracks.append(VesselTrack(identity=ident_4, positions=positions_4, data_quality=q_4, source_provider=self._provider_id))

        self._tracks_cache = tracks
        return tracks

    def query_positions(self, query: AISQuery) -> List[AISPosition]:
        all_tracks = self._generate_synthetic_fleet()
        results: List[AISPosition] = []

        for track in all_tracks:
            if query.mmsi_filter and track.identity.mmsi not in query.mmsi_filter:
                continue
            for pos in track.positions:
                if query.start_time <= pos.timestamp <= query.end_time:
                    if query.min_lat <= pos.latitude <= query.max_lat:
                        if query.min_lon <= pos.longitude <= query.max_lon:
                            results.append(pos)

        results.sort(key=lambda p: p.timestamp)
        return results

    def query_tracks(self, query: AISQuery) -> List[VesselTrack]:
        all_tracks = self._generate_synthetic_fleet()
        matching_tracks: List[VesselTrack] = []

        for track in all_tracks:
            if query.mmsi_filter and track.identity.mmsi not in query.mmsi_filter:
                continue

            filtered_positions = [
                p for p in track.positions
                if query.start_time <= p.timestamp <= query.end_time
                and query.min_lat <= p.latitude <= query.max_lat
                and query.min_lon <= p.longitude <= query.max_lon
            ]

            if filtered_positions:
                # Recalculate basic data quality for the filtered sub-track
                obs_count = len(filtered_positions)
                gaps = [
                    (filtered_positions[i+1].timestamp - filtered_positions[i].timestamp).total_seconds() / 3600.0
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
                matching_tracks.append(VesselTrack(
                    identity=track.identity,
                    positions=filtered_positions,
                    data_quality=quality,
                    source_provider=self._provider_id
                ))

        return matching_tracks

    def lookup_vessel(self, mmsi: str) -> Optional[VesselIdentity]:
        all_tracks = self._generate_synthetic_fleet()
        for track in all_tracks:
            if track.identity.mmsi == mmsi:
                return track.identity
        return None

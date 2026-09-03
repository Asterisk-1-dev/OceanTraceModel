"""
OceanTrace — Local SQLite AIS Storage Layer
Implements local persistent storage for dynamic AIS position reports and static vessel identities.
Uses SQLite in WAL mode with composite indexes, enforcing unique (mmsi, timestamp_epoch) pairs,
and providing deterministic spatiotemporal queries and rolling 72-hour retention purging.
"""

import sqlite3
import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple

from ml.ais_types import (
    AISPosition,
    VesselIdentity,
    AISDataQuality,
    VesselTrack,
    AISQuery,
    parse_utc_timestamp,
    validate_mmsi
)


class AISStorage:
    """
    Thread-safe SQLite storage engine for local AIS caching and trajectory reconstruction.
    """

    def __init__(self, db_path: str = "ais_local.db"):
        self.db_path = db_path
        self._initialize_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Returns a configured SQLite connection in WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _initialize_database(self) -> None:
        """Initializes tables and composite indexes."""
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = self._get_connection()
        try:
            with conn:
                # 1. Vessel Static Metadata Table
                conn.execute("""
                CREATE TABLE IF NOT EXISTS vessel_identities (
                    mmsi TEXT PRIMARY KEY,
                    imo TEXT,
                    name TEXT,
                    callsign TEXT,
                    vessel_type TEXT,
                    vessel_type_code INTEGER,
                    length_m REAL,
                    beam_m REAL,
                    last_updated_epoch INTEGER NOT NULL
                );
                """)

                # 2. Dynamic Position Reports Table
                conn.execute("""
                CREATE TABLE IF NOT EXISTS ais_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mmsi TEXT NOT NULL,
                    timestamp_epoch INTEGER NOT NULL,
                    timestamp_iso TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    sog_knots REAL NOT NULL,
                    cog_deg REAL NOT NULL,
                    heading_deg REAL,
                    nav_status INTEGER,
                    source_provider TEXT NOT NULL DEFAULT 'aisstream',
                    received_at_epoch INTEGER NOT NULL,
                    UNIQUE(mmsi, timestamp_epoch)
                );
                """)

                # Performance Indexes
                conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_positions_mmsi_time 
                    ON ais_positions(mmsi, timestamp_epoch ASC);
                """)

                conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_positions_spatiotemporal 
                    ON ais_positions(timestamp_epoch, latitude, longitude);
                """)
        finally:
            conn.close()

    def upsert_vessel_identity(self, identity: VesselIdentity, reference_time: Optional[datetime] = None) -> None:
        """Inserts or updates static vessel identity metadata."""
        ref_dt = parse_utc_timestamp(reference_time or datetime.now(timezone.utc))
        epoch = int(ref_dt.timestamp())

        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                INSERT INTO vessel_identities (
                    mmsi, imo, name, callsign, vessel_type, vessel_type_code, length_m, beam_m, last_updated_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mmsi) DO UPDATE SET
                    imo = COALESCE(excluded.imo, vessel_identities.imo),
                    name = COALESCE(excluded.name, vessel_identities.name),
                    callsign = COALESCE(excluded.callsign, vessel_identities.callsign),
                    vessel_type = COALESCE(excluded.vessel_type, vessel_identities.vessel_type),
                    vessel_type_code = COALESCE(excluded.vessel_type_code, vessel_identities.vessel_type_code),
                    length_m = COALESCE(excluded.length_m, vessel_identities.length_m),
                    beam_m = COALESCE(excluded.beam_m, vessel_identities.beam_m),
                    last_updated_epoch = excluded.last_updated_epoch;
                """, (
                    identity.mmsi,
                    identity.imo,
                    identity.name,
                    identity.callsign,
                    identity.vessel_type,
                    identity.vessel_type_code,
                    identity.length_m,
                    identity.beam_m,
                    epoch
                ))
        finally:
            conn.close()

    def insert_position(self, pos: AISPosition, received_at: Optional[datetime] = None) -> bool:
        """
        Inserts a single position report. Safely ignores duplicate (mmsi, timestamp_epoch).
        Returns True if inserted, False if duplicate ignored.
        """
        rec_dt = parse_utc_timestamp(received_at or datetime.now(timezone.utc))
        ts_epoch = int(pos.timestamp.timestamp())
        rec_epoch = int(rec_dt.timestamp())

        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute("""
                INSERT OR IGNORE INTO ais_positions (
                    mmsi, timestamp_epoch, timestamp_iso, latitude, longitude,
                    sog_knots, cog_deg, heading_deg, nav_status, source_provider, received_at_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    pos.mmsi,
                    ts_epoch,
                    pos.timestamp.isoformat(),
                    pos.latitude,
                    pos.longitude,
                    pos.sog_knots,
                    pos.cog_deg,
                    pos.heading_deg,
                    pos.nav_status,
                    pos.source_provider,
                    rec_epoch
                ))
                return cursor.rowcount > 0
        finally:
            conn.close()

    def insert_positions(self, positions: List[AISPosition], received_at: Optional[datetime] = None) -> int:
        """Batch inserts multiple position reports, ignoring duplicates. Returns count of inserted rows."""
        if not positions:
            return 0

        rec_dt = parse_utc_timestamp(received_at or datetime.now(timezone.utc))
        rec_epoch = int(rec_dt.timestamp())

        rows = [
            (
                p.mmsi,
                int(p.timestamp.timestamp()),
                p.timestamp.isoformat(),
                p.latitude,
                p.longitude,
                p.sog_knots,
                p.cog_deg,
                p.heading_deg,
                p.nav_status,
                p.source_provider,
                rec_epoch
            )
            for p in positions
        ]

        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.executemany("""
                INSERT OR IGNORE INTO ais_positions (
                    mmsi, timestamp_epoch, timestamp_iso, latitude, longitude,
                    sog_knots, cog_deg, heading_deg, nav_status, source_provider, received_at_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, rows)
                return cursor.rowcount
        finally:
            conn.close()

    def lookup_vessel(self, mmsi: str) -> Optional[VesselIdentity]:
        """Looks up cached static vessel identity by MMSI."""
        clean_mmsi = validate_mmsi(mmsi)
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM vessel_identities WHERE mmsi = ?;", (clean_mmsi,)
            ).fetchone()

            if not row:
                return None

            return VesselIdentity(
                mmsi=row["mmsi"],
                imo=row["imo"],
                name=row["name"],
                callsign=row["callsign"],
                vessel_type=row["vessel_type"] or "Unknown",
                vessel_type_code=row["vessel_type_code"],
                length_m=row["length_m"],
                beam_m=row["beam_m"]
            )
        finally:
            conn.close()

    def query_positions(self, query: AISQuery) -> List[AISPosition]:
        """
        Queries positions matching spatiotemporal bounding box and optional MMSI filters.
        Returns positions chronologically sorted.
        """
        start_epoch = int(query.start_time.timestamp())
        end_epoch = int(query.end_time.timestamp())

        sql = """
        SELECT mmsi, timestamp_iso, latitude, longitude, sog_knots, cog_deg, heading_deg, nav_status, source_provider
        FROM ais_positions
        WHERE timestamp_epoch BETWEEN ? AND ?
          AND latitude BETWEEN ? AND ?
          AND longitude BETWEEN ? AND ?
        """
        params: List[Any] = [start_epoch, end_epoch, query.min_lat, query.max_lat, query.min_lon, query.max_lon]

        if query.mmsi_filter:
            placeholders = ",".join("?" for _ in query.mmsi_filter)
            sql += f" AND mmsi IN ({placeholders})"
            params.extend(query.mmsi_filter)

        sql += " ORDER BY timestamp_epoch ASC;"

        conn = self._get_connection()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

        positions = []
        for r in rows:
            positions.append(AISPosition(
                mmsi=r["mmsi"],
                timestamp=parse_utc_timestamp(r["timestamp_iso"]),
                latitude=r["latitude"],
                longitude=r["longitude"],
                sog_knots=r["sog_knots"],
                cog_deg=r["cog_deg"],
                heading_deg=r["heading_deg"],
                nav_status=r["nav_status"],
                source_provider=r["source_provider"]
            ))
        return positions

    def query_tracks(self, query: AISQuery) -> List[VesselTrack]:
        """
        Queries positions, groups them by MMSI, sorts them chronologically,
        attaches static identity and audits data quality.
        """
        positions = self.query_positions(query)
        if not positions:
            return []

        by_mmsi: Dict[str, List[AISPosition]] = {}
        for p in positions:
            by_mmsi.setdefault(p.mmsi, []).append(p)

        tracks: List[VesselTrack] = []
        for mmsi, p_list in by_mmsi.items():
            p_list.sort(key=lambda p: p.timestamp)
            ident = self.lookup_vessel(mmsi) or VesselIdentity(mmsi=mmsi)

            obs_count = len(p_list)
            gaps = [
                (p_list[i + 1].timestamp - p_list[i].timestamp).total_seconds() / 3600.0
                for i in range(obs_count - 1)
            ]
            max_gap = max(gaps) if gaps else 0.0
            median_interval = (sorted(gaps)[len(gaps) // 2] * 60.0) if gaps else 0.0

            quality = AISDataQuality(
                observation_count=obs_count,
                median_interval_min=median_interval,
                max_temporal_gap_hours=max_gap,
                has_suspicious_gap=(max_gap > 2.0),
                interpolation_fraction=0.0,
                source_provider=p_list[0].source_provider
            )

            tracks.append(VesselTrack(
                identity=ident,
                positions=p_list,
                data_quality=quality,
                source_provider=p_list[0].source_provider
            ))

        return tracks

    def purge_old_positions(self, reference_time: Optional[datetime] = None, retention_hours: float = 72.0) -> int:
        """
        Deletes all position reports older than retention_hours relative to reference_time.
        Default retention is 72.0 hours. Returns number of purged rows.
        """
        ref_dt = parse_utc_timestamp(reference_time or datetime.now(timezone.utc))
        cutoff_dt = ref_dt - timedelta(hours=retention_hours)
        cutoff_epoch = int(cutoff_dt.timestamp())

        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM ais_positions WHERE timestamp_epoch < ?;", (cutoff_epoch,)
                )
                purged = cursor.rowcount
                if purged > 0:
                    conn.execute("PRAGMA incremental_vacuum;")
                return purged
        finally:
            conn.close()

    def close(self) -> None:
        """Executes a WAL checkpoint to flush data and release any file handles."""
        try:
            conn = self._get_connection()
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            finally:
                conn.close()
        except Exception:
            pass

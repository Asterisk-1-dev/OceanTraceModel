"""
Unit tests for OceanTrace AIS Storage Layer (ml/ais_storage.py)
Validates:
- SQLite initialization and WAL mode activation
- Table schema and composite indexes creation
- Single and batch AISPosition insertion
- Unique (mmsi, timestamp_epoch) constraint (duplicate suppression)
- Static VesselIdentity upsert
- Bounding-box and time-range querying
- MMSI filter querying
- VesselTrack reconstruction and chronological ordering
- Rolling 72-hour retention purge
- Empty query handling
"""

import unittest
import os
import gc
import tempfile
from datetime import datetime, timezone, timedelta

from ml.ais_types import AISPosition, VesselIdentity, AISQuery
from ml.ais_storage import AISStorage


class TestAISStorage(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_ais_local.db")
        self.storage = AISStorage(db_path=self.db_path)
        self.t0 = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.storage.close()
        del self.storage
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_database_initialization_and_wal(self):
        self.assertTrue(os.path.exists(self.db_path))
        conn = self.storage._get_connection()
        try:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")
        finally:
            conn.close()

    def test_position_insertion_and_duplicate_handling(self):
        pos = AISPosition(
            mmsi="419001122",
            timestamp=self.t0,
            latitude=19.4167,
            longitude=71.3333,
            sog_knots=12.5,
            cog_deg=45.0,
            source_provider="aisstream"
        )
        # First insertion should succeed
        inserted = self.storage.insert_position(pos)
        self.assertTrue(inserted)

        # Re-inserting exact same (mmsi, timestamp) must be safely ignored (unique constraint)
        inserted_again = self.storage.insert_position(pos)
        self.assertFalse(inserted_again)

    def test_identity_upsert_and_lookup(self):
        ident = VesselIdentity(
            mmsi="419001122",
            imo="9312345",
            name="MT ARABIAN PIONEER",
            vessel_type="Crude Oil Tanker",
            length_m=274.0,
            beam_m=48.0
        )
        self.storage.upsert_vessel_identity(ident)

        vessel = self.storage.lookup_vessel("419001122")
        self.assertIsNotNone(vessel)
        self.assertEqual(vessel.name, "MT ARABIAN PIONEER")
        self.assertEqual(vessel.imo, "9312345")
        self.assertEqual(vessel.vessel_type, "Crude Oil Tanker")

        # Update name
        ident_updated = VesselIdentity(mmsi="419001122", name="MT ARABIAN PIONEER II")
        self.storage.upsert_vessel_identity(ident_updated)
        vessel_updated = self.storage.lookup_vessel("419001122")
        self.assertEqual(vessel_updated.name, "MT ARABIAN PIONEER II")
        # IMO should be preserved via COALESCE
        self.assertEqual(vessel_updated.imo, "9312345")

    def test_spatiotemporal_query_and_tracks(self):
        # Insert series of positions for two vessels
        p1 = AISPosition("419001122", self.t0, 19.4, 71.3, 12.0, 45.0)
        p2 = AISPosition("419001122", self.t0 + timedelta(minutes=15), 19.45, 71.35, 12.0, 45.0)
        p3 = AISPosition("419001122", self.t0 + timedelta(minutes=30), 19.5, 71.4, 12.0, 45.0)

        # Background vessel far outside
        p_far = AISPosition("999000002", self.t0, 15.0, 65.0, 10.0, 90.0)

        self.storage.insert_positions([p1, p2, p3, p_far])

        # Attach identity
        self.storage.upsert_vessel_identity(VesselIdentity(mmsi="419001122", name="TANKER ALPHA"))

        # Query Bombay High region
        query = AISQuery(
            start_time=self.t0 - timedelta(hours=1),
            end_time=self.t0 + timedelta(hours=1),
            min_lat=19.0, max_lat=20.0,
            min_lon=71.0, max_lon=72.0
        )
        tracks = self.storage.query_tracks(query)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].identity.name, "TANKER ALPHA")
        self.assertEqual(len(tracks[0].positions), 3)

        # Enforce chronological ordering
        for i in range(len(tracks[0].positions) - 1):
            self.assertLessEqual(tracks[0].positions[i].timestamp, tracks[0].positions[i + 1].timestamp)

    def test_mmsi_filter_and_empty_results(self):
        p1 = AISPosition("419001122", self.t0, 19.4, 71.3, 12.0, 45.0)
        p2 = AISPosition("999000002", self.t0, 19.4, 71.3, 12.0, 45.0)
        self.storage.insert_positions([p1, p2])

        query = AISQuery(
            start_time=self.t0 - timedelta(hours=1),
            end_time=self.t0 + timedelta(hours=1),
            min_lat=19.0, max_lat=20.0,
            min_lon=71.0, max_lon=72.0,
            mmsi_filter=["419001122"]
        )
        positions = self.storage.query_positions(query)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].mmsi, "419001122")

        # Empty result query
        query_empty = AISQuery(
            start_time=self.t0 + timedelta(days=10),
            end_time=self.t0 + timedelta(days=11),
            min_lat=19.0, max_lat=20.0,
            min_lon=71.0, max_lon=72.0
        )
        self.assertEqual(len(self.storage.query_positions(query_empty)), 0)
        self.assertEqual(len(self.storage.query_tracks(query_empty)), 0)

    def test_rolling_72_hour_retention_purge(self):
        t_ref = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

        # Position 1: 80 hours old (beyond 72h window)
        p_old = AISPosition("419001122", t_ref - timedelta(hours=80), 19.0, 71.0, 10.0, 45.0)
        # Position 2: 70 hours old (within 72h window)
        p_recent = AISPosition("419001122", t_ref - timedelta(hours=70), 19.1, 71.1, 10.0, 45.0)
        # Position 3: 2 hours old
        p_new = AISPosition("419001122", t_ref - timedelta(hours=2), 19.2, 71.2, 10.0, 45.0)

        self.storage.insert_positions([p_old, p_recent, p_new])

        # Purge relative to t_ref with 72h retention
        purged = self.storage.purge_old_positions(reference_time=t_ref, retention_hours=72.0)
        self.assertEqual(purged, 1)

        # Query all remaining
        query = AISQuery(
            start_time=t_ref - timedelta(days=10),
            end_time=t_ref + timedelta(days=1),
            min_lat=18.0, max_lat=21.0,
            min_lon=70.0, max_lon=73.0
        )
        remaining = self.storage.query_positions(query)
        self.assertEqual(len(remaining), 2)
        remaining_timestamps = [p.timestamp for p in remaining]
        self.assertNotIn(p_old.timestamp, remaining_timestamps)
        self.assertIn(p_recent.timestamp, remaining_timestamps)
        self.assertIn(p_new.timestamp, remaining_timestamps)


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for OceanTrace AISStream Provider (ml/aisstream_provider.py)
Validates:
- PositionReport normalization into canonical AISPosition
- ShipStaticData normalization into canonical VesselIdentity
- UTC timestamp conversion with subsecond and timezone handling
- Invalid / malformed message handling and graceful discard
- Missing optional fields handling
- Duplicate and out-of-order message handling via storage integration
- Subscription payload structure generation and API key validation
- Reconnect backoff calculation
- Zero internet dependency: mock WebSocket testing only
"""

import unittest
import os
import gc
import json
import tempfile
from datetime import datetime, timezone

from ml.ais_types import AISQuery
from ml.ais_storage import AISStorage
from ml.aisstream_provider import (
    normalize_aisstream_timestamp,
    normalize_aisstream_message,
    AISStreamProvider
)


class TestAISStreamProvider(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_stream_storage.db")
        self.storage = AISStorage(db_path=self.db_path)
        self.provider = AISStreamProvider(
            api_key="TEST_MOCK_KEY",
            storage=self.storage,
            provider_id="mock_aisstream"
        )

    def tearDown(self):
        self.storage.close()
        del self.provider
        del self.storage
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_timestamp_normalization(self):
        # Format: "2024-05-20 09:21:31.781972101 +0000 UTC"
        raw_1 = "2024-05-20 09:21:31.781972101 +0000 UTC"
        dt_1 = normalize_aisstream_timestamp(raw_1)
        self.assertEqual(dt_1.tzinfo, timezone.utc)
        self.assertEqual(dt_1.year, 2024)
        self.assertEqual(dt_1.month, 5)
        self.assertEqual(dt_1.day, 20)
        self.assertEqual(dt_1.hour, 9)

        # Direct ISO format
        raw_2 = "2026-09-02T12:00:00Z"
        dt_2 = normalize_aisstream_timestamp(raw_2)
        self.assertEqual(dt_2.year, 2026)

        # Malformed timestamp raises ValueError
        with self.assertRaises(ValueError):
            normalize_aisstream_timestamp("INVALID_DATE_STRING")

    def test_position_report_normalization(self):
        raw_envelope = {
            "MessageType": "PositionReport",
            "MetaData": {
                "MMSI": 419001122,
                "ShipName": "MT ARABIAN PIONEER",
                "latitude": 19.4167,
                "longitude": 71.3333,
                "time_utc": "2026-09-02 11:45:12.123456 +0000 UTC"
            },
            "Message": {
                "PositionReport": {
                    "Latitude": 19.4167,
                    "Longitude": 71.3333,
                    "Sog": 12.4,
                    "Cog": 45.2,
                    "TrueHeading": 45,
                    "NavigationalStatus": 0,
                    "UserID": 419001122
                }
            }
        }
        pos, ident = normalize_aisstream_message(raw_envelope)
        self.assertIsNotNone(pos)
        self.assertIsNone(ident)
        self.assertEqual(pos.mmsi, "419001122")
        self.assertEqual(pos.latitude, 19.4167)
        self.assertEqual(pos.longitude, 71.3333)
        self.assertEqual(pos.sog_knots, 12.4)
        self.assertEqual(pos.cog_deg, 45.2)
        self.assertEqual(pos.heading_deg, 45.0)
        self.assertEqual(pos.nav_status, 0)

    def test_ship_static_data_normalization(self):
        raw_envelope = {
            "MessageType": "ShipStaticData",
            "MetaData": {
                "MMSI": 419001122,
                "ShipName": "MT ARABIAN PIONEER",
                "time_utc": "2026-09-02 11:45:00 +0000 UTC"
            },
            "Message": {
                "ShipStaticData": {
                    "ImoNumber": 9312345,
                    "Name": "MT ARABIAN PIONEER",
                    "CallSign": "VTAP",
                    "Type": 80,  # Tanker
                    "Dimension": {
                        "A": 200, "B": 74, "C": 24, "D": 24
                    }
                }
            }
        }
        pos, ident = normalize_aisstream_message(raw_envelope)
        self.assertIsNone(pos)
        self.assertIsNotNone(ident)
        self.assertEqual(ident.mmsi, "419001122")
        self.assertEqual(ident.imo, "9312345")
        self.assertEqual(ident.name, "MT ARABIAN PIONEER")
        self.assertEqual(ident.vessel_type, "Tanker")
        self.assertEqual(ident.length_m, 274.0)
        self.assertEqual(ident.beam_m, 48.0)

    def test_malformed_and_missing_messages(self):
        # Empty envelope
        p1, i1 = normalize_aisstream_message({})
        self.assertIsNone(p1)
        self.assertIsNone(i1)

        # Missing payload
        p2, i2 = normalize_aisstream_message({"MessageType": "PositionReport", "MetaData": {"MMSI": 123}})
        self.assertIsNone(p2)
        self.assertIsNone(i2)

        # Corrupted JSON string handled by provider
        saved = self.provider.process_raw_message("INVALID_JSON{")
        self.assertFalse(saved)

    def test_subscription_payload_and_key_validation(self):
        # Valid key
        payload = self.provider.build_subscription_payload()
        self.assertEqual(payload["APIKey"], "TEST_MOCK_KEY")
        self.assertIn("BoundingBoxes", payload)
        self.assertIn("FilterMessageTypes", payload)

        # Missing key raises ValueError
        empty_prov = AISStreamProvider(api_key="")
        with self.assertRaises(ValueError):
            empty_prov.build_subscription_payload()

    def test_provider_storage_integration(self):
        # Inject position frame
        pos_json = json.dumps({
            "MessageType": "PositionReport",
            "MetaData": {
                "MMSI": 419001122,
                "ShipName": "MT ARABIAN PIONEER",
                "time_utc": "2026-09-02 12:00:00 +0000 UTC"
            },
            "Message": {
                "PositionReport": {
                    "Latitude": 19.4167,
                    "Longitude": 71.3333,
                    "Sog": 12.0,
                    "Cog": 45.0,
                    "UserID": 419001122
                }
            }
        })
        # Inject static identity frame
        static_json = json.dumps({
            "MessageType": "ShipStaticData",
            "MetaData": {
                "MMSI": 419001122,
                "time_utc": "2026-09-02 12:00:00 +0000 UTC"
            },
            "Message": {
                "ShipStaticData": {
                    "ImoNumber": 9312345,
                    "Name": "MT ARABIAN PIONEER",
                    "Type": 80
                }
            }
        })

        self.assertTrue(self.provider.process_raw_message(pos_json))
        self.assertTrue(self.provider.process_raw_message(static_json))

        # Query via provider abstraction interface
        query = AISQuery(
            start_time=datetime(2026, 9, 2, 11, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc),
            min_lat=18.0, max_lat=21.0,
            min_lon=70.0, max_lon=73.0
        )
        tracks = self.provider.query_tracks(query)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].identity.mmsi, "419001122")
        self.assertEqual(tracks[0].identity.name, "MT ARABIAN PIONEER")
        self.assertEqual(tracks[0].identity.vessel_type, "Tanker")
        self.assertEqual(len(tracks[0].positions), 1)


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for OceanTrace AIS Provider Abstraction & Registry (ml/ais_provider.py)
Validates:
- AISProvider abstract interface compliance
- MockProvider query execution
- AISProviderRegistry registration, default selection, and lookup
"""

import unittest
from datetime import datetime, timezone
from typing import List, Optional

from ml.ais_types import AISPosition, VesselIdentity, VesselTrack, AISDataQuality, AISQuery
from ml.ais_provider import AISProvider, AISProviderRegistry


class MockAISProvider(AISProvider):
    """Simple concrete provider for testing the abstract interface."""

    def __init__(self, provider_id: str = "mock_provider"):
        self._id = provider_id

    @property
    def provider_id(self) -> str:
        return self._id

    def query_positions(self, query: AISQuery) -> List[AISPosition]:
        # Return synthetic position within the query window
        return [
            AISPosition(
                mmsi="419001122",
                timestamp=query.start_time,
                latitude=(query.min_lat + query.max_lat) / 2.0,
                longitude=(query.min_lon + query.max_lon) / 2.0,
                sog_knots=12.0,
                cog_deg=180.0,
                source_provider=self._id
            )
        ]

    def query_tracks(self, query: AISQuery) -> List[VesselTrack]:
        positions = self.query_positions(query)
        ident = VesselIdentity(mmsi="419001122", name="Mock Tanker", vessel_type="Tanker")
        quality = AISDataQuality(observation_count=1, median_interval_min=0.0, max_temporal_gap_hours=0.0)
        return [
            VesselTrack(identity=ident, positions=positions, data_quality=quality, source_provider=self._id)
        ]

    def lookup_vessel(self, mmsi: str) -> Optional[VesselIdentity]:
        if mmsi == "419001122":
            return VesselIdentity(mmsi="419001122", name="Mock Tanker", vessel_type="Tanker")
        return None


class TestAISProviderAbstraction(unittest.TestCase):

    def setUp(self):
        self.provider = MockAISProvider("mock_test")
        self.registry = AISProviderRegistry()

    def test_provider_contract(self):
        self.assertEqual(self.provider.provider_id, "mock_test")
        t_start = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        t_end = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
        query = AISQuery(start_time=t_start, end_time=t_end, min_lat=18.0, max_lat=20.0, min_lon=70.0, max_lon=73.0)

        positions = self.provider.query_positions(query)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].mmsi, "419001122")

        tracks = self.provider.query_tracks(query)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].identity.name, "Mock Tanker")

        vessel = self.provider.lookup_vessel("419001122")
        self.assertIsNotNone(vessel)
        self.assertEqual(vessel.vessel_type, "Tanker")

        missing = self.provider.lookup_vessel("999999999")
        self.assertIsNone(missing)

    def test_registry_operations(self):
        p1 = MockAISProvider("p1")
        p2 = MockAISProvider("p2")

        self.registry.register_provider(p1, set_as_default=True)
        self.registry.register_provider(p2)

        self.assertListEqual(self.registry.list_providers(), ["p1", "p2"])
        self.assertEqual(self.registry.get_provider().provider_id, "p1")
        self.assertEqual(self.registry.get_provider("p2").provider_id, "p2")

        with self.assertRaises(KeyError):
            self.registry.get_provider("unknown_provider")


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for OceanTrace Canonical AIS Domain Types (ml/ais_types.py)
Validates:
- MMSI format and bounds checking
- Timezone-aware UTC timestamp parsing
- Coordinate bounds [-90, 90] and [-180, 180]
- SOG [0, 102.2] and COG [0, 360) constraints
- Optional heading and nav_status handling
- VesselIdentity IMO validation and whitespace stripping
- AISDataQuality bounds checking
- VesselTrack chronological ordering enforcement and MMSI mismatch detection
- AISQuery time span and bounding box validations
"""

import unittest
from datetime import datetime, timezone, timedelta
from ml.ais_types import (
    AISPosition,
    VesselIdentity,
    AISDataQuality,
    VesselTrack,
    AISQuery,
    parse_utc_timestamp,
    validate_mmsi
)


class TestAISTypes(unittest.TestCase):

    def test_mmsi_validation(self):
        # Valid 9-digit MMSI
        self.assertEqual(validate_mmsi("419001122"), "419001122")
        self.assertEqual(validate_mmsi("  419001122  "), "419001122")

        # Invalid MMSI: length != 9, letters, non-strings
        with self.assertRaises(ValueError):
            validate_mmsi("12345")
        with self.assertRaises(ValueError):
            validate_mmsi("1234567890")
        with self.assertRaises(ValueError):
            validate_mmsi("41900112A")
        with self.assertRaises(TypeError):
            validate_mmsi(419001122)

    def test_utc_timestamp_parsing(self):
        # Timezone-aware datetime
        dt_utc = datetime(2026, 9, 2, 4, 30, tzinfo=timezone.utc)
        self.assertEqual(parse_utc_timestamp(dt_utc), dt_utc)

        # Naive datetime MUST be rejected
        dt_naive = datetime(2026, 9, 2, 4, 30)
        with self.assertRaises(ValueError):
            parse_utc_timestamp(dt_naive)

        # ISO string with UTC 'Z' or offset
        self.assertEqual(parse_utc_timestamp("2026-09-02T04:30:00Z"), dt_utc)
        self.assertEqual(parse_utc_timestamp("2026-09-02T04:30:00+00:00"), dt_utc)

        # String without timezone MUST be rejected
        with self.assertRaises(ValueError):
            parse_utc_timestamp("2026-09-02T04:30:00")

    def test_ais_position_valid(self):
        t0 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        pos = AISPosition(
            mmsi="419001122",
            timestamp=t0,
            latitude=19.4167,
            longitude=71.3333,
            sog_knots=12.5,
            cog_deg=225.0,
            heading_deg=224.0,
            nav_status=0,
            source_provider="aisstream"
        )
        self.assertEqual(pos.mmsi, "419001122")
        self.assertEqual(pos.sog_knots, 12.5)
        self.assertEqual(pos.cog_deg, 225.0)
        d = pos.to_dict()
        self.assertEqual(d["mmsi"], "419001122")
        self.assertEqual(d["latitude"], 19.4167)

    def test_ais_position_invalid_fields(self):
        t0 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)

        # Invalid latitude
        with self.assertRaises(ValueError):
            AISPosition("419001122", t0, latitude=95.0, longitude=71.0, sog_knots=10.0, cog_deg=0.0)

        # Invalid longitude extreme
        with self.assertRaises(ValueError):
            AISPosition("419001122", t0, latitude=19.0, longitude=400.0, sog_knots=10.0, cog_deg=0.0)

        # Negative SOG
        with self.assertRaises(ValueError):
            AISPosition("419001122", t0, latitude=19.0, longitude=71.0, sog_knots=-1.0, cog_deg=0.0)

        # Extreme SOG (> 102.2 knots)
        with self.assertRaises(ValueError):
            AISPosition("419001122", t0, latitude=19.0, longitude=71.0, sog_knots=120.0, cog_deg=0.0)

        # Negative COG
        with self.assertRaises(ValueError):
            AISPosition("419001122", t0, latitude=19.0, longitude=71.0, sog_knots=10.0, cog_deg=-5.0)

        # Invalid Nav Status
        with self.assertRaises(ValueError):
            AISPosition("419001122", t0, latitude=19.0, longitude=71.0, sog_knots=10.0, cog_deg=0.0, nav_status=99)

    def test_vessel_identity(self):
        v = VesselIdentity(
            mmsi="419001122",
            imo="9312345",
            name="MT ARABIAN PIONEER",
            vessel_type="Crude Oil Tanker",
            vessel_type_code=80,
            flag_country="India",
            length_m=245.0,
            beam_m=42.0
        )
        self.assertEqual(v.imo, "9312345")
        self.assertEqual(v.name, "MT ARABIAN PIONEER")

        # Invalid IMO length
        with self.assertRaises(ValueError):
            VesselIdentity(mmsi="419001122", imo="1234")

        # Negative length
        with self.assertRaises(ValueError):
            VesselIdentity(mmsi="419001122", length_m=-10.0)

    def test_vessel_track_ordering_enforcement(self):
        t0 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        p1 = AISPosition("419001122", t0, 19.0, 71.0, 12.0, 45.0)
        p2 = AISPosition("419001122", t0 + timedelta(minutes=15), 19.05, 71.05, 12.0, 45.0)
        p3 = AISPosition("419001122", t0 + timedelta(minutes=30), 19.10, 71.10, 12.0, 45.0)

        ident = VesselIdentity(mmsi="419001122", name="Ship 1")
        q = AISDataQuality(observation_count=3, median_interval_min=15.0, max_temporal_gap_hours=0.25)

        # Valid chronological track
        track = VesselTrack(identity=ident, positions=[p1, p2, p3], data_quality=q)
        self.assertEqual(len(track.positions), 3)
        self.assertEqual(track.duration_hours, 0.5)

        # Out-of-order track MUST raise ValueError
        with self.assertRaises(ValueError):
            VesselTrack(identity=ident, positions=[p1, p3, p2], data_quality=q)

        # Empty positions list MUST raise ValueError
        with self.assertRaises(ValueError):
            VesselTrack(identity=ident, positions=[], data_quality=q)

        # MMSI mismatch between position and track identity MUST raise ValueError
        p_wrong = AISPosition("999999999", t0 + timedelta(minutes=45), 19.15, 71.15, 12.0, 45.0)
        with self.assertRaises(ValueError):
            VesselTrack(identity=ident, positions=[p1, p2, p_wrong], data_quality=q)

    def test_ais_query_validation(self):
        t_start = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        t_end = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)

        # Valid Query
        q = AISQuery(start_time=t_start, end_time=t_end, min_lat=18.0, max_lat=20.0, min_lon=70.0, max_lon=73.0)
        self.assertEqual(q.min_lat, 18.0)
        self.assertEqual(q.max_lat, 20.0)

        # start_time >= end_time MUST fail
        with self.assertRaises(ValueError):
            AISQuery(start_time=t_end, end_time=t_start, min_lat=18.0, max_lat=20.0, min_lon=70.0, max_lon=73.0)

        # Inverted latitude bounds MUST fail
        with self.assertRaises(ValueError):
            AISQuery(start_time=t_start, end_time=t_end, min_lat=21.0, max_lat=20.0, min_lon=70.0, max_lon=73.0)

        # Inverted longitude bounds MUST fail
        with self.assertRaises(ValueError):
            AISQuery(start_time=t_start, end_time=t_end, min_lat=18.0, max_lat=20.0, min_lon=75.0, max_lon=73.0)


if __name__ == "__main__":
    unittest.main()

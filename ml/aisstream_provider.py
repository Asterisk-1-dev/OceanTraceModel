"""
OceanTrace — Live AISStream.io Ingestion Provider
Implements live WebSocket ingestion from wss://stream.aisstream.io/v0/stream,
normalizes raw JSON messages into canonical AISPosition and VesselIdentity domain types,
persists streaming data to local SQLite storage, and serves spatiotemporal queries.
"""

import os
import json
import asyncio
import threading
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple

from ml.ais_types import (
    AISPosition,
    VesselIdentity,
    VesselTrack,
    AISQuery,
    parse_utc_timestamp,
    validate_mmsi
)
from ml.ais_provider import AISProvider
from ml.ais_storage import AISStorage

logger = logging.getLogger("OceanTrace.AISStream")


def normalize_aisstream_timestamp(raw_ts: str) -> datetime:
    """
    Normalizes AISStream MetaData.time_utc string to timezone-aware UTC datetime.
    Example input: "2024-05-20 09:21:31.781972101 +0000 UTC"
    """
    if not isinstance(raw_ts, str) or not raw_ts.strip():
        raise ValueError(f"Invalid timestamp string: {raw_ts}")

    clean_ts = raw_ts.strip()
    # If ends with ' +0000 UTC', format can be parsed after removing the trailing ' UTC'
    if clean_ts.endswith(" UTC"):
        clean_ts = clean_ts[:-4].strip()

    # Split subseconds if too long for standard strptime
    try:
        # Try direct ISO parsing first
        return parse_utc_timestamp(clean_ts)
    except Exception:
        pass

    # Try space-separated format: 'YYYY-MM-DD HH:MM:SS.subsecond +0000'
    try:
        # Handle nanoseconds by truncating to microseconds (6 digits)
        if "." in clean_ts:
            prefix, rest = clean_ts.split(".", 1)
            parts = rest.split(" ")
            subsecs = parts[0][:6].ljust(6, '0')
            tz_part = parts[1] if len(parts) > 1 else "+00:00"
            if not tz_part.startswith("+") and not tz_part.startswith("-"):
                tz_part = "+00:00"
            iso_str = f"{prefix}.{subsecs}{tz_part}"
            return datetime.fromisoformat(iso_str).astimezone(timezone.utc)
        else:
            parts = clean_ts.split(" ")
            base_str = parts[0] + "T" + parts[1]
            tz_part = parts[2] if len(parts) > 2 else "+00:00"
            return datetime.fromisoformat(f"{base_str}{tz_part}").astimezone(timezone.utc)
    except Exception as e:
        raise ValueError(f"Failed to parse AISStream timestamp '{raw_ts}': {e}")


def normalize_aisstream_message(
    msg_envelope: Dict[str, Any],
    source_provider: str = "aisstream"
) -> Tuple[Optional[AISPosition], Optional[VesselIdentity]]:
    """
    Normalizes a decoded AISStream JSON envelope into canonical AISPosition or VesselIdentity.
    Returns (position, identity).
    """
    msg_type = msg_envelope.get("MessageType")
    meta = msg_envelope.get("MetaData", {})
    msg_payload = msg_envelope.get("Message", {})

    if not msg_type or not meta or not msg_payload:
        return None, None

    # 1. Extract MMSI
    raw_mmsi = meta.get("MMSI")
    if raw_mmsi is None:
        return None, None
    mmsi_str = str(raw_mmsi).strip().zfill(9)

    # 2. Extract UTC timestamp
    raw_ts = meta.get("time_utc")
    if not raw_ts:
        return None, None
    try:
        ts_utc = normalize_aisstream_timestamp(raw_ts)
    except Exception as e:
        logger.debug(f"Discarding message with invalid timestamp: {e}")
        return None, None

    # Case A: PositionReport (Types 1, 2, 3)
    if msg_type == "PositionReport" and "PositionReport" in msg_payload:
        p_data = msg_payload["PositionReport"]
        lat = p_data.get("Latitude")
        lon = p_data.get("Longitude")
        sog = p_data.get("Sog")
        cog = p_data.get("Cog")

        # Fallback coordinates from MetaData if payload coordinates are invalid/default
        if (lat is None or lat == 91.0) and "latitude" in meta:
            lat = meta["latitude"]
        if (lon is None or lon == 181.0) and "longitude" in meta:
            lon = meta["longitude"]

        if lat is None or lon is None or sog is None or cog is None:
            return None, None

        # Value 102.3 in AIS indicates SOG not available
        if sog >= 102.3:
            sog = 0.0
        # Value 360.0 in AIS indicates COG not available
        if cog >= 360.0:
            cog = 0.0

        heading = p_data.get("TrueHeading")
        if heading is not None and (heading == 511 or heading > 359 or heading < 0):
            heading = None

        nav_status = p_data.get("NavigationalStatus")
        if nav_status is not None and not (0 <= nav_status <= 15):
            nav_status = None

        try:
            pos = AISPosition(
                mmsi=mmsi_str,
                timestamp=ts_utc,
                latitude=float(lat),
                longitude=float(lon),
                sog_knots=float(sog),
                cog_deg=float(cog),
                heading_deg=float(heading) if heading is not None else None,
                nav_status=int(nav_status) if nav_status is not None else None,
                source_provider=source_provider
            )
            return pos, None
        except Exception as e:
            logger.debug(f"Invalid PositionReport fields: {e}")
            return None, None

    # Case B: ShipStaticData (Type 5)
    elif msg_type == "ShipStaticData" and "ShipStaticData" in msg_payload:
        s_data = msg_payload["ShipStaticData"]
        name = s_data.get("Name") or meta.get("ShipName")
        clean_name = str(name).strip() if name else None

        imo_raw = s_data.get("ImoNumber")
        clean_imo = None
        if imo_raw and int(imo_raw) > 0:
            clean_imo = str(imo_raw).strip()

        callsign = s_data.get("CallSign")
        clean_callsign = str(callsign).strip() if callsign else None

        vtype_code = s_data.get("Type")
        vtype_str = "Unknown"
        if vtype_code:
            if 70 <= vtype_code <= 79:
                vtype_str = "Cargo"
            elif 80 <= vtype_code <= 89:
                vtype_str = "Tanker"
            elif vtype_code == 30:
                vtype_str = "Fishing"
            elif 60 <= vtype_code <= 69:
                vtype_str = "Passenger"
            elif 50 <= vtype_code <= 59:
                vtype_str = "Special Craft"

        dim = s_data.get("Dimension", {})
        length = None
        beam = None
        if dim:
            a = dim.get("A", 0)
            b = dim.get("B", 0)
            c = dim.get("C", 0)
            d = dim.get("D", 0)
            if (a + b) > 0:
                length = float(a + b)
            if (c + d) > 0:
                beam = float(c + d)

        try:
            ident = VesselIdentity(
                mmsi=mmsi_str,
                imo=clean_imo,
                name=clean_name,
                callsign=clean_callsign,
                vessel_type=vtype_str,
                vessel_type_code=int(vtype_code) if vtype_code else None,
                length_m=length,
                beam_m=beam
            )
            return None, ident
        except Exception as e:
            logger.debug(f"Invalid ShipStaticData fields: {e}")
            return None, None

    return None, None


class AISStreamProvider(AISProvider):
    """
    Live streaming AIS provider connecting to AISStream.io WebSocket.
    Stores normalized reports into a local SQLite database for querying.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        bounding_boxes: Optional[List[List[List[float]]]] = None,
        storage: Optional[AISStorage] = None,
        db_path: str = "ais_local.db",
        provider_id: str = "aisstream",
        ws_endpoint: str = "wss://stream.aisstream.io/v0/stream",
        max_reconnect_attempts: int = 5
    ):
        self._provider_id = provider_id
        # Secret management: environment variable precedence
        self.api_key = api_key or os.environ.get("OCEANTRACE_AISSTREAM_API_KEY", "")
        self.ws_endpoint = ws_endpoint
        self.bounding_boxes = bounding_boxes or [[[18.0, 70.0], [21.0, 73.0]]]
        self.storage = storage or AISStorage(db_path=db_path)
        self.max_reconnect_attempts = max_reconnect_attempts

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def build_subscription_payload(self) -> Dict[str, Any]:
        """Constructs the verified AISStream JSON subscription payload."""
        if not self.api_key or not self.api_key.strip():
            raise ValueError(
                "AISStream API key is required. Set OCEANTRACE_AISSTREAM_API_KEY environment variable."
            )
        return {
            "APIKey": self.api_key.strip(),
            "BoundingBoxes": self.bounding_boxes,
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"]
        }

    def process_raw_message(self, raw_json: str) -> bool:
        """
        Parses raw JSON string from WebSocket and persists to SQLite.
        Returns True if a valid position or identity was saved.
        """
        try:
            envelope = json.loads(raw_json)
        except Exception as e:
            logger.warning(f"Malformed JSON frame received: {e}")
            return False

        pos, ident = normalize_aisstream_message(envelope, source_provider=self._provider_id)
        saved = False

        if ident is not None:
            self.storage.upsert_vessel_identity(ident)
            saved = True

        if pos is not None:
            self.storage.insert_position(pos)
            saved = True

        return saved

    async def _stream_loop(self) -> None:
        """Asynchronous stream receiver with bounded exponential backoff."""
        import websockets

        backoff = 1.0
        max_backoff = 30.0
        attempts = 0

        while self._running:
            try:
                payload = self.build_subscription_payload()
            except ValueError as e:
                logger.error(f"Configuration error: {e}")
                break

            try:
                logger.info(f"Connecting to AISStream at {self.ws_endpoint}...")
                async with websockets.connect(self.ws_endpoint, open_timeout=10.0) as ws:
                    # Verified contract: send subscription JSON immediately within 3 seconds
                    await ws.send(json.dumps(payload))
                    logger.info("AISStream subscription payload sent successfully.")
                    backoff = 1.0
                    attempts = 0

                    while self._running:
                        try:
                            msg_str = await asyncio.wait_for(ws.recv(), timeout=60.0)
                            self.process_raw_message(msg_str)
                        except asyncio.TimeoutError:
                            # Send ping or wait
                            continue

            except (websockets.exceptions.InvalidStatusCode, websockets.exceptions.SecurityOptionsError) as e:
                logger.error(f"Authentication/Security error connecting to AISStream: {e}")
                break  # Don't retry authentication errors
            except Exception as e:
                attempts += 1
                if not self._running:
                    break
                logger.warning(f"WebSocket connection error (attempt {attempts}): {e}")
                if self.max_reconnect_attempts and attempts >= self.max_reconnect_attempts:
                    logger.error("Max reconnect attempts reached. Stopping stream loop.")
                    break
                await asyncio.sleep(backoff)
                backoff = min(max_backoff, backoff * 2.0)

    def start_background_ingestion(self) -> None:
        """Starts the live stream ingestion in a daemon background thread."""
        if self._running:
            return

        self._running = True

        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._stream_loop())

        self._thread = threading.Thread(target=_run, daemon=True, name="AISStreamIngestionThread")
        self._thread.start()

    def stop_background_ingestion(self) -> None:
        """Stops the live stream ingestion gracefully."""
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # -------------------------------------------------------------
    # Canonical AISProvider Interface Delegation
    # -------------------------------------------------------------

    def query_positions(self, query: AISQuery) -> List[AISPosition]:
        return self.storage.query_positions(query)

    def query_tracks(self, query: AISQuery) -> List[VesselTrack]:
        return self.storage.query_tracks(query)

    def lookup_vessel(self, mmsi: str) -> Optional[VesselIdentity]:
        return self.storage.lookup_vessel(mmsi)

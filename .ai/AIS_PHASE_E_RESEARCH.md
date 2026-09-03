# AIS Phase E — Live Ingestion & SQLite Research/Verification

**Project:** OceanTrace — Maritime Oil Spill Intelligence  
**Problem Statement:** SIH26143 — Leveraging satellite imagery to determine oil spills at sea along with AIS data correlations to identify the vessel responsible for the spill.  
**Subsystem:** AIS Data Acquisition, Spatiotemporal Correlation & Attribution Engine  
**Phase:** Phase E (Research & Verification Only — No Code Changes)  
**Date:** 2026-09-03  
**Status:** COMPLETE & VERIFIED

---

## 1. Executive Summary

This research investigates the technical, operational, and contractual viability of using **AISStream.io** as OceanTrace's live streaming AIS provider, alongside the architecture of a **local SQLite 72-hour rolling buffer store**.

### Key Findings:
1. **Live Suitability for Hackathon:** **VERIFIED SUITABLE.** AISStream.io is a free, real-time WebSocket service (`wss://stream.aisstream.io/v0/stream`) requiring only an API key passed in the initial JSON subscription frame. It supports server-side geographic bounding box filtering and vessel MMSI filtering.
2. **Zero Historical Replay Capability:** **VERIFIED.** AISStream provides **strictly live streaming data**. It does **not** provide historical endpoints, time-range queries, or archived voyage replays. OceanTrace **cannot query the past** from AISStream directly. Therefore:
   * Historical spill investigations require local persistence (capturing live data into a local rolling buffer as it occurs) OR querying our existing `HistoricalFileProvider`.
3. **Bombay High Coverage Caveat:** **VERIFIED CAVEAT.** Bombay High is located $\approx 160\text{ km}$ offshore Mumbai in the Arabian Sea. Terrestrial VHF AIS range is line-of-sight ($\approx 40\text{--}60\text{ km}$). AISStream relies primarily on crowdsourced terrestrial coastal receivers. While the API *accepts* the Bombay High bounding box, **reception of offshore pings is not guaranteed** unless a nearby platform/satellite receiver feeds AISStream. The demo must rely on `HistoricalFileProvider` and `SyntheticAISProvider` for guaranteed air-gapped repeatability.
4. **Local Persistence Architecture:** A lightweight embedded SQLite database (`ais_local.db`) with composite indexes on `(timestamp_epoch, latitude, longitude)` and `(mmsi, timestamp_epoch)` in Write-Ahead Logging (WAL) mode provides hackathon-grade performance with automated 72-hour rolling TTL purge.

---

## 2. AISStream Current API Verification

### A. Authentication
* **Method:** Passed directly in the initial JSON subscription message payload (not in HTTP headers or URL query parameters).
* **Field:** `"APIKey": "<YOUR_API_KEY>"`
* **Registration:** Free registration on [aisstream.io](https://aisstream.io/).
* **Security Guardrail:** The key must be read strictly from the environment variable `OCEANTRACE_AISSTREAM_API_KEY`. It must never be committed to git or logged.

### B. Transport & Lifecycle
* **Endpoint:** `wss://stream.aisstream.io/v0/stream` (Secure WebSocket WSS only).
* **Protocol:** Text-based JSON frames over persistent WebSocket.
* **Handshake Deadline:** The JSON subscription message must be transmitted within 3 seconds of opening the WebSocket connection, or the server closes the connection.
* **Filter Updates:** A new subscription message can be transmitted over an established connection at any time to dynamically replace geographic filters.

### C. Subscription Syntax
```json
{
  "APIKey": "<API_KEY>",
  "BoundingBoxes": [
    [
      [19.10, 71.00],
      [19.85, 71.85]
    ]
  ],
  "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
  "FiltersShipMMSI": []
}
```
* **BoundingBoxes Syntax:** Array of bounding boxes: `[[ [lat_min, lon_min], [lat_max, lon_max] ]]`.
* **Server-Side Filtering:** AISStream performs geographic and message-type filtering on its ingestion servers before streaming messages to the client, preventing local bandwidth exhaustion.

### D. Message Schema & Envelopes
Every message emitted by AISStream conforms to a 3-part JSON envelope:
```json
{
  "MessageType": "PositionReport",
  "MetaData": {
    "MMSI": 419001122,
    "ShipName": "MT ARABIAN PIONEER",
    "latitude": 19.416723,
    "longitude": 71.333315,
    "time_utc": "2026-09-02 11:45:12.123456789 +0000 UTC"
  },
  "Message": {
    "PositionReport": {
      "Cog": 45.2,
      "Sog": 12.4,
      "TrueHeading": 45,
      "NavigationalStatus": 0,
      "RateOfTurn": 0,
      "Latitude": 19.416723,
      "Longitude": 71.333315,
      "UserID": 419001122
    }
  }
}
```

#### Message Types Handled by OceanTrace:
1. **`PositionReport` (ITU-R M.1371 Types 1, 2, 3):** Dynamic vessel navigation (lat, lon, SOG, COG, heading, nav status).
2. **`ShipStaticData` (ITU-R M.1371 Type 5):** Static metadata (IMO, ship name, callsign, vessel type code, length, beam, draught). Arrives infrequently (every 6 minutes).

---

## 3. Canonical OceanTrace Field Mapping

Mapping from raw AISStream JSON frames to OceanTrace domain types in `ml/ais_types.py`:

| AISStream JSON Source | Canonical Target | Field Type | Transformation / Validation Rules |
| :--- | :--- | :---: | :--- |
| `MetaData.MMSI` / `PositionReport.UserID` | `AISPosition.mmsi` | Required | Convert integer to 9-digit string `str(mmsi).zfill(9)`. Validate via `validate_mmsi()`. |
| `MetaData.time_utc` | `AISPosition.timestamp` | Required | Parse string `"%Y-%m-%d %H:%M:%S.%f %z UTC"` to timezone-aware UTC `datetime`. |
| `PositionReport.Latitude` | `AISPosition.latitude` | Required | Float in $[-90.0, 90.0]$. NaN/Inf rejected. |
| `PositionReport.Longitude` | `AISPosition.longitude` | Required | Float in $[-180.0, 180.0]$. Normalized across antimeridian. |
| `PositionReport.Sog` | `AISPosition.sog_knots` | Required | Speed Over Ground in knots. Value `102.3` represents unavailable $\to$ maps to `None` or validated to $[0.0, 102.2]$. |
| `PositionReport.Cog` | `AISPosition.cog_deg` | Required | Course Over Ground in degrees $[0.0, 360.0)$. Value `360.0` represents unavailable $\to$ maps to `None`. |
| `PositionReport.TrueHeading` | `AISPosition.heading_deg` | Optional | Value `511` represents unavailable $\to$ maps to `None`. Range $[0, 359]$. |
| `PositionReport.NavigationalStatus` | `AISPosition.nav_status` | Optional | Value `15` represents default / undefined. Integer in $[0, 15]$. |
| `ShipStaticData.ImoNumber` | `VesselIdentity.imo` | Optional | Value `0` represents unavailable $\to$ maps to `None`. 7-digit string. |
| `MetaData.ShipName` / `ShipStaticData.Name` | `VesselIdentity.name` | Optional | Stripped UTF-8 string. Null/empty mapped to `None`. |
| `ShipStaticData.Type` | `VesselIdentity.vessel_type_code` | Optional | Integer code ($70\text{--}79$ cargo, $80\text{--}89$ tanker, $30$ fishing). Mapped to descriptive category. |

---

## 4. Live Data Semantics & Realities

1. **Timestamps:** `MetaData.time_utc` represents the server reception timestamp in UTC. It guarantees a valid monotonic time reference even if ship GPS clocks have minor jitter.
2. **Decoupled Identity vs Position:** Dynamic positions arrive every $2\text{--}10\text{ seconds}$ for underway vessels; static identity arrives every $6\text{ minutes}$. An ingestion engine must maintain an in-memory or database identity cache keyed by MMSI so that position reports inherit vessel names and types.
3. **Duplicate & Out-of-Order Frames:** Crowdsourced receivers can pick up the same VHF transmission simultaneously, producing duplicates with slight millisecond timing differences. The local store must enforce `UNIQUE(mmsi, timestamp_epoch)` with `INSERT OR IGNORE`.
4. **Coverage Gaps & Disappearances:** Vessels may enter RF shadows, turn off transponders, or sail beyond terrestrial antenna range. As established in Phase C and D, **tracking gaps must be treated as unobserved data voids and never as proof of vessel guilt**.

---

## 5. Geographic Coverage & Bombay High Caveat

* **Geographic Coordinates:** Bombay High offshore platforms are located at approximately $19.4167^\circ\text{N}, 71.3333^\circ\text{E}$ in the Arabian Sea, approximately $160\text{ km}$ ($86\text{ nautical miles}$) west of Mumbai coast.
* **Line-of-Sight Limit:** Standard coastal VHF transponders reach $\approx 25\text{--}35\text{ NM}$ ($45\text{--}65\text{ km}$) depending on mast height.
* **API Capability vs Physical Reception:**
  * **API capability (VERIFIED):** The AISStream WebSocket accepts the bounding box `[[19.10, 71.00], [19.85, 71.85]]` without error.
  * **Physical reception (CAVEAT):** Unless an AIS receiver located on an offshore rig (e.g. ONGC Bombay High platform) feeds AISStream, traffic in the offshore field will appear sparse or intermittent compared to coastal harbor areas.
* **Hackathon Presentation Strategy:**
  * Document this physical RF constraint transparently in the presentation.
  * For live demonstration, connect to a coastal corridor with high receiver density (e.g., Mumbai Harbor / Jawaharlal Nehru Port Trust approach).
  * For the offshore Bombay High incident demonstration, execute the verified scenario via `HistoricalFileProvider` and `SyntheticAISProvider`.

---

## 6. Usage Terms & Limitations

* **Cost:** Free service for developers and hobbyists.
* **Account:** Requires a registered account on [aisstream.io](https://aisstream.io/) to generate an API key.
* **Rate & Connection Limits:** Single persistent WebSocket connection per API key is expected.
* **Local Storage & Redistribution:**
  * Caching data locally in a rolling buffer for application processing is standard and necessary.
  * Commercial resale or mass redistribution of raw uncurated AIS feeds is restricted. For SIH academic / competition prototyping, usage is fully compliant.
* **Historical Access:** Zero historical query support. All historical evaluation requires local buffer storage or offline scenario files.

---

## 7. Reliability & Ingestion Failure Modes

| Failure Mode | System Symptom | Recommended Deterministic Mitigation |
| :--- | :--- | :--- |
| **Network Disconnect** | WebSocket close code `1006` / EOF | Exponential backoff reconnect: $1\text{s} \to 2\text{s} \to 4\text{s} \to \dots \to 30\text{s}$ max. Resubscribe automatically on reconnect. |
| **Invalid / Missing API Key** | Connection closed immediately with error | Log clear warning: `"OCEANTRACE_AISSTREAM_API_KEY missing or invalid"`. Gracefully fallback to `HistoricalFileProvider` or `SyntheticAISProvider`. |
| **Malformed JSON Frame** | `json.JSONDecodeError` | Log debug warning, discard frame, increment error metric. Never crash ingestion loop. |
| **Duplicate Position** | Same MMSI and timestamp received | SQLite `INSERT OR IGNORE` on `UNIQUE(mmsi, timestamp_epoch)`. |
| **Out-of-Order Arrival** | Newer message arrives before older ping | Ingestion stores by exact timestamp. Track reconstruction queries use `ORDER BY timestamp_epoch ASC`. |
| **Provider Downtime** | Server unreachable | Correlator notes absence of live feed; Phase D scores reflect lower observation confidence without fabricating evidence. |

---

## 8. Local SQLite Storage Architecture (`ais_local.db`)

An embedded SQLite database is selected for hackathon simplicity, zero external process dependencies, and fast index scans.

### Schema Design:

```sql
-- 1. Vessel Static Metadata Table
CREATE TABLE IF NOT EXISTS vessel_identities (
    mmsi TEXT PRIMARY KEY,
    imo TEXT,
    name TEXT,
    callsign TEXT,
    vessel_type TEXT,
    vessel_type_code INTEGER,
    length_m REAL,
    beam_m REAL,
    last_updated_utc TEXT NOT NULL
);

-- 2. Dynamic Position Reports Table
CREATE TABLE IF NOT EXISTS ais_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mmsi TEXT NOT NULL,
    timestamp_epoch INTEGER NOT NULL,  -- Unix timestamp in seconds for fast numeric range scans
    timestamp_iso TEXT NOT NULL,       -- ISO8601 UTC string for auditability
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

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_positions_mmsi_time 
    ON ais_positions(mmsi, timestamp_epoch ASC);

CREATE INDEX IF NOT EXISTS idx_positions_spatiotemporal 
    ON ais_positions(timestamp_epoch, latitude, longitude);
```

### Key Technical Properties:
* **WAL Mode:** Executing `PRAGMA journal_mode=WAL;` enables concurrent reads from Model 2 correlation while the background WebSocket thread writes incoming pings without lock contention.
* **Synchronous Normal:** `PRAGMA synchronous=NORMAL;` maximizes disk write throughput while maintaining database durability.
* **Epoch-Based Querying:** Filtering on `timestamp_epoch BETWEEN ? AND ?` avoids slow string date parsing in SQLite queries.

---

## 9. Rolling 72-Hour Retention Policy

* **Window Sufficiency:** Model 2 hindcast horizon is strictly **48 hours** ($t_0 - 48\text{h} \to t_0$). A 72-hour retention window provides a **24-hour safety buffer** for late satellite tasking and delayed SAR ingestion.
* **Purge Execution:**
  ```sql
  DELETE FROM ais_positions 
  WHERE timestamp_epoch < strftime('%s', 'now', '-72 hours');
  ```
* **Frequency:** Run purge once per hour in a background maintenance task.
* **Storage Footprint:** At 50 regional vessels reporting every 30 seconds, 72 hours generates $\approx 432,000$ rows, consuming only $\approx 45\text{ MB}$ of disk space.

---

## 10. Concrete Phase E Implementation Roadmap (For Future Builder)

When implementation begins, the following modules will be created:

### 1. `ml/ais_store.py` (Local SQLite Storage Layer)
* `AISStore`: Manages SQLite connection pool in WAL mode.
* Methods:
  * `insert_position(pos: AISPosition)`
  * `insert_identity(ident: VesselIdentity)`
  * `query_positions(query: AISQuery) -> List[AISPosition]`
  * `query_tracks(query: AISQuery) -> List[VesselTrack]`
  * `lookup_vessel(mmsi: str) -> Optional[VesselIdentity]`
  * `purge_older_than(hours: float = 72.0) -> int`

### 2. `ml/providers/aisstream_provider.py` (Live Streaming Provider)
* `AISStreamProvider(AISProvider)`:
  * Manages background WebSocket listener thread.
  * Ingests JSON frames, normalizes to `AISPosition` and `VesselIdentity`, and writes to `AISStore`.
  * Exposes standard `AISProvider` query methods backed by `AISStore`.
  * Gracefully handles connection drops and exponential reconnect backoff.

### 3. Verification & Mock Tests (`tests/test_ais_store.py`, `tests/test_aisstream_provider.py`)
* Unit tests using mock recorded JSON payloads without live internet dependencies.

---

## 11. Alternative & Fallback Provider Comparison

| Provider | Access / Cost | Live Feed | Historical Support | Offshore Bombay High Coverage | Hackathon Suitability |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **AISStream.io** | **Free** (API Key) | **WebSocket** | **No** (Live only) | Moderate / unverified offshore | **Excellent for live demo**; requires local caching |
| **HistoricalFileProvider (OceanTrace)** | **Free** (Local) | No | **Yes** (CSV/SQLite) | **Guaranteed** (Deterministic) | **Essential for reproducible evaluation** |
| **SyntheticAISProvider (OceanTrace)** | **Free** (Local) | No | **Yes** (Procedural) | **100% Deterministic** | **Essential for CI/CD and air-gapped demo** |
| **Global Fishing Watch (GFW)** | Free (Research) | Daily API | Yes (via BigQuery) | Satellite (Global) | Good for post-hoc fishing context; slow for live |
| **Spire / MarineTraffic** | Paid / Commercial | Yes | Yes | Satellite (High) | Inapplicable for free student hackathon |

---

## 12. Verified Facts vs. Assumptions

| Claim / Item | Status | Verified Source |
| :--- | :---: | :--- |
| AISStream WebSocket URL is `wss://stream.aisstream.io/v0/stream` | **VERIFIED** | Official AISStream documentation |
| Authentication is via JSON payload `"APIKey"` field | **VERIFIED** | Official AISStream documentation |
| Handshake timeout is 3 seconds after connection open | **VERIFIED** | Official AISStream documentation |
| AISStream does NOT provide historical REST endpoints or replay | **VERIFIED** | Official AISStream GitHub & developer docs |
| AISStream accepts bounding boxes in `[[lat1, lon1], [lat2, lon2]]` format | **VERIFIED** | Official AISStream documentation |
| Terrestrial AIS reliably covers $160\text{ km}$ offshore Bombay High | **FALSE / CAVEAT** | VHF propagation physics & receiver density |
| SQLite WAL mode supports simultaneous read/write without locks | **VERIFIED** | SQLite documentation |
| Model 1 Checkpoint remains intact and untouched | **VERIFIED** | Checkpoint SHA256 matches frozen hash |

---

## 13. External Sources

1. **AISStream.io Official API Documentation:** `https://aisstream.io/documentation` (Accessed 2026-09-03).
2. **AISStream Message Models Repository:** `https://github.com/aisstream/ais-message-models` (Official schema definitions).
3. **ITU-R M.1371-5 Standard:** Technical characteristics for an automatic identification system using time division multiple access in the VHF maritime mobile band.
4. **SQLite Documentation:** Write-Ahead Logging (`https://sqlite.org/wal.html`).

---

## 14. Project Integrity Verification

* **Model 1 Checkpoint:** `V6_E21_FINAL/oceantrace_v6_E21_final.pth`
* **Verified Checkpoint SHA256:** `4de684fa85daf05fa9d5b330103b4e3536450ccaa9d65724f889225c13eef635` *(Strictly unchanged)*
* **Model 1 Code:** `ml/models.py`, `ml/dataset.py` *(Strictly untouched)*
* **Model 2 Physics:** `ml/drift_engine.py`, `ml/forecast.py`, `ml/hindcast.py` *(Strictly untouched)*
* **Phase B, C, D Code:** `ml/ais_types.py`, `ml/ais_provider.py`, `ml/historical_ais_provider.py`, `ml/synthetic_ais_provider.py`, `ml/ais_corridor.py`, `ml/vessel_attribution.py` *(Strictly untouched)*
* **Part 3 Test Data:** Completely untouched.

---

**STOPPED.** Phase E research and verification is complete. No implementation files or database schemas were created.

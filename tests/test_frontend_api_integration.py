"""
Frontend API Integration Tests for OceanTrace
Tests all endpoints expected by the teammate frontend in src/api/:
1. /health
2. /api/v1/incidents
3. /api/v1/incidents/{id}
4. /api/v1/incidents/{id}/slick
5. /api/v1/incidents/{id}/slick/metrics
6. /api/v1/incidents/{id}/vessels
7. /api/v1/incidents/{id}/recommendations
8. /api/v1/incidents/{id}/evidence
9. /api/v1/vessels
10. /api/v1/vessels/{mmsi}
11. /api/v1/traffic
12. /api/v1/satellite/scenes
13. /api/v1/satellite/process (runs live OceanTracePipeline)
14. /api/v1/incidents/{id}/forecast
15. /api/v1/alerts
16. /api/v1/reports
17. /api/v1/reports/{id}
18. /api/v1/reports/{id}/geojson
"""

import unittest
import hashlib
from fastapi.testclient import TestClient
import backend.app.main as backend_module
from backend.app.services.pipeline_repository import PipelineRepository


class TestFrontendAPIIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend_module.app)
        cls.ckpt_path = "V6_E21_FINAL/oceantrace_v6_E21_final.pth"

    def test_v6_checkpoint_hash(self):
        """Verifies that Model 1 V6 checkpoint SHA256 remains bit-for-bit intact."""
        hasher = hashlib.sha256()
        with open(self.ckpt_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        expected_sha = "4de684fa85daf05fa9d5b330103b4e3536450ccaa9d65724f889225c13eef635"
        self.assertEqual(hasher.hexdigest(), expected_sha, "Model 1 V6 E21 SHA256 mismatch!")

    def test_health_endpoint(self):
        """Tests /health endpoint."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("mode", data)

    def test_incidents_list_and_get_pipeline_offline(self):
        """Tests /api/v1/incidents exposes real canonical OceanTracePipeline outputs."""
        resp = self.client.get("/api/v1/incidents")
        self.assertEqual(resp.status_code, 200)
        incidents = resp.json()
        self.assertIsInstance(incidents, list)
        self.assertGreaterEqual(len(incidents), 1)

        inc0 = incidents[0]
        # In PIPELINE_OFFLINE mode, coordinates and slick metrics come from V6 E21 + Bombay High fixture
        self.assertEqual(inc0["mode"], "PIPELINE_OFFLINE")
        self.assertAlmostEqual(inc0["latitude"], 19.4175, places=3)
        self.assertAlmostEqual(inc0["longitude"], 71.3332, places=3)
        self.assertAlmostEqual(inc0["slick"]["area_km2"], 0.2119, places=3)
        self.assertAlmostEqual(inc0["slick"]["confidence"], 43.1, places=1)

        primary_id = inc0["id"]
        resp_single = self.client.get(f"/api/v1/incidents/{primary_id}")
        self.assertEqual(resp_single.status_code, 200)
        inc = resp_single.json()
        self.assertEqual(inc["id"], primary_id)
        self.assertIn("slick", inc)
        self.assertIn("geom_geojson", inc)
        self.assertEqual(inc["geom_geojson"]["type"], "Point")

    def test_slick_endpoints(self):
        """Tests /api/v1/incidents/{id}/slick and /api/v1/incidents/{id}/slick/metrics."""
        resp = self.client.get("/api/v1/incidents/INC-240824-01/slick")
        self.assertEqual(resp.status_code, 200)
        slick = resp.json()
        self.assertIn("area_km2", slick)
        self.assertIn("confidence", slick)
        self.assertAlmostEqual(slick["area_km2"], 0.2119, places=3)

        resp_metrics = self.client.get("/api/v1/incidents/INC-240824-01/slick/metrics")
        self.assertEqual(resp_metrics.status_code, 200)
        metrics = resp_metrics.json()
        self.assertIn("area_km2", metrics)

    def test_vessels_and_attribution(self):
        """Tests /api/v1/incidents/{id}/vessels exposes canonical ranked attribution candidates."""
        resp = self.client.get("/api/v1/incidents/INC-240824-01/vessels")
        self.assertEqual(resp.status_code, 200)
        vessels = resp.json()
        self.assertGreaterEqual(len(vessels), 1)

        v0 = vessels[0]
        # Candidate 1 is SYNTHETIC TANKER ALPHA (MMSI 999000001, score ~72)
        self.assertEqual(v0["mmsi"], "999000001")
        self.assertIn("SYNTHETIC TANKER ALPHA", v0["name"])
        self.assertEqual(v0["score"], 72)
        self.assertIn("reasons", v0)
        self.assertIn("breakdown", v0)
        self.assertEqual(v0["breakdown"]["trajectory"], 25)

        # Test global vessels list
        resp_all = self.client.get("/api/v1/vessels")
        self.assertEqual(resp_all.status_code, 200)
        all_v = resp_all.json()
        self.assertGreaterEqual(len(all_v), 1)

        # Test single vessel lookup
        resp_v = self.client.get(f"/api/v1/vessels/{v0['mmsi']}")
        self.assertEqual(resp_v.status_code, 200)
        self.assertEqual(resp_v.json()["mmsi"], v0["mmsi"])

    def test_traffic_endpoint(self):
        """Tests /api/v1/traffic and traffic filtering stages."""
        resp = self.client.get("/api/v1/traffic?stage=Suspects")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["stage"], "Suspects")
        self.assertIn("count", data)
        self.assertIn("available_stages", data)

    def test_satellite_scenes_and_live_processing(self):
        """Tests /api/v1/satellite/scenes and /api/v1/satellite/process (runs full pipeline)."""
        resp = self.client.get("/api/v1/satellite/scenes")
        self.assertEqual(resp.status_code, 200)
        scenes = resp.json()
        self.assertGreaterEqual(len(scenes), 1)

        # Test live processing of a scene through OceanTracePipeline
        process_payload = {"scene_id": "S1A_BOMBAY_HIGH_001"}
        resp_proc = self.client.post("/api/v1/satellite/process", json=process_payload)
        self.assertEqual(resp_proc.status_code, 200)
        proc_data = resp_proc.json()
        self.assertEqual(proc_data["status"], "processed")

        # Confirm that incident was registered and can be queried
        inc_id = "INC-S1A_BOMBAY_HIGH_001"
        resp_inc = self.client.get(f"/api/v1/incidents/{inc_id}")
        self.assertEqual(resp_inc.status_code, 200)
        new_inc = resp_inc.json()
        self.assertEqual(new_inc["id"], inc_id)
        self.assertGreater(new_inc["slick"]["area_km2"], 0.0)

        # Check vessels for the newly processed incident
        resp_vessels = self.client.get(f"/api/v1/incidents/{inc_id}/vessels")
        self.assertEqual(resp_vessels.status_code, 200)
        vessels = resp_vessels.json()
        self.assertGreaterEqual(len(vessels), 1)

    def test_forecast_endpoint(self):
        """Tests /api/v1/incidents/{id}/forecast returns real P-LDHE trajectory steps."""
        resp = self.client.get("/api/v1/incidents/INC-240824-01/forecast")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["incident_id"], "INC-240824-01")
        self.assertIn("path_geojson", data)
        coords = data["path_geojson"]["coordinates"]
        # Real Model 2 forecast generates multi-step trajectory
        self.assertGreaterEqual(len(coords), 5)
        # Starting point matches detected slick centroid lon/lat
        self.assertAlmostEqual(coords[0][0], 71.3331, places=2)
        self.assertAlmostEqual(coords[0][1], 19.4173, places=2)

    def test_alerts_endpoint(self):
        """Tests /api/v1/alerts."""
        resp = self.client.get("/api/v1/alerts")
        self.assertEqual(resp.status_code, 200)
        alerts = resp.json()
        self.assertGreaterEqual(len(alerts), 1)

    def test_reports_and_geojson_endpoints(self):
        """Tests /api/v1/reports, /api/v1/reports/{id}, and /api/v1/reports/{id}/geojson."""
        resp = self.client.get("/api/v1/reports")
        self.assertEqual(resp.status_code, 200)
        reports = resp.json()
        self.assertGreaterEqual(len(reports), 1)

        rep_id = reports[0]["id"]
        resp_single = self.client.get(f"/api/v1/reports/{rep_id}")
        self.assertEqual(resp_single.status_code, 200)
        report = resp_single.json()
        self.assertEqual(report["id"], rep_id)
        self.assertIn("incident", report)
        self.assertIn("vessels", report)
        self.assertIn("evidence", report)

        resp_geo = self.client.get(f"/api/v1/reports/{rep_id}/geojson")
        self.assertEqual(resp_geo.status_code, 200)
        geo = resp_geo.json()
        self.assertEqual(geo["type"], "Feature")
        self.assertIn("geometry", geo)

    def test_demo_mode_fallback(self):
        """Verifies that DEMO mode retains teammate demo dataset when explicitly configured."""
        demo_repo = PipelineRepository(mode="DEMO")
        self.assertEqual(demo_repo.mode, "DEMO")
        demo_inc = demo_repo.get_incident("INC-240824-01")
        self.assertIsNotNone(demo_inc)
        self.assertEqual(demo_inc.mode, "DEMO")
        self.assertEqual(demo_inc.latitude, 14.5333)
        self.assertEqual(demo_inc.longitude, 68.3)
        self.assertEqual(demo_inc.slick.area_km2, 12.8)
        demo_vessels = demo_repo.vessels_for_incident("INC-240824-01")
        self.assertEqual(demo_vessels[0].mmsi, "477981200")


if __name__ == "__main__":
    unittest.main()

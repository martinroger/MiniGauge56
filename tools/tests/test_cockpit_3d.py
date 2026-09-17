"""Unit and integration tests for MiniGauge 3D Cyber-Cockpit Replayer (cockpit_3d.py)."""

import io
import json
import sys
import unittest
from pathlib import Path

# Ensure workspace root and decoder dir are on sys.path
TEST_DIR = Path(__file__).resolve().parent
DECODER_DIR = TEST_DIR.parent
WORKSPACE_DIR = DECODER_DIR.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))
if str(DECODER_DIR) not in sys.path:
    sys.path.insert(0, str(DECODER_DIR))

from cockpit_3d import (
    lat_lon_to_enu,
    extract_cockpit_trajectory,
    CockpitHandler,
    GEAR_MAP,
    STATUS_MAP,
)
from common.dbc import get_dbc
from common.can_core import find_bin_files

SCRIPT_DIR = Path(__file__).resolve().parent.parent


class TestCockpit3D(unittest.TestCase):
    """Test suite for 3D trajectory projection and cockpit telemetry extraction."""

    def setUp(self):
        self.dbc_path = SCRIPT_DIR / "binocan.dbc"
        self.db = get_dbc(self.dbc_path)

    def test_lat_lon_to_enu(self):
        # Point identical to origin should be (0, 0, 0)
        lat0, lon0, alt0 = 45.893, 15.939, 250.0
        x, y, z = lat_lon_to_enu(lat0, lon0, alt0, lat0, lon0, alt0)
        self.assertAlmostEqual(x, 0.0, places=2)
        self.assertAlmostEqual(y, 0.0, places=2)
        self.assertAlmostEqual(z, 0.0, places=2)

        # 1 degree North (~111.19 km)
        x_n, y_n, z_n = lat_lon_to_enu(lat0 + 1.0, lon0, alt0 + 50.0, lat0, lon0, alt0)
        self.assertAlmostEqual(x_n, 0.0, delta=100.0)
        self.assertGreater(y_n, 110000.0)
        self.assertLess(y_n, 112000.0)
        self.assertAlmostEqual(z_n, 50.0, places=2)

        # 1 degree East (~77.4 km at 45.89 deg latitude)
        x_e, y_e, z_e = lat_lon_to_enu(lat0, lon0 + 1.0, alt0, lat0, lon0, alt0)
        self.assertGreater(x_e, 76000.0)
        self.assertLess(x_e, 79000.0)
        self.assertAlmostEqual(y_e, 0.0, delta=100.0)

    def test_extract_trajectory_real_log(self):
        bin_files = find_bin_files(SCRIPT_DIR)
        if not bin_files:
            self.skipTest("No .bin log files found in tools directory")

        log_path = bin_files[0]
        data = extract_cockpit_trajectory(log_path, self.db, downsample=1)

        self.assertEqual(data["filename"], log_path.name)
        self.assertGreater(data["frame_count"], 0)
        self.assertGreater(data["duration_s"], 0.0)
        self.assertIn("stats", data)
        self.assertIn("avg_g", data["stats"])
        self.assertIn("max_g", data["stats"])
        self.assertIn("g_thresh", data["stats"])
        self.assertIn("g_bound", data["stats"])
        self.assertIn("g_mid", data["stats"])
        self.assertAlmostEqual(data["stats"]["g_thresh"], data["stats"]["max_g"] * 0.75, places=2)
        self.assertAlmostEqual(data["stats"]["g_bound"], data["stats"]["max_g"] * 1.1, places=2)
        self.assertAlmostEqual(data["stats"]["g_mid"], data["stats"]["max_g"] * 0.5, places=2)
        self.assertIn("points", data)

        if data["has_gps"]:
            self.assertGreater(data["point_count"], 0)
            pt0 = data["points"][0]
            required_keys = [
                "t", "x", "y", "z", "lat", "lon", "alt",
                "speed", "gps_speed", "heading", "rpm", "gear",
                "gear_txt", "coolant", "fuel", "battery",
                "g_lat", "g_lon", "g_vert", "grade", "status_l", "status_r", "tell_tales"
            ]
            for k in required_keys:
                self.assertIn(k, pt0, f"Missing key {k} in trajectory point")

            # Origin check: initial point must be at re-scaled 0.0 elevation
            self.assertAlmostEqual(pt0["x"], 0.0, delta=1.0)
            self.assertAlmostEqual(pt0["y"], 0.0, delta=1.0)
            self.assertAlmostEqual(pt0["z"], 0.0, places=2)

    def test_trajectory_downsampling(self):
        bin_files = find_bin_files(SCRIPT_DIR)
        if not bin_files:
            self.skipTest("No .bin log files found in tools directory")
        log_path = bin_files[0]

        data_full = extract_cockpit_trajectory(log_path, self.db, downsample=1)
        if not data_full["has_gps"] or data_full["point_count"] < 10:
            self.skipTest("Log has insufficient GPS points for downsampling test")

        data_down = extract_cockpit_trajectory(log_path, self.db, downsample=2)
        # Downsampled count should be approximately half
        self.assertAlmostEqual(data_down["point_count"], data_full["point_count"] // 2 + 1, delta=3)

    def test_gear_and_status_mappings(self):
        self.assertEqual(GEAR_MAP[0], "N")
        self.assertEqual(GEAR_MAP[1], "1")
        self.assertEqual(GEAR_MAP[6], "6")
        self.assertEqual(GEAR_MAP[15], "R")

        self.assertEqual(STATUS_MAP[2], "OK")
        self.assertEqual(STATUS_MAP[3], "DEGRADED")

    def test_acceleration_axes_orientation(self):
        """Verifies X and Y acceleration axes are correctly mapped:
        - g_lon tracks longitudinal acceleration (positive when accelerating, negative when braking)
        - g_lat tracks lateral acceleration (positive when turning right, negative when turning left)
        """
        bin_files = find_bin_files(SCRIPT_DIR)
        if not bin_files:
            self.skipTest("No .bin log files found in tools directory")
        log_path = bin_files[0]
        data = extract_cockpit_trajectory(log_path, self.db, downsample=1)
        pts = data["points"]
        self.assertGreater(len(pts), 100)

        corr_lon, corr_lat = 0.0, 0.0
        corr_rot_lon, corr_rot_lat = 0.0, 0.0

        for i in range(len(pts) - 1):
            dt = pts[i + 1]["t"] - pts[i]["t"]
            if 0.05 <= dt <= 0.5:
                dv = (pts[i + 1]["speed"] - pts[i]["speed"]) / 3.6
                a_g = (dv / dt) / 9.81
                corr_lon += a_g * pts[i]["g_lon"]
                corr_lat += a_g * pts[i]["g_lat"]

                if pts[i]["speed"] > 20:
                    dh = pts[i + 1]["heading"] - pts[i]["heading"]
                    if dh > 180:
                        dh -= 360
                    if dh < -180:
                        dh += 360
                    yaw_rate = dh / dt
                    corr_rot_lon += yaw_rate * pts[i]["g_lon"]
                    corr_rot_lat += yaw_rate * pts[i]["g_lat"]

        # g_lon must correlate much more strongly with dv/dt than g_lat
        self.assertGreater(corr_lon, 3.0)
        self.assertGreater(corr_lon, corr_lat * 2.0)

        # g_lat must correlate much more strongly with turn rate than g_lon
        self.assertGreater(corr_rot_lat, 50.0)
        self.assertGreater(corr_rot_lat, corr_rot_lon * 5.0)

    def test_local_road_grade_calculation(self):
        """Verifies local road grade (%) calculation across trajectory points."""
        bin_files = find_bin_files(SCRIPT_DIR)
        if not bin_files:
            self.skipTest("No .bin log files found in tools directory")
        log_path = bin_files[0]
        data = extract_cockpit_trajectory(log_path, self.db, downsample=1)
        pts = data["points"]
        self.assertGreater(len(pts), 50)
        grades = [p["grade"] for p in pts]

        # Road grades should be reasonable realistic percentages (between -35% and +35%)
        self.assertGreater(max(grades), -35.0)
        self.assertLess(max(grades), 35.0)
        self.assertGreater(min(grades), -35.0)
        self.assertLess(min(grades), 35.0)

        # Confirm non-trivial grade variation exists
        self.assertNotEqual(min(grades), max(grades))


class MockSocket:
    def makefile(self, *args, **kwargs):
        return io.BytesIO(b"")


import threading
import urllib.request
import urllib.error
from common.http_server import ThreadingHTTPServer


class TestCockpitHandlerEndpoints(unittest.TestCase):
    """Verifies HTTP routing for template, static files, and JSON trajectory API."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), CockpitHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_template_and_static_files_exist(self):
        template = SCRIPT_DIR / "web" / "templates" / "cockpit_3d.html"
        self.assertTrue(template.is_file(), "cockpit_3d.html template must exist")

        css = SCRIPT_DIR / "web" / "static" / "css" / "cockpit_3d.css"
        self.assertTrue(css.is_file(), "cockpit_3d.css must exist")

        js = SCRIPT_DIR / "web" / "static" / "js" / "cockpit_3d.js"
        self.assertTrue(js.is_file(), "cockpit_3d.js must exist")

    def test_http_get_index(self):
        req = urllib.request.Request(f"{self.base_url}/")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            self.assertIn("rpm-glyph", body)
            self.assertIn("speed-glyph", body)
            self.assertIn("gear-glyph", body)
            self.assertIn("arc-rpm", body)
            self.assertIn("arc-speed", body)
            self.assertIn("g-meter-uncontainerized", body)
            self.assertIn("g-circle", body)
            self.assertIn("g-heatmap-canvas", body)
            self.assertIn("g-mid-ring", body)
            self.assertIn("g-lbl-outer", body)
            self.assertIn("g-lbl-mid", body)
            self.assertIn("chk-g-vectors", body)
            self.assertIn("log-filename", body)
            self.assertNotIn("telltale-cluster", body)
            self.assertNotIn("txt-status-l", body)
            self.assertNotIn("txt-status-r", body)
            self.assertNotIn("theme-toggle-btn", body)

    def test_http_get_favicon(self):
        req = urllib.request.Request(f"{self.base_url}/favicon.ico")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("image/svg+xml", resp.headers.get("Content-Type", ""))

    def test_http_get_static_assets(self):
        assets = [
            ("/static/css/cockpit_3d.css", "text/css"),
            ("/static/js/cockpit_3d.js", "javascript"),
            ("/static/css/theme.css", "text/css"),
            ("/static/css/base.css", "text/css"),
            ("/static/js/theme.js", "javascript"),
            ("/static/js/toast.js", "javascript"),
        ]
        for path, expected_mime in assets:
            req = urllib.request.Request(f"{self.base_url}{path}")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200, f"Failed for {path}")
                ct = resp.headers.get("Content-Type", "")
                self.assertIn(expected_mime, ct, f"MIME mismatch for {path}: {ct}")
                data = resp.read()
                self.assertGreater(len(data), 0, f"Empty body for {path}")

    def test_http_get_static_not_found(self):
        req = urllib.request.Request(f"{self.base_url}/static/css/nonexistent_xyz.css")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    def test_http_api_logs(self):
        req = urllib.request.Request(f"{self.base_url}/api/logs")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIsInstance(data, list)
            if not data:
                self.skipTest("No .bin logs found on disk")
            self.assertIn("filename", data[0])

    def test_http_api_trajectory(self):
        req = urllib.request.Request(f"{self.base_url}/api/trajectory")
        try:
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                if not data.get("points"):
                    self.skipTest("No .bin logs found on disk for trajectory")
                self.assertIn("points", data)
                self.assertIn("stats", data)
                self.assertTrue(data["has_gps"])
                self.assertGreater(len(data["points"]), 0)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                self.skipTest("No .bin log files found on disk for trajectory")
            raise



if __name__ == "__main__":
    unittest.main()

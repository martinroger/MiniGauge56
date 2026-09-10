import json
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DECODER_DIR = REPO_ROOT / "decoder"
CALIBRATION_FILE = DECODER_DIR / "gear_calibration.json"


class TestTunerServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Backup gear_calibration.json if it exists
        cls.orig_cal_bytes = None
        if CALIBRATION_FILE.is_file():
            cls.orig_cal_bytes = CALIBRATION_FILE.read_bytes()

        # Start tuner.py on an isolated test port
        cls.port = 8199
        print(f"\n[test_tuner] Starting tuner.py on port {cls.port}...")
        cls.proc = subprocess.Popen(
            [sys.executable, str(DECODER_DIR / "tuner.py"), "--port", str(cls.port), "--no-browser"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO_ROOT)
        )
        time.sleep(1.8)

    @classmethod
    def tearDownClass(cls):
        # Terminate server process
        if cls.proc and cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                cls.proc.kill()

        # Restore original gear_calibration.json
        if cls.orig_cal_bytes is not None:
            CALIBRATION_FILE.write_bytes(cls.orig_cal_bytes)

    def test_01_index_html_structure_and_dom_ids(self):
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode('utf-8')

        # Check core UI controls
        required_controls = [
            "select-gear-preset",
            "chk-gear-rpm-filter",
            "chk-gear-latch",
            "card-gear-math",
            "btn-replay-play",
            "slider-replay-scrub",
            "chk-gear-gauge-pod",
            "pod-simulated-gear",
            "pod-tuner-gear",
            "btn-save-shared-cal",
            "chk-speed-filter-accel",
            "slider-speed-maxaccel",
            "sc-speed-samples",
            "sc-fuel-mae",
            "sc-fuel-rmse",
            "sc-fuel-maxerr",
            "sc-fuel-sim-slew",
            "sc-fuel-sim-jitter",
            "sc-fuel-meas-slew",
            "sc-fuel-meas-jitter",
            "sc-fuel-samples",
        ]
        for ctrl in required_controls:
            self.assertIn(ctrl, html, f"Missing control or metric element: {ctrl}")

        # Check that all getElementById targets in client JS exist in HTML DOM
        import re
        scripts = re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.DOTALL)
        inline_script = '\n'.join([s for s in scripts if len(s.strip()) > 100])
        js_ids = set(re.findall(r'getElementById\([\"\']([^\"\']+)[\\"\']\)', inline_script))
        html_ids = set(re.findall(r'id=[\"\']([^\"\']+)[\"\']', html))
        missing_ids = [jid for jid in js_ids if jid not in html_ids]
        self.assertEqual(len(missing_ids), 0, f"Found missing HTML IDs referenced in JS: {missing_ids}")
        print(f"[test_tuner] ✓ Verified all {len(js_ids)} getElementById targets exist in DOM.")

    def test_02_api_logs(self):
        url = f"http://127.0.0.1:{self.port}/api/logs"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            logs = json.loads(resp.read().decode('utf-8'))
            self.assertIsInstance(logs, list)
            self.assertGreaterEqual(len(logs), 1)
            print(f"[test_tuner] ✓ /api/logs returned {len(logs)} log files.")

    def test_03_api_algo_data(self):
        url_logs = f"http://127.0.0.1:{self.port}/api/logs"
        with urllib.request.urlopen(url_logs) as resp:
            logs = json.loads(resp.read().decode('utf-8'))
        log_name = logs[0]["filename"]

        url_algo = f"http://127.0.0.1:{self.port}/api/algo_data?file={log_name}"
        with urllib.request.urlopen(url_algo) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode('utf-8'))
            self.assertIn("gear", data)
            self.assertIn("fuel", data)
            self.assertIn("speed", data)
            self.assertGreater(len(data["gear"]["times"]), 0)
            print(f"[test_tuner] ✓ /api/algo_data returned {len(data['gear']['times'])} frames.")

    def test_04_api_calibration_get_and_post(self):
        url_cal = f"http://127.0.0.1:{self.port}/api/calibration"
        with urllib.request.urlopen(url_cal) as resp:
            self.assertEqual(resp.status, 200)
            cal = json.loads(resp.read().decode('utf-8'))
            self.assertIn("nominal_ratios", cal)
            print(f"[test_tuner] ✓ GET /api/calibration nominal ratios: {cal['nominal_ratios']}")

        post_data = json.dumps({"tolerance": 0.25, "latch_ms": 225}).encode('utf-8')
        req = urllib.request.Request(url_cal, data=post_data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode('utf-8'))
            self.assertEqual(res.get("status"), "ok")
            self.assertEqual(res["saved"]["latch_ms"], 225)
            print("[test_tuner] ✓ POST /api/calibration updated shared parameters successfully.")


if __name__ == "__main__":
    unittest.main()


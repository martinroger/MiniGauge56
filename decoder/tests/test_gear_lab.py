import json
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DECODER_DIR = REPO_ROOT / "decoder"
CALIBRATION_FILE = DECODER_DIR / "gear_calibration.json"


class TestGearLabServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_cal_bytes = None
        if CALIBRATION_FILE.is_file():
            cls.orig_cal_bytes = CALIBRATION_FILE.read_bytes()

        cls.port = 8198
        print(f"\n[test_gear_lab] Starting gear_lab.py on port {cls.port}...")
        cls.proc = subprocess.Popen(
            [sys.executable, str(DECODER_DIR / "gear_lab.py"), "--port", str(cls.port), "--no-browser"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO_ROOT)
        )
        time.sleep(1.8)

    @classmethod
    def tearDownClass(cls):
        if cls.proc and cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                cls.proc.kill()

        if cls.orig_cal_bytes is not None:
            CALIBRATION_FILE.write_bytes(cls.orig_cal_bytes)

    def test_01_index_html_dashboard(self):
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode('utf-8')

        required = [
            "MiniGauge Gear Estimator Lab",
            "benchmark-table",
            "btn-replay-play",
            "slider-replay-scrub",
            "m1-pod-gear",
            "m2-pod-gear",
            "m3-pod-gear",
            "btn-auto-tune",
            "btn-save-shared-cal",
        ]
        for elem in required:
            self.assertIn(elem, html, f"Missing dashboard element: {elem}")
        print("[test_gear_lab] ✓ HTML dashboard rendered with Triple Gauge Pod, Replayer, and Auto-Tune controls.")

    def test_02_api_logs(self):
        url = f"http://127.0.0.1:{self.port}/api/logs"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            logs = json.loads(resp.read().decode('utf-8'))
            self.assertIsInstance(logs, list)
            self.assertGreaterEqual(len(logs), 1)
            print(f"[test_gear_lab] ✓ Discovered {len(logs)} log files.")

    def test_03_api_dataset_all(self):
        url = f"http://127.0.0.1:{self.port}/api/dataset?log=all"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode('utf-8'))
            self.assertIn("fitted", data)
            self.assertEqual(len(data["fitted"]["means"]), 5)
            self.assertIn("benchmarks", data)
            b = data["benchmarks"]
            self.assertIn("m1", b)
            self.assertIn("m2", b)
            self.assertIn("m3", b)
            print(f"[test_gear_lab] ✓ Benchmarks evaluated: M1={b['m1']['glitch_score']}%, M2={b['m2']['glitch_score']}%, M3={b['m3']['glitch_score']}%")

    def test_04_api_calibration_and_autotune(self):
        url_cal = f"http://127.0.0.1:{self.port}/api/calibration"
        with urllib.request.urlopen(url_cal) as resp:
            self.assertEqual(resp.status, 200)
            cal = json.loads(resp.read().decode('utf-8'))
            self.assertIn("nominal_ratios", cal)

        # POST calibration update
        post_data = json.dumps({"tolerance": 0.25, "latch_ms": 220}).encode('utf-8')
        req = urllib.request.Request(url_cal, data=post_data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode('utf-8'))
            self.assertEqual(res.get("status"), "ok")

        # POST auto_tune
        tune_req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/auto_tune", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(tune_req) as resp:
            self.assertEqual(resp.status, 200)
            tune_res = json.loads(resp.read().decode('utf-8'))
            self.assertEqual(tune_res.get("status"), "ok")
            rec = tune_res["recommended"]
            print(f"[test_gear_lab] ✓ Auto-tune completed: best score = {rec['best_score']}%")

    def test_05_api_export_c_and_gcc_verification(self):
        url = f"http://127.0.0.1:{self.port}/api/export_c"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            c_header = resp.read().decode('utf-8')
            self.assertIn("gear_estimator_params.h", c_header)
            self.assertIn("gear_heuristic_update", c_header)
            self.assertIn("gear_bayesian_update", c_header)
            self.assertIn("gear_hmm_update", c_header)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            header_file = tmppath / "gear_estimator_params.h"
            header_file.write_text(c_header)

            c_src = """#include <stdio.h>
#include "gear_estimator_params.h"

int main(void) {
    gear_heuristic_state_t h_st;
    gear_heuristic_init(&h_st);
    uint8_t g1 = gear_heuristic_update(&h_st, 37.6f, 10.0f, 0.05f);

    gear_bayesian_state_t b_st;
    gear_bayesian_init(&b_st);
    uint8_t g2 = gear_bayesian_update(&b_st, 37.6f, 10.0f, 0.05f);

    gear_hmm_state_t hmm_st;
    gear_hmm_init(&hmm_st);
    uint8_t g3 = gear_hmm_update(&hmm_st, 37.6f, 10.0f, 0.05f);

    printf("C verification: Heuristic=%d, Bayesian=%d, HMM=%d\\n", g1, g2, g3);
    return 0;
}
"""
            src_file = tmppath / "verify.c"
            src_file.write_text(c_src)
            bin_file = tmppath / "verify"

            gcc_proc = subprocess.run(
                ["gcc", "-Wall", "-Wextra", "-Werror", "-O2", str(src_file), "-lm", "-o", str(bin_file)],
                capture_output=True,
                text=True
            )
            self.assertEqual(gcc_proc.returncode, 0, f"GCC compilation failed:\n{gcc_proc.stderr}")

            run_proc = subprocess.run([str(bin_file)], capture_output=True, text=True)
            self.assertEqual(run_proc.returncode, 0)
            print(f"[test_gear_lab] ✓ GCC compiled exported C header with zero warnings (-Wall -Wextra -Werror). Execution output: {run_proc.stdout.strip()}")


if __name__ == "__main__":
    unittest.main()


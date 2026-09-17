"""Unit tests for MiniGauge common decoder subcomponents."""

import io
import json
import tempfile
import unittest
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
TOOLS_DIR = TEST_DIR.parent
WORKSPACE_DIR = TOOLS_DIR.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from common.can_core import (
    CanFrame,
    read_bin_file,
    find_bin_files,
    natural_sort_key,
    RECORD_STRUCT,
    RECORD_SIZE,
)
from common.dbc import (
    SignalDef,
    MessageDef,
    DbcDatabase,
    get_dbc,
)
from common.calibration import (
    load_calibration,
    save_calibration,
    get_default_calibration,
)
from common.http_server import (
    BaseAppHandler,
    find_available_port,
    MIME_TYPES,
)



class TestCanCore(unittest.TestCase):
    def test_can_frame_init_and_properties(self):
        # 5-arg signature (decode.py style)
        f1 = CanFrame(1000, 1.0, 0x100, 8, b"\x01\x02\x03\x04\x05\x06\x07\x08")
        self.assertEqual(f1.timestamp_ms, 1000)
        self.assertEqual(f1.ts_ms, 1000)
        self.assertEqual(f1.time_rel_s, 1.0)
        self.assertEqual(f1.rel_s, 1.0)
        self.assertEqual(f1.can_id, 0x100)
        self.assertEqual(f1.dlc, 8)
        self.assertEqual(f1.data, b"\x01\x02\x03\x04\x05\x06\x07\x08")

        # 4-arg signature (gear_lab style)
        f2 = CanFrame(2000, 0x300, 4, b"\xaa\xbb\xcc\xdd")
        self.assertEqual(f2.timestamp_ms, 2000)
        self.assertEqual(f2.time_rel_s, 0.0)
        self.assertEqual(f2.can_id, 0x300)
        self.assertEqual(f2.dlc, 4)

        # Mutability of aliases
        f2.ts_ms = 2500
        f2.rel_s = 0.5
        self.assertEqual(f2.timestamp_ms, 2500)
        self.assertEqual(f2.time_rel_s, 0.5)

    def test_find_bin_files_and_natural_sort(self):
        # Verify natural sort order
        names = [Path("log_1.bin"), Path("log_2.bin"), Path("log_10.bin")]
        sorted_names = sorted(names, key=natural_sort_key)
        self.assertEqual([p.name for p in sorted_names], ["log_1.bin", "log_2.bin", "log_10.bin"])

        files = find_bin_files()
        if not files:
            self.skipTest("No .bin log files found on disk")
        self.assertGreater(len(files), 0)
        for f in files:
            self.assertTrue(f.name.endswith(".bin"))

    def test_find_bin_files_fixtures_fallback(self):
        # Empty search dir should trigger fixtures fallback
        with tempfile.TemporaryDirectory() as empty_dir:
            files = find_bin_files(search_dirs=[Path(empty_dir)])
            self.assertGreater(len(files), 0)
            self.assertTrue(any("fixtures" in str(p) for p in files))
            self.assertTrue(all(p.name.endswith(".bin") for p in files))



class TestDbc(unittest.TestCase):
    def test_dbc_loading(self):
        db = get_dbc()
        self.assertIsNotNone(db)
        self.assertGreater(len(db.messages), 0)

        # Verify known messages
        m100 = db.get_message(0x100)
        self.assertIsNotNone(m100)
        self.assertIn("ITF_speed_kph", m100.signals)
        self.assertIn("ITF_rpm", m100.signals)

        # Verify decode
        payload = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        decoded = m100.decode(payload)
        self.assertIn("ITF_speed_kph", decoded)
        self.assertEqual(decoded["ITF_speed_kph"]["value"], 0)


class TestCalibration(unittest.TestCase):
    def test_calibration_io(self):
        cal = get_default_calibration()
        self.assertIn("nominal_ratios", cal)
        self.assertEqual(len(cal["nominal_ratios"]), 5)
        self.assertIn("vars", cal)
        self.assertEqual(len(cal["vars"]), 5)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "test_cal.json"
            save_calibration({"m2_decay": 0.99, "min_speed_hz": 5.0, "min_rpm_hz": 40.0}, tmppath, source="unit_test")
            loaded = load_calibration(tmppath)
            self.assertEqual(loaded["m2_decay"], 0.99)
            self.assertEqual(loaded["source"], "unit_test")
            self.assertAlmostEqual(loaded["min_speed_kph"], 5.0 * 2.214, places=2)
            self.assertEqual(loaded["min_rpm"], 40 * 30)

            # Test reverse sync
            save_calibration({"min_speed_kph": 22.14, "min_rpm": 1200}, tmppath, source="unit_test_rev")
            loaded_rev = load_calibration(tmppath)
            self.assertAlmostEqual(loaded_rev["min_speed_hz"], 10.0, places=1)
            self.assertAlmostEqual(loaded_rev["min_rpm_hz"], 40.0, places=1)


class TestHttpServerBasics(unittest.TestCase):
    def test_find_port(self):
        port = find_available_port(18000)
        self.assertGreaterEqual(port, 18000)

    def test_mime_types(self):
        self.assertEqual(MIME_TYPES[".css"], "text/css; charset=utf-8")
        self.assertEqual(MIME_TYPES[".js"], "application/javascript; charset=utf-8")

    def test_static_asset_serving(self):
        class DummyHandler(BaseAppHandler):
            def __init__(self):
                self.headers_sent = []
                self.status_code = None
                self.output = bytearray()

            def send_response(self, code, message=None):
                self.status_code = code

            def send_header(self, keyword, value):
                self.headers_sent.append((keyword, value))

            def end_headers(self):
                pass

            @property
            def wfile(self):
                class Writer:
                    def __init__(self, buf):
                        self.buf = buf
                    def write(self, data):
                        self.buf.extend(data)
                return Writer(self.output)

            def send_error(self, code, message=None):
                self.status_code = code

        h = DummyHandler()
        # Existing CSS
        ok = h.serve_static("css/theme.css")
        self.assertTrue(ok)
        self.assertEqual(h.status_code, 200)
        self.assertTrue(any(k == "Content-Type" and "text/css" in v for k, v in h.headers_sent))

        # Existing JS
        h2 = DummyHandler()
        ok2 = h2.serve_static("/static/js/theme.js")
        self.assertTrue(ok2)
        self.assertEqual(h2.status_code, 200)

        # Missing file
        h3 = DummyHandler()
        ok3 = h3.serve_static("css/nonexistent.css")
        self.assertFalse(ok3)

        # Directory traversal attempt
        h4 = DummyHandler()
        ok4 = h4.serve_static("../../../etc/passwd")
        self.assertEqual(h4.status_code, 403)


if __name__ == "__main__":
    unittest.main()

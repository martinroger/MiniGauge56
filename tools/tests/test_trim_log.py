import os
import struct
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DECODER_DIR = REPO_ROOT / "tools"
import sys
if str(DECODER_DIR) not in sys.path:
    sys.path.insert(0, str(DECODER_DIR))

from trim_log import trim_log, read_raw_log, generate_safe_output_path
from decode import read_bin_file


class TestTrimLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmppath = Path(self.tmpdir.name)

        # Create a synthetic 16-byte binary CAN log with 100 frames (10 Hz, 10 seconds total)
        self.test_log = self.tmppath / "test_run.bin"
        RECORD_STRUCT = struct.Struct("<IHB8sx")
        records = bytearray()
        for i in range(100):
            ts = 50000 + i * 100  # Starts at 50,000 ms uptime
            cid = 0x100 if (i % 2 == 0) else 0x301
            dlc = 8
            payload = struct.pack("<I4s", i, b"DATA")
            records.extend(RECORD_STRUCT.pack(ts, cid, dlc, payload))
        self.test_log.write_bytes(records)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_01_time_slice_zero_rebase(self):
        # Trim from 2.0s to 5.0s (should be roughly frames 20 to 50)
        out_file, n_frames, dur = trim_log(self.test_log, start_s=2.0, end_s=5.0, rebase_zero=True)
        self.assertTrue(out_file.is_file())
        self.assertNotEqual(out_file.resolve(), self.test_log.resolve())

        frames = read_bin_file(out_file)
        self.assertEqual(len(frames), n_frames)
        # Verify first timestamp is 0 ms due to zero-rebasing
        self.assertEqual(frames[0].timestamp_ms, 0)
        self.assertAlmostEqual(frames[0].time_rel_s, 0.0, places=3)
        self.assertAlmostEqual(dur, 3.0, delta=0.2)

    def test_02_preserve_timestamps(self):
        # Trim with preserve_timestamps (should keep raw 50,000+ ms timestamps)
        out_file, n_frames, dur = trim_log(self.test_log, start_s=1.0, end_s=3.0, rebase_zero=False)
        frames = read_bin_file(out_file)
        self.assertGreaterEqual(frames[0].timestamp_ms, 50000)

    def test_03_frame_index_slicing(self):
        out_file, n_frames, dur = trim_log(self.test_log, from_frame=10, to_frame=29, rebase_zero=True)
        self.assertEqual(n_frames, 20)
        frames = read_bin_file(out_file)
        self.assertEqual(len(frames), 20)

    def test_04_can_id_filter(self):
        # Filter only CAN ID 0x301 (odd frames)
        out_file, n_frames, dur = trim_log(self.test_log, from_frame=0, to_frame=99, allowed_ids=[0x301])
        frames = read_bin_file(out_file)
        self.assertEqual(len(frames), 50)
        for f in frames:
            self.assertEqual(f.can_id, 0x301)

    def test_05_strict_non_destructive_safety(self):
        # Attempting to overwrite the input log must raise ValueError
        with self.assertRaises(ValueError):
            trim_log(self.test_log, output_path=self.test_log, start_s=1.0, end_s=2.0)

    def test_06_safe_automatic_suffixing_collision(self):
        # First cut
        out1, _, _ = trim_log(self.test_log, start_s=1.0, end_s=3.0)
        self.assertTrue(out1.exists())
        # Second cut with same bounds creates _01.bin suffix without collision or overwrite
        out2, _, _ = trim_log(self.test_log, start_s=1.0, end_s=3.0)
        self.assertTrue(out2.exists())
        self.assertNotEqual(out1.resolve(), out2.resolve())
        self.assertIn("_01", out2.name)

    def test_07_preview_data_without_gps(self):
        # Synthetic log without 0x601 frames should return empty gps list
        from trim_log import get_preview_data
        data = get_preview_data(self.test_log)
        self.assertEqual(data["gps"], [])
        self.assertEqual(data["total_frames"], 100)

    def test_08_preview_data_with_gps(self):
        # Create a log with synthetic GPS frames (ID 0x601)
        from trim_log import get_preview_data
        RECORD_STRUCT = struct.Struct("<IHB8sx")
        records = bytearray()
        gps_log = self.tmppath / "gps_test.bin"
        for i in range(50):
            ts = 1000 + i * 100
            cid = 0x601
            dlc = 8
            # Lat 45.8 deg, Lon 15.8 deg
            lat_raw = int(45.8000000 * 1e7) + i * 100
            lon_raw = int(15.8000000 * 1e7) + i * 100
            payload = struct.pack("<ii", lat_raw, lon_raw)
            records.extend(RECORD_STRUCT.pack(ts, cid, dlc, payload))
        gps_log.write_bytes(records)

        data = get_preview_data(gps_log)
        self.assertEqual(len(data["gps"]), 50)
        self.assertAlmostEqual(data["gps"][0]["lat"], 45.8, places=2)
        self.assertAlmostEqual(data["gps"][0]["lon"], 15.8, places=2)


if __name__ == "__main__":
    unittest.main()


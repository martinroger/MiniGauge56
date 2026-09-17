"""Unit and integration tests for MiniGauge CAN Log Replayer & UDP Streamer (streamer.py)."""

import io
import json
import socket
import struct
import sys
import time
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

from streamer import (
    UDP_MAGIC,
    MASK_STANDBY,
    pack_udp_packet,
    find_closest_fuel_step,
    LogTimeline,
    PlaybackStreamer,
    StreamerHandler,
)
from common.dbc import get_dbc
from common.can_core import find_bin_files


class TestStreamer(unittest.TestCase):
    """Test suite for streamer packet packing, timeline indexing, and playback engine."""

    def setUp(self):
        self.dbc_path = DECODER_DIR / "binocan.dbc"
        self.db = get_dbc(self.dbc_path)

    def test_pack_udp_packet(self):
        """Validates 14-byte VehicleUdpPacket layout, little-endian encoding, and checksum."""
        mask = 0xD940
        speed_freq = 100.0   # 1000 in 0.1 Hz
        rpm_freq = 200.0     # 2000 in 0.1 Hz
        coolant_duty = 35.70 # 3570 in 0.01 %
        fuel_ohm = 120.0     # 1200 in 0.1 Ohm

        packet, checksum = pack_udp_packet(mask, speed_freq, rpm_freq, coolant_duty, fuel_ohm)

        # 1. Verify exact 14 bytes
        self.assertEqual(len(packet), 14)

        # 2. Verify magic header [0xAA, 0x55]
        self.assertEqual(packet[0:2], b"\xAA\x55")

        # 3. Unpack all 16-bit fields
        magic, rx_mask, rx_spd, rx_rpm, rx_cool, rx_fuel, rx_chk = struct.unpack("<2sHHHHHH", packet)
        self.assertEqual(magic, b"\xAA\x55")
        self.assertEqual(rx_mask, 0xD940)
        self.assertEqual(rx_spd, 1000)
        self.assertEqual(rx_rpm, 2000)
        self.assertEqual(rx_cool, 3570)
        self.assertEqual(rx_fuel, 1200)
        self.assertEqual(rx_chk, checksum)

        # 4. Verify checksum calculation (sum of first 12 bytes)
        calc_chk = sum(packet[0:12]) & 0xFFFF
        self.assertEqual(calc_chk, checksum)

    def test_closest_fuel_step(self):
        """Verifies fuel step resolution for various resistance values."""
        self.assertEqual(find_closest_fuel_step(30.0), 1)   # 30.2 Ohm -> Step 1
        self.assertEqual(find_closest_fuel_step(119.0), 10) # 118.9 Ohm -> Step 10
        self.assertEqual(find_closest_fuel_step(270.0), 19) # 270.0 Ohm -> Step 19

    def test_log_timeline_indexing(self):
        """Tests reading a real .bin log, indexing signals, and sampling at timeline points."""
        bin_files = find_bin_files(DECODER_DIR)
        if not bin_files:
            self.skipTest("No .bin log files found in tools dir")

        timeline = LogTimeline(bin_files[0], self.db)
        self.assertGreater(timeline.frame_count, 0)
        self.assertGreater(timeline.duration_s, 0.0)

        # Sample at midpoint
        mid_time = timeline.duration_s / 2.0
        sample = timeline.sample_at(mid_time)

        self.assertIn("speed_freq", sample)
        self.assertIn("rpm_freq", sample)
        self.assertIn("coolant_duty", sample)
        self.assertIn("fuel_ohm", sample)
        self.assertIn("telltales_mask", sample)
        self.assertIn("disp_kph", sample)
        self.assertIn("disp_rpm", sample)

        # Invariant: Bit 15 (Ignition) must ALWAYS be 1 to protect emulator board power
        self.assertTrue(bool(sample["telltales_mask"] & 0x8000), "Ignition bit 15 must be set")

    def test_loopback_udp_streaming(self):
        """Starts PlaybackStreamer and captures actual UDP datagrams on loopback port."""
        # Find an open UDP port for testing
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        streamer = None
        try:
            test_sock.bind(("127.0.0.1", 0))
            _, test_port = test_sock.getsockname()
            test_sock.settimeout(2.0)

            bin_files = find_bin_files(DECODER_DIR)
            if not bin_files:
                self.skipTest("No .bin log files found in tools dir")

            streamer = PlaybackStreamer(target_host="127.0.0.1", target_port=test_port)
            streamer.load_log(bin_files[0], self.db)

            # Start streaming
            streamer.play()
            time.sleep(0.1)

            # Receive a packet
            data, addr = test_sock.recvfrom(64)
            self.assertEqual(len(data), 14)
            self.assertEqual(data[0:2], b"\xAA\x55")

            # Checksum verification
            calc_chk = sum(data[0:12]) & 0xFFFF
            pkt_chk = struct.unpack("<H", data[12:14])[0]
            self.assertEqual(calc_chk, pkt_chk)

            # Pause streaming
            streamer.pause()
            status = streamer.get_status()
            self.assertEqual(status["state"], "PAUSED")
            self.assertGreater(status["packets_sent"], 0)

            # Test seek
            streamer.seek(10.0)
            status_seek = streamer.get_status()
            self.assertAlmostEqual(status_seek["current_time_s"], 10.0, places=1)

        finally:
            if streamer:
                streamer.close()
            test_sock.close()

    def test_streamer_web_assets(self):
        """Verifies that streamer.html, streamer.css, and streamer.js exist and are valid."""
        template_file = DECODER_DIR / "web" / "templates" / "streamer.html"
        css_file = DECODER_DIR / "web" / "static" / "css" / "streamer.css"
        js_file = DECODER_DIR / "web" / "static" / "js" / "streamer.js"

        self.assertTrue(template_file.is_file(), "streamer.html not found")
        self.assertTrue(css_file.is_file(), "streamer.css not found")
        self.assertTrue(js_file.is_file(), "streamer.js not found")

        html_content = template_file.read_text(encoding="utf-8")
        self.assertIn("MINIGAUGE", html_content)
        self.assertIn("val-speed-kph", html_content)
        self.assertIn("val-rpm", html_content)
        self.assertIn("scrub-slider", html_content)
        self.assertIn("telltale-grid", html_content)
        self.assertIn("plot-traces", html_content)
        self.assertIn("graph-cursor", html_content)

    def test_timeline_traces(self):
        """Verifies downsampled trace extraction for Speed & RPM Plotly chart."""
        bin_files = find_bin_files(DECODER_DIR)
        if not bin_files:
            self.skipTest("No .bin log files found in tools dir")

        timeline = LogTimeline(bin_files[0], self.db)
        traces = timeline.get_traces(max_points=2500)

        self.assertIn("times", traces)
        self.assertIn("speeds", traces)
        self.assertIn("rpms", traces)
        self.assertIn("duration_s", traces)

        self.assertEqual(len(traces["times"]), len(traces["speeds"]))
        self.assertEqual(len(traces["times"]), len(traces["rpms"]))
        self.assertLessEqual(len(traces["times"]), 2500)
        self.assertGreater(len(traces["times"]), 0)
        self.assertAlmostEqual(traces["duration_s"], timeline.duration_s, places=2)


if __name__ == "__main__":
    unittest.main()


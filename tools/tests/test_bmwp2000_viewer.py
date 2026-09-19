"""Automated unit and regression tests for MiniGauge BMWP2000 Exchange Viewer.

Verifies:
- Multi-format log loader (.bin, candump .log, Vector .asc)
- Fixture regression on candump-2024-02-24_015831.log & candump-2024-02-24_020530.log
- ISO-TP transport framing (SF, FF, CF, multi-frame reassembly)
- KWP2000 protocol dissection (0x2C LID, 0x21 Data, 0x22 CID, 0x7F NRC error decoding)
- Unimplemented / unknown service detection
- Dynamic LID registration and CID formula scaling
- POST /api/add_cid atomic backup creation
- HTTP API endpoints and server lifecycles

Zero pip dependencies (Python 3 stdlib only).
"""

import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

# Ensure workspace root and tools dir are on sys.path
TEST_DIR = Path(__file__).resolve().parent
TOOLS_DIR = TEST_DIR.parent
REPO_ROOT = TOOLS_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from common.can_core import CanFrame
from common.log_loader import detect_log_format, load_log_file, parse_candump_log
from common.isotp_kwp import (
    IsoTpReassembler,
    BmwP2000Dissector,
    LidDefinition,
    LidEntry,
)
import bmwp2000_viewer
from bmwp2000_viewer import (
    analyze_log_exchanges,
    create_backup,
    BmwP2000ViewerHandler,
)
from common.http_server import ThreadingHTTPServer, find_available_port


class TestBmwP2000ViewerLogic(unittest.TestCase):
    """Unit tests for protocol reassembly, dissection, and multi-format log parsing."""

    def setUp(self):
        self.fixtures_dir = TOOLS_DIR / "fixtures"
        self.candump_log1 = self.fixtures_dir / "candump-2024-02-24_015831.log"
        self.candump_log2 = self.fixtures_dir / "candump-2024-02-24_020530.log"
        self.bin_log = self.fixtures_dir / "20260912_log_165944.bin"

    def test_log_format_detection(self):
        self.assertEqual(detect_log_format(self.candump_log1), "candump")
        self.assertEqual(detect_log_format(self.candump_log2), "candump")
        self.assertEqual(detect_log_format(self.bin_log), "bin")

    def test_candump_log_parsing(self):
        frames = load_log_file(self.candump_log1)
        self.assertGreater(len(frames), 100)
        # Verify timestamps, can_ids, and data lengths
        self.assertEqual(frames[0].can_id, 0x130)
        # Find diagnostic frames (0x6F1, 0x612)
        diag_frames = [f for f in frames if f.can_id in (0x6F1, 0x612)]
        self.assertGreater(len(diag_frames), 10)

    def test_isotp_single_frame_reassembly(self):
        reassembler = IsoTpReassembler()
        # Single Frame on 0x6F1: target 0x12, length 3, payload: 0x2C 0xF0 0x04
        frame = CanFrame(100, 0.1, 0x6F1, 8, bytes.fromhex("12032CF004000000"))
        msg = reassembler.process_frame(frame)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.can_id, 0x6F1)
        self.assertEqual(msg.direction, "OUTGOING")
        self.assertEqual(msg.target_ecu, 0x12)
        self.assertEqual(msg.raw_payload, bytes.fromhex("2CF004"))
        self.assertFalse(msg.is_multiframe)
        self.assertEqual(msg.frame_count, 1)

    def test_isotp_multi_frame_reassembly(self):
        reassembler = IsoTpReassembler()
        # First Frame: FF len 0x0E (14 bytes), payload 2CF0020101
        f1 = CanFrame(100, 0.1, 0x6F1, 8, bytes.fromhex("12100E2CF0020101"))
        # Consecutive Frame 1: SN 1, payload 580C01020201
        f2 = CanFrame(102, 0.102, 0x6F1, 8, bytes.fromhex("1221580C01020201"))
        # Consecutive Frame 2: SN 2, payload 440201000000
        f3 = CanFrame(104, 0.104, 0x6F1, 8, bytes.fromhex("1222440201000000"))

        self.assertIsNone(reassembler.process_frame(f1))
        self.assertIsNone(reassembler.process_frame(f2))
        msg = reassembler.process_frame(f3)
        self.assertIsNotNone(msg)
        self.assertTrue(msg.is_multiframe)
        self.assertEqual(msg.frame_count, 3)
        self.assertEqual(len(msg.raw_payload), 14)
        self.assertEqual(msg.raw_payload[:3], bytes.fromhex("2CF002"))

    def test_kwp2000_lid_dissection_and_unknown_cid_detection(self):
        master_cids = {
            "RPM": {"id": "0x580C", "mul": 40, "div": 1, "add": 0, "unit": "RPM"},
        }
        dissector = BmwP2000Dissector(master_cids)
        reassembler = IsoTpReassembler()

        # Reassemble LID setup: LocalId 0xF0, two mode 0x02 entries:
        # Entry 1: 0x02 (mode), 0x01 (pos_in_lid), 0x01 (mem_size), 0x58 0x0C (CID RPM), 0x01 (pos_in_cid)
        # Entry 2: 0x02 (mode), 0x02 (pos_in_lid), 0x02 (mem_size), 0x99 0x99 (Unknown CID), 0x01 (pos_in_cid)
        payload = bytes.fromhex("2CF0020101580C01020202999901")
        frame = CanFrame(100, 0.1, 0x6F1, 8, bytes([0x12, len(payload)]) + payload)
        msg = reassembler.process_frame(frame)

        dissected = dissector.dissect_message(msg)
        self.assertEqual(dissected["service_id"], "0x2C")
        self.assertEqual(dissected["service_name"], "dynamicallyDefineLocalIdentifier")
        self.assertIn(0xF0, dissector.active_lids)

        entries = dissected["details"]["entries"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["cid_name"], "RPM")
        self.assertTrue(entries[0]["is_known"])
        self.assertEqual(entries[1]["cid_name"], "UNKNOWN_0x9999")
        self.assertFalse(entries[1]["is_known"])

        # Verify unknown CIDs list for prompt
        unknowns = dissected["details"]["unknown_cids"]
        self.assertEqual(len(unknowns), 1)
        self.assertEqual(unknowns[0]["id"], "0x9999")

    def test_negative_response_decoding(self):
        dissector = BmwP2000Dissector()
        reassembler = IsoTpReassembler()
        # 0x7F Negative Response: rejected 0x2C, NRC 0x11 (serviceNotSupported)
        payload = bytes.fromhex("7F2C11")
        frame = CanFrame(200, 0.2, 0x612, 8, bytes([0xF1, len(payload)]) + payload + b"\xFF\xFF\xFF")
        msg = reassembler.process_frame(frame)

        dissected = dissector.dissect_message(msg)
        self.assertTrue(dissected["is_negative_response"])
        self.assertEqual(dissected["details"]["rejected_service_id"], "0x2C")
        self.assertEqual(dissected["details"]["nrc"], "0x11")
        self.assertEqual(dissected["details"]["nrc_name"], "serviceNotSupported")

    def test_unimplemented_service_highlighting(self):
        dissector = BmwP2000Dissector()
        reassembler = IsoTpReassembler()
        # Proprietary or unhandled service 0xBA
        payload = bytes.fromhex("BA010203")
        frame = CanFrame(300, 0.3, 0x6F1, 8, bytes([0x12, len(payload)]) + payload + b"\x00\x00")
        msg = reassembler.process_frame(frame)

        dissected = dissector.dissect_message(msg)
        self.assertFalse(dissected["is_implemented"])
        self.assertEqual(dissected["service_id"], "0xBA")

    def test_fixture_analysis_candump1(self):
        analysis = analyze_log_exchanges(self.candump_log1)
        self.assertGreater(analysis["frame_count"], 100)
        self.assertGreater(analysis["stats"]["outgoing_count"], 5)
        self.assertGreater(analysis["stats"]["incoming_count"], 5)
        # Should detect LID setup and positive response
        lid_exchanges = [e for e in analysis["exchanges"] if e["service_id"] in ("0x2C", "0x6C")]
        self.assertGreater(len(lid_exchanges), 0)

    def test_fixture_analysis_candump2(self):
        analysis = analyze_log_exchanges(self.candump_log2)
        self.assertGreater(analysis["frame_count"], 1000)
        # Multi-frame responses should be present
        multiframe_exchanges = [e for e in analysis["exchanges"] if e["is_multiframe"]]
        self.assertGreater(len(multiframe_exchanges), 5)

    def test_service_parameters_decryption(self):
        dissector = BmwP2000Dissector()
        reassembler = IsoTpReassembler()

        # 1. 0x21 ReadDataByLocalIdentifier with fastRate polling (0x04)
        payload = bytes.fromhex("21F004")
        frame = CanFrame(100, 0.1, 0x6F1, 8, bytes([0x12, len(payload)]) + payload)
        msg = reassembler.process_frame(frame)
        dissected = dissector.dissect_message(msg)
        self.assertEqual(dissected["service_id"], "0x21")
        self.assertEqual(dissected["details"]["recordLocalIdentifier"], "0xF0")
        self.assertEqual(dissected["details"]["transmissionMode"], "0x04")
        self.assertEqual(dissected["details"]["transmission_mode_name"], "fast")

        # 2. 0x10 StartDiagnosticSession with bmwSpecialDiagnosticSession (0x86)
        payload10 = bytes.fromhex("1086")
        frame10 = CanFrame(110, 0.11, 0x6F1, 8, bytes([0x12, len(payload10)]) + payload10)
        msg10 = reassembler.process_frame(frame10)
        dissected10 = dissector.dissect_message(msg10)
        self.assertEqual(dissected10["service_id"], "0x10")
        self.assertEqual(dissected10["details"]["diagnosticSessionType"], "0x86")
        self.assertEqual(dissected10["details"]["diagnosticSessionName"], "bmwSpecialDiagnosticSession")

    def test_timing_deltas_and_raw_can(self):
        # Analyze candump1 which contains both non-diagnostic (0x130, 0x153) and diagnostic (0x6F1, 0x612)
        analysis = analyze_log_exchanges(self.candump_log1, include_raw_can=True)
        exchanges = analysis["exchanges"]
        self.assertGreater(len(exchanges), 50)

        # Verify raw CAN traffic is flagged
        raw_frames = [e for e in exchanges if e.get("is_raw_can")]
        self.assertGreater(len(raw_frames), 10)
        self.assertEqual(raw_frames[0]["service_name"], "Raw CAN Frame")

        # Verify delta timing is computed
        for idx in range(1, len(exchanges)):
            self.assertIsNotNone(exchanges[idx]["delta_prev_ms"])
            self.assertGreaterEqual(exchanges[idx]["delta_prev_ms"], 0.0)

        # Verify request intervals on consecutive requests
        requests = [e for e in exchanges if e.get("direction") == "OUTGOING"]
        self.assertGreater(len(requests), 5)
        self.assertIsNone(requests[0]["req_interval_ms"])
        self.assertIsNotNone(requests[1]["req_interval_ms"])
        self.assertGreater(requests[1]["req_interval_ms"], 0.0)

    def test_canonical_services_summary(self):
        analysis = analyze_log_exchanges(self.candump_log1)
        canonical = analysis["canonical_services"]
        self.assertGreater(len(canonical), 10)

        active_sids = {s["sid_hex"] for s in canonical if s["is_active"]}
        self.assertIn("0x2C", active_sids)
        self.assertIn("0x21", active_sids)


class TestBmwP2000ServerAndApi(unittest.TestCase):
    """Direct in-memory integration tests for request handler and API endpoints."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_cids_file = Path(self.temp_dir.name) / "cids.json"
        self.test_cids_file.write_text(json.dumps({
            "_schema_guide": {"description": "test guide"},
            "RPM": {"id": "0x580C", "memory_size": 1, "position": 1, "mul": 40, "div": 1, "add": 0, "unit": "RPM"}
        }, indent=2), encoding="utf-8")
        bmwp2000_viewer.CIDS_FILE_PATH = self.test_cids_file

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_mock_handler(self, path: str, method: str = "GET", body: bytes = None):
        import io

        class DummyHandler(BmwP2000ViewerHandler):
            def __init__(self):
                self.command = method
                self.path = path
                self.headers = {
                    "Content-Length": str(len(body)) if body else "0",
                    "Content-Type": "application/json",
                }
                self.rfile = io.BytesIO(body or b"")
                self.wfile = io.BytesIO()
                self.status_code = 200
                self.headers_sent = []

            def send_response(self, code, message=None):
                self.status_code = code

            def send_header(self, keyword, value):
                self.headers_sent.append((keyword, value))

            def end_headers(self):
                pass

            def send_error(self, code, message=None, explain=None):
                self.status_code = code

        return DummyHandler()

    def test_get_root_page(self):
        h = self._create_mock_handler("/")
        h.do_GET()
        self.assertEqual(h.status_code, 200)
        output = h.wfile.getvalue().decode("utf-8")
        self.assertIn("BMWP2000", output)
        self.assertIn("Diagnostic Exchange", output)

    def test_get_api_files(self):
        h = self._create_mock_handler("/api/files")
        h.do_GET()
        self.assertEqual(h.status_code, 200)
        files = json.loads(h.wfile.getvalue().decode("utf-8"))
        self.assertIsInstance(files, list)
        self.assertGreater(len(files), 0)

    def test_get_api_exchanges(self):
        h = self._create_mock_handler("/api/exchanges?file=candump-2024-02-24_015831.log")
        h.do_GET()
        self.assertEqual(h.status_code, 200)
        data = json.loads(h.wfile.getvalue().decode("utf-8"))
        self.assertIn("exchanges", data)
        self.assertIn("stats", data)
        self.assertGreater(len(data["exchanges"]), 0)

    def test_post_add_cid_with_backup_and_unique_suffixing(self):
        new_cid = {
            "name": "Target_Boost",
            "id": "0x58F2",
            "memory_size": 2,
            "position": 1,
            "signed": False,
            "mul": 0.0390625,
            "div": 1.0,
            "add": 0.0,
            "unit": "Bar",
            "description": "Target boost pressure"
        }
        body_bytes = json.dumps(new_cid).encode("utf-8")
        h = self._create_mock_handler("/api/add_cid", method="POST", body=body_bytes)
        h.do_POST()
        self.assertEqual(h.status_code, 200)
        res_data = json.loads(h.wfile.getvalue().decode("utf-8"))
        self.assertEqual(res_data["status"], "success")
        self.assertEqual(res_data["name"], "Target_Boost")
        self.assertIsNotNone(res_data["backup"])

        backup_path = Path(res_data["backup"])
        self.assertTrue(backup_path.is_file())

        saved_cids = json.loads(self.test_cids_file.read_text(encoding="utf-8"))
        self.assertIn("Target_Boost", saved_cids)
        self.assertEqual(saved_cids["Target_Boost"]["id"], "0x58F2")
        self.assertEqual(saved_cids["Target_Boost"]["mul"], 0.0390625)
        self.assertEqual(saved_cids["Target_Boost"]["description"], "Target boost pressure")

        # Now add duplicate "Target_Boost" - verify suffixing to "Target_Boost_1"
        h2 = self._create_mock_handler("/api/add_cid", method="POST", body=body_bytes)
        h2.do_POST()
        self.assertEqual(h2.status_code, 200)
        res_data2 = json.loads(h2.wfile.getvalue().decode("utf-8"))
        self.assertEqual(res_data2["name"], "Target_Boost_1")
        self.assertTrue(res_data2["renamed"])

        saved_cids2 = json.loads(self.test_cids_file.read_text(encoding="utf-8"))
        self.assertIn("Target_Boost", saved_cids2)
        self.assertIn("Target_Boost_1", saved_cids2)

    def test_signed_integer_unpacking(self):
        master_cids = {
            "ambientTemp": {"id": "0x4401", "signed": True, "mul": 1, "div": 1, "add": 0, "unit": "°C"},
            "timingAdvance": {"id": "0x4402", "signed": True, "mul": 0.5, "div": 1.0, "add": 0, "unit": "deg"},
        }
        dissector = BmwP2000Dissector(master_cids)
        reassembler = IsoTpReassembler()

        # LID setup: Local ID 0xF0, two mode 0x02 entries:
        # Entry 1: 0x02 (mode), 0x01 (pos_in_lid), 0x01 (mem_size), 0x44 0x01 (CID ambientTemp), 0x01 (pos_in_cid)
        # Entry 2: 0x02 (mode), 0x02 (pos_in_lid), 0x02 (mem_size), 0x44 0x02 (CID timingAdvance), 0x01 (pos_in_cid)
        payload = bytes.fromhex("2CF0020101440101020202440201")
        frame = CanFrame(100, 0.1, 0x6F1, 8, bytes([0x12, len(payload)]) + payload)
        msg = reassembler.process_frame(frame)
        dissector.dissect_message(msg)

        # Response: 0x61 0xF0, byte1: 0xFB (-5 in int8), byte2-3: 0xFFF6 (-10 in int16 -> -5.0 deg)
        resp_payload = bytes.fromhex("61F0FBFFF6")
        resp_frame = CanFrame(110, 0.11, 0x612, 8, bytes([0xF1, len(resp_payload)]) + resp_payload)
        resp_msg = reassembler.process_frame(resp_frame)
        resp_dissected = dissector.dissect_message(resp_msg)

        signals = resp_dissected["details"].get("signals", [])
        self.assertEqual(len(signals), 2)
        self.assertEqual(signals[0]["cid_name"], "ambientTemp")
        self.assertEqual(signals[0]["raw_int"], -5)
        self.assertEqual(signals[0]["scaled_value"], -5)
        self.assertEqual(signals[1]["cid_name"], "timingAdvance")
        self.assertEqual(signals[1]["raw_int"], -10)
        self.assertEqual(signals[1]["scaled_value"], -5.0)

    def test_interrupted_iso_tp_detection(self):
        reassembler = IsoTpReassembler(session_timeout_s=0.5)
        # First Frame: FF len 0x20 (32 bytes)
        f1 = CanFrame(100, 0.1, 0x612, 8, bytes.fromhex("F1102061F0001122"))
        reassembler.process_frame_events(f1)
        # Sequence number mismatch on CF: expected 1, send 5
        f2 = CanFrame(105, 0.105, 0x612, 8, bytes.fromhex("F125334455667788"))
        interrupted, completed = reassembler.process_frame_events(f2)
        self.assertIn(0x612, reassembler.active_sessions)
        self.assertFalse(reassembler.active_sessions[0x612]["is_compliant"])
        self.assertTrue(any("sequence number mismatch" in w for w in reassembler.active_sessions[0x612]["warnings"]))

        # Premature EOF flush
        flushed = reassembler.flush_interrupted_sessions()
        self.assertEqual(len(flushed), 1)
        self.assertTrue(flushed[0].is_interrupted)
        self.assertFalse(flushed[0].is_compliant)

    def test_lid_subfunction_0x02_and_unknown_signals_unpacking(self):
        master_cids = {
            "Engine_Speed": {"id": "0x580C", "mul": 40, "div": 1, "add": 0, "unit": "RPM"},
        }
        dissector = BmwP2000Dissector(master_cids)
        reassembler = IsoTpReassembler()

        # LID setup: Local ID 0xF0, two mode 0x02 entries:
        # Entry 1: 0x02 (mode), 0x01 (pos_in_lid), 0x02 (mem_size), 0x58 0x0C (CID Engine_Speed), 0x01 (pos_in_cid)
        # Entry 2: 0x02 (mode), 0x03 (pos_in_lid), 0x01 (mem_size), 0x77 0x88 (Unknown CID), 0x01 (pos_in_cid)
        payload = bytes.fromhex("2CF0020102580C01020301778801")
        frame = CanFrame(100, 0.1, 0x6F1, 8, bytes([0x12, len(payload)]) + payload)
        msg = reassembler.process_frame(frame)
        dissected = dissector.dissect_message(msg)
        self.assertEqual(dissected["details"]["local_id"], "0xF0")
        self.assertEqual(len(dissected["details"]["entries"]), 2)

        # ReadDataByLocalIdentifier response: 0x61 0xF0 [data: 0x00 0x64 (100 -> 4000 RPM), 0x2A (42 dec)]
        resp_payload = bytes.fromhex("61F000642A")
        resp_frame = CanFrame(110, 0.11, 0x612, 8, bytes([0xF1, len(resp_payload)]) + resp_payload)
        resp_msg = reassembler.process_frame(resp_frame)
        resp_dissected = dissector.dissect_message(resp_msg)

        signals = resp_dissected["details"].get("signals", [])
        self.assertEqual(len(signals), 2)
        # Known CID
        self.assertEqual(signals[0]["cid_name"], "Engine_Speed")
        self.assertEqual(signals[0]["scaled_value"], 4000)
        self.assertEqual(signals[0]["unit"], "RPM")
        # Unknown CID: still unpacked with raw values!
        self.assertEqual(signals[1]["cid_hex"], "0x7788")
        self.assertEqual(signals[1]["scaled_value"], 42)
        self.assertEqual(signals[1]["raw_hex"], "2A")

    def test_post_upload_api(self):
        import base64
        test_log_content = "(1708736315.011192) can0 6F1#12032CF004000000\n(1708736315.015143) can0 612#F1026CF0FFFFFFFF\n"
        b64_content = base64.b64encode(test_log_content.encode("utf-8")).decode("utf-8")
        upload_payload = {
            "filename": "uploaded_test_fixture.log",
            "content_base64": b64_content,
        }
        body_bytes = json.dumps(upload_payload).encode("utf-8")
        h = self._create_mock_handler("/api/upload", method="POST", body=body_bytes)
        h.do_POST()
        self.assertEqual(h.status_code, 200)
        res = json.loads(h.wfile.getvalue().decode("utf-8"))
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["filename"], "uploaded_test_fixture.log")
        self.assertEqual(res["format"], "candump")


if __name__ == "__main__":
    unittest.main()

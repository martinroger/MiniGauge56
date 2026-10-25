"""BMW-FAST over CAN (extended addressing) compliance rules in the ISO-TP reassembler and dissector."""
import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_DIR))

from common.can_core import CanFrame  # noqa: E402
from common.isotp_kwp import IsoTpReassembler, BmwP2000Dissector  # noqa: E402


def frame(t, can_id, hexdata):
    data = bytes.fromhex(hexdata)
    return CanFrame(int(t * 1000), t, can_id, len(data), data)


def feed(reassembler, frames):
    out = []
    for f in frames:
        for m in reassembler.process_frame_events(f):
            if m:
                out.append(m)
    return out


class BmwFastIsoTpTests(unittest.TestCase):
    def test_seven_byte_first_frame_is_compliant(self):
        # 7 bytes do not fit a BMW-FAST SF (6 max), so FF+CF is the correct framing
        msgs = feed(IsoTpReassembler(), [
            frame(0.000, 0x6F1, "1210072CF0020101"),
            frame(0.001, 0x612, "F1300000FFFFFFFF"),
            frame(0.002, 0x6F1, "1221580CAAAAAAAA"),
        ])
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].is_compliant, msgs[0].warnings)
        self.assertEqual(msgs[0].raw_payload.hex().upper(), "2CF0020101580C")

    def test_short_first_frame_is_flagged(self):
        msgs = feed(IsoTpReassembler(), [
            frame(0.000, 0x6F1, "1210062CF0020101"),
            frame(0.002, 0x6F1, "122158AAAAAAAAAA"),
        ])
        self.assertFalse(msgs[0].is_compliant)
        self.assertTrue(any("fits a BMW-FAST Single Frame" in w for w in msgs[0].warnings))

    def test_single_frame_longer_than_six_is_flagged(self):
        msgs = feed(IsoTpReassembler(), [frame(0.0, 0x612, "F10761F001020304")])
        self.assertFalse(msgs[0].is_compliant)
        self.assertTrue(any("> 6" in w for w in msgs[0].warnings))

    def test_ecu_flow_control_is_attached_to_tester_transfer(self):
        msgs = feed(IsoTpReassembler(), [
            frame(0.000, 0x6F1, "1210072CF0020101"),
            frame(0.001, 0x612, "F1300000FFFFFFFF"),
            frame(0.002, 0x6F1, "1221580CAAAAAAAA"),
        ])
        self.assertEqual([f["can_id"] for f in msgs[0].can_frames], ["0x6F1", "0x612", "0x6F1"])

    def test_non_diagnostic_6xx_traffic_is_not_iso_tp(self):
        r = IsoTpReassembler()
        self.assertFalse(r.is_iso_tp_candidate(0x600, bytes.fromhex("00000000201C0000")))
        self.assertTrue(r.is_iso_tp_candidate(0x612, bytes.fromhex("F1026CF0FFFFFFFF")))
        self.assertTrue(r.is_iso_tp_candidate(0x640, bytes.fromhex("F1025A80AAAAAAAA")))
        self.assertEqual(feed(r, [frame(0.0, 0x601, "0000000000000000")]), [])

    def test_read_lid_with_any_extra_byte_warns(self):
        d = BmwP2000Dissector({})
        two = d.dissect_message(feed(IsoTpReassembler(), [frame(0.0, 0x6F1, "120221F0AAAAAAAA")])[0])
        three = d.dissect_message(feed(IsoTpReassembler(), [frame(0.0, 0x6F1, "120321F001AAAAAA")])[0])
        fast = d.dissect_message(feed(IsoTpReassembler(), [frame(0.0, 0x6F1, "120321F004AAAAAA")])[0])
        self.assertEqual(two["warnings"], [])
        self.assertTrue(any("NRC 0x12" in w for w in three["warnings"]))
        self.assertTrue(any("NRC 0x12" in w for w in fast["warnings"]))
        self.assertNotIn("transmission_mode", fast["details"])


if __name__ == "__main__":
    unittest.main()

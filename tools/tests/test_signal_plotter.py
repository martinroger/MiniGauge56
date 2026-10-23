import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_DIR))

import signal_plotter  # noqa: E402

FIXTURE = TOOLS_DIR / "fixtures" / "candump-2024-08-11_172107.log"


class SignalPlotterTests(unittest.TestCase):
    def setUp(self):
        signal_plotter.viewer.CIDS_FILE_PATH = signal_plotter.viewer.DEFAULT_CIDS_PATH
        signal_plotter._CACHE.clear()

    def test_extract_signals_returns_parallel_series(self):
        data = signal_plotter.extract_signals(FIXTURE)
        names = {s["name"] for s in data["signals"]}
        self.assertIn("rpm", names)
        for s in data["signals"]:
            self.assertEqual(len(s["t"]), len(s["v"]))
            self.assertEqual(s["t"], sorted(s["t"]))

    def test_log_without_readouts_yields_no_signals(self):
        data = signal_plotter.extract_signals(TOOLS_DIR / "fixtures" / "uploaded_test_fixture.log")
        self.assertEqual(data["signals"], [])


if __name__ == "__main__":
    unittest.main()

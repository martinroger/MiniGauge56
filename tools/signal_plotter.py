#!/usr/bin/env python3
"""MiniGauge Signal Plotter.

Local web workstation to plot parsed CID signals from a CAN log against time
(stacked lanes or shared axis) or against each other (XY), in the spirit of
vx-tools. Reuses the BMWP2000 viewer's log loader and KWP2000 dissector.

Zero pip dependencies (Python 3 stdlib only).
"""

import argparse
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
for _p in (REPO_ROOT, SCRIPT_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common.http_server import BaseAppHandler, start_server
from common.log_loader import find_all_log_files, detect_log_format
import bmwp2000_viewer as viewer

INITIAL_LOG_FILE: Optional[Path] = None
_CACHE: Dict[str, Dict[str, Any]] = {}


def extract_signals(log_path: Path, use_lids_fallback: bool = True) -> Dict[str, Any]:
    """Collects every decoded signal of a log as parallel time/value series.

    With use_lids_fallback, LIDs the log never defines are decoded using
    config/lids.json (same behaviour as the exchange viewer's toggle).
    """
    key = f"{log_path}:{log_path.stat().st_mtime_ns}:{viewer.CIDS_FILE_PATH}:{use_lids_fallback}"
    if key in _CACHE:
        return _CACHE[key]

    result = viewer.analyze_log_exchanges(
        log_path,
        parse_cids=True,
        master_cids=viewer.load_cids_dictionary(viewer.CIDS_FILE_PATH),
        include_raw_can=False,
        fallback_lids=viewer.load_lids_config(viewer.LIDS_FILE_PATH) if use_lids_fallback else None,
    )
    series: Dict[str, Dict[str, Any]] = {}
    for ex in result["exchanges"]:
        details = ex.get("details", {})
        for sig in details.get("signals", []) or []:
            if sig.get("is_truncated") or sig.get("scaled_value") is None:
                continue
            s = series.setdefault(sig["cid_name"], {
                "name": sig["cid_name"],
                "cid": sig.get("cid_hex"),
                "unit": sig.get("unit", ""),
                "lid": details.get("local_id"),
                "t": [],
                "v": [],
            })
            s["t"].append(ex["time_s"])
            s["v"].append(sig["scaled_value"])

    data = {
        "filename": log_path.name,
        "duration_s": result["duration_s"],
        "lids_fallback": use_lids_fallback,
        "signals": sorted(series.values(), key=lambda s: s["name"].lower()),
    }
    _CACHE.clear()
    _CACHE[key] = data
    return data


class SignalPlotterHandler(BaseAppHandler):
    def do_GET(self) -> None:
        path, query = self.parse_query()

        if path.startswith("/static/"):
            if not self.serve_static(path):
                self.send_error(404, f"Static asset {path} not found")
            return

        if path in ("/", "/index.html"):
            self.send_html(self.render_template("signal_plotter.html"))
            return

        if path == "/api/files":
            self.send_json([
                {"filename": p.name, "path": str(p), "size": p.stat().st_size,
                 "format": detect_log_format(p)}
                for p in find_all_log_files(INITIAL_LOG_FILE)
            ])
            return

        if path == "/api/signals":
            wanted = query.get("file", [""])[0]
            target = next((p for p in find_all_log_files(INITIAL_LOG_FILE)
                           if p.name == wanted or str(p) == wanted), None)
            if target is None:
                self.send_json({"error": f"Log '{wanted}' not found"}, status=404)
                return
            use_fallback = query.get("lids_fallback", ["true"])[0].lower() != "false"
            try:
                self.send_json(extract_signals(target, use_lids_fallback=use_fallback))
            except Exception as exc:  # surface parse errors to the UI
                self.send_json({"error": str(exc)}, status=500)
            return

        self.send_error(404, "Not found")


def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MiniGauge Signal Plotter")
    parser.add_argument("--port", type=int, default=8097, help="TCP port (default: 8097)")
    parser.add_argument("--log", type=str, default=None, help="Initial CAN log file")
    parser.add_argument("--cids", type=str, default=str(viewer.DEFAULT_CIDS_PATH))
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    global INITIAL_LOG_FILE
    args = parse_arguments(sys.argv[1:])
    viewer.CIDS_FILE_PATH = Path(args.cids).resolve()
    if args.log and Path(args.log).is_file():
        INITIAL_LOG_FILE = Path(args.log).resolve()
    start_server(SignalPlotterHandler, port=args.port,
                 open_browser=not args.no_browser, server_name="Signal Plotter")


if __name__ == "__main__":
    main()

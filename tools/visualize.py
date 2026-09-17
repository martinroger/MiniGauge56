#!/usr/bin/env python3
"""
CAN Bus Signal Visualizer
=========================
Interactive browser-based visualization tool for MiniGauge CAN bus binary logs.
Decodes .bin files using the DBC database and plots multiple signals against time
with multi-axis auto-scaling, hover tooltips, range slider, manual Y-axis controls,
2D X & Y panning, cursor-centered time zooming, independent Y-axis panning/scaling, and collapsible message groups.
"""

import sys
import os
import glob
import json
import socket
import argparse
import webbrowser
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

# Ensure decoder folder is on sys.path for common imports
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (
    CanFrame,
    read_bin_file,
    find_bin_files,
    resolve_bin_file,
    natural_sort_key,
    DbcDatabase,
    get_dbc,
    load_calibration,
    BaseAppHandler,
    start_server,
)

# Global caches for decoded logs
LOG_CACHE: Dict[str, Dict[str, Any]] = {}
DBC_PATH: Optional[Path] = SCRIPT_DIR / "binocan.dbc"
INITIAL_LOG_FILE: Optional[Path] = None


def load_and_decode_log(log_path: Path, db: DbcDatabase) -> Dict[str, Any]:
    """Reads and decodes a .bin log into per-signal time-series series."""
    key = str(log_path.resolve())
    mtime = log_path.stat().st_mtime
    if key in LOG_CACHE and LOG_CACHE[key]["mtime"] == mtime:
        return LOG_CACHE[key]

    frames = read_bin_file(log_path)
    if not frames:
        result = {
            "mtime": mtime,
            "filename": log_path.name,
            "size": log_path.stat().st_size,
            "frame_count": 0,
            "duration_s": 0.0,
            "signals": {},
            "messages": {},
            "gps": {
                "has_gps": False,
                "points": [],
                "max_speed": 0.0,
                "min_speed": 0.0,
            },
        }
        LOG_CACHE[key] = result
        return result

    duration_s = frames[-1].time_rel_s
    signals_data: Dict[str, Dict[str, Any]] = {}
    message_meta: Dict[str, Dict[str, Any]] = {}

    current_gps_speed = 0.0
    current_gps_heading = 0.0
    current_gps_alt = 0.0
    gps_points: List[Dict[str, Any]] = []

    for frame in frames:
        msg_def = db.get_message(frame.can_id)
        if not msg_def:
            continue
        msg_name = msg_def.name
        if msg_name not in message_meta:
            message_meta[msg_name] = {
                "can_id": f"0x{frame.can_id:03X}",
                "signals": [s.name for s in msg_def.signals],
            }

        decoded = msg_def.decode(frame.data)
        t = round(frame.time_rel_s, 5)

        # Extract GPS telemetry
        if "RBX_speed_kph" in decoded:
            current_gps_speed = float(decoded["RBX_speed_kph"]["value"])
        if "RBX_heading_deg" in decoded:
            current_gps_heading = float(decoded["RBX_heading_deg"]["value"])
        if "RBX_msl_altitude_m" in decoded:
            current_gps_alt = float(decoded["RBX_msl_altitude_m"]["value"])

        lat_sig = next((k for k in decoded if "latitude" in k.lower()), None)
        lon_sig = next((k for k in decoded if "longitude" in k.lower()), None)
        if lat_sig and lon_sig:
            lat = float(decoded[lat_sig]["value"])
            lon = float(decoded[lon_sig]["value"])
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and (lat != 0.0 or lon != 0.0):
                gps_points.append({
                    "t": t,
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "speed": round(current_gps_speed, 1),
                    "heading": round(current_gps_heading, 1),
                    "alt": round(current_gps_alt, 1),
                })

        for sig_name, info in decoded.items():
            if sig_name not in signals_data:
                signals_data[sig_name] = {
                    "message": msg_name,
                    "unit": info["unit"],
                    "times": [],
                    "values": [],
                    "states": [],
                }
            signals_data[sig_name]["times"].append(t)
            signals_data[sig_name]["values"].append(info["value"])
            signals_data[sig_name]["states"].append(info["choice"] or "")

    max_gps_speed = max((p["speed"] for p in gps_points), default=0.0)
    min_gps_speed = min((p["speed"] for p in gps_points), default=0.0)

    result = {
        "mtime": mtime,
        "filename": log_path.name,
        "size": log_path.stat().st_size,
        "frame_count": len(frames),
        "duration_s": duration_s,
        "signals": signals_data,
        "messages": message_meta,
        "gps": {
            "has_gps": len(gps_points) > 0,
            "points": gps_points,
            "max_speed": max_gps_speed,
            "min_speed": min_gps_speed,
        },
    }
    LOG_CACHE[key] = result
    return result


def get_visualize_html() -> str:
    template_path = SCRIPT_DIR / "web" / "templates" / "visualize.html"
    return template_path.read_text(encoding="utf-8")


HTML_PAGE = get_visualize_html()


class VisualizerHandler(BaseAppHandler):
    def do_GET(self):
        if self.path.startswith("/static/"):
            if self.serve_static(self.path):
                return

        path, query = self.parse_query()

        try:
            if path in ("/", "/index.html"):
                self.send_html(HTML_PAGE)

            elif path == "/api/logs":
                db = get_dbc()
                candidates = find_bin_files(INITIAL_LOG_FILE)

                logs_meta = []
                for p in candidates:
                    if p.stat().st_size == 0:
                        continue
                    info = load_and_decode_log(p, db)
                    logs_meta.append({
                        "filename": p.name,
                        "size": p.stat().st_size,
                        "frame_count": info["frame_count"],
                        "duration_s": info["duration_s"],
                    })

                self.send_json(logs_meta)

            elif path == "/api/signals":
                filename = self.get_query_param("file")
                if not filename:
                    self.send_error(400, "Missing 'file' parameter")
                    return
                p = resolve_bin_file(filename, [SCRIPT_DIR])
                if not p and INITIAL_LOG_FILE and INITIAL_LOG_FILE.name == filename:
                    p = INITIAL_LOG_FILE
                if not p or not p.is_file():
                    self.send_error(404, f"File {filename} not found")
                    return

                db = get_dbc()
                decoded_info = load_and_decode_log(p, db)
                summary = {
                    "filename": decoded_info["filename"],
                    "size": decoded_info["size"],
                    "frame_count": decoded_info["frame_count"],
                    "duration_s": decoded_info["duration_s"],
                    "has_gps": decoded_info.get("gps", {}).get("has_gps", False),
                    "gps_count": len(decoded_info.get("gps", {}).get("points", [])),
                    "signals": {
                        name: {"message": data["message"], "unit": data["unit"]}
                        for name, data in decoded_info["signals"].items()
                    },
                }
                self.send_json(summary)

            elif path == "/api/gps":
                filename = self.get_query_param("file")
                if not filename:
                    self.send_error(400, "Missing 'file' parameter")
                    return
                p = SCRIPT_DIR / filename
                if not p.is_file():
                    p = Path(filename)
                if not p.is_file() and INITIAL_LOG_FILE and INITIAL_LOG_FILE.name == filename:
                    p = INITIAL_LOG_FILE
                if not p.is_file():
                    self.send_error(404, f"File {filename} not found")
                    return

                db = get_dbc()
                decoded_info = load_and_decode_log(p, db)
                self.send_json(decoded_info.get("gps", {
                    "has_gps": False,
                    "points": [],
                    "max_speed": 0.0,
                    "min_speed": 0.0
                }))

            elif path == "/api/data":
                filename = self.get_query_param("file")
                signals_req = self.get_query_param("signals").split(",")
                if not filename:
                    self.send_error(400, "Missing 'file' parameter")
                    return
                p = SCRIPT_DIR / filename
                if not p.is_file():
                    p = Path(filename)
                if not p.is_file() and INITIAL_LOG_FILE and INITIAL_LOG_FILE.name == filename:
                    p = INITIAL_LOG_FILE
                if not p.is_file():
                    self.send_error(404, f"File {filename} not found")
                    return

                db = get_dbc()
                decoded_info = load_and_decode_log(p, db)
                result = {}
                for s in signals_req:
                    s = s.strip()
                    if s in decoded_info["signals"]:
                        result[s] = decoded_info["signals"][s]

                self.send_json(result)

            elif path == "/api/calibration":
                cal = load_calibration()
                self.send_json(cal)

            else:
                self.send_error(404, "Not Found")

        except Exception as ex:
            self.send_error(500, f"Internal Error: {str(ex)}")

    def send_json(self, data: Any):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser(description="Interactive CAN Signal Visualizer Dashboard")
    parser.add_argument("log_file", nargs="?", help="Specific .bin file to open initially")
    parser.add_argument("--dbc", "-d", help="Path to DBC file")
    parser.add_argument("--port", "-p", type=int, default=8080, help="HTTP server port (default 8080)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically launch web browser")
    args = parser.parse_args()

    # Set initial log file if passed via CLI
    global INITIAL_LOG_FILE
    if args.log_file:
        p = Path(args.log_file)
        if p.is_file():
            INITIAL_LOG_FILE = p.resolve()
        elif (SCRIPT_DIR / args.log_file).is_file():
            INITIAL_LOG_FILE = (SCRIPT_DIR / args.log_file).resolve()
        else:
            print(f"[-] Warning: Log file '{args.log_file}' not found.")

    # Pre-init DBC
    dbc_path = Path(args.dbc) if args.dbc else None
    try:
        db = get_dbc(dbc_path)
        print(f"[+] Loaded DBC database: {DBC_PATH.name} ({len(db.messages)} messages)")
    except Exception as ex:
        print(f"[-] Error loading DBC: {ex}")
        sys.exit(1)

    start_server(
        VisualizerHandler,
        port=args.port,
        open_browser=not args.no_browser,
        server_name="MiniGauge CAN Signal Visualizer",
    )


if __name__ == "__main__":
    main()

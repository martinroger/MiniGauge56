#!/usr/bin/env python3
"""
MiniGauge Algorithm Calibration & Tuning Dashboard
===================================================
A bespoke standalone calibration and tuning dashboard for MiniGauge CAN bus binary logs (*.bin).
Provides interactive tab-based navigation for testing and calibrating:
   1. Gear Position Estimator (Kinematic Bayesian Filter with Markov state persistence & dynamic priors)
  2. Fuel Level Filtering (SMA vs EMA with dynamic window/tau, quantization, error residuals)
  3. Speed Correction & ECE R39 Compliance Check (gain/offset sliders, automated optimizer, regulatory corridor)
  4. Signal & Message Analytics (cycle times, jitter, packet loss rate, slew rate dispersion, CSV export)

Pure Python standard library with zero external pip dependencies.
Uses Plotly.js (via CDN) for interactive plotting.
"""

import sys
import os
import glob
import json
import socket
import argparse
import webbrowser
import math
import csv
import io
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
    natural_sort_key,
    DbcDatabase,
    get_dbc,
    load_calibration,
    save_calibration,
    BaseAppHandler,
    start_server,
)

# Global caches
ALGO_CACHE: Dict[str, Dict[str, Any]] = {}
ANALYTICS_CACHE: Dict[str, Dict[str, Any]] = {}
DBC_PATH: Optional[Path] = SCRIPT_DIR / "binocan.dbc"
INITIAL_LOG_FILE: Optional[Path] = None


def extract_algo_data(log_path: Path, db: DbcDatabase) -> Dict[str, Any]:
    """Extracts synchronized signal data needed for algorithm tuning."""
    key = str(log_path.resolve())
    mtime = log_path.stat().st_mtime
    if key in ALGO_CACHE and ALGO_CACHE[key]["mtime"] == mtime:
        return ALGO_CACHE[key]["data"]

    frames = read_bin_file(log_path)
    if not frames:
        empty = {
            "filename": log_path.name,
            "duration_s": 0.0,
            "frame_count": 0,
            "gear": {"times": [], "speed_freq": [], "rpm_freq": [], "speed_kph": [], "rpm": [], "ground_truth": []},
            "fuel": {"times": [], "unfiltered": [], "raw_v": [], "r_ohm": [], "recorded_times": [], "recorded_pc": []},
            "speed": {"times": [], "ind_speed": [], "gps_times": [], "gps_speed": [], "gps_valid": [], "gps_fix_st": []},
            "gps": {"has_gps": False, "points": [], "max_speed": 0.0, "min_speed": 0.0},
        }
        ALGO_CACHE[key] = {"mtime": mtime, "data": empty}
        return empty

    duration_s = frames[-1].time_rel_s

    gear_times = []
    gear_speed_freq = []
    gear_rpm_freq = []
    gear_speed_kph = []
    gear_rpm = []
    gear_ground_truth = []

    fuel_times = []
    fuel_unfiltered = []
    fuel_raw_v = []
    fuel_r_ohm = []
    fuel_recorded_times = []
    fuel_recorded_pc = []

    speed_times = []
    speed_ind = []
    gps_times = []
    gps_speed = []
    gps_valid = []
    gps_fix_st = []

    latest_speed_freq = None
    latest_rpm_freq = None
    latest_speed_kph = None
    latest_rpm = None
    latest_gear_gt = 0

    current_gps_speed = 0.0
    current_gps_heading = 0.0
    current_gps_alt = 0.0
    gps_points = []

    for frame in frames:
        cid = frame.can_id
        t = round(frame.time_rel_s, 4)

        if cid == 0x100:
            m = db.get_message(0x100)
            if m:
                d = m.decode(frame.data)
                if "ITF_speed_kph" in d:
                    latest_speed_kph = float(d["ITF_speed_kph"]["value"])
                    speed_times.append(t)
                    speed_ind.append(latest_speed_kph)
                if "ITF_rpm" in d:
                    latest_rpm = float(d["ITF_rpm"]["value"])
                if "ITF_gear_position_ST" in d:
                    latest_gear_gt = int(d["ITF_gear_position_ST"]["value"])

        elif cid == 0x300:
            m = db.get_message(0x300)
            if m:
                d = m.decode(frame.data)
                if "DBG_speed_freq" in d:
                    latest_speed_freq = float(d["DBG_speed_freq"]["value"])

        elif cid == 0x301:
            m = db.get_message(0x301)
            if m:
                d = m.decode(frame.data)
                if "DBG_RPM_freq" in d:
                    latest_rpm_freq = float(d["DBG_RPM_freq"]["value"])
                    gear_times.append(t)
                    gear_speed_freq.append(latest_speed_freq if latest_speed_freq is not None else 0.0)
                    gear_rpm_freq.append(latest_rpm_freq)
                    gear_speed_kph.append(latest_speed_kph if latest_speed_kph is not None else 0.0)
                    gear_rpm.append(latest_rpm if latest_rpm is not None else 0.0)
                    gear_ground_truth.append(latest_gear_gt)

        elif cid == 0x305:
            m = db.get_message(0x305)
            if m:
                d = m.decode(frame.data)
                if "DBG_fuel_level_unfiltered" in d:
                    fuel_times.append(t)
                    fuel_unfiltered.append(float(d["DBG_fuel_level_unfiltered"]["value"]))
                    fuel_raw_v.append(float(d.get("DBG_fuel_raw_v", {}).get("value", 0.0)))
                    fuel_r_ohm.append(float(d.get("DBG_fuel_r", {}).get("value", 0.0)))

        elif cid == 0x110:
            m = db.get_message(0x110)
            if m:
                d = m.decode(frame.data)
                if "ITF_fuel_level_pc" in d:
                    fuel_recorded_times.append(t)
                    fuel_recorded_pc.append(float(d["ITF_fuel_level_pc"]["value"]))

        elif cid == 0x600:
            m = db.get_message(0x600)
            if m:
                d = m.decode(frame.data)
                if "RBX_speed_kph" in d:
                    current_gps_speed = float(d["RBX_speed_kph"]["value"])
                    gps_times.append(t)
                    gps_speed.append(current_gps_speed)
                    gps_valid.append(int(d.get("RBX_valid_fix", {}).get("value", 0)))
                    gps_fix_st.append(int(d.get("RBX_fix_ST", {}).get("value", 0)))
                if "RBX_heading_deg" in d:
                    current_gps_heading = float(d["RBX_heading_deg"]["value"])

        elif cid == 0x601:
            m = db.get_message(0x601)
            if m:
                d = m.decode(frame.data)
                lat_sig = next((k for k in d if "latitude" in k.lower()), None)
                lon_sig = next((k for k in d if "longitude" in k.lower()), None)
                if lat_sig and lon_sig:
                    lat = float(d[lat_sig]["value"])
                    lon = float(d[lon_sig]["value"])
                    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and (lat != 0.0 or lon != 0.0):
                        gps_points.append({
                            "t": t,
                            "lat": round(lat, 6),
                            "lon": round(lon, 6),
                            "speed": round(current_gps_speed, 1),
                            "heading": round(current_gps_heading, 1),
                            "alt": round(current_gps_alt, 1),
                        })

        elif cid == 0x602:
            m = db.get_message(0x602)
            if m:
                d = m.decode(frame.data)
                if "RBX_msl_altitude_m" in d:
                    current_gps_alt = float(d["RBX_msl_altitude_m"]["value"])

    max_gps_speed = max((p["speed"] for p in gps_points), default=0.0)
    min_gps_speed = min((p["speed"] for p in gps_points), default=0.0)

    result = {
        "filename": log_path.name,
        "duration_s": round(duration_s, 2),
        "frame_count": len(frames),
        "gear": {
            "times": gear_times,
            "speed_freq": gear_speed_freq,
            "rpm_freq": gear_rpm_freq,
            "speed_kph": gear_speed_kph,
            "rpm": gear_rpm,
            "ground_truth": gear_ground_truth,
        },
        "fuel": {
            "times": fuel_times,
            "unfiltered": fuel_unfiltered,
            "raw_v": fuel_raw_v,
            "r_ohm": fuel_r_ohm,
            "recorded_times": fuel_recorded_times,
            "recorded_pc": fuel_recorded_pc,
        },
        "speed": {
            "times": speed_times,
            "ind_speed": speed_ind,
            "gps_times": gps_times,
            "gps_speed": gps_speed,
            "gps_valid": gps_valid,
            "gps_fix_st": gps_fix_st,
        },
        "gps": {
            "has_gps": len(gps_points) > 0,
            "points": gps_points,
            "max_speed": max_gps_speed,
            "min_speed": min_gps_speed,
        },
    }

    ALGO_CACHE[key] = {"mtime": mtime, "data": result}
    return result


def compute_analytics(log_path: Path, db: DbcDatabase) -> Dict[str, Any]:
    """Computes comprehensive bus cycle metrics and signal slew rates."""
    key = str(log_path.resolve())
    mtime = log_path.stat().st_mtime
    if key in ANALYTICS_CACHE and ANALYTICS_CACHE[key]["mtime"] == mtime:
        return ANALYTICS_CACHE[key]["data"]

    frames = read_bin_file(log_path)
    if not frames:
        return {"messages": [], "signals": [], "summary": {"total_frames": 0, "duration_s": 0.0}}

    duration_s = frames[-1].time_rel_s - frames[0].time_rel_s if len(frames) > 1 else 0.0

    msg_times: Dict[int, List[float]] = {}
    sig_values: Dict[str, List[float]] = {}
    sig_times: Dict[str, List[float]] = {}
    sig_units: Dict[str, str] = {}
    sig_msgs: Dict[str, str] = {}

    for f in frames:
        msg_times.setdefault(f.can_id, []).append(f.time_rel_s)
        m = db.get_message(f.can_id)
        if not m:
            continue
        decoded = m.decode(f.data)
        t = f.time_rel_s
        for sname, sinfo in decoded.items():
            v = sinfo["value"]
            if isinstance(v, (int, float)):
                if sname not in sig_values:
                    sig_values[sname] = []
                    sig_times[sname] = []
                    sig_units[sname] = sinfo["unit"] or ""
                    sig_msgs[sname] = m.name
                sig_values[sname].append(float(v))
                sig_times[sname].append(t)

    messages_out = []
    for cid, times in sorted(msg_times.items()):
        m_def = db.get_message(cid)
        name = m_def.name if m_def else f"UNKNOWN_0x{cid:03X}"
        n = len(times)
        if n < 2:
            continue
        deltas = [times[i] - times[i - 1] for i in range(1, n)]
        avg_dt = sum(deltas) / len(deltas)
        min_dt = min(deltas)
        max_dt = max(deltas)
        var_dt = sum((x - avg_dt) ** 2 for x in deltas) / len(deltas)
        std_dt = math.sqrt(var_dt)

        sorted_dt = sorted(deltas)
        median_dt = sorted_dt[len(sorted_dt) // 2]
        nominal_ms = round(median_dt * 1000)
        for snap in [10, 20, 25, 40, 50, 100, 200, 250, 500, 1000, 2000]:
            if abs(nominal_ms - snap) <= max(2, snap * 0.15):
                nominal_ms = snap
                break

        nominal_s = nominal_ms / 1000.0
        dropped_count = 0
        if nominal_s > 0:
            for dt in deltas:
                if dt > 1.8 * nominal_s:
                    dropped_count += int(round(dt / nominal_s)) - 1

        total_expected = n + dropped_count
        loss_pct = (dropped_count / total_expected * 100.0) if total_expected > 0 else 0.0

        messages_out.append({
            "name": name,
            "can_id_hex": f"0x{cid:03X}",
            "can_id_dec": cid,
            "count": n,
            "nominal_ms": nominal_ms,
            "avg_ms": round(avg_dt * 1000, 2),
            "min_ms": round(min_dt * 1000, 2),
            "max_ms": round(max_dt * 1000, 2),
            "std_ms": round(std_dt * 1000, 3),
            "freq_hz": round(1.0 / avg_dt, 1) if avg_dt > 0 else 0.0,
            "dropped_count": dropped_count,
            "loss_pct": round(loss_pct, 2),
        })

    signals_out = []
    for sname, vals in sorted(sig_values.items()):
        n = len(vals)
        if n == 0:
            continue
        times = sig_times[sname]
        min_v = min(vals)
        max_v = max(vals)
        avg_v = sum(vals) / n
        var_v = sum((x - avg_v) ** 2 for x in vals) / n
        std_v = math.sqrt(var_v)

        sorted_v = sorted(vals)
        med_v = sorted_v[n // 2] if n % 2 != 0 else (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2.0

        max_slew = 0.0
        sum_slew = 0.0
        slew_cnt = 0
        for i in range(1, n):
            dt = times[i] - times[i - 1]
            if dt > 0.001:
                rate = abs(vals[i] - vals[i - 1]) / dt
                if rate > max_slew:
                    max_slew = rate
                sum_slew += rate
                slew_cnt += 1
        avg_slew = (sum_slew / slew_cnt) if slew_cnt > 0 else 0.0

        signals_out.append({
            "name": sname,
            "message": sig_msgs[sname],
            "unit": sig_units[sname],
            "count": n,
            "min": round(min_v, 3),
            "max": round(max_v, 3),
            "avg": round(avg_v, 3),
            "median": round(med_v, 3),
            "std": round(std_v, 3),
            "max_slew": round(max_slew, 2),
            "avg_slew": round(avg_slew, 2),
        })

    result = {
        "summary": {
            "total_frames": len(frames),
            "duration_s": round(duration_s, 2),
            "message_types": len(messages_out),
            "signal_count": len(signals_out),
        },
        "messages": messages_out,
        "signals": signals_out,
    }

    ANALYTICS_CACHE[key] = {"mtime": mtime, "data": result}
    return result


def export_analytics_csv(analytics_data: Dict[str, Any]) -> str:
    """Renders analytics data into CSV formatted string."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["=== CAN MESSAGE CYCLE & BUS HEALTH ANALYTICS ==="])
    writer.writerow([
        "Message Name", "CAN ID (Hex)", "CAN ID (Dec)", "Frame Count",
        "Nominal Cycle (ms)", "Avg Cycle (ms)", "Min Cycle (ms)", "Max Cycle (ms)",
        "Jitter StdDev (ms)", "Frequency (Hz)", "Est Dropped Frames", "Est Loss Rate (%)"
    ])
    for m in analytics_data.get("messages", []):
        writer.writerow([
            m["name"], m["can_id_hex"], m["can_id_dec"], m["count"],
            m["nominal_ms"], m["avg_ms"], m["min_ms"], m["max_ms"],
            m["std_ms"], m["freq_hz"], m["dropped_count"], m["loss_pct"]
        ])

    writer.writerow([])
    writer.writerow(["=== CAN SIGNAL STATISTICAL & SLEW RATE DISPERSION ==="])
    writer.writerow([
        "Signal Name", "Parent Message", "Unit", "Sample Count",
        "Min Value", "Max Value", "Average Value", "Median Value",
        "Std Deviation", "Max Slew Rate (unit/s)", "Avg Slew Rate (unit/s)"
    ])
    for s in analytics_data.get("signals", []):
        writer.writerow([
            s["name"], s["message"], s["unit"], s["count"],
            s["min"], s["max"], s["avg"], s["median"],
            s["std"], s["max_slew"], s["avg_slew"]
        ])

    return output.getvalue()


def get_tuner_html() -> str:
    template_path = SCRIPT_DIR / "web" / "templates" / "tuner.html"
    return template_path.read_text(encoding="utf-8")


HTML_PAGE = get_tuner_html()


class TunerHandler(BaseAppHandler):
    def do_GET(self):
        if self.path.startswith("/static/"):
            if self.serve_static(self.path):
                return

        path, query = self.parse_query()

        try:
            if path in ("/", "/index.html"):
                self.send_html(HTML_PAGE)

            elif path == "/api/logs":
                candidates = find_bin_files(INITIAL_LOG_FILE)
                logs_meta = []
                for p in candidates:
                    if p.stat().st_size == 0:
                        continue
                    logs_meta.append({
                        "filename": p.name,
                        "size": p.stat().st_size,
                    })
                self.send_json(logs_meta)

            elif path == "/api/algo_data":
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

                db = get_dbc(DBC_PATH)
                data = extract_algo_data(p, db)
                self.send_json(data)

            elif path == "/api/analytics":
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

                db = get_dbc(DBC_PATH)
                data = compute_analytics(p, db)
                self.send_json(data)

            elif path == "/api/export_analytics":
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

                db = get_dbc(DBC_PATH)
                data = compute_analytics(p, db)
                csv_str = export_analytics_csv(data)
                csv_bytes = csv_str.encode("utf-8")
                base_name = p.stem

                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{base_name}_analytics.csv"')
                self.send_header("Content-Length", str(len(csv_bytes)))
                self.end_headers()
                self.wfile.write(csv_bytes)

            elif path == "/api/calibration":
                cal = load_calibration()
                self.send_json(cal)

            else:
                self.send_error(404, "Not Found")

        except Exception as e:
            self.send_error(500, str(e))

    def do_POST(self):
        path, _ = self.parse_query()

        if path == "/api/calibration":
            try:
                data = self.read_json_body()
                saved_path = save_calibration(data, source="tuner")
                updated = load_calibration(saved_path)
                self.send_json({"status": "ok", "saved": updated})
            except Exception as e:
                self.send_json({"status": "error", "error": str(e)}, status=500)
        else:
            self.send_error(404)


def main():
    global INITIAL_LOG_FILE, DBC_PATH

    parser = argparse.ArgumentParser(
        description="MiniGauge Algorithm Calibration & Tuning Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("log_file", nargs="?", help="Optional initial .bin file to inspect")
    parser.add_argument("--port", "-p", type=int, default=8081, help="Port to run web server on (default: 8081)")
    parser.add_argument("--dbc", "-d", help="Custom DBC file path (default: binocan.dbc)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")

    args = parser.parse_args()

    if args.dbc:
        dbc_candidate = Path(args.dbc)
        if dbc_candidate.is_file():
            DBC_PATH = dbc_candidate
        else:
            print(f"Warning: DBC file {args.dbc} not found. Searching default locations.")

    if args.log_file:
        p = Path(args.log_file)
        if p.is_file():
            INITIAL_LOG_FILE = p.resolve()
        else:
            print(f"Warning: Initial file {args.log_file} not found.")

    start_server(
        TunerHandler,
        port=args.port,
        open_browser=not args.no_browser,
        server_name="MiniGauge Algorithm Calibration & Tuning Lab",
    )


if __name__ == "__main__":
    main()


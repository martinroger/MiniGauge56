#!/usr/bin/env python3
"""
MiniGauge Algorithm Calibration & Tuning Dashboard
===================================================
A bespoke standalone calibration and tuning dashboard for MiniGauge CAN bus binary logs (*.bin).
Provides interactive tab-based navigation for testing and calibrating:
  1. Gear Position Estimator (gated EMA on speed/RPM frequency ratio, histogram, auto-peaks)
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
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Dict, List, Any, Optional

# Ensure decoder folder is on sys.path to import decode.py
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from decode import DbcDatabase, read_bin_file, CanFrame
except ImportError:
    from decode import DbcDatabase, read_bin_file, CanFrame

# Global caches
ALGO_CACHE: Dict[str, Dict[str, Any]] = {}
ANALYTICS_CACHE: Dict[str, Dict[str, Any]] = {}
DBC_INSTANCE: Optional[DbcDatabase] = None
DBC_PATH: Optional[Path] = None
INITIAL_LOG_FILE: Optional[Path] = None


def natural_sort_key(p: Path):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', p.name)]


def find_bin_files(initial: Optional[Path] = None) -> List[Path]:
    """Finds all *.bin files in SCRIPT_DIR and CWD."""
    seen = set()
    files: List[Path] = []
    if initial and initial.is_file():
        seen.add(initial.resolve())
        files.append(initial)

    search_dirs = [SCRIPT_DIR]
    cwd = Path(".").resolve()
    if cwd != SCRIPT_DIR.resolve():
        search_dirs.append(cwd)

    discovered = []
    for d in search_dirs:
        for p in d.glob("*.bin"):
            if p.is_file() and p.resolve() not in seen:
                seen.add(p.resolve())
                discovered.append(p)

    discovered.sort(key=natural_sort_key)
    files.extend(discovered)
    return files


def get_dbc(path: Optional[Path] = None) -> DbcDatabase:
    global DBC_INSTANCE, DBC_PATH
    if DBC_INSTANCE is None or (path and path != DBC_PATH):
        if not path:
            candidates = [
                SCRIPT_DIR / "binocan.dbc",
                Path("binocan.dbc"),
                *SCRIPT_DIR.glob("*.dbc"),
                *Path(".").glob("*.dbc"),
            ]
            for c in candidates:
                if c.is_file():
                    path = c
                    break
        if not path or not path.is_file():
            raise FileNotFoundError("Could not find a DBC file (e.g. binocan.dbc).")
        DBC_PATH = path
        DBC_INSTANCE = DbcDatabase(str(path))
    return DBC_INSTANCE


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


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MiniGauge Algorithm Calibration & Tuning Lab</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <style>
    :root, [data-theme="dark"] {
      --bg: #0f1115;
      --card-bg: #181b21;
      --panel-border: #262c36;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --accent: #10b981;
      --accent-hover: #059669;
      --warning: #f59e0b;
      --danger: #ef4444;
      --tag-bg: #222731;
      --badge-bg: #1e3a8a;
      --badge-text: #93c5fd;
      --hover-bg: rgba(255, 255, 255, 0.04);
      --input-bg: #13151b;
      --input-border: #333a48;
    }
    [data-theme="light"] {
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --panel-border: #cbd5e1;
      --text: #0f172a;
      --text-muted: #64748b;
      --primary: #2563eb;
      --primary-hover: #1d4ed8;
      --accent: #059669;
      --accent-hover: #047857;
      --warning: #d97706;
      --danger: #dc2626;
      --tag-bg: #f1f5f9;
      --badge-bg: #dbeafe;
      --badge-text: #1e40af;
      --hover-bg: rgba(0, 0, 0, 0.04);
      --input-bg: #ffffff;
      --input-border: #cbd5e1;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
      transition: background-color 0.2s, color 0.2s;
    }
    header {
      background: var(--card-bg);
      border-bottom: 1px solid var(--panel-border);
      padding: 0.5rem 1.25rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      flex-shrink: 0;
    }
    .header-left {
      display: flex;
      align-items: center;
      gap: 1rem;
    }
    .app-title {
      font-weight: 700;
      font-size: 1.05rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      color: var(--text);
      letter-spacing: -0.02em;
    }
    .app-title span.badge {
      background: var(--badge-bg);
      color: var(--badge-text);
      font-size: 0.7rem;
      padding: 0.15rem 0.45rem;
      border-radius: 4px;
      font-weight: 600;
      text-transform: uppercase;
    }
    .log-select-wrap {
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }
    select, input, button {
      background: var(--input-bg);
      color: var(--text);
      border: 1px solid var(--input-border);
      border-radius: 6px;
      padding: 0.35rem 0.6rem;
      font-size: 0.82rem;
      outline: none;
      transition: border-color 0.15s, background-color 0.15s;
    }
    select:focus, input:focus {
      border-color: var(--primary);
    }
    button {
      cursor: pointer;
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
    }
    button:hover {
      background: var(--hover-bg);
    }
    button.btn-primary {
      background: var(--primary);
      color: #ffffff;
      border-color: var(--primary);
    }
    button.btn-primary:hover {
      background: var(--primary-hover);
    }
    button.btn-accent {
      background: var(--accent);
      color: #ffffff;
      border-color: var(--accent);
    }
    button.btn-accent:hover {
      background: var(--accent-hover);
    }
    .header-right {
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }
    .time-ctrls {
      display: flex;
      align-items: center;
      gap: 0.35rem;
      font-size: 0.8rem;
      color: var(--text-muted);
    }
    .time-ctrls input {
      width: 70px;
      text-align: right;
    }

    nav.tab-nav {
      background: var(--card-bg);
      border-bottom: 1px solid var(--panel-border);
      display: flex;
      padding: 0 1.25rem;
      gap: 0.25rem;
      flex-shrink: 0;
    }
    .tab-btn {
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      border-radius: 0;
      padding: 0.65rem 1.1rem;
      font-size: 0.88rem;
      font-weight: 600;
      color: var(--text-muted);
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 0.45rem;
      transition: all 0.15s;
    }
    .tab-btn:hover {
      color: var(--text);
      background: var(--hover-bg);
    }
    .tab-btn.active {
      color: var(--primary);
      border-bottom-color: var(--primary);
      background: transparent;
    }

    main.tab-viewport {
      flex: 1;
      display: flex;
      overflow: hidden;
      position: relative;
    }
    .tab-pane {
      display: none;
      width: 100%;
      height: 100%;
      flex-direction: row;
      overflow: hidden;
    }
    .tab-pane.active {
      display: flex;
      flex: 1;
      min-width: 0;
    }

    .algo-sidebar {
      width: 320px;
      min-width: 320px;
      background: var(--card-bg);
      border-right: 1px solid var(--panel-border);
      display: flex;
      flex-direction: column;
      overflow-y: auto;
      padding: 1rem;
      gap: 1.1rem;
    }
    .algo-content {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      background: var(--bg);
      padding: 0.75rem;
      gap: 0.75rem;
    }

    .card {
      background: var(--card-bg);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      padding: 0.85rem;
    }
    .card-title {
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-muted);
      margin-bottom: 0.6rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .ctrl-group {
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      margin-bottom: 0.75rem;
    }
    .ctrl-group:last-child {
      margin-bottom: 0;
    }
    .ctrl-label-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.8rem;
    }
    .ctrl-label {
      color: var(--text);
      font-weight: 500;
    }
    .ctrl-val {
      font-family: monospace;
      font-weight: 600;
      color: var(--primary);
    }
    input[type="range"] {
      width: 100%;
      accent-color: var(--primary);
      cursor: pointer;
      height: 6px;
      background: var(--input-border);
      border-radius: 3px;
      border: none;
    }

    .scorecards-row {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 0.6rem;
      flex-shrink: 0;
    }
    .scorecard {
      background: var(--card-bg);
      border: 1px solid var(--panel-border);
      border-radius: 6px;
      padding: 0.6rem 0.8rem;
      display: flex;
      flex-direction: column;
      gap: 0.2rem;
    }
    .sc-label {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      color: var(--text-muted);
      font-weight: 600;
    }
    .sc-val {
      font-size: 1.15rem;
      font-weight: 700;
      font-family: monospace;
    }
    .sc-val.good { color: var(--accent); }
    .sc-val.warn { color: var(--warning); }
    .sc-val.bad { color: var(--danger); }

    .plots-column {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
      overflow: hidden;
      min-height: 0;
    }
    .plot-box {
      flex: 1;
      background: var(--card-bg);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      position: relative;
      min-height: 180px;
    }
    .timeline-needle {
      position: absolute;
      top: 0;
      width: 2px;
      background-color: #ef4444;
      pointer-events: none;
      z-index: 50;
      box-shadow: 0 0 6px rgba(239, 68, 68, 0.8);
      transition: none;
    }
    .model-badge {
      display: inline-block;
      padding: 0.15rem 0.45rem;
      border-radius: 4px;
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .badge-latched { background: rgba(59, 130, 246, 0.2); color: #3b82f6; border: 1px solid rgba(59, 130, 246, 0.35); }
    .badge-neutral { background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3); }

    .analytics-viewport {
      width: 100%;
      height: 100%;
      display: flex;
      flex-direction: column;
      background: var(--bg);
      padding: 0.85rem;
      gap: 0.75rem;
      overflow: hidden;
    }
    .analytics-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      flex-shrink: 0;
    }
    .table-container {
      flex: 1;
      background: var(--card-bg);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      overflow: auto;
      position: relative;
    }
    table.analytics-table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.8rem;
    }
    table.analytics-table th {
      position: sticky;
      top: 0;
      background: var(--card-bg);
      border-bottom: 2px solid var(--panel-border);
      padding: 0.6rem 0.8rem;
      font-weight: 600;
      color: var(--text-muted);
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
      z-index: 10;
    }
    table.analytics-table th:hover {
      color: var(--text);
    }
    table.analytics-table td {
      padding: 0.45rem 0.8rem;
      border-bottom: 1px solid var(--panel-border);
      white-space: nowrap;
    }
    table.analytics-table tr.msg-row {
      background: var(--hover-bg);
      cursor: pointer;
      font-weight: 600;
    }
    table.analytics-table tr.msg-row:hover {
      background: rgba(59, 130, 246, 0.08);
    }
    table.analytics-table tr.sig-row {
      color: var(--text-muted);
      font-size: 0.78rem;
    }
    table.analytics-table tr.sig-row:hover {
      background: var(--hover-bg);
      color: var(--text);
    }
    .mono { font-family: monospace; }
    .badge-pill {
      font-size: 0.7rem;
      padding: 0.1rem 0.4rem;
      border-radius: 4px;
      font-weight: 600;
    }
    .badge-ok { background: rgba(16, 185, 129, 0.15); color: var(--accent); }
    .badge-warn { background: rgba(245, 158, 11, 0.15); color: var(--warning); }
    .badge-err { background: rgba(239, 68, 68, 0.15); color: var(--danger); }

    #loading-overlay {
      position: absolute;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(15, 17, 21, 0.7);
      backdrop-filter: blur(3px);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 0.75rem;
      z-index: 9999;
      font-weight: 600;
    }
    .spinner {
      width: 36px;
      height: 36px;
      border: 3px solid var(--panel-border);
      border-top-color: var(--primary);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* Map Drawer & Resizer */
    .map-resizer {
      width: 6px;
      cursor: col-resize;
      background: transparent;
      transition: background-color 0.2s;
      flex-shrink: 0;
      position: relative;
      z-index: 20;
      display: none;
    }
    .map-resizer:hover, .map-resizer.dragging {
      background-color: var(--primary);
    }
    .map-resizer.open {
      display: block;
    }
    .map-panel {
      width: 440px;
      min-width: 250px;
      max-width: 85vw;
      background: var(--card-bg);
      border-left: 1px solid var(--panel-border);
      display: none;
      flex-direction: column;
      flex-shrink: 0;
      position: relative;
      z-index: 10;
    }
    .map-panel.open {
      display: flex;
    }
    .map-header {
      padding: 0.6rem 0.9rem;
      border-bottom: 1px solid var(--panel-border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--card-bg);
    }
    .map-title {
      font-weight: 600;
      font-size: 0.88rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .map-points-badge {
      font-size: 0.7rem;
      background: var(--badge-bg);
      color: var(--badge-text);
      padding: 1px 6px;
      border-radius: 4px;
      font-weight: normal;
    }
    .map-header-actions {
      display: flex;
      gap: 0.35rem;
      align-items: center;
    }
    .map-btn-mini {
      padding: 0.2rem 0.5rem;
      font-size: 0.76rem;
      line-height: 1.2;
    }
    .map-container-inner {
      flex: 1;
      width: 100%;
      height: 100%;
      min-height: 250px;
      background: var(--bg);
    }
    .map-telemetry-bar {
      background: var(--bg);
      border-top: 1px solid var(--panel-border);
      padding: 0.5rem 0.8rem;
      display: flex;
      justify-content: space-around;
      align-items: center;
      font-size: 0.76rem;
    }
    .map-telemetry-item {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
    }
    .map-telemetry-label {
      color: var(--text-muted);
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .map-telemetry-val {
      font-weight: 600;
      color: var(--text);
      font-family: monospace;
      font-size: 0.82rem;
    }
    .vehicle-marker-wrapper {
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .vehicle-marker-pulse {
      position: absolute;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: rgba(59, 130, 246, 0.45);
      animation: pulseMarker 2s infinite ease-out;
      pointer-events: none;
    }
    @keyframes pulseMarker {
      0% { transform: scale(0.6); opacity: 0.9; }
      100% { transform: scale(2.2); opacity: 0; }
    }
    .vehicle-marker-circle {
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: #3b82f6;
      border: 2px solid #ffffff;
      box-shadow: 0 0 6px rgba(0, 0, 0, 0.8);
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
      z-index: 2;
    }
    .vehicle-marker-arrow {
      font-size: 9px;
      line-height: 1;
      color: #ffffff;
      transform-origin: center center;
      transition: transform 0.1s linear;
      user-select: none;
    }
    .map-marker-tooltip {
      background: var(--card-bg) !important;
      color: var(--text) !important;
      border: 1px solid var(--panel-border) !important;
      font-size: 0.74rem !important;
      border-radius: 5px !important;
      box-shadow: 0 4px 12px rgba(0,0,0,0.5) !important;
      padding: 3px 6px !important;
    }
    .leaflet-container {
      background: var(--bg) !important;
      font-family: inherit !important;
    }
    .leaflet-bar {
      border: 1px solid var(--panel-border) !important;
      border-radius: 6px !important;
      overflow: hidden;
      box-shadow: 0 4px 12px rgba(0,0,0,0.5) !important;
    }
    .leaflet-bar a {
      background-color: var(--card-bg) !important;
      color: var(--text) !important;
      border-bottom: 1px solid var(--panel-border) !important;
      width: 28px !important;
      height: 28px !important;
      line-height: 28px !important;
    }
    .leaflet-bar a:hover {
      background-color: var(--tag-bg) !important;
      color: var(--primary) !important;
    }
    .leaflet-control-attribution {
      background: var(--card-bg) !important;
      color: var(--text-muted) !important;
      font-size: 0.65rem !important;
      opacity: 0.9;
    }
    .leaflet-control-attribution a {
      color: var(--primary) !important;
    }
    button.btn-active-toggle {
      background: var(--primary);
      color: #ffffff;
      border-color: var(--primary);
    }
  </style>
</head>
<body>

  <div id="loading-overlay">
    <div class="spinner"></div>
    <div id="loading-text">Decoding CAN log...</div>
  </div>

  <header>
    <div class="header-left">
      <div class="app-title">
        <span>MiniGauge</span>
        <span class="badge">Calibration Lab</span>
      </div>
      <div class="log-select-wrap">
        <label for="log-select" style="font-size:0.8rem; color:var(--text-muted);">Log:</label>
        <select id="log-select"></select>
      </div>
    </div>
    <div class="header-right">
      <div class="time-ctrls">
        <span>Time (s):</span>
        <input type="number" id="time-from" placeholder="0" step="1">
        <span>to</span>
        <input type="number" id="time-to" placeholder="End" step="1">
        <button id="btn-time-apply" title="Apply exact time window">Apply</button>
        <button id="btn-time-fit" title="Fit full duration">Fit</button>
        <button id="btn-zoom-in" title="Zoom in 2x">+</button>
        <button id="btn-zoom-out" title="Zoom out 2x">−</button>
      </div>
      <button id="btnToggleMap" title="Toggle GPS Track Map">🗺 Map</button>
      <button id="btn-theme-toggle" title="Toggle Theme">🌓</button>
    </div>
  </header>

  <nav class="tab-nav">
    <button class="tab-btn active" data-tab="tab-gear">⚙️ Gear Position Estimator</button>
    <button class="tab-btn" data-tab="tab-fuel">⛽ Fuel Level Filter</button>
    <button class="tab-btn" data-tab="tab-speed">🏎️ Speed & ECE R39 Check</button>
    <button class="tab-btn" data-tab="tab-analytics">📊 Signal & Bus Analytics</button>
  </nav>

  <main class="tab-viewport">

    <!-- TAB 1: GEAR POSITION ESTIMATOR -->
    <div id="tab-gear" class="tab-pane active">
      <div class="algo-sidebar">
        <div class="card" style="border-left: 3px solid var(--primary);">
          <div class="card-title">Algorithm Preset</div>
          <div class="ctrl-group">
            <select id="select-gear-preset" style="width:100%; font-weight:600;">
              <option value="baseline" selected>1. Baseline (Gated Ratio EMA)</option>
              <option value="rpm_filter">2. RPM Pre-Filtered + Ratio EMA</option>
              <option value="latched">3. Full Pipeline (RPM Filter + Latch)</option>
              <option value="custom">Custom Pipeline</option>
            </select>
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>Stage 1: Input RPM Pre-Filter</span>
            <label style="font-size:0.75rem; font-weight:normal; display:flex; align-items:center; gap:0.3rem; text-transform:none; cursor:pointer;">
              <input type="checkbox" id="chk-gear-rpm-filter"> Enable
            </label>
          </div>
          <div id="gear-rpm-filter-controls" style="display:none; flex-direction:column; gap:0.6rem; margin-top:0.4rem;">
            <div style="display:flex; gap:0.6rem;">
              <label style="display:flex; align-items:center; gap:0.3rem; font-size:0.78rem; cursor:pointer;">
                <input type="radio" name="gear-rpm-algo" value="EMA" checked id="radio-gear-rpm-ema"> EMA
              </label>
              <label style="display:flex; align-items:center; gap:0.3rem; font-size:0.78rem; cursor:pointer;">
                <input type="radio" name="gear-rpm-algo" value="SMA" id="radio-gear-rpm-sma"> SMA
              </label>
            </div>
            <div class="ctrl-group">
              <div class="ctrl-label-row">
                <span class="ctrl-label" id="lbl-gear-rpm-param">Time Constant (τ)</span>
                <span class="ctrl-val" id="val-gear-rpm-param">0.10 s</span>
              </div>
              <input type="range" id="slider-gear-rpm-param" min="0.02" max="1.00" step="0.02" value="0.10">
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-title">Stage 2: Gating Filters</div>
          <div class="ctrl-group">
            <div class="ctrl-label-row">
              <span class="ctrl-label">Min Speed Freq</span>
              <span class="ctrl-val" id="val-gear-minspeed">5.0 Hz (~1.2 km/h)</span>
            </div>
            <input type="range" id="slider-gear-minspeed" min="0" max="40" step="0.5" value="5.0">
          </div>
          <div class="ctrl-group">
            <div class="ctrl-label-row">
              <span class="ctrl-label">Min RPM Freq</span>
              <span class="ctrl-val" id="val-gear-minrpm">25.0 Hz (750 RPM)</span>
            </div>
            <input type="range" id="slider-gear-minrpm" min="5" max="80" step="1" value="25.0">
          </div>
          <div class="ctrl-group">
            <div class="ctrl-label-row">
              <span class="ctrl-label">Stability Gate |dRatio/dt|</span>
              <span class="ctrl-val" id="val-gear-stab">0.050</span>
            </div>
            <input type="range" id="slider-gear-stab" min="0.005" max="0.200" step="0.005" value="0.050">
          </div>
        </div>

        <div class="card">
          <div class="card-title">Stage 3: Ratio Smoothing</div>
          <div class="ctrl-group">
            <div class="ctrl-label-row">
              <span class="ctrl-label">EMA Alpha (α)</span>
              <span class="ctrl-val" id="val-gear-alpha">0.15</span>
            </div>
            <input type="range" id="slider-gear-alpha" min="0.01" max="1.00" step="0.01" value="0.15">
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>Stage 4: Output Latch / Debounce</span>
            <label style="font-size:0.75rem; font-weight:normal; display:flex; align-items:center; gap:0.3rem; text-transform:none; cursor:pointer;">
              <input type="checkbox" id="chk-gear-latch"> Enable
            </label>
          </div>
          <div id="gear-latch-controls" style="display:none; flex-direction:column; gap:0.6rem; margin-top:0.4rem;">
            <div class="ctrl-group">
              <div class="ctrl-label-row">
                <span class="ctrl-label">Hold Confirmation Time</span>
                <span class="ctrl-val" id="val-gear-latch">200 ms</span>
              </div>
              <input type="range" id="slider-gear-latch" min="50" max="600" step="25" value="200">
            </div>
            <div style="font-size:0.72rem; color:var(--text-muted); line-height:1.35;">
              Requires candidate gear to hold continuously before confirming transition, suppressing shift chatter.
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>Gear Ratio Centers</span>
            <button class="btn-accent" id="btn-auto-gear-peaks" style="padding:0.15rem 0.45rem; font-size:0.7rem;">⚡ Auto-Detect</button>
          </div>
          <div class="ctrl-group">
            <div class="ctrl-label-row">
              <span class="ctrl-label">Tolerance Window (Absolute ±Δ)</span>
              <span class="ctrl-val" id="val-gear-tol">±0.25</span>
            </div>
            <input type="range" id="slider-gear-tol" min="0.05" max="0.50" step="0.01" value="0.25">
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:0.4rem; font-size:0.78rem;">
            <div>
              <label>1st Gear</label>
              <input type="number" id="gear-r-1" step="0.01" value="1.01" style="width:100%;">
            </div>
            <div>
              <label>2nd Gear</label>
              <input type="number" id="gear-r-2" step="0.01" value="1.80" style="width:100%;">
            </div>
            <div>
              <label>3rd Gear</label>
              <input type="number" id="gear-r-3" step="0.01" value="2.73" style="width:100%;">
            </div>
            <div>
              <label>4th Gear</label>
              <input type="number" id="gear-r-4" step="0.01" value="3.76" style="width:100%;">
            </div>
            <div>
              <label>5th Gear</label>
              <input type="number" id="gear-r-5" step="0.01" value="4.54" style="width:100%;">
            </div>
          </div>
          <div style="font-size:0.72rem; color:var(--text-muted); margin-top:0.4rem;">
            5 forward gears + Neutral. (Reverse is not directly signaled in CAN logs and defaults to Neutral/Uncertain).
          </div>
        </div>

        <div class="card">
          <div class="card-title">Display Options</div>
          <label style="display:flex; align-items:center; gap:0.45rem; font-size:0.8rem; cursor:pointer;">
            <input type="checkbox" id="chk-gear-groundtruth">
            <span>Show ITF_gear_position_ST trace</span>
          </label>
          <label style="display:flex; align-items:center; gap:0.45rem; font-size:0.8rem; cursor:pointer; margin-top:0.35rem;">
            <input type="checkbox" id="chk-gear-gauge-pod" checked>
            <span>Show Simulated Gear Gauge</span>
          </label>
          <div style="display:flex; gap:0.4rem; margin-top:0.75rem;">
            <button id="btn-save-shared-cal" style="flex:1; font-size:0.75rem;" title="Save current tolerance and latch to gear_calibration.json">💾 Save Cal</button>
            <button id="btn-load-shared-cal" style="flex:1; font-size:0.75rem;" title="Load parameters from gear_calibration.json">📥 Load Cal</button>
          </div>
          <div style="margin-top:0.4rem;">
            <button id="btn-reset-gear-defaults" style="width:100%;">Reset Gear Defaults</button>
          </div>
        </div>

        <div class="card" id="card-gear-math" style="border-left: 3px solid var(--primary);"></div>
      </div>

      <div class="algo-content">
        <div class="scorecards-row">
          <div class="scorecard">
            <span class="sc-label">Drive Active</span>
            <span class="sc-val good" id="sc-gear-active">--%</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Glitch-Free Score</span>
            <span class="sc-val good" id="sc-gear-glitch-score">100%</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Neutral Dropouts</span>
            <span class="sc-val" id="sc-gear-dropouts">0</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Chatter (&lt;300ms)</span>
            <span class="sc-val" id="sc-gear-chatter">0</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Coast Phantoms</span>
            <span class="sc-val" id="sc-gear-phantoms">0</span>
          </div>
        </div>
        <div class="scorecards-row" style="margin-top:-0.35rem;">
          <div class="scorecard">
            <span class="sc-label">Est. 1st Gear</span>
            <span class="sc-val" id="sc-gear-time-1">--s</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Est. 2nd Gear</span>
            <span class="sc-val" id="sc-gear-time-2">--s</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Est. 3rd Gear</span>
            <span class="sc-val" id="sc-gear-time-3">--s</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Est. 4th Gear</span>
            <span class="sc-val" id="sc-gear-time-4">--s</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Est. 5th Gear</span>
            <span class="sc-val" id="sc-gear-time-5">--s</span>
          </div>
        </div>

        <!-- DRIVE REPLAYER TOOLBAR & SIMULATED GEAR GAUGE -->
        <div style="display:flex; flex-direction:column; gap:0.45rem; margin-top:0.45rem;">
          <div class="card" style="display:flex; align-items:center; gap:0.6rem; padding:0.45rem 0.75rem; margin-bottom:0; flex-wrap:wrap;">
            <div style="display:flex; align-items:center; gap:0.35rem;">
              <button id="btn-replay-play" class="btn-primary" style="padding:0.25rem 0.6rem; font-size:0.75rem;">▶ Play</button>
              <button id="btn-replay-reset" style="padding:0.25rem 0.5rem; font-size:0.75rem;">⏹ Reset</button>
              <button id="btn-replay-prev" style="padding:0.25rem 0.45rem; font-size:0.75rem;" title="Step Back 200ms">◀</button>
              <button id="btn-replay-next" style="padding:0.25rem 0.45rem; font-size:0.75rem;" title="Step Forward 200ms">▶</button>
              <select id="select-replay-speed" style="padding:0.2rem 0.4rem; font-size:0.75rem;">
                <option value="0.25">0.25x</option>
                <option value="0.5">0.5x</option>
                <option value="1.0" selected>1.0x</option>
                <option value="2.0">2.0x</option>
                <option value="5.0">5.0x</option>
                <option value="10.0">10.0x</option>
              </select>
            </div>
            <div style="flex:1; display:flex; align-items:center; gap:0.5rem; min-width:200px;">
              <input type="range" id="slider-replay-scrub" min="0" max="100" step="0.05" value="0" style="flex:1;">
              <span id="lbl-replay-time" style="font-family:monospace; font-size:0.75rem; color:var(--text-muted); white-space:nowrap;">0.00s / 0.00s</span>
            </div>
          </div>

          <!-- Simulated Gear Position Gauge (Toggleable) -->
          <div id="pod-simulated-gear" class="card" style="display:flex; align-items:center; justify-content:space-between; padding:0.55rem 1.25rem; background:linear-gradient(180deg, var(--card-bg) 0%, rgba(30,41,59,0.85) 100%); border-left:3px solid #3b82f6; margin-bottom:0;">
            <div style="display:flex; align-items:center; gap:1.5rem;">
              <div style="text-align:center;">
                <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; font-weight:700; letter-spacing:0.04em;">Simulated Gear</div>
                <div id="pod-tuner-gear" style="font-size:2.2rem; font-weight:800; font-family:monospace; line-height:1; color:#3b82f6; margin-top:0.15rem;">N</div>
              </div>
              <div style="height:32px; width:1px; background:var(--panel-border);"></div>
              <div style="display:flex; flex-direction:column; gap:0.15rem; font-size:0.75rem; font-family:monospace;">
                <div>Speed: <span id="pod-tuner-speed" style="color:var(--text); font-weight:600;">0.0 km/h</span></div>
                <div>Engine: <span id="pod-tuner-rpm" style="color:var(--text); font-weight:600;">0 RPM</span></div>
              </div>
              <div style="display:flex; flex-direction:column; gap:0.15rem; font-size:0.75rem; font-family:monospace;">
                <div>Ratio: <span id="pod-tuner-ratio" style="color:var(--text); font-weight:600;">--</span></div>
                <div>Status: <span id="pod-tuner-status" class="model-badge badge-neutral" style="font-size:0.65rem;">NEUTRAL</span></div>
              </div>
            </div>
            <div style="display:flex; align-items:center; gap:0.6rem;">
              <span id="pod-tuner-lock" style="font-size:0.72rem; color:var(--text-muted); font-family:monospace;">GPS Track Synced</span>
            </div>
          </div>
        </div>
        <div class="plots-column">
          <div class="plot-box" id="plot-gear-hist" style="flex:0.65; min-height: 135px;"></div>
          <div class="plot-box" id="plot-gear-dynamics" style="flex:0.8; min-height: 155px;"></div>
          <div class="plot-box" id="plot-gear-time" style="flex:1.1; min-height: 195px;"></div>
        </div>
      </div>
    </div>

    <!-- TAB 2: FUEL LEVEL FILTERING -->
    <div id="tab-fuel" class="tab-pane">
      <div class="algo-sidebar">
        <div class="card">
          <div class="card-title">Filter Algorithm</div>
          <div style="display:flex; gap:0.5rem; margin-bottom:0.75rem;">
            <label style="display:flex; align-items:center; gap:0.3rem; font-size:0.8rem; cursor:pointer;">
              <input type="radio" name="fuel-algo" value="SMA" checked id="radio-fuel-sma"> SMA (Moving Avg)
            </label>
            <label style="display:flex; align-items:center; gap:0.3rem; font-size:0.8rem; cursor:pointer;">
              <input type="radio" name="fuel-algo" value="EMA" id="radio-fuel-ema"> EMA (Exponential)
            </label>
          </div>
          <div class="ctrl-group">
            <div class="ctrl-label-row">
              <span class="ctrl-label" id="lbl-fuel-param">Time Window</span>
              <span class="ctrl-val" id="val-fuel-window">30 s</span>
            </div>
            <input type="range" id="slider-fuel-window" min="1" max="180" step="1" value="30">
          </div>
        </div>

        <div class="card">
          <div class="card-title">Quantization Simulation</div>
          <div class="ctrl-group">
            <label style="font-size:0.8rem; margin-bottom:0.3rem;">Rounding Step</label>
            <select id="select-fuel-quant" style="width:100%;">
              <option value="0">Continuous (No Rounding)</option>
              <option value="0.5">0.5% (DBC Standard)</option>
              <option value="1.0" selected>1.0% (Integer Percent)</option>
            </select>
          </div>
        </div>

        <div class="card">
          <div class="card-title">Diagnostics</div>
          <p style="font-size:0.78rem; color:var(--text-muted); line-height:1.4;">
            Compares theoretical moving average filter against real unfiltered raw sensor measurements and firmware-recorded filtered level.
          </p>
          <div style="margin-top:0.75rem;">
            <button id="btn-reset-fuel-defaults" style="width:100%;">Reset Fuel Defaults</button>
          </div>
        </div>
      </div>

      <div class="algo-content">
        <div class="scorecards-row">
          <div class="scorecard">
            <span class="sc-label">Mean Abs Error (MAE)</span>
            <span class="sc-val good" id="sc-fuel-mae">-- %</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Root Mean Sq (RMSE)</span>
            <span class="sc-val good" id="sc-fuel-rmse">-- %</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Max Deviation</span>
            <span class="sc-val warn" id="sc-fuel-maxerr">-- %</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Sim Max Slew</span>
            <span class="sc-val" id="sc-fuel-sim-slew">-- %/s</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Sim Max Jitter</span>
            <span class="sc-val" id="sc-fuel-sim-jitter">-- %</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Meas Max Slew</span>
            <span class="sc-val" id="sc-fuel-meas-slew">-- %/s</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Meas Max Jitter</span>
            <span class="sc-val" id="sc-fuel-meas-jitter">-- %</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Samples</span>
            <span class="sc-val" id="sc-fuel-samples">--</span>
          </div>
        </div>
        <div class="plots-column">
          <div class="plot-box" id="plot-fuel-main" style="flex:1.4;"></div>
          <div class="plot-box" id="plot-fuel-residual" style="flex:0.6;"></div>
        </div>
      </div>
    </div>

    <!-- TAB 3: SPEED CORRECTION & ECE R39 -->
    <div id="tab-speed" class="tab-pane">
      <div class="algo-sidebar">
        <div class="card">
          <div class="card-title">Calibration Tuning</div>
          <div class="ctrl-group">
            <div class="ctrl-label-row">
              <span class="ctrl-label">Gain Multiplier (k)</span>
              <span class="ctrl-val" id="val-speed-gain">1.000</span>
            </div>
            <input type="range" id="slider-speed-gain" min="0.800" max="1.250" step="0.002" value="1.000">
          </div>
          <div class="ctrl-group">
            <div class="ctrl-label-row">
              <span class="ctrl-label">Offset (c)</span>
              <span class="ctrl-val" id="val-speed-offset">0.0 km/h</span>
            </div>
            <input type="range" id="slider-speed-offset" min="-10.0" max="15.0" step="0.2" value="0.0">
          </div>
          <div style="font-size:0.78rem; color:var(--text-muted); margin-top:0.4rem;">
            Formula: <code class="mono" style="color:var(--text);">V_corr = k · V_ind + c</code>
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>Automated Optimizer</span>
          </div>
          <p style="font-size:0.76rem; color:var(--text-muted); margin-bottom:0.6rem; line-height:1.4;">
            Solves optimal gain <code class="mono">k</code> and offset <code class="mono">c</code> to meet UNECE R39 (<code class="mono">V_gps &le; V_ind &le; 1.1·V_gps + 4</code>) while minimizing excess over-read.
          </p>
          <button class="btn-accent" id="btn-auto-opt-speed" style="width:100%;">⚡ Auto-Optimize for ECE R39</button>
        </div>

        <div class="card">
          <div class="card-title">GPS Fix Masking</div>
          <label style="display:flex; align-items:center; gap:0.45rem; font-size:0.8rem; cursor:pointer;">
            <input type="checkbox" id="chk-speed-require-gps" checked>
            <span>Ignore invalid GPS fixes (&lt; 3D fix)</span>
          </label>
          <div class="ctrl-group" style="margin-top:0.6rem;">
            <div class="ctrl-label-row">
              <span class="ctrl-label">Min Evaluation Speed</span>
              <span class="ctrl-val" id="val-speed-mineval">5.0 km/h</span>
            </div>
            <input type="range" id="slider-speed-mineval" min="0" max="25" step="1" value="5.0">
          </div>
          <div style="margin-top:0.75rem;">
            <button id="btn-reset-speed-defaults" style="width:100%;">Reset Speed Defaults</button>
          </div>
        </div>
      </div>

      <div class="algo-content">
        <div class="scorecards-row">
          <div class="scorecard">
            <span class="sc-label">ECE R39 Compliance</span>
            <span class="sc-val" id="sc-speed-ece">-- %</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">V_ind &ge; V_gps Rate</span>
            <span class="sc-val" id="sc-speed-ge-rate">-- %</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Max Under-Read</span>
            <span class="sc-val" id="sc-speed-maxunder">-- km/h</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Max Over-Read</span>
            <span class="sc-val" id="sc-speed-maxover">-- km/h</span>
          </div>
          <div class="scorecard">
            <span class="sc-label">Avg Speed Delta</span>
            <span class="sc-val" id="sc-speed-avgdelta">-- km/h</span>
          </div>
        </div>
        <div class="plots-column">
          <div class="plot-box" id="plot-speed-main" style="flex:1.4;"></div>
          <div class="plot-box" id="plot-speed-delta" style="flex:0.6;"></div>
        </div>
      </div>
    </div>

    <!-- TAB 4: SIGNAL & MESSAGE ANALYTICS -->
    <div id="tab-analytics" class="tab-pane">
      <div class="analytics-viewport">
        <div class="analytics-toolbar">
          <div style="display:flex; align-items:center; gap:0.6rem;">
            <input type="text" id="analytics-search" placeholder="🔍 Search messages or signals..." style="width:260px;">
            <button id="btn-expand-all">Expand All</button>
            <button id="btn-collapse-all">Collapse All</button>
          </div>
          <div style="display:flex; align-items:center; gap:0.6rem;">
            <button class="btn-primary" id="btn-export-csv">⬇ Export Analytics CSV</button>
          </div>
        </div>
        <div class="table-container">
          <table class="analytics-table" id="analytics-table">
            <thead>
              <tr>
                <th style="width:30px;"></th>
                <th data-sort="name">Message / Signal</th>
                <th data-sort="can_id">CAN ID / Unit</th>
                <th data-sort="count">Count</th>
                <th data-sort="nominal">Nominal</th>
                <th data-sort="avg">Avg Cycle / Value</th>
                <th data-sort="min">Min</th>
                <th data-sort="max">Max</th>
                <th data-sort="jitter">Jitter / StdDev</th>
                <th data-sort="slew">Max Slew / Loss</th>
              </tr>
            </thead>
            <tbody id="analytics-tbody"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="map-resizer" id="mapResizer" title="Drag to resize map panel (double-click to reset)"></div>
    <div class="map-panel" id="mapPanel">
      <div class="map-header">
        <div class="map-title">
          <span>🗺 GPS Track</span>
          <span class="map-points-badge" id="mapPointsCount">0 pts</span>
        </div>
        <div class="map-header-actions">
          <button class="map-btn-mini" id="btnMapTheme" title="Switch between Dark Matter and Positron map tiles">🌓 Map Tiles</button>
          <button class="map-btn-mini" id="btnMapFit" title="Fit track bounds in view">Fit</button>
          <button class="map-btn-mini" id="btnMapClose" title="Close map drawer">✕</button>
        </div>
      </div>
      <div class="map-container-inner" id="mapContainer"></div>
      <div class="map-telemetry-bar" id="mapTelemetryBar">
        <div class="map-telemetry-item">
          <span class="map-telemetry-label">Time</span>
          <span class="map-telemetry-val" id="mapTeleTime">-- s</span>
        </div>
        <div class="map-telemetry-item">
          <span class="map-telemetry-label">Speed</span>
          <span class="map-telemetry-val" id="mapTeleSpeed">-- km/h</span>
        </div>
        <div class="map-telemetry-item">
          <span class="map-telemetry-label">Heading</span>
          <span class="map-telemetry-val" id="mapTeleHeading">--°</span>
        </div>
        <div class="map-telemetry-item">
          <span class="map-telemetry-label">Alt</span>
          <span class="map-telemetry-val" id="mapTeleAlt">-- m</span>
        </div>
      </div>
    </div>
  </main>

  <script>
    let currentTheme = localStorage.getItem('minigauge_theme') || 'dark';
    document.documentElement.setAttribute('data-theme', currentTheme);

    document.getElementById('btn-theme-toggle').addEventListener('click', () => {
      currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', currentTheme);
      localStorage.setItem('minigauge_theme', currentTheme);
      updateMapTheme();
      renderActiveTabPlots();
    });

    function getPlotlyLayoutTheme() {
      const isDark = (document.documentElement.getAttribute('data-theme') === 'dark');
      return {
        paper_bgcolor: isDark ? '#181b21' : '#ffffff',
        plot_bgcolor: isDark ? '#121417' : '#f8fafc',
        font: { color: isDark ? '#e2e8f0' : '#0f172a', size: 11 },
        gridcolor: isDark ? '#262c36' : '#e2e8f0',
        zerolinecolor: isDark ? '#3b82f6' : '#94a3b8'
      };
    }

    let activeTabId = 'tab-gear';
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        activeTabId = btn.getAttribute('data-tab');
        document.getElementById(activeTabId).classList.add('active');
        renderActiveTabPlots();
        setTimeout(resizeActivePlots, 50);
      });
    });

    // Map State & Drawer Functions
    const DARK_TILES = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
    const LIGHT_TILES = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
    let isMapOpen = localStorage.getItem('minigauge_tuner_map_open') === 'true';
    let leafletMap = null;
    let leafletTileLayer = null;
    let trackPolylineLayer = null;
    let hitPolylineLayer = null;
    let vehicleMarker = null;
    let startMarker = null;
    let endMarker = null;
    let currentMapTileTheme = null;

    function getEffectiveTheme() {
      if (currentMapTileTheme) return currentMapTileTheme;
      return (document.documentElement.getAttribute('data-theme') === 'dark') ? 'dark' : 'light';
    }

    function updateMapTheme() {
      if (!leafletTileLayer) return;
      const isDark = getEffectiveTheme() === 'dark';
      leafletTileLayer.setUrl(isDark ? DARK_TILES : LIGHT_TILES);
    }

    function getSpeedColor(speed, maxSpeed) {
      if (maxSpeed <= 0) return '#3b82f6';
      const ratio = Math.min(1.0, Math.max(0.0, speed / maxSpeed));
      if (ratio < 0.25) {
        const t = ratio / 0.25;
        const r = Math.round(59 + (6 - 59) * t);
        const g = Math.round(130 + (182 - 130) * t);
        const b = Math.round(246 + (212 - 246) * t);
        return `rgb(${r},${g},${b})`;
      } else if (ratio < 0.5) {
        const t = (ratio - 0.25) / 0.25;
        const r = Math.round(6 + (16 - 6) * t);
        const g = Math.round(182 + (185 - 182) * t);
        const b = Math.round(212 + (129 - 212) * t);
        return `rgb(${r},${g},${b})`;
      } else if (ratio < 0.75) {
        const t = (ratio - 0.5) / 0.25;
        const r = Math.round(16 + (245 - 16) * t);
        const g = Math.round(185 + (158 - 185) * t);
        const b = Math.round(129 + (11 - 129) * t);
        return `rgb(${r},${g},${b})`;
      } else {
        const t = (ratio - 0.75) / 0.25;
        const r = Math.round(245 + (239 - 245) * t);
        const g = Math.round(158 + (68 - 158) * t);
        const b = Math.round(11 + (68 - 11) * t);
        return `rgb(${r},${g},${b})`;
      }
    }

    function initOrUpdateMap() {
      if (typeof L === 'undefined') {
        const container = document.getElementById('mapContainer');
        if (container) {
          container.innerHTML = '<div style="color:var(--text-muted);padding:2rem;text-align:center;">Leaflet library loading...</div>';
        }
        return;
      }
      const container = document.getElementById('mapContainer');
      if (!container) return;

      if (!leafletMap) {
        leafletMap = L.map('mapContainer', {
          zoomControl: true,
          attributionControl: true
        }).setView([0, 0], 2);

        const isDark = getEffectiveTheme() === 'dark';
        leafletTileLayer = L.tileLayer(isDark ? DARK_TILES : LIGHT_TILES, {
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
          subdomains: 'abcd',
          maxZoom: 19
        }).addTo(leafletMap);
      } else {
        updateMapTheme();
      }

      leafletMap.invalidateSize();

      if (trackPolylineLayer) { leafletMap.removeLayer(trackPolylineLayer); trackPolylineLayer = null; }
      if (hitPolylineLayer) { leafletMap.removeLayer(hitPolylineLayer); hitPolylineLayer = null; }
      if (vehicleMarker) { leafletMap.removeLayer(vehicleMarker); vehicleMarker = null; }
      if (startMarker) { leafletMap.removeLayer(startMarker); startMarker = null; }
      if (endMarker) { leafletMap.removeLayer(endMarker); endMarker = null; }

      const gps = (algoData && algoData.gps) ? algoData.gps : null;
      const badge = document.getElementById('mapPointsCount');
      if (!gps || !gps.has_gps || !gps.points || gps.points.length === 0) {
        if (badge) badge.innerText = '0 pts';
        container.innerHTML = '<div style="color:var(--text-muted);padding:2rem;text-align:center;">No valid GPS coordinates in this log.</div>';
        return;
      }

      const points = gps.points;
      if (badge) badge.innerText = `${points.length} pts`;
      const maxSpeed = gps.max_speed || 1.0;

      trackPolylineLayer = L.featureGroup().addTo(leafletMap);

      let currentBin = -1;
      let currentChunk = [];
      const numBins = 10;

      for (let i = 0; i < points.length; i++) {
        const pt = points[i];
        const bin = Math.min(numBins - 1, Math.floor((pt.speed / (maxSpeed || 1.0)) * numBins));
        const coord = [pt.lat, pt.lon];

        if (bin === currentBin) {
          currentChunk.push(coord);
        } else {
          if (currentChunk.length > 1) {
            const binMidSpeed = ((currentBin + 0.5) / numBins) * maxSpeed;
            L.polyline(currentChunk, {
              color: getSpeedColor(binMidSpeed, maxSpeed),
              weight: 4,
              opacity: 0.85,
              lineJoin: 'round',
              lineCap: 'round'
            }).addTo(trackPolylineLayer);
          }
          currentBin = bin;
          currentChunk = (i > 0) ? [[points[i - 1].lat, points[i - 1].lon], coord] : [coord];
        }
      }
      if (currentChunk.length > 1) {
        const binMidSpeed = ((currentBin + 0.5) / numBins) * maxSpeed;
        L.polyline(currentChunk, {
          color: getSpeedColor(binMidSpeed, maxSpeed),
          weight: 4,
          opacity: 0.85,
          lineJoin: 'round',
          lineCap: 'round'
        }).addTo(trackPolylineLayer);
      }

      const allCoords = points.map(p => [p.lat, p.lon]);
      hitPolylineLayer = L.polyline(allCoords, {
        weight: 16,
        opacity: 0.0,
        interactive: true
      }).addTo(leafletMap);

      hitPolylineLayer.on('click', (e) => {
        const closest = findClosestGpsPoint(e.latlng.lat, e.latlng.lng);
        if (closest) {
          jumpToTime(closest.t);
        }
      });

      const startPt = points[0];
      const endPt = points[points.length - 1];

      startMarker = L.circleMarker([startPt.lat, startPt.lon], {
        radius: 5,
        fillColor: '#10b981',
        color: '#ffffff',
        weight: 1.5,
        fillOpacity: 1
      }).bindTooltip('Start (t=0s)').addTo(leafletMap);

      endMarker = L.circleMarker([endPt.lat, endPt.lon], {
        radius: 5,
        fillColor: '#ef4444',
        color: '#ffffff',
        weight: 1.5,
        fillOpacity: 1
      }).bindTooltip(`End (t=${endPt.t.toFixed(1)}s)`).addTo(leafletMap);

      const vehicleIcon = L.divIcon({
        className: 'vehicle-marker-wrapper',
        html: `
          <div class="vehicle-marker-pulse"></div>
          <div class="vehicle-marker-circle">
            <div class="vehicle-marker-arrow" id="vehicleMarkerArrow">▲</div>
          </div>
        `,
        iconSize: [28, 28],
        iconAnchor: [14, 14]
      });

      vehicleMarker = L.marker([startPt.lat, startPt.lon], {
        icon: vehicleIcon,
        zIndexOffset: 1000
      }).addTo(leafletMap);

      vehicleMarker.bindTooltip(`${startPt.speed.toFixed(1)} km/h`, {
        permanent: false,
        direction: 'top',
        offset: [0, -14],
        className: 'map-marker-tooltip'
      });

      leafletMap.fitBounds(trackPolylineLayer.getBounds(), { padding: [25, 25] });
      updateTelemetryBar(startPt);
    }

    function findGpsPointAtTime(t) {
      if (!algoData || !algoData.gps || !algoData.gps.points || algoData.gps.points.length === 0) return null;
      const pts = algoData.gps.points;
      let low = 0;
      let high = pts.length - 1;
      if (t <= pts[0].t) return pts[0];
      if (t >= pts[high].t) return pts[high];

      while (low <= high) {
        const mid = (low + high) >> 1;
        if (pts[mid].t === t) return pts[mid];
        if (pts[mid].t < t) low = mid + 1;
        else high = mid - 1;
      }
      if (low >= pts.length) return pts[pts.length - 1];
      if (high < 0) return pts[0];
      return Math.abs(pts[low].t - t) < Math.abs(pts[high].t - t) ? pts[low] : pts[high];
    }

    function findClosestGpsPoint(lat, lng) {
      if (!algoData || !algoData.gps || !algoData.gps.points || algoData.gps.points.length === 0) return null;
      let minDist = Infinity;
      let closest = algoData.gps.points[0];
      for (let i = 0; i < algoData.gps.points.length; i++) {
        const p = algoData.gps.points[i];
        const dLat = p.lat - lat;
        const dLon = p.lon - lng;
        const dist = dLat * dLat + dLon * dLon;
        if (dist < minDist) {
          minDist = dist;
          closest = p;
        }
      }
      return closest;
    }

    function updateVehicleMarker(t) {
      if (!algoData || !algoData.gps || !algoData.gps.has_gps || !algoData.gps.points || algoData.gps.points.length === 0) return;
      const pt = findGpsPointAtTime(t);
      if (!pt) return;

      if (vehicleMarker) {
        vehicleMarker.setLatLng([pt.lat, pt.lon]);
        const arrow = document.getElementById('vehicleMarkerArrow');
        if (arrow) {
          arrow.style.transform = `rotate(${pt.heading}deg)`;
        }
        vehicleMarker.setTooltipContent(`<b>${pt.speed.toFixed(1)} km/h</b><br>t: ${pt.t.toFixed(2)}s | hdg: ${pt.heading.toFixed(0)}°`);
      }
      updateTelemetryBar(pt);

      if (leafletMap && isMapOpen) {
        if (!leafletMap.getBounds().contains([pt.lat, pt.lon])) {
          leafletMap.panTo([pt.lat, pt.lon], { animate: true, duration: 0.2 });
        }
      }
    }

    function updateTelemetryBar(pt) {
      if (!pt) return;
      const tEl = document.getElementById('mapTeleTime');
      const sEl = document.getElementById('mapTeleSpeed');
      const hEl = document.getElementById('mapTeleHeading');
      const aEl = document.getElementById('mapTeleAlt');
      if (tEl) tEl.textContent = `${pt.t.toFixed(2)} s`;
      if (sEl) sEl.textContent = `${pt.speed.toFixed(1)} km/h`;
      if (hEl) hEl.textContent = `${pt.heading.toFixed(0)}°`;
      if (aEl) aEl.textContent = `${pt.alt.toFixed(1)} m`;
    }

    function jumpToTime(t) {
      if (!algoData) return;
      let span = (timeRange[1] !== null && timeRange[0] !== null) ? (timeRange[1] - timeRange[0]) : 30;
      if (span <= 0 || span > algoData.duration_s) span = 30;
      const half = span / 2;
      timeRange = [Math.max(0, t - half), Math.min(algoData.duration_s, t + half)];
      document.getElementById('time-from').value = timeRange[0].toFixed(1);
      document.getElementById('time-to').value = timeRange[1].toFixed(1);
      renderActiveTabPlots();
      updateVehicleMarker(t);
    }

    function toggleMap(forceState) {
      if (forceState !== undefined) {
        isMapOpen = forceState;
      } else {
        isMapOpen = !isMapOpen;
      }
      localStorage.setItem('minigauge_tuner_map_open', isMapOpen);
      const mapPanel = document.getElementById('mapPanel');
      const resizer = document.getElementById('mapResizer');
      const btnToggleMap = document.getElementById('btnToggleMap');
      if (isMapOpen) {
        if (mapPanel) mapPanel.classList.add('open');
        if (resizer) resizer.classList.add('open');
        if (btnToggleMap) btnToggleMap.classList.add('btn-active-toggle');
        setTimeout(() => {
          initOrUpdateMap();
          resizeActivePlots();
        }, 50);
      } else {
        if (mapPanel) mapPanel.classList.remove('open');
        if (resizer) resizer.classList.remove('open');
        if (btnToggleMap) btnToggleMap.classList.remove('btn-active-toggle');
        resizeActivePlots();
      }
    }

    function setupMapResizer() {
      const resizer = document.getElementById('mapResizer');
      const mapPanel = document.getElementById('mapPanel');
      const viewport = document.querySelector('main.tab-viewport');
      if (!resizer || !mapPanel || !viewport) return;

      let isDragging = false;
      let startX = 0;
      let startWidth = 0;

      const savedWidth = localStorage.getItem('minigauge_map_panel_width');
      if (savedWidth) {
        const w = parseInt(savedWidth, 10);
        if (!isNaN(w) && w >= 250 && w <= window.innerWidth * 0.8) {
          mapPanel.style.width = `${w}px`;
        }
      }

      resizer.addEventListener('mousedown', (e) => {
        isDragging = true;
        startX = e.clientX;
        startWidth = mapPanel.getBoundingClientRect().width;
        resizer.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
      });

      window.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const deltaX = startX - e.clientX;
        let newWidth = startWidth + deltaX;
        const minW = 250;
        const maxW = Math.max(minW, viewport.getBoundingClientRect().width - 320);
        newWidth = Math.max(minW, Math.min(maxW, newWidth));
        mapPanel.style.width = `${newWidth}px`;
        resizeActivePlots();
      });

      window.addEventListener('mouseup', () => {
        if (isDragging) {
          isDragging = false;
          resizer.classList.remove('dragging');
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
          localStorage.setItem('minigauge_map_panel_width', parseInt(mapPanel.style.width, 10));
          resizeActivePlots();
        }
      });

      resizer.addEventListener('dblclick', () => {
        mapPanel.style.width = '440px';
        localStorage.setItem('minigauge_map_panel_width', 440);
        resizeActivePlots();
      });
    }

    function resizeActivePlots() {
      const activePane = document.getElementById(activeTabId);
      if (activePane) {
        activePane.querySelectorAll('.plot-box').forEach(div => {
          if (div.id && window.Plotly) Plotly.Plots.resize(div);
        });
      }
      if (leafletMap && isMapOpen) {
        leafletMap.invalidateSize();
      }
    }

    function handlePlotRelayout(ev) {
      if (ev && ev['xaxis.range[0]'] !== undefined && ev['xaxis.range[1]'] !== undefined) {
        timeRange = [parseFloat(ev['xaxis.range[0]']), parseFloat(ev['xaxis.range[1]'])];
        document.getElementById('time-from').value = timeRange[0].toFixed(1);
        document.getElementById('time-to').value = timeRange[1].toFixed(1);
        renderActiveTabPlots();
      } else if (ev && (ev['xaxis.autorange'] === true || ev['autosize'] === true)) {
        timeRange = [0, algoData.duration_s];
        document.getElementById('time-from').value = '0';
        document.getElementById('time-to').value = algoData.duration_s.toFixed(1);
        renderActiveTabPlots();
      }
    }

    function handlePlotHover(ev) {
      if (ev && ev.points && ev.points[0] && ev.points[0].x !== undefined) {
        const t = ev.points[0].x;
        updateVehicleMarker(t);
        if (typeof updateTunerReplayDisplay === 'function' && (!tunerReplayer || !tunerReplayer.playing)) {
          updateTunerReplayDisplay(t);
        }
      }
    }

    document.getElementById('btnToggleMap').addEventListener('click', () => toggleMap());
    document.getElementById('btnMapClose').addEventListener('click', () => toggleMap(false));
    document.getElementById('btnMapFit').addEventListener('click', () => {
      if (leafletMap && trackPolylineLayer) {
        leafletMap.fitBounds(trackPolylineLayer.getBounds(), { padding: [25, 25] });
      }
    });
    document.getElementById('btnMapTheme').addEventListener('click', () => {
      currentMapTileTheme = (getEffectiveTheme() === 'dark') ? 'light' : 'dark';
      updateMapTheme();
    });
    window.addEventListener('resize', resizeActivePlots);

    let currentLog = '';
    let algoData = null;
    let analyticsData = null;
    let timeRange = [null, null];

    function showLoading(text) {
      document.getElementById('loading-text').innerText = text || 'Loading...';
      document.getElementById('loading-overlay').style.display = 'flex';
    }
    function hideLoading() {
      document.getElementById('loading-overlay').style.display = 'none';
    }

    document.getElementById('btn-time-apply').addEventListener('click', () => {
      const fromVal = parseFloat(document.getElementById('time-from').value);
      const toVal = parseFloat(document.getElementById('time-to').value);
      timeRange = [
        isNaN(fromVal) ? null : fromVal,
        isNaN(toVal) ? null : toVal
      ];
      renderActiveTabPlots();
    });

    document.getElementById('btn-time-fit').addEventListener('click', () => {
      timeRange = [null, null];
      fuelUserYRange = null;
      document.getElementById('time-from').value = '';
      document.getElementById('time-to').value = '';
      renderActiveTabPlots();
    });

    document.getElementById('btn-zoom-in').addEventListener('click', () => {
      if (!algoData) return;
      const curFrom = timeRange[0] !== null ? timeRange[0] : 0;
      const curTo = timeRange[1] !== null ? timeRange[1] : algoData.duration_s;
      const center = (curFrom + curTo) / 2;
      const halfSpan = (curTo - curFrom) / 4;
      timeRange = [Math.max(0, center - halfSpan), center + halfSpan];
      document.getElementById('time-from').value = timeRange[0].toFixed(1);
      document.getElementById('time-to').value = timeRange[1].toFixed(1);
      renderActiveTabPlots();
    });

    document.getElementById('btn-zoom-out').addEventListener('click', () => {
      if (!algoData) return;
      const curFrom = timeRange[0] !== null ? timeRange[0] : 0;
      const curTo = timeRange[1] !== null ? timeRange[1] : algoData.duration_s;
      const center = (curFrom + curTo) / 2;
      const span = (curTo - curFrom);
      timeRange = [Math.max(0, center - span), Math.min(algoData.duration_s, center + span)];
      document.getElementById('time-from').value = timeRange[0].toFixed(1);
      document.getElementById('time-to').value = timeRange[1].toFixed(1);
      renderActiveTabPlots();
    });

    async function initLogs() {
      showLoading('Fetching logs...');
      try {
        const res = await fetch('/api/logs');
        const logs = await res.json();
        const sel = document.getElementById('log-select');
        sel.innerHTML = '';
        logs.forEach(l => {
          const opt = document.createElement('option');
          opt.value = l.filename;
          opt.innerText = `${l.filename} (${(l.size / (1024*1024)).toFixed(1)} MB)`;
          sel.appendChild(opt);
        });
        if (logs.length > 0) {
          sel.value = logs[0].filename;
          currentLog = logs[0].filename;
          await loadLogData(currentLog);
        }
      } catch (e) {
        console.error("Failed to load logs:", e);
      } finally {
        hideLoading();
      }
    }

    document.getElementById('log-select').addEventListener('change', async (e) => {
      currentLog = e.target.value;
      await loadLogData(currentLog);
    });

    async function loadLogData(filename) {
      showLoading(`Decoding ${filename}...`);
      try {
        const [resAlgo, resAnalytics] = await Promise.all([
          fetch(`/api/algo_data?file=${encodeURIComponent(filename)}`),
          fetch(`/api/analytics?file=${encodeURIComponent(filename)}`)
        ]);
        algoData = await resAlgo.json();
        analyticsData = await resAnalytics.json();

        timeRange = [0, algoData.duration_s];
        document.getElementById('time-from').value = 0;
        document.getElementById('time-to').value = algoData.duration_s.toFixed(1);

        const btnMap = document.getElementById('btnToggleMap');
        const badge = document.getElementById('mapPointsCount');
        if (algoData.gps && algoData.gps.has_gps && algoData.gps.points && algoData.gps.points.length > 0) {
          if (btnMap) {
            btnMap.disabled = false;
            btnMap.style.opacity = '1';
            btnMap.title = `Toggle GPS Track Map (${algoData.gps.points.length} points)`;
          }
          if (badge) badge.innerText = `${algoData.gps.points.length} pts`;
        } else {
          if (btnMap) {
            btnMap.title = 'No GPS coordinates in this log';
            btnMap.style.opacity = '0.5';
          }
          if (badge) badge.innerText = '0 pts';
        }

        renderActiveTabPlots();
        if (isMapOpen) {
          initOrUpdateMap();
        }
      } catch (e) {
        console.error("Error loading log data:", e);
        alert("Failed to load log data: " + e.message);
      } finally {
        hideLoading();
      }
    }

    function renderActiveTabPlots() {
      if (!algoData) return;
      if (activeTabId === 'tab-gear') {
        computeAndRenderGear();
      } else if (activeTabId === 'tab-fuel') {
        computeAndRenderFuel();
      } else if (activeTabId === 'tab-speed') {
        computeAndRenderSpeed();
      } else if (activeTabId === 'tab-analytics') {
        renderAnalyticsTable();
      }
    }

    // TAB 1: GEAR POSITION ESTIMATOR LOGIC
    const gearParams = {
      preset: 'baseline',
      rpmFilterEnabled: false,
      rpmFilterType: 'EMA',
      rpmFilterTau: 0.10,
      minSpeed: 5.0,
      minRpm: 25.0,
      stabGate: 0.050,
      alpha: 0.15,
      latchEnabled: false,
      latchHoldMs: 200,
      tol: 0.25,
      r: [1.01, 1.80, 2.73, 3.76, 4.54],
      showGroundTruth: false
    };

    function updateGearLabels() {
      const speedKph = (gearParams.minSpeed * 0.2444).toFixed(1);
      const rpmVal = Math.round(gearParams.minRpm * 30);
      document.getElementById('val-gear-minspeed').innerText = `${gearParams.minSpeed.toFixed(1)} Hz (~${speedKph} km/h)`;
      document.getElementById('val-gear-minrpm').innerText = `${gearParams.minRpm.toFixed(0)} Hz (${rpmVal} RPM)`;
      document.getElementById('val-gear-stab').innerText = gearParams.stabGate.toFixed(3);
      document.getElementById('val-gear-alpha').innerText = gearParams.alpha.toFixed(2);
      document.getElementById('val-gear-tol').innerText = '±' + gearParams.tol.toFixed(2);
      if (document.getElementById('val-gear-rpm-param')) {
        document.getElementById('val-gear-rpm-param').innerText = gearParams.rpmFilterTau.toFixed(2) + ' s';
      }
      if (document.getElementById('val-gear-latch')) {
        document.getElementById('val-gear-latch').innerText = gearParams.latchHoldMs + ' ms';
      }
    }

    function renderGearMathExplanation() {
      const card = document.getElementById('card-gear-math');
      if (!card) return;

      const presetNames = {
        'baseline': '1. Baseline (Gated Ratio EMA)',
        'rpm_filter': '2. RPM Pre-Filtered + Ratio EMA',
        'latched': '3. Full Pipeline (RPM Filter + Latch)',
        'custom': 'Custom Modular Pipeline'
      };

      const presetLabel = presetNames[gearParams.preset] || 'Custom Modular Pipeline';

      let stepNum = 1;
      let stepsHtml = '';

      if (gearParams.rpmFilterEnabled) {
        if (gearParams.rpmFilterType === 'EMA') {
          stepsHtml += `
            <div>
              <strong>Step ${stepNum++}: Input RPM Frequency Smoothing (EMA):</strong>
              <div style="font-family:monospace; background:var(--input-bg); padding:3px 6px; border-radius:4px; margin-top:2px;">
                f_RPM,filt(t) = &alpha;_rpm &middot; f_RPM(t) + (1 - &alpha;_rpm) &middot; f_RPM,filt(t - &Delta;t)
              </div>
              <span style="color:var(--text-muted); font-size:0.7rem;">Exponential filter on 0x301 DBG_RPM_freq with &tau; = ${gearParams.rpmFilterTau.toFixed(2)}s (&alpha;_rpm &approx; ${(0.1 / (gearParams.rpmFilterTau + 0.1)).toFixed(2)}).</span>
            </div>
          `;
        } else {
          const winPts = Math.max(1, Math.round(gearParams.rpmFilterTau / 0.1));
          stepsHtml += `
            <div>
              <strong>Step ${stepNum++}: Input RPM Frequency Smoothing (SMA):</strong>
              <div style="font-family:monospace; background:var(--input-bg); padding:3px 6px; border-radius:4px; margin-top:2px;">
                f_RPM,filt(t) = (1 / W) &sum; f_RPM(t - k&Delta;t)
              </div>
              <span style="color:var(--text-muted); font-size:0.7rem;">Moving window of ${winPts} samples (&Delta;t = ${gearParams.rpmFilterTau.toFixed(2)}s) on 0x301 DBG_RPM_freq.</span>
            </div>
          `;
        }
      }

      const rpmSource = gearParams.rpmFilterEnabled ? 'f_RPM,filt(t)' : 'f_RPM(t)';

      stepsHtml += `
        <div>
          <strong>Step ${stepNum++}: Instantaneous Gear Ratio:</strong>
          <div style="font-family:monospace; background:var(--input-bg); padding:3px 6px; border-radius:4px; margin-top:2px;">
            r_inst(t) = f_speed(t) / ${rpmSource}
          </div>
          <span style="color:var(--text-muted); font-size:0.7rem;">Computed from 0x300 <code>DBG_speed_freq</code> & 0x301 ${gearParams.rpmFilterEnabled ? 'filtered' : 'raw'} <code>DBG_RPM_freq</code>.</span>
        </div>
        <div>
          <strong>Step ${stepNum++}: Triple Gating (Clutch / Slip Rejection):</strong>
          <ul style="padding-left:1rem; margin-top:2px; color:var(--text-muted); font-size:0.7rem;">
            <li><code>f_speed &ge; minSpeed</code> (${gearParams.minSpeed.toFixed(1)} Hz &approx; ${(gearParams.minSpeed * 0.2444).toFixed(1)} km/h, rejects standstill)</li>
            <li><code>f_RPM &ge; minRPM</code> (${gearParams.minRpm.toFixed(0)} Hz = ${Math.round(gearParams.minRpm * 30)} RPM, rejects stall/idle)</li>
            <li><code>|&Delta;r / &Delta;t| &le; Gate</code> (${gearParams.stabGate.toFixed(3)}, rejects clutch slip and active shift transients)</li>
          </ul>
        </div>
        <div>
          <strong>Step ${stepNum++}: Ratio-Domain EMA (Filter on Ratio):</strong>
          <div style="font-family:monospace; background:var(--input-bg); padding:3px 6px; border-radius:4px; margin-top:2px;">
            r_EMA(t) = &alpha; &middot; r_inst(t) + (1 - &alpha;) &middot; r_EMA(t - 1)
          </div>
          <div style="font-size:0.7rem; color:var(--warning); margin-top:3px; line-height:1.35;">
            ⚡ <em>Note:</em> Primary smoothing applies directly to the <strong>ratio</strong> (&alpha; = ${gearParams.alpha.toFixed(2)}) to prevent differential phase lag between engine and wheel inertia.
          </div>
        </div>
        <div>
          <strong>Step ${stepNum++}: Tolerance Classification:</strong>
            Candidate gear <em>i</em> &isin; [1..5] if <code>|r_EMA - R_i| &le; tol</code> (&plusmn;${gearParams.tol.toFixed(2)} ratio units, with Voronoi collision protection).<br>
            Fails tolerance or gating &rarr; Neutral (N / 0).
          </div>
        </div>
      `;

      if (gearParams.latchEnabled) {
        stepsHtml += `
          <div>
            <strong>Step ${stepNum++}: Output Gear Latching / Debouncing:</strong>
            <div style="font-family:monospace; background:var(--input-bg); padding:3px 6px; border-radius:4px; margin-top:2px;">
              G_out(t) = G_cand(t) &nbsp; iff sustained &ge; ${gearParams.latchHoldMs} ms
            </div>
            <span style="color:var(--text-muted); font-size:0.7rem;">Holds current gear and suppresses 1-sample transitions or jitter during clutching. Immediate drop to Neutral on vehicle stop.</span>
          </div>
        `;
      }

      card.innerHTML = `
        <div class="card-title" style="color:var(--primary); display:flex; justify-content:space-between; align-items:center;">
          <span>📐 Algorithm Math & Workflow</span>
          <span style="font-size:0.68rem; font-weight:normal; background:var(--badge-bg); color:var(--badge-text); padding:2px 6px; border-radius:4px;">${presetLabel}</span>
        </div>
        <div style="font-size:0.75rem; color:var(--text); line-height:1.45; display:flex; flex-direction:column; gap:0.5rem; margin-top:0.4rem;">
          ${stepsHtml}
        </div>
      `;
    }

    function loadGearSettings() {
      const saved = localStorage.getItem('minigauge_gear_params');
      if (saved) {
        try {
          Object.assign(gearParams, JSON.parse(saved));
        } catch(e){}
      }
      if (document.getElementById('select-gear-preset')) {
        document.getElementById('select-gear-preset').value = gearParams.preset || 'baseline';
      }
      if (document.getElementById('chk-gear-rpm-filter')) {
        document.getElementById('chk-gear-rpm-filter').checked = !!gearParams.rpmFilterEnabled;
        document.getElementById('gear-rpm-filter-controls').style.display = gearParams.rpmFilterEnabled ? 'flex' : 'none';
      }
      if (document.getElementById('radio-gear-rpm-ema')) {
        document.getElementById('radio-gear-rpm-ema').checked = (gearParams.rpmFilterType === 'EMA');
        document.getElementById('radio-gear-rpm-sma').checked = (gearParams.rpmFilterType === 'SMA');
        document.getElementById('lbl-gear-rpm-param').innerText = (gearParams.rpmFilterType === 'EMA') ? 'Time Constant (τ)' : 'Window Size (s)';
      }
      if (document.getElementById('slider-gear-rpm-param')) {
        document.getElementById('slider-gear-rpm-param').value = gearParams.rpmFilterTau;
      }
      if (document.getElementById('chk-gear-latch')) {
        document.getElementById('chk-gear-latch').checked = !!gearParams.latchEnabled;
        document.getElementById('gear-latch-controls').style.display = gearParams.latchEnabled ? 'flex' : 'none';
      }
      if (document.getElementById('slider-gear-latch')) {
        document.getElementById('slider-gear-latch').value = gearParams.latchHoldMs;
      }

      document.getElementById('slider-gear-minspeed').value = gearParams.minSpeed;
      document.getElementById('slider-gear-minrpm').value = gearParams.minRpm;
      document.getElementById('slider-gear-stab').value = gearParams.stabGate;
      document.getElementById('slider-gear-alpha').value = gearParams.alpha;
      document.getElementById('slider-gear-tol').value = gearParams.tol;
      document.getElementById('chk-gear-groundtruth').checked = gearParams.showGroundTruth;

      for (let i = 1; i <= 5; i++) {
        const inp = document.getElementById(`gear-r-${i}`);
        if (inp && gearParams.r[i - 1] !== undefined) inp.value = gearParams.r[i - 1].toFixed(2);
      }
      updateGearLabels();
      renderGearMathExplanation();
    }
    loadGearSettings();

    function saveGearSettings() {
      localStorage.setItem('minigauge_gear_params', JSON.stringify(gearParams));
    }

    document.getElementById('select-gear-preset').addEventListener('change', (e) => {
      const p = e.target.value;
      gearParams.preset = p;
      if (p === 'baseline') {
        gearParams.rpmFilterEnabled = false;
        gearParams.latchEnabled = false;
      } else if (p === 'rpm_filter') {
        gearParams.rpmFilterEnabled = true;
        gearParams.latchEnabled = false;
      } else if (p === 'latched') {
        gearParams.rpmFilterEnabled = true;
        gearParams.latchEnabled = true;
      }
      document.getElementById('chk-gear-rpm-filter').checked = gearParams.rpmFilterEnabled;
      document.getElementById('gear-rpm-filter-controls').style.display = gearParams.rpmFilterEnabled ? 'flex' : 'none';
      document.getElementById('chk-gear-latch').checked = gearParams.latchEnabled;
      document.getElementById('gear-latch-controls').style.display = gearParams.latchEnabled ? 'flex' : 'none';
      saveGearSettings();
      renderGearMathExplanation();
      computeAndRenderGear();
    });

    document.getElementById('chk-gear-rpm-filter').addEventListener('change', (e) => {
      gearParams.rpmFilterEnabled = e.target.checked;
      gearParams.preset = 'custom';
      document.getElementById('select-gear-preset').value = 'custom';
      document.getElementById('gear-rpm-filter-controls').style.display = gearParams.rpmFilterEnabled ? 'flex' : 'none';
      saveGearSettings();
      renderGearMathExplanation();
      computeAndRenderGear();
    });

    document.querySelectorAll('input[name="gear-rpm-algo"]').forEach(r => {
      r.addEventListener('change', (e) => {
        gearParams.rpmFilterType = e.target.value;
        document.getElementById('lbl-gear-rpm-param').innerText = (gearParams.rpmFilterType === 'EMA') ? 'Time Constant (τ)' : 'Window Size (s)';
        saveGearSettings();
        renderGearMathExplanation();
        computeAndRenderGear();
      });
    });

    document.getElementById('slider-gear-rpm-param').addEventListener('input', (e) => {
      gearParams.rpmFilterTau = parseFloat(e.target.value);
      updateGearLabels();
      saveGearSettings();
      renderGearMathExplanation();
      computeAndRenderGear();
    });

    document.getElementById('chk-gear-latch').addEventListener('change', (e) => {
      gearParams.latchEnabled = e.target.checked;
      gearParams.preset = 'custom';
      document.getElementById('select-gear-preset').value = 'custom';
      document.getElementById('gear-latch-controls').style.display = gearParams.latchEnabled ? 'flex' : 'none';
      saveGearSettings();
      renderGearMathExplanation();
      computeAndRenderGear();
    });

    document.getElementById('slider-gear-latch').addEventListener('input', (e) => {
      gearParams.latchHoldMs = parseInt(e.target.value, 10);
      updateGearLabels();
      saveGearSettings();
      renderGearMathExplanation();
      computeAndRenderGear();
    });

    document.getElementById('slider-gear-minspeed').addEventListener('input', (e) => {
      gearParams.minSpeed = parseFloat(e.target.value);
      updateGearLabels();
      saveGearSettings();
      renderGearMathExplanation();
      computeAndRenderGear();
    });
    document.getElementById('slider-gear-minrpm').addEventListener('input', (e) => {
      gearParams.minRpm = parseFloat(e.target.value);
      updateGearLabels();
      saveGearSettings();
      renderGearMathExplanation();
      computeAndRenderGear();
    });
    document.getElementById('slider-gear-stab').addEventListener('input', (e) => {
      gearParams.stabGate = parseFloat(e.target.value);
      updateGearLabels();
      saveGearSettings();
      renderGearMathExplanation();
      computeAndRenderGear();
    });
    document.getElementById('slider-gear-alpha').addEventListener('input', (e) => {
      gearParams.alpha = parseFloat(e.target.value);
      updateGearLabels();
      saveGearSettings();
      renderGearMathExplanation();
      computeAndRenderGear();
    });
    document.getElementById('slider-gear-tol').addEventListener('input', (e) => {
      gearParams.tol = parseFloat(e.target.value);
      updateGearLabels();
      saveGearSettings();
      renderGearMathExplanation();
      computeAndRenderGear();
    });
    document.getElementById('chk-gear-groundtruth').addEventListener('change', (e) => {
      gearParams.showGroundTruth = e.target.checked;
      saveGearSettings();
      computeAndRenderGear();
    });
    for (let i = 1; i <= 5; i++) {
      const inp = document.getElementById(`gear-r-${i}`);
      if (inp) {
        inp.addEventListener('change', (e) => {
          gearParams.r[i - 1] = parseFloat(e.target.value) || 1.0;
          saveGearSettings();
          computeAndRenderGear();
        });
      }
    }

    document.getElementById('btn-reset-gear-defaults').addEventListener('click', () => {
      gearParams.preset = 'baseline';
      gearParams.rpmFilterEnabled = false;
      gearParams.rpmFilterType = 'EMA';
      gearParams.rpmFilterTau = 0.10;
      gearParams.minSpeed = 5.0;
      gearParams.minRpm = 25.0;
      gearParams.stabGate = 0.050;
      gearParams.alpha = 0.15;
      gearParams.latchEnabled = false;
      gearParams.latchHoldMs = 200;
      gearParams.tol = 0.25;
      gearParams.r = [1.01, 1.80, 2.73, 3.76, 4.54];
      gearParams.showGroundTruth = false;
      saveGearSettings();
      loadGearSettings();
      computeAndRenderGear();
    });

    document.getElementById('btn-auto-gear-peaks').addEventListener('click', () => {
      if (!algoData || !algoData.gear) return;
      const g = algoData.gear;
      const validRatios = [];
      for (let i = 0; i < g.times.length; i++) {
        const s = g.speed_freq[i];
        const r = g.rpm_freq[i];
        if (s > gearParams.minSpeed && r > gearParams.minRpm) {
          validRatios.push(s / r);
        }
      }
      if (validRatios.length < 50) {
        alert("Not enough valid driving samples to auto-detect peaks.");
        return;
      }
      const binSize = 0.04;
      const bins = {};
      validRatios.forEach(v => {
        if (v >= 0.2 && v <= 8.0) {
          const b = Math.round(v / binSize) * binSize;
          bins[b] = (bins[b] || 0) + 1;
        }
      });
      const sortedKeys = Object.keys(bins).map(Number).sort((a,b)=>a-b);
      const candidates = [];
      for (let i = 1; i < sortedKeys.length - 1; i++) {
        const k = sortedKeys[i];
        const count = bins[k];
        if (count > bins[sortedKeys[i-1]] && count > bins[sortedKeys[i+1]] && count > 15) {
          candidates.push({ ratio: k, count: count });
        }
      }
      candidates.sort((a,b) => b.count - a.count);
      const finalPeaks = [];
      for (let c of candidates) {
        if (!finalPeaks.some(p => Math.abs(p - c.ratio) < 0.45)) {
          finalPeaks.push(c.ratio);
        }
      }
      finalPeaks.sort((a,b) => a - b);
      if (finalPeaks.length >= 2) {
        for (let i = 0; i < Math.min(5, finalPeaks.length); i++) {
          gearParams.r[i] = parseFloat(finalPeaks[i].toFixed(2));
          const el = document.getElementById(`gear-r-${i+1}`);
          if (el) el.value = gearParams.r[i];
        }
        saveGearSettings();
        computeAndRenderGear();
        alert(`Detected ${Math.min(5, finalPeaks.length)} gear clusters: ${gearParams.r.slice(0, Math.min(5, finalPeaks.length)).map(p=>p.toFixed(2)).join(', ')}`);
      } else {
        alert("Could not clearly isolate distinct cluster peaks. Drive cycle may have stayed in a single gear.");
      }
    });

    // Toggle simulated gear gauge pod
    const chkGaugePod = document.getElementById('chk-gear-gauge-pod');
    if (chkGaugePod) {
      chkGaugePod.addEventListener('change', (e) => {
        const pod = document.getElementById('pod-simulated-gear');
        if (pod) pod.style.display = e.target.checked ? 'flex' : 'none';
      });
    }

    // Shared calibration save / load
    const btnSaveCal = document.getElementById('btn-save-shared-cal');
    if (btnSaveCal) {
      btnSaveCal.addEventListener('click', async () => {
        btnSaveCal.disabled = true;
        try {
          const payload = {
            tolerance: gearParams.tol,
            latch_ms: gearParams.latchHoldMs
          };
          const resp = await fetch('/api/calibration', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const res = await resp.json();
          if (res.status === 'ok') {
            alert('Shared Calibration saved to decoder/gear_calibration.json');
          } else {
            alert('Failed to save calibration: ' + (res.error || 'error'));
          }
        } catch (e) {
          alert('Save calibration error: ' + e.message);
        } finally {
          btnSaveCal.disabled = false;
        }
      });
    }

    const btnLoadCal = document.getElementById('btn-load-shared-cal');
    if (btnLoadCal) {
      btnLoadCal.addEventListener('click', async () => {
        btnLoadCal.disabled = true;
        try {
          const resp = await fetch('/api/calibration');
          const cal = await resp.json();
          if (cal.tolerance !== undefined) {
            gearParams.tol = cal.tolerance;
            const el = document.getElementById('slider-gear-tol');
            if (el) el.value = cal.tolerance;
          }
          if (cal.latch_ms !== undefined) {
            gearParams.latchHoldMs = cal.latch_ms;
            const el = document.getElementById('slider-gear-latch');
            if (el) el.value = cal.latch_ms;
          }
          saveGearSettings();
          updateGearLabels();
          renderGearMathExplanation();
          computeAndRenderGear();
          alert('Shared Calibration loaded from decoder/gear_calibration.json');
        } catch (e) {
          alert('Load calibration error: ' + e.message);
        } finally {
          btnLoadCal.disabled = false;
        }
      });
    }

    function computeAndRenderGear() {
      if (!algoData || !algoData.gear) return;
      const g = algoData.gear;
      const n = g.times.length;

      const tMin = timeRange[0] !== null ? timeRange[0] : 0;
      const tMax = timeRange[1] !== null ? timeRange[1] : algoData.duration_s;

      const filteredTimes = [];
      const rawRatios = [];
      const smoothedRatios = [];
      const estimatedGears = [];
      const groundTruthGears = [];
      const filteredSpeeds = [];
      const filteredRpms = [];
      const histRatios = [];

      let currentEma = null;
      let prevRaw = null;
      let activeCount = 0;
      let totalEvalCount = 0;

      const gearTimeCounts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0};

      // Step 0: Precompute filtered RPM frequency if enabled
      const effRpmFreqs = new Float64Array(n);
      if (gearParams.rpmFilterEnabled) {
        if (gearParams.rpmFilterType === 'EMA') {
          const tau = Math.max(0.01, gearParams.rpmFilterTau);
          let emaRpm = g.rpm_freq[0] || 0.0;
          effRpmFreqs[0] = emaRpm;
          for (let i = 1; i < n; i++) {
            const dt = Math.max(0.001, Math.min(1.0, g.times[i] - g.times[i - 1]));
            const alphaRpm = dt / (tau + dt);
            emaRpm = alphaRpm * g.rpm_freq[i] + (1.0 - alphaRpm) * emaRpm;
            effRpmFreqs[i] = emaRpm;
          }
        } else {
          // SMA sliding window
          const winSec = Math.max(0.02, gearParams.rpmFilterTau);
          let sum = 0.0;
          let startIdx = 0;
          for (let i = 0; i < n; i++) {
            sum += g.rpm_freq[i];
            while (startIdx < i && (g.times[i] - g.times[startIdx]) > winSec) {
              sum -= g.rpm_freq[startIdx];
              startIdx++;
            }
            const count = (i - startIdx + 1);
            effRpmFreqs[i] = count > 0 ? (sum / count) : g.rpm_freq[i];
          }
        }
      } else {
        for (let i = 0; i < n; i++) {
          effRpmFreqs[i] = g.rpm_freq[i];
        }
      }

      // Output latch state variables
      let latchedGear = 0;
      let pendingGear = 0;
      let pendingStartTime = 0;

      for (let i = 0; i < n; i++) {
        const t = g.times[i];
        const sf = g.speed_freq[i];
        const rf = effRpmFreqs[i];
        const gt = g.ground_truth[i];

        const speedValid = (sf >= gearParams.minSpeed);
        const rpmValid = (rf >= gearParams.minRpm);
        const ratio = (rpmValid && sf > 0) ? (sf / rf) : null;

        let stable = false;
        if (ratio !== null && prevRaw !== null) {
          stable = (Math.abs(ratio - prevRaw) <= gearParams.stabGate);
        } else if (ratio !== null) {
          stable = true;
        }
        prevRaw = ratio;

        const isGatedActive = (speedValid && rpmValid && stable && ratio !== null);
        if (t >= tMin && t <= tMax) {
          totalEvalCount++;
          if (isGatedActive) activeCount++;
        }

        if (isGatedActive) {
          if (currentEma === null) {
            currentEma = ratio;
          } else {
            currentEma = gearParams.alpha * ratio + (1.0 - gearParams.alpha) * currentEma;
          }
          if (t >= tMin && t <= tMax) {
            histRatios.push(currentEma);
          }
        } else {
          currentEma = null;
        }

        let candGear = 0;
        if (currentEma !== null) {
          for (let gi = 0; gi < 5; gi++) {
            const nominal = gearParams.r[gi];
            let maxTol = gearParams.tol;
            if (gi > 0) {
              maxTol = Math.min(maxTol, (nominal - gearParams.r[gi - 1]) * 0.48);
            }
            if (gi < 4) {
              maxTol = Math.min(maxTol, (gearParams.r[gi + 1] - nominal) * 0.48);
            }
            if (Math.abs(currentEma - nominal) <= maxTol) {
              candGear = gi + 1;
              break;
            }
          }
        }

        let finalGear = candGear;
        if (gearParams.latchEnabled) {
          // If vehicle is stopped or engine stalled, drop immediately to Neutral
          if (!speedValid || !rpmValid) {
            latchedGear = 0;
            pendingGear = 0;
            pendingStartTime = t;
            finalGear = 0;
          } else {
            if (candGear !== pendingGear) {
              pendingGear = candGear;
              pendingStartTime = t;
            }
            const elapsedMs = (t - pendingStartTime) * 1000.0;
            if (elapsedMs >= gearParams.latchHoldMs) {
              latchedGear = pendingGear;
            }
            finalGear = latchedGear;
          }
        }

        if (t >= tMin && t <= tMax) {
          filteredTimes.push(t);
          rawRatios.push(isGatedActive ? ratio : null);
          smoothedRatios.push(currentEma);
          estimatedGears.push(finalGear);
          groundTruthGears.push(gt);
          filteredSpeeds.push(g.speed_kph[i] || 0);
          filteredRpms.push(g.rpm[i] || 0);
          const dt = (i > 0) ? Math.min(0.2, Math.max(0.01, t - g.times[i-1])) : 0.1;
          gearTimeCounts[finalGear] = (gearTimeCounts[finalGear] || 0) + dt;
        }
      }

      const activePct = totalEvalCount > 0 ? (activeCount / totalEvalCount * 100).toFixed(1) : '0.0';
      document.getElementById('sc-gear-active').innerText = activePct + '%';
      document.getElementById('sc-gear-time-1').innerText = (gearTimeCounts[1] || 0).toFixed(1) + 's';
      document.getElementById('sc-gear-time-2').innerText = (gearTimeCounts[2] || 0).toFixed(1) + 's';
      document.getElementById('sc-gear-time-3').innerText = (gearTimeCounts[3] || 0).toFixed(1) + 's';
      document.getElementById('sc-gear-time-4').innerText = (gearTimeCounts[4] || 0).toFixed(1) + 's';
      document.getElementById('sc-gear-time-5').innerText = (gearTimeCounts[5] || 0).toFixed(1) + 's';

      // Compute Glitch & Stability Scorecards
      let dropouts = 0;
      let chatterEvents = 0;
      let phantomShifts = 0;

      const m = filteredTimes.length;
      if (m > 2) {
        const segments = [];
        let curGear = estimatedGears[0];
        let curStart = 0;
        for (let i = 1; i < m; i++) {
          if (estimatedGears[i] !== curGear) {
            segments.push({
              gear: curGear,
              startIdx: curStart,
              endIdx: i - 1,
              startTime: filteredTimes[curStart],
              endTime: filteredTimes[i - 1],
              duration: filteredTimes[i - 1] - filteredTimes[curStart]
            });
            curGear = estimatedGears[i];
            curStart = i;
          }
        }
        segments.push({
          gear: curGear,
          startIdx: curStart,
          endIdx: m - 1,
          startTime: filteredTimes[curStart],
          endTime: filteredTimes[m - 1],
          duration: filteredTimes[m - 1] - filteredTimes[curStart]
        });

        const dropoutTimes = [];
        const dropoutGears = [];
        const dropoutTexts = [];

        const chatterTimes = [];
        const chatterGears = [];
        const chatterTexts = [];

        const phantomTimes = [];
        const phantomGears = [];
        const phantomTexts = [];

        for (let s = 0; s < segments.length; s++) {
          const seg = segments[s];
          if (seg.gear > 0 && seg.duration < 0.30) {
            chatterEvents++;
            chatterTimes.push(seg.startTime);
            chatterGears.push(seg.gear);
            chatterTexts.push(`Chatter: ${seg.gear}G dwell only ${(seg.duration * 1000).toFixed(0)} ms`);
          }
          if (seg.gear === 0 && s > 0 && s < segments.length - 1) {
            const prevSeg = segments[s - 1];
            const nextSeg = segments[s + 1];
            if (prevSeg.gear > 0 && prevSeg.gear === nextSeg.gear && seg.duration < 0.45) {
              const avgSpeed = (filteredSpeeds[seg.startIdx] + filteredSpeeds[seg.endIdx]) / 2.0;
              if (avgSpeed >= 20.0) {
                dropouts++;
                dropoutTimes.push(seg.startTime);
                dropoutGears.push(0);
                dropoutTexts.push(`Dropout: ${prevSeg.gear}G -> N -> ${nextSeg.gear}G in ${(seg.duration * 1000).toFixed(0)} ms @ ${avgSpeed.toFixed(1)} km/h`);
              }
            }
          }
        }

        for (let s = 1; s < segments.length; s++) {
          const prevSeg = segments[s - 1];
          const curSeg = segments[s];
          if (curSeg.gear > prevSeg.gear && prevSeg.gear > 0) {
            const idx = curSeg.startIdx;
            const backIdx = Math.max(0, idx - 4);
            const dt = filteredTimes[idx] - filteredTimes[backIdx];
            if (dt > 0.05) {
              const dRpm = (filteredRpms[idx] - filteredRpms[backIdx]) / dt;
              const dSpeed = (filteredSpeeds[idx] - filteredSpeeds[backIdx]) / dt;
              if (dRpm < -1200.0 && dSpeed < 1.0) {
                phantomShifts++;
                phantomTimes.push(filteredTimes[idx]);
                phantomGears.push(curSeg.gear);
                phantomTexts.push(`Phantom Shift: ${prevSeg.gear}G -> ${curSeg.gear}G during engine drop (${dRpm.toFixed(0)} RPM/s)`);
              }
            }
          }
        }
      }

      const glitchScore = Math.max(0, Math.min(100, Math.round(100 - (2.5 * dropouts + 1.0 * chatterEvents + 5.0 * phantomShifts))));
      const glitchEl = document.getElementById('sc-gear-glitch-score');
      if (glitchEl) {
        glitchEl.innerText = glitchScore + '%';
        glitchEl.className = 'sc-val ' + (glitchScore >= 90 ? 'good' : (glitchScore >= 70 ? 'warn' : 'bad'));
      }
      const dropEl = document.getElementById('sc-gear-dropouts');
      if (dropEl) {
        dropEl.innerText = dropouts;
        dropEl.className = 'sc-val ' + (dropouts === 0 ? 'good' : 'warn');
      }
      const chatEl = document.getElementById('sc-gear-chatter');
      if (chatEl) {
        chatEl.innerText = chatterEvents;
        chatEl.className = 'sc-val ' + (chatterEvents === 0 ? 'good' : (chatterEvents < 5 ? 'warn' : 'bad'));
      }
      const phanEl = document.getElementById('sc-gear-phantoms');
      if (phanEl) {
        phanEl.innerText = phantomShifts;
        phanEl.className = 'sc-val ' + (phantomShifts === 0 ? 'good' : 'bad');
      }

      const theme = getPlotlyLayoutTheme();

      const histShapes = [];
      const gearColors = ['#94a3b8', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'];
      for (let gi = 0; gi < 5; gi++) {
        const nom = gearParams.r[gi];
        let span = gearParams.tol;
        if (gi > 0) span = Math.min(span, (nom - gearParams.r[gi - 1]) * 0.48);
        if (gi < 4) span = Math.min(span, (gearParams.r[gi + 1] - nom) * 0.48);
        histShapes.push({
          type: 'rect',
          xref: 'x',
          yref: 'paper',
          x0: nom - span,
          x1: nom + span,
          y0: 0,
          y1: 1,
          fillcolor: gearColors[gi + 1],
          opacity: 0.2,
          line: { width: 1, color: gearColors[gi + 1] }
        });
      }

      Plotly.react('plot-gear-hist', [
        {
          x: histRatios,
          type: 'histogram',
          nbinsx: 120,
          marker: { color: '#3b82f6' },
          name: 'Ratio Samples'
        }
      ], {
        ...theme,
        margin: { t: 30, b: 35, l: 50, r: 25 },
        title: { text: 'Gear Ratio Distribution & Calibrated Bands (5 Forward Gears + N)', font: { size: 12 } },
        xaxis: { title: 'Speed Freq / RPM Freq Ratio', gridcolor: theme.gridcolor, range: [0.0, 7.0] },
        yaxis: { title: 'Samples', gridcolor: theme.gridcolor },
        shapes: histShapes,
        showlegend: false
      }, { responsive: true });

      const dynTraces = [
        {
          x: filteredTimes,
          y: filteredSpeeds,
          mode: 'lines',
          name: 'ITF_speed_kph',
          line: { color: '#3b82f6', width: 2 },
          yaxis: 'y'
        },
        {
          x: filteredTimes,
          y: filteredRpms,
          mode: 'lines',
          name: 'ITF_rpm',
          line: { color: '#f59e0b', width: 1.8 },
          yaxis: 'y2'
        }
      ];

      Plotly.react('plot-gear-dynamics', dynTraces, {
        ...theme,
        margin: { t: 25, b: 25, l: 50, r: 50 },
        title: { text: 'Synchronized Vehicle Dynamics (ITF_speed_kph & ITF_rpm)', font: { size: 12 } },
        xaxis: { title: '', gridcolor: theme.gridcolor, range: [tMin, tMax] },
        yaxis: {
          title: 'Speed (km/h)',
          titlefont: { color: '#3b82f6', size: 11 },
          tickfont: { color: '#3b82f6', size: 10 },
          gridcolor: theme.gridcolor
        },
        yaxis2: {
          title: 'RPM',
          titlefont: { color: '#f59e0b', size: 11 },
          tickfont: { color: '#f59e0b', size: 10 },
          overlaying: 'y',
          side: 'right',
          gridcolor: 'transparent'
        },
        legend: { orientation: 'h', y: 1.15, x: 0 }
      }, { responsive: true });

      const dynEl = document.getElementById('plot-gear-dynamics');
      if (dynEl && !dynEl._hasListeners) {
        dynEl._hasListeners = true;
        dynEl.on('plotly_relayout', handlePlotRelayout);
        dynEl.on('plotly_hover', handlePlotHover);
      }

      const timeTraces = [
        {
          x: filteredTimes,
          y: rawRatios,
          mode: 'markers',
          name: 'Raw Ratio',
          marker: { size: 3, color: '#64748b', opacity: 0.6 },
          yaxis: 'y'
        },
        {
          x: filteredTimes,
          y: smoothedRatios,
          mode: 'lines',
          name: 'Smoothed Ratio (EMA)',
          line: { color: '#3b82f6', width: 2 },
          yaxis: 'y'
        },
        {
          x: filteredTimes,
          y: estimatedGears,
          mode: 'lines',
          name: 'Estimated Gear',
          line: { color: '#10b981', width: 2, shape: 'hv' },
          yaxis: 'y2'
        }
      ];

      if (gearParams.showGroundTruth) {
        timeTraces.push({
          x: filteredTimes,
          y: groundTruthGears,
          mode: 'lines',
          name: 'ITF_gear_position_ST',
          line: { color: '#f59e0b', width: 1.5, dash: 'dot', shape: 'hv' },
          yaxis: 'y2'
        });
      }

      if (dropoutTimes.length > 0) {
        timeTraces.push({
          x: dropoutTimes,
          y: dropoutGears,
          mode: 'markers',
          name: `🔴 Dropout (${dropoutTimes.length})`,
          text: dropoutTexts,
          hoverinfo: 'text+x',
          marker: { symbol: 'circle', size: 10, color: '#ef4444', line: { color: '#ffffff', width: 1.5 } },
          yaxis: 'y2'
        });
      }
      if (chatterTimes.length > 0) {
        timeTraces.push({
          x: chatterTimes,
          y: chatterGears,
          mode: 'markers',
          name: `🟠 Chatter (${chatterTimes.length})`,
          text: chatterTexts,
          hoverinfo: 'text+x',
          marker: { symbol: 'diamond', size: 10, color: '#f97316', line: { color: '#ffffff', width: 1.5 } },
          yaxis: 'y2'
        });
      }
      if (phantomTimes.length > 0) {
        timeTraces.push({
          x: phantomTimes,
          y: phantomGears,
          mode: 'markers',
          name: `🟣 Phantom (${phantomTimes.length})`,
          text: phantomTexts,
          hoverinfo: 'text+x',
          marker: { symbol: 'triangle-up', size: 12, color: '#a855f7', line: { color: '#ffffff', width: 1.5 } },
          yaxis: 'y2'
        });
      }

      Plotly.react('plot-gear-time', timeTraces, {
        ...theme,
        margin: { t: 30, b: 35, l: 50, r: 50 },
        title: { text: 'Ratio Smoothing & Classified Gear Trace', font: { size: 12 } },
        xaxis: { title: 'Time (s)', gridcolor: theme.gridcolor, range: [tMin, tMax] },
        yaxis: { title: 'Ratio', gridcolor: theme.gridcolor, domain: [0.38, 1.0] },
        yaxis2: {
          title: 'Gear',
          gridcolor: theme.gridcolor,
          domain: [0.0, 0.30],
          tickvals: [0, 1, 2, 3, 4, 5],
          ticktext: ['N', '1st', '2nd', '3rd', '4th', '5th']
        },
        legend: { orientation: 'h', y: 1.1, x: 0 }
      }, { responsive: true });

      const timeEl = document.getElementById('plot-gear-time');
      if (timeEl && !timeEl._hasListeners) {
        timeEl._hasListeners = true;
        timeEl.on('plotly_relayout', handlePlotRelayout);
        timeEl.on('plotly_hover', handlePlotHover);
      }

      currentGearData = {
        times: filteredTimes,
        speeds: filteredSpeeds,
        rpms: filteredRpms,
        ratios: smoothedRatios,
        rawRatios: rawRatios,
        gears: estimatedGears
      };
      initTunerReplayer();
    }

    // =========================================================================
    // TUNER DRIVE REPLAYER & SIMULATED GEAR GAUGE
    // =========================================================================
    let currentGearData = null;
    const tunerReplayer = {
      playing: false,
      timer: null,
      lastTimestamp: 0,
      currentTime: 0,
      minTime: 0,
      maxTime: 0,
      speed: 1.0
    };

    function ensureTunerNeedles() {
      ['plot-gear-dynamics', 'plot-gear-time'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (!el.querySelector(`.timeline-needle-${id}`)) {
          const needle = document.createElement('div');
          needle.className = `timeline-needle timeline-needle-${id}`;
          needle.style.display = 'none';
          el.appendChild(needle);
        }
      });
    }

    function initTunerReplayer() {
      if (!currentGearData || !currentGearData.times || currentGearData.times.length === 0) return;
      ensureTunerNeedles();
      const times = currentGearData.times;
      tunerReplayer.minTime = times[0];
      tunerReplayer.maxTime = times[times.length - 1];

      const scrub = document.getElementById('slider-replay-scrub');
      if (scrub) {
        scrub.min = tunerReplayer.minTime;
        scrub.max = tunerReplayer.maxTime;
        scrub.step = Math.max(0.01, (tunerReplayer.maxTime - tunerReplayer.minTime) / 3500);
        if (tunerReplayer.currentTime < tunerReplayer.minTime || tunerReplayer.currentTime > tunerReplayer.maxTime) {
          tunerReplayer.currentTime = tunerReplayer.minTime;
        }
        scrub.value = tunerReplayer.currentTime;
      }
      updateTunerReplayDisplay(tunerReplayer.currentTime);
    }

    function updateTunerReplayDisplay(t) {
      tunerReplayer.currentTime = t;
      const scrub = document.getElementById('slider-replay-scrub');
      if (scrub && Math.abs(parseFloat(scrub.value) - t) > 0.05) {
        scrub.value = t;
      }
      const lbl = document.getElementById('lbl-replay-time');
      if (lbl) {
        lbl.textContent = `${t.toFixed(2)}s / ${tunerReplayer.maxTime.toFixed(2)}s`;
      }

      // Update Plotly needles on dynamics and gear time
      ['plot-gear-dynamics', 'plot-gear-time'].forEach(id => {
        const el = document.getElementById(id);
        if (!el || !el._fullLayout || !el._fullLayout.xaxis) return;
        const needle = el.querySelector(`.timeline-needle-${id}`);
        if (!needle) return;

        const xaxis = el._fullLayout.xaxis;
        if (t < xaxis.range[0] || t > xaxis.range[1]) {
          needle.style.display = 'none';
          return;
        }
        const leftPx = xaxis._offset + xaxis.d2p(t);
        needle.style.left = `${leftPx}px`;
        needle.style.top = `${el._fullLayout.margin.t}px`;
        needle.style.height = `${el._fullLayout._size.h}px`;
        needle.style.display = 'block';
      });

      // Update vehicle marker on GPS map
      updateVehicleMarker(t);

      // Update Simulated Gear Gauge Pod
      if (!currentGearData || !currentGearData.times || currentGearData.times.length === 0) return;
      const d = currentGearData;
      let low = 0, high = d.times.length - 1;
      let idx = 0;
      while (low <= high) {
        const mid = (low + high) >> 1;
        if (d.times[mid] === t) { idx = mid; break; }
        else if (d.times[mid] < t) { idx = mid; low = mid + 1; }
        else high = mid - 1;
      }

      const spd = d.speeds[idx] !== undefined ? d.speeds[idx] : 0;
      const rpm = d.rpms[idx] !== undefined ? d.rpms[idx] : 0;
      const ratio = (d.ratios[idx] !== null && d.ratios[idx] !== undefined) ? d.ratios[idx] : (d.rawRatios[idx] || 0);
      const gear = d.gears[idx] !== undefined ? d.gears[idx] : 0;

      const gEl = document.getElementById('pod-tuner-gear');
      if (gEl) {
        gEl.textContent = gear === 0 ? 'N' : String(gear);
        gEl.style.color = gear === 0 ? 'var(--text-muted)' : '#3b82f6';
      }
      const sEl = document.getElementById('pod-tuner-speed');
      if (sEl) sEl.textContent = `${spd.toFixed(1)} km/h`;
      const rEl = document.getElementById('pod-tuner-rpm');
      if (rEl) rEl.textContent = `${Math.round(rpm)} RPM`;
      const ratEl = document.getElementById('pod-tuner-ratio');
      if (ratEl) ratEl.textContent = ratio > 0.01 ? ratio.toFixed(2) : '--';
      const statEl = document.getElementById('pod-tuner-status');
      if (statEl) {
        statEl.textContent = gear === 0 ? 'NEUTRAL/COAST' : 'LATCHED';
        statEl.className = `model-badge ${gear === 0 ? 'badge-neutral' : 'badge-latched'}`;
      }
    }

    function playTunerStep(timestamp) {
      if (!tunerReplayer.playing) return;
      if (!tunerReplayer.lastTimestamp) tunerReplayer.lastTimestamp = timestamp;
      const dt = (timestamp - tunerReplayer.lastTimestamp) / 1000.0;
      tunerReplayer.lastTimestamp = timestamp;

      let nextT = tunerReplayer.currentTime + dt * tunerReplayer.speed;
      if (nextT >= tunerReplayer.maxTime) {
        nextT = tunerReplayer.maxTime;
        updateTunerReplayDisplay(nextT);
        stopTunerPlayback();
        return;
      }
      updateTunerReplayDisplay(nextT);
      tunerReplayer.timer = requestAnimationFrame(playTunerStep);
    }

    function startTunerPlayback() {
      if (tunerReplayer.currentTime >= tunerReplayer.maxTime) {
        tunerReplayer.currentTime = tunerReplayer.minTime;
      }
      tunerReplayer.playing = true;
      tunerReplayer.lastTimestamp = 0;
      const btn = document.getElementById('btn-replay-play');
      if (btn) btn.textContent = '⏸ Pause';
      tunerReplayer.timer = requestAnimationFrame(playTunerStep);
    }

    function stopTunerPlayback() {
      tunerReplayer.playing = false;
      if (tunerReplayer.timer) {
        cancelAnimationFrame(tunerReplayer.timer);
        tunerReplayer.timer = null;
      }
      const btn = document.getElementById('btn-replay-play');
      if (btn) btn.textContent = '▶ Play';
    }

    // Replayer controls setup
    const btnPlay = document.getElementById('btn-replay-play');
    if (btnPlay) {
      btnPlay.addEventListener('click', () => {
        if (tunerReplayer.playing) stopTunerPlayback();
        else startTunerPlayback();
      });
    }

    const btnReset = document.getElementById('btn-replay-reset');
    if (btnReset) {
      btnReset.addEventListener('click', () => {
        stopTunerPlayback();
        updateTunerReplayDisplay(tunerReplayer.minTime);
      });
    }

    const btnPrev = document.getElementById('btn-replay-prev');
    if (btnPrev) {
      btnPrev.addEventListener('click', () => {
        stopTunerPlayback();
        updateTunerReplayDisplay(Math.max(tunerReplayer.minTime, tunerReplayer.currentTime - 0.2));
      });
    }

    const btnNext = document.getElementById('btn-replay-next');
    if (btnNext) {
      btnNext.addEventListener('click', () => {
        stopTunerPlayback();
        updateTunerReplayDisplay(Math.min(tunerReplayer.maxTime, tunerReplayer.currentTime + 0.2));
      });
    }

    const selSpeed = document.getElementById('select-replay-speed');
    if (selSpeed) {
      selSpeed.addEventListener('change', (e) => {
        tunerReplayer.speed = parseFloat(e.target.value) || 1.0;
      });
    }

    const scrubSlider = document.getElementById('slider-replay-scrub');
    if (scrubSlider) {
      scrubSlider.addEventListener('input', (e) => {
        stopTunerPlayback();
        updateTunerReplayDisplay(parseFloat(e.target.value));
      });
    }

    ['plot-gear-dynamics', 'plot-gear-time'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.on('plotly_click', (d) => {
          if (d && d.points && d.points[0] && d.points[0].x !== undefined) {
            stopTunerPlayback();
            updateTunerReplayDisplay(d.points[0].x);
          }
        });
      }
    });

    // TAB 2: FUEL LEVEL FILTERING LOGIC
    const fuelParams = {
      algo: 'SMA',
      window: 30,
      quant: 1.0
    };
    let fuelUserYRange = null;

    function loadFuelSettings() {
      const saved = localStorage.getItem('minigauge_fuel_params');
      if (saved) {
        try { Object.assign(fuelParams, JSON.parse(saved)); } catch(e){}
      }
      if (fuelParams.algo === 'EMA') {
        document.getElementById('radio-fuel-ema').checked = true;
        document.getElementById('lbl-fuel-param').innerText = 'Time Constant (τ)';
      } else {
        document.getElementById('radio-fuel-sma').checked = true;
        document.getElementById('lbl-fuel-param').innerText = 'Time Window';
      }
      document.getElementById('slider-fuel-window').value = fuelParams.window;
      document.getElementById('val-fuel-window').innerText = fuelParams.window + ' s';
      document.getElementById('select-fuel-quant').value = fuelParams.quant.toString();
    }
    loadFuelSettings();

    function saveFuelSettings() {
      localStorage.setItem('minigauge_fuel_params', JSON.stringify(fuelParams));
    }

    document.querySelectorAll('input[name="fuel-algo"]').forEach(r => {
      r.addEventListener('change', (e) => {
        fuelParams.algo = e.target.value;
        document.getElementById('lbl-fuel-param').innerText = fuelParams.algo === 'EMA' ? 'Time Constant (τ)' : 'Time Window';
        saveFuelSettings();
        computeAndRenderFuel();
      });
    });

    document.getElementById('slider-fuel-window').addEventListener('input', (e) => {
      fuelParams.window = parseInt(e.target.value);
      document.getElementById('val-fuel-window').innerText = fuelParams.window + ' s';
      saveFuelSettings();
      computeAndRenderFuel();
    });

    document.getElementById('select-fuel-quant').addEventListener('change', (e) => {
      fuelParams.quant = parseFloat(e.target.value);
      saveFuelSettings();
      computeAndRenderFuel();
    });

    document.getElementById('btn-reset-fuel-defaults').addEventListener('click', () => {
      fuelParams.algo = 'SMA';
      fuelParams.window = 30;
      fuelParams.quant = 1.0;
      fuelUserYRange = null;
      saveFuelSettings();
      loadFuelSettings();
      computeAndRenderFuel();
    });

    function computeAndRenderFuel() {
      if (!algoData || !algoData.fuel) return;
      const f = algoData.fuel;
      const tMin = timeRange[0] !== null ? timeRange[0] : 0;
      const tMax = timeRange[1] !== null ? timeRange[1] : algoData.duration_s;

      const n = f.times.length;
      if (n === 0) return;

      const simTimes = [];
      const simValues = [];
      const rawValues = [];

      if (fuelParams.algo === 'SMA') {
        let windowSum = 0;
        let leftIdx = 0;
        for (let rightIdx = 0; rightIdx < n; rightIdx++) {
          const tRight = f.times[rightIdx];
          const vRight = f.unfiltered[rightIdx];
          windowSum += vRight;

          while (leftIdx < rightIdx && (tRight - f.times[leftIdx]) > fuelParams.window) {
            windowSum -= f.unfiltered[leftIdx];
            leftIdx++;
          }
          const count = rightIdx - leftIdx + 1;
          let val = windowSum / count;

          if (fuelParams.quant > 0) {
            val = Math.round(val / fuelParams.quant) * fuelParams.quant;
          }

          if (tRight >= tMin && tRight <= tMax) {
            simTimes.push(tRight);
            simValues.push(val);
            rawValues.push(vRight);
          }
        }
      } else {
        let ema = f.unfiltered[0];
        for (let i = 0; i < n; i++) {
          const t = f.times[i];
          const dt = i > 0 ? (t - f.times[i-1]) : 0.2;
          const tau = Math.max(0.5, fuelParams.window);
          const alpha = dt / (tau + dt);
          ema = alpha * f.unfiltered[i] + (1.0 - alpha) * ema;

          let val = ema;
          if (fuelParams.quant > 0) {
            val = Math.round(val / fuelParams.quant) * fuelParams.quant;
          }

          if (t >= tMin && t <= tMax) {
            simTimes.push(t);
            simValues.push(val);
            rawValues.push(f.unfiltered[i]);
          }
        }
      }

      const recTimes = [];
      const recValues = [];
      for (let i = 0; i < f.recorded_times.length; i++) {
        const t = f.recorded_times[i];
        if (t >= tMin && t <= tMax) {
          recTimes.push(t);
          recValues.push(f.recorded_pc[i]);
        }
      }

      const resTimes = [];
      const resDiffs = [];
      let sumAbsErr = 0;
      let sumSqErr = 0;
      let maxErr = 0;
      let compareCount = 0;

      for (let i = 0; i < recTimes.length; i++) {
        const t = recTimes[i];
        const rec = recValues[i];
        let low = 0, high = simTimes.length - 1;
        while (low <= high) {
          const mid = (low + high) >> 1;
          if (Math.abs(simTimes[mid] - t) < 0.25) {
            const diff = simValues[mid] - rec;
            resTimes.push(t);
            resDiffs.push(diff);
            const absD = Math.abs(diff);
            sumAbsErr += absD;
            sumSqErr += diff * diff;
            if (absD > maxErr) maxErr = absD;
            compareCount++;
            break;
          } else if (simTimes[mid] < t) {
            low = mid + 1;
          } else {
            high = mid - 1;
          }
        }
      }

      // Calculate jitter & slew rate for Simulated Filtered
      let simMaxSlew = 0.0;
      let simMaxJitter = 0.0;
      for (let i = 1; i < simValues.length; i++) {
        const dt = simTimes[i] - simTimes[i - 1];
        const dv = Math.abs(simValues[i] - simValues[i - 1]);
        if (dt > 0.001) {
          const rate = dv / dt;
          if (rate > simMaxSlew) simMaxSlew = rate;
        }
        if (dv > simMaxJitter) simMaxJitter = dv;
      }

      // Calculate jitter & slew rate for Measured Filtered
      let recMaxSlew = 0.0;
      let recMaxJitter = 0.0;
      for (let i = 1; i < recValues.length; i++) {
        const dt = recTimes[i] - recTimes[i - 1];
        const dv = Math.abs(recValues[i] - recValues[i - 1]);
        if (dt > 0.001) {
          const rate = dv / dt;
          if (rate > recMaxSlew) recMaxSlew = rate;
        }
        if (dv > recMaxJitter) recMaxJitter = dv;
      }

      // Update Scorecards
      const mae = compareCount > 0 ? (sumAbsErr / compareCount).toFixed(2) : '--';
      const rmse = compareCount > 0 ? Math.sqrt(sumSqErr / compareCount).toFixed(2) : '--';
      document.getElementById('sc-fuel-mae').innerText = mae + '%';
      document.getElementById('sc-fuel-rmse').innerText = rmse + '%';
      document.getElementById('sc-fuel-maxerr').innerText = maxErr.toFixed(2) + '%';
      document.getElementById('sc-fuel-sim-slew').innerText = simMaxSlew.toFixed(2) + ' %/s';
      document.getElementById('sc-fuel-sim-jitter').innerText = simMaxJitter.toFixed(2) + '%';
      document.getElementById('sc-fuel-meas-slew').innerText = recMaxSlew.toFixed(2) + ' %/s';
      document.getElementById('sc-fuel-meas-jitter').innerText = recMaxJitter.toFixed(2) + '%';
      document.getElementById('sc-fuel-samples').innerText = rawValues.length;

      // Dynamic autoscale calculation based on measured and simulated filtered level
      let minF = Infinity;
      let maxF = -Infinity;
      for (let i = 0; i < simValues.length; i++) {
        if (simValues[i] < minF) minF = simValues[i];
        if (simValues[i] > maxF) maxF = simValues[i];
      }
      for (let i = 0; i < recValues.length; i++) {
        if (recValues[i] < minF) minF = recValues[i];
        if (recValues[i] > maxF) maxF = recValues[i];
      }
      if (!isFinite(minF) || !isFinite(maxF)) {
        minF = 0;
        maxF = 100;
      }
      const spanF = Math.max(1.0, maxF - minF);
      const padF = Math.max(0.5, spanF * 0.15);
      const autoYRange = [
        Math.max(0, Math.floor((minF - padF) * 10) / 10),
        Math.min(100, Math.ceil((maxF + padF) * 10) / 10)
      ];

      const activeYRange = fuelUserYRange ? fuelUserYRange : autoYRange;

      const theme = getPlotlyLayoutTheme();

      Plotly.react('plot-fuel-main', [
        {
          x: simTimes,
          y: rawValues,
          mode: 'markers',
          name: 'Raw Unfiltered (DBG)',
          marker: { size: 3, color: '#64748b', opacity: 0.5 }
        },
        {
          x: simTimes,
          y: simValues,
          mode: 'lines',
          name: `Simulated Filter (${fuelParams.algo})`,
          line: { color: '#3b82f6', width: 2.5 }
        },
        {
          x: recTimes,
          y: recValues,
          mode: 'lines',
          name: 'Recorded Filtered (ITF)',
          line: { color: '#10b981', width: 2, dash: 'dash' }
        }
      ], {
        ...theme,
        uirevision: 'fuel_scale',
        margin: { t: 30, b: 35, l: 50, r: 25 },
        title: { text: `Fuel Level Comparison (Window: ${fuelParams.window}s, Quant: ${fuelParams.quant}%)`, font: { size: 12 } },
        xaxis: { title: 'Time (s)', gridcolor: theme.gridcolor, range: [tMin, tMax] },
        yaxis: { title: 'Fuel Level (%)', gridcolor: theme.gridcolor, range: activeYRange },
        legend: { orientation: 'h', y: 1.1, x: 0 }
      }, { responsive: true });

      const fuelEl = document.getElementById('plot-fuel-main');
      if (fuelEl && !fuelEl._hasRelayoutListener) {
        fuelEl._hasRelayoutListener = true;
        fuelEl.on('plotly_relayout', (ev) => {
          if (ev['yaxis.range[0]'] !== undefined && ev['yaxis.range[1]'] !== undefined) {
            fuelUserYRange = [ev['yaxis.range[0]'], ev['yaxis.range[1]']];
          } else if (ev['yaxis.autorange'] === true || ev['autosize'] === true) {
            fuelUserYRange = null;
            computeAndRenderFuel();
          }
          if (ev['xaxis.range[0]'] !== undefined && ev['xaxis.range[1]'] !== undefined) {
            handlePlotRelayout(ev);
          }
        });
        fuelEl.on('plotly_hover', handlePlotHover);
        fuelEl.on('plotly_doubleclick', () => {
          fuelUserYRange = null;
          computeAndRenderFuel();
        });
      }

      Plotly.react('plot-fuel-residual', [
        {
          x: resTimes,
          y: resDiffs,
          mode: 'lines',
          name: 'Residual (Simulated - Recorded)',
          line: { color: '#f59e0b', width: 1.5 }
        }
      ], {
        ...theme,
        margin: { t: 25, b: 35, l: 50, r: 25 },
        title: { text: 'Residual Error vs Recorded Level (Δ %)', font: { size: 11 } },
        xaxis: { title: 'Time (s)', gridcolor: theme.gridcolor, range: [tMin, tMax] },
        yaxis: { title: 'Error (%)', gridcolor: theme.gridcolor, zeroline: true, zerolinecolor: theme.zerolinecolor },
        showlegend: false
      }, { responsive: true });
    }

    // TAB 3: SPEED CORRECTION & ECE R39 CHECK LOGIC
    const speedParams = {
      gain: 1.000,
      offset: 0.0,
      requireGps: true,
      minEvalSpeed: 5.0
    };

    function loadSpeedSettings() {
      const saved = localStorage.getItem('minigauge_speed_params');
      if (saved) {
        try { Object.assign(speedParams, JSON.parse(saved)); } catch(e){}
      }
      document.getElementById('slider-speed-gain').value = speedParams.gain;
      document.getElementById('val-speed-gain').innerText = speedParams.gain.toFixed(3);
      document.getElementById('slider-speed-offset').value = speedParams.offset;
      document.getElementById('val-speed-offset').innerText = speedParams.offset.toFixed(1) + ' km/h';
      document.getElementById('chk-speed-require-gps').checked = speedParams.requireGps;
      document.getElementById('slider-speed-mineval').value = speedParams.minEvalSpeed;
      document.getElementById('val-speed-mineval').innerText = speedParams.minEvalSpeed.toFixed(1) + ' km/h';
    }
    loadSpeedSettings();

    function saveSpeedSettings() {
      localStorage.setItem('minigauge_speed_params', JSON.stringify(speedParams));
    }

    document.getElementById('slider-speed-gain').addEventListener('input', (e) => {
      speedParams.gain = parseFloat(e.target.value);
      document.getElementById('val-speed-gain').innerText = speedParams.gain.toFixed(3);
      saveSpeedSettings();
      computeAndRenderSpeed();
    });

    document.getElementById('slider-speed-offset').addEventListener('input', (e) => {
      speedParams.offset = parseFloat(e.target.value);
      document.getElementById('val-speed-offset').innerText = speedParams.offset.toFixed(1) + ' km/h';
      saveSpeedSettings();
      computeAndRenderSpeed();
    });

    document.getElementById('chk-speed-require-gps').addEventListener('change', (e) => {
      speedParams.requireGps = e.target.checked;
      saveSpeedSettings();
      computeAndRenderSpeed();
    });

    document.getElementById('slider-speed-mineval').addEventListener('input', (e) => {
      speedParams.minEvalSpeed = parseFloat(e.target.value);
      document.getElementById('val-speed-mineval').innerText = speedParams.minEvalSpeed.toFixed(1) + ' km/h';
      saveSpeedSettings();
      computeAndRenderSpeed();
    });

    document.getElementById('btn-reset-speed-defaults').addEventListener('click', () => {
      speedParams.gain = 1.000;
      speedParams.offset = 0.0;
      speedParams.requireGps = true;
      speedParams.minEvalSpeed = 5.0;
      saveSpeedSettings();
      loadSpeedSettings();
      computeAndRenderSpeed();
    });

    document.getElementById('btn-auto-opt-speed').addEventListener('click', () => {
      if (!algoData || !algoData.speed) return;
      const spd = algoData.speed;
      if (spd.gps_times.length === 0 || spd.times.length === 0) {
        alert("No GPS data found in this log.");
        return;
      }

      const pairs = [];
      let indIdx = 0;
      for (let i = 0; i < spd.gps_times.length; i++) {
        const tg = spd.gps_times[i];
        const vGps = spd.gps_speed[i];
        const fixOk = (!speedParams.requireGps || (spd.gps_valid[i] === 1 && spd.gps_fix_st[i] >= 3));

        if (fixOk && vGps >= speedParams.minEvalSpeed) {
          while (indIdx < spd.times.length - 1 && spd.times[indIdx] < tg) {
            indIdx++;
          }
          if (Math.abs(spd.times[indIdx] - tg) < 0.2) {
            pairs.push({ vGps: vGps, vInd: spd.ind_speed[indIdx] });
          }
        }
      }

      if (pairs.length < 50) {
        alert("Not enough paired GPS points to run automated optimizer.");
        return;
      }

      let bestGain = 1.0;
      let bestOffset = 0.0;
      let bestCompliance = -1;
      let minExcessOverread = 999999;

      for (let k = 0.90; k <= 1.20; k += 0.005) {
        for (let c = -2.0; c <= 6.0; c += 0.5) {
          let compliantCount = 0;
          let totalOverread = 0;
          for (let p of pairs) {
            const vCorr = k * p.vInd + c;
            const eceUpper = 1.10 * p.vGps + 4.0;
            if (vCorr >= p.vGps && vCorr <= eceUpper) {
              compliantCount++;
            }
            totalOverread += Math.max(0, vCorr - p.vGps);
          }
          const rate = compliantCount / pairs.length;
          if (rate > bestCompliance || (rate === bestCompliance && totalOverread < minExcessOverread)) {
            bestCompliance = rate;
            bestGain = k;
            bestOffset = c;
            minExcessOverread = totalOverread;
          }
        }
      }

      speedParams.gain = parseFloat(bestGain.toFixed(3));
      speedParams.offset = parseFloat(bestOffset.toFixed(1));
      saveSpeedSettings();
      loadSpeedSettings();
      computeAndRenderSpeed();
      alert(`Optimized parameters:\nGain k = ${speedParams.gain}\nOffset c = ${speedParams.offset} km/h\nECE R39 Compliance: ${(bestCompliance * 100).toFixed(1)}%`);
    });

    function computeAndRenderSpeed() {
      if (!algoData || !algoData.speed) return;
      const spd = algoData.speed;
      const tMin = timeRange[0] !== null ? timeRange[0] : 0;
      const tMax = timeRange[1] !== null ? timeRange[1] : algoData.duration_s;

      const indTimes = [];
      const corrSpeeds = [];
      for (let i = 0; i < spd.times.length; i++) {
        const t = spd.times[i];
        if (t >= tMin && t <= tMax) {
          indTimes.push(t);
          corrSpeeds.push(speedParams.gain * spd.ind_speed[i] + speedParams.offset);
        }
      }

      const gpsTimes = [];
      const gpsSpeeds = [];
      const eceUpper = [];
      const pairedDeltaTimes = [];
      const speedDeltas = [];
      const violationTimes = [];
      const violationValues = [];

      let compliantCount = 0;
      let geGpsCount = 0;
      let evalSampleCount = 0;
      let maxUnderread = 0;
      let maxOverread = 0;
      let sumDelta = 0;

      let indIdx = 0;
      for (let i = 0; i < spd.gps_times.length; i++) {
        const t = spd.gps_times[i];
        const vGps = spd.gps_speed[i];
        const fixOk = (!speedParams.requireGps || (spd.gps_valid[i] === 1 && spd.gps_fix_st[i] >= 3));

        if (t >= tMin && t <= tMax) {
          if (fixOk) {
            gpsTimes.push(t);
            gpsSpeeds.push(vGps);
            const maxAllowed = 1.10 * vGps + 4.0;
            eceUpper.push(maxAllowed);

            while (indIdx < indTimes.length - 1 && indTimes[indIdx] < t) {
              indIdx++;
            }
            if (indIdx < indTimes.length && Math.abs(indTimes[indIdx] - t) < 0.25) {
              const vCorr = corrSpeeds[indIdx];
              const delta = vCorr - vGps;
              pairedDeltaTimes.push(t);
              speedDeltas.push(delta);

              if (vGps >= speedParams.minEvalSpeed) {
                evalSampleCount++;
                sumDelta += delta;
                if (vCorr >= vGps) geGpsCount++;
                if (vCorr >= vGps && vCorr <= maxAllowed) {
                  compliantCount++;
                } else {
                  violationTimes.push(t);
                  violationValues.push(vCorr);
                }
                if (delta < 0 && Math.abs(delta) > maxUnderread) maxUnderread = Math.abs(delta);
                if (delta > 0 && delta > maxOverread) maxOverread = delta;
              }
            }
          }
        }
      }

      const eceRate = evalSampleCount > 0 ? (compliantCount / evalSampleCount * 100).toFixed(1) : '--';
      const geRate = evalSampleCount > 0 ? (geGpsCount / evalSampleCount * 100).toFixed(1) : '--';
      const avgDelta = evalSampleCount > 0 ? (sumDelta / evalSampleCount).toFixed(2) : '--';

      const scEce = document.getElementById('sc-speed-ece');
      scEce.innerText = eceRate + '%';
      scEce.className = 'sc-val ' + (parseFloat(eceRate) >= 95 ? 'good' : 'warn');

      const scGe = document.getElementById('sc-speed-ge-rate');
      scGe.innerText = geRate + '%';
      scGe.className = 'sc-val ' + (parseFloat(geRate) >= 98 ? 'good' : 'bad');

      document.getElementById('sc-speed-maxunder').innerText = (maxUnderread > 0 ? '-' : '') + maxUnderread.toFixed(1) + ' km/h';
      document.getElementById('sc-speed-maxover').innerText = '+' + maxOverread.toFixed(1) + ' km/h';
      document.getElementById('sc-speed-avgdelta').innerText = (avgDelta !== '--' ? (avgDelta > 0 ? '+' : '') + avgDelta : '--') + ' km/h';

      const theme = getPlotlyLayoutTheme();

      Plotly.react('plot-speed-main', [
        {
          x: gpsTimes,
          y: gpsSpeeds,
          mode: 'lines',
          name: 'True GPS Speed (Lower Limit)',
          line: { color: '#10b981', width: 2 }
        },
        {
          x: gpsTimes,
          y: eceUpper,
          mode: 'lines',
          name: 'ECE R39 Max (1.1·V + 4)',
          line: { color: '#059669', width: 1.5, dash: 'dash' },
          fill: 'tonexty',
          fillcolor: 'rgba(16, 185, 129, 0.12)'
        },
        {
          x: indTimes,
          y: corrSpeeds,
          mode: 'lines',
          name: 'Corrected Speed (V_corr)',
          line: { color: '#3b82f6', width: 2.5 }
        },
        {
          x: violationTimes,
          y: violationValues,
          mode: 'markers',
          name: 'ECE Violation',
          marker: { size: 5, color: '#ef4444', symbol: 'x' }
        }
      ], {
        ...theme,
        margin: { t: 30, b: 35, l: 50, r: 25 },
        title: { text: `ECE R39 Speed Compliance Corridor (k = ${speedParams.gain}, c = ${speedParams.offset} km/h)`, font: { size: 12 } },
        xaxis: { title: 'Time (s)', gridcolor: theme.gridcolor, range: [tMin, tMax] },
        yaxis: { title: 'Speed (km/h)', gridcolor: theme.gridcolor },
        legend: { orientation: 'h', y: 1.1, x: 0 }
      }, { responsive: true });

      Plotly.react('plot-speed-delta', [
        {
          x: pairedDeltaTimes,
          y: speedDeltas,
          mode: 'lines',
          name: 'Delta (V_corr - V_gps)',
          line: { color: '#8b5cf6', width: 1.5 }
        }
      ], {
        ...theme,
        margin: { t: 25, b: 35, l: 50, r: 25 },
        title: { text: 'Speed Error Delta (V_corr - V_gps) km/h', font: { size: 11 } },
        xaxis: { title: 'Time (s)', gridcolor: theme.gridcolor, range: [tMin, tMax] },
        yaxis: { title: 'Delta (km/h)', gridcolor: theme.gridcolor, zeroline: true, zerolinecolor: '#ef4444' },
        showlegend: false
      }, { responsive: true });

      const speedEl = document.getElementById('plot-speed-main');
      if (speedEl && !speedEl._hasListeners) {
        speedEl._hasListeners = true;
        speedEl.on('plotly_relayout', handlePlotRelayout);
        speedEl.on('plotly_hover', handlePlotHover);
      }
    }

    // TAB 4: SIGNAL & MESSAGE ANALYTICS LOGIC
    let expandedMessages = new Set();
    let analyticsSortCol = 'can_id';
    let analyticsSortAsc = true;

    document.getElementById('btn-export-csv').addEventListener('click', () => {
      if (!currentLog) return;
      window.location.href = `/api/export_analytics?file=${encodeURIComponent(currentLog)}`;
    });

    document.getElementById('analytics-search').addEventListener('input', () => {
      renderAnalyticsTable();
    });

    document.getElementById('btn-expand-all').addEventListener('click', () => {
      if (!analyticsData) return;
      analyticsData.messages.forEach(m => expandedMessages.add(m.name));
      renderAnalyticsTable();
    });

    document.getElementById('btn-collapse-all').addEventListener('click', () => {
      expandedMessages.clear();
      renderAnalyticsTable();
    });

    document.querySelectorAll('table.analytics-table th').forEach(th => {
      th.addEventListener('click', () => {
        const col = th.getAttribute('data-sort');
        if (!col) return;
        if (analyticsSortCol === col) {
          analyticsSortAsc = !analyticsSortAsc;
        } else {
          analyticsSortCol = col;
          analyticsSortAsc = true;
        }
        renderAnalyticsTable();
      });
    });

    function renderAnalyticsTable() {
      if (!analyticsData) return;
      const tbody = document.getElementById('analytics-tbody');
      const query = document.getElementById('analytics-search').value.toLowerCase().trim();

      const sigMap = {};
      analyticsData.signals.forEach(s => {
        sigMap[s.message] = sigMap[s.message] || [];
        sigMap[s.message].push(s);
      });

      let msgs = [...analyticsData.messages];

      msgs.sort((a, b) => {
        let valA = a[analyticsSortCol] !== undefined ? a[analyticsSortCol] : a.name;
        let valB = b[analyticsSortCol] !== undefined ? b[analyticsSortCol] : b.name;
        if (analyticsSortCol === 'can_id') {
          valA = a.can_id_dec;
          valB = b.can_id_dec;
        } else if (analyticsSortCol === 'nominal') {
          valA = a.nominal_ms;
          valB = b.nominal_ms;
        } else if (analyticsSortCol === 'avg') {
          valA = a.avg_ms;
          valB = b.avg_ms;
        } else if (analyticsSortCol === 'jitter') {
          valA = a.std_ms;
          valB = b.std_ms;
        } else if (analyticsSortCol === 'slew') {
          valA = a.loss_pct;
          valB = b.loss_pct;
        }
        if (valA < valB) return analyticsSortAsc ? -1 : 1;
        if (valA > valB) return analyticsSortAsc ? 1 : -1;
        return 0;
      });

      let html = '';
      msgs.forEach(m => {
        const childSignals = sigMap[m.name] || [];
        const msgMatch = m.name.toLowerCase().includes(query) || m.can_id_hex.toLowerCase().includes(query);
        const matchingSigs = childSignals.filter(s => s.name.toLowerCase().includes(query));

        if (query && !msgMatch && matchingSigs.length === 0) {
          return;
        }

        const isExpanded = expandedMessages.has(m.name) || (query && matchingSigs.length > 0);
        const toggleIcon = isExpanded ? '▼' : '▶';

        const lossBadge = m.loss_pct > 1.0 ? `<span class="badge-pill badge-err">${m.loss_pct}% loss</span>` :
                          (m.loss_pct > 0 ? `<span class="badge-pill badge-warn">${m.loss_pct}%</span>` :
                          `<span class="badge-pill badge-ok">0%</span>`);

        html += `
          <tr class="msg-row" onclick="toggleMessage('${m.name}')">
            <td style="text-align:center; color:var(--text-muted);">${toggleIcon}</td>
            <td><strong style="color:var(--text);">${m.name}</strong> <span style="font-size:0.7rem; color:var(--text-muted);">(${childSignals.length} sigs)</span></td>
            <td><span class="mono badge-pill" style="background:var(--tag-bg); color:var(--badge-text);">${m.can_id_hex}</span></td>
            <td class="mono">${m.count.toLocaleString()}</td>
            <td class="mono">${m.nominal_ms} ms</td>
            <td class="mono">${m.avg_ms} ms <span style="font-size:0.7rem; color:var(--text-muted);">(${m.freq_hz} Hz)</span></td>
            <td class="mono">${m.min_ms} ms</td>
            <td class="mono">${m.max_ms} ms</td>
            <td class="mono">${m.std_ms} ms</td>
            <td>${lossBadge}</td>
          </tr>
        `;

        if (isExpanded) {
          const sigsToDisplay = query && !msgMatch ? matchingSigs : childSignals;
          sigsToDisplay.forEach(s => {
            html += `
              <tr class="sig-row">
                <td></td>
                <td style="padding-left:1.8rem;">↳ <span style="color:var(--text); font-weight:500;">${s.name}</span></td>
                <td><span class="mono" style="color:var(--primary); font-size:0.75rem;">${s.unit || '–'}</span></td>
                <td class="mono">${s.count.toLocaleString()}</td>
                <td style="color:var(--text-muted);">–</td>
                <td class="mono">${s.avg}</td>
                <td class="mono">${s.min}</td>
                <td class="mono">${s.max}</td>
                <td class="mono">σ=${s.std}</td>
                <td class="mono" style="color:var(--warning);">${s.max_slew} <span style="font-size:0.7rem;">/s</span></td>
              </tr>
            `;
          });
        }
      });

      tbody.innerHTML = html || '<tr><td colspan="10" style="text-align:center; padding:2rem; color:var(--text-muted);">No messages or signals matched search query.</td></tr>';
    }

    window.toggleMessage = function(name) {
      if (expandedMessages.has(name)) {
        expandedMessages.delete(name);
      } else {
        expandedMessages.add(name);
      }
      renderAnalyticsTable();
    };

    window.addEventListener('DOMContentLoaded', () => {
      setupMapResizer();
      if (isMapOpen) {
        toggleMap(true);
      }
      initLogs();
    });
  </script>
</body>
</html>
"""


class TunerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data: Any, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/" or path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(HTML_PAGE.encode("utf-8"))))
                self.end_headers()
                self.wfile.write(HTML_PAGE.encode("utf-8"))

            elif path == "/api/logs":
                db = get_dbc()
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
                filename = query.get("file", [""])[0]
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
                data = extract_algo_data(p, db)
                self.send_json(data)

            elif path == "/api/analytics":
                filename = query.get("file", [""])[0]
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
                data = compute_analytics(p, db)
                self.send_json(data)

            elif path == "/api/export_analytics":
                filename = query.get("file", [""])[0]
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
                cal_file = SCRIPT_DIR / "gear_calibration.json"
                if cal_file.is_file():
                    try:
                        with open(cal_file, "r", encoding="utf-8") as f:
                            self.send_json(json.load(f))
                            return
                    except Exception:
                        pass
                self.send_json({
                    "version": 1,
                    "nominal_ratios": [1.018, 1.793, 2.726, 3.763, 4.542],
                    "tolerance": 0.25,
                    "latch_ms": 200,
                    "min_speed_kph": 3.0,
                    "min_rpm": 650.0
                })

            else:
                self.send_error(404, "Not Found")

        except Exception as e:
            self.send_error(500, str(e))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/calibration":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))
                cal_file = SCRIPT_DIR / "gear_calibration.json"
                existing = {}
                if cal_file.is_file():
                    try:
                        with open(cal_file, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                    except Exception:
                        pass
                existing.update(data)
                with open(cal_file, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2)
                self.send_json({"status": "ok", "saved": existing})
            except Exception as e:
                self.send_json({"status": "error", "error": str(e)}, status=500)
        else:
            self.send_error(404)


def find_available_port(start_port: int = 8081, max_tries: int = 100) -> int:
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_tries}")


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

    port = find_available_port(args.port)
    server = HTTPServer(("0.0.0.0", port), TunerHandler)
    url = f"http://localhost:{port}"

    print("=" * 70)
    print("  MiniGauge Algorithm Calibration & Tuning Lab")
    print("=" * 70)
    print(f"  Web Dashboard running at: {url}")
    print("  Tabs available:")
    print("    - ⚙️ Gear Position Estimator (Histogram, Auto-Peaks, Gated EMA)")
    print("    - ⛽ Fuel Level Filter (SMA vs EMA, Quantization, Residuals)")
    print("    - 🏎️ Speed Correction & ECE R39 Check (Corr Factor, Auto-Optimizer)")
    print("    - 📊 Signal & Message Analytics (Cycle Jitter, Loss Rate, Slew Rate)")
    print("  Press Ctrl+C to terminate server.")
    print("=" * 70)

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()


if __name__ == "__main__":
    main()


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
                    gps_times.append(t)
                    gps_speed.append(float(d["RBX_speed_kph"]["value"]))
                    gps_valid.append(int(d.get("RBX_valid_fix", {}).get("value", 0)))
                    gps_fix_st.append(int(d.get("RBX_fix_ST", {}).get("value", 0)))

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
        <div class="card">
          <div class="card-title">Gating Filters</div>
          <div class="ctrl-group">
            <div class="ctrl-label-row">
              <span class="ctrl-label">Min Speed Freq</span>
              <span class="ctrl-val" id="val-gear-minspeed">5.0 Hz</span>
            </div>
            <input type="range" id="slider-gear-minspeed" min="0" max="40" step="0.5" value="5.0">
          </div>
          <div class="ctrl-group">
            <div class="ctrl-label-row">
              <span class="ctrl-label">Min RPM Freq</span>
              <span class="ctrl-val" id="val-gear-minrpm">25.0 Hz</span>
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
          <div class="card-title">Smoothing Filter</div>
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
            <span>Gear Ratio Centers</span>
            <button class="btn-accent" id="btn-auto-gear-peaks" style="padding:0.15rem 0.45rem; font-size:0.7rem;">⚡ Auto-Detect</button>
          </div>
          <div class="ctrl-group">
            <div class="ctrl-label-row">
              <span class="ctrl-label">Tolerance Window</span>
              <span class="ctrl-val" id="val-gear-tol">±8.0%</span>
            </div>
            <input type="range" id="slider-gear-tol" min="2.0" max="20.0" step="0.5" value="8.0">
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:0.4rem; font-size:0.78rem;">
            <div>
              <label>1st Gear</label>
              <input type="number" id="gear-r-1" step="0.01" value="1.82" style="width:100%;">
            </div>
            <div>
              <label>2nd Gear</label>
              <input type="number" id="gear-r-2" step="0.01" value="2.73" style="width:100%;">
            </div>
            <div>
              <label>3rd Gear</label>
              <input type="number" id="gear-r-3" step="0.01" value="3.76" style="width:100%;">
            </div>
            <div>
              <label>4th Gear</label>
              <input type="number" id="gear-r-4" step="0.01" value="4.54" style="width:100%;">
            </div>
            <div>
              <label>5th Gear</label>
              <input type="number" id="gear-r-5" step="0.01" value="5.25" style="width:100%;">
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
          <div style="margin-top:0.75rem;">
            <button id="btn-reset-gear-defaults" style="width:100%;">Reset Gear Defaults</button>
          </div>
        </div>
      </div>

      <div class="algo-content">
        <div class="scorecards-row">
          <div class="scorecard">
            <span class="sc-label">Drive State</span>
            <span class="sc-val good" id="sc-gear-active">--%</span>
          </div>
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
        <div class="plots-column">
          <div class="plot-box" id="plot-gear-hist" style="flex:0.8;"></div>
          <div class="plot-box" id="plot-gear-time" style="flex:1.2;"></div>
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

  </main>

  <script>
    let currentTheme = localStorage.getItem('minigauge_theme') || 'dark';
    document.documentElement.setAttribute('data-theme', currentTheme);

    document.getElementById('btn-theme-toggle').addEventListener('click', () => {
      currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', currentTheme);
      localStorage.setItem('minigauge_theme', currentTheme);
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
      });
    });

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

        renderActiveTabPlots();
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
      minSpeed: 5.0,
      minRpm: 25.0,
      stabGate: 0.050,
      alpha: 0.15,
      tol: 8.0,
      r: [1.82, 2.73, 3.76, 4.54, 5.25],
      showGroundTruth: false
    };

    function loadGearSettings() {
      const saved = localStorage.getItem('minigauge_gear_params');
      if (saved) {
        try {
          Object.assign(gearParams, JSON.parse(saved));
        } catch(e){}
      }
      document.getElementById('slider-gear-minspeed').value = gearParams.minSpeed;
      document.getElementById('val-gear-minspeed').innerText = gearParams.minSpeed.toFixed(1) + ' Hz';
      document.getElementById('slider-gear-minrpm').value = gearParams.minRpm;
      document.getElementById('val-gear-minrpm').innerText = gearParams.minRpm.toFixed(1) + ' Hz';
      document.getElementById('slider-gear-stab').value = gearParams.stabGate;
      document.getElementById('val-gear-stab').innerText = gearParams.stabGate.toFixed(3);
      document.getElementById('slider-gear-alpha').value = gearParams.alpha;
      document.getElementById('val-gear-alpha').innerText = gearParams.alpha.toFixed(2);
      document.getElementById('slider-gear-tol').value = gearParams.tol;
      document.getElementById('val-gear-tol').innerText = '±' + gearParams.tol.toFixed(1) + '%';
      document.getElementById('chk-gear-groundtruth').checked = gearParams.showGroundTruth;
      for (let i = 1; i <= 5; i++) {
        const inp = document.getElementById(`gear-r-${i}`);
        if (inp && gearParams.r[i - 1] !== undefined) inp.value = gearParams.r[i - 1].toFixed(2);
      }
    }
    loadGearSettings();

    function saveGearSettings() {
      localStorage.setItem('minigauge_gear_params', JSON.stringify(gearParams));
    }

    document.getElementById('slider-gear-minspeed').addEventListener('input', (e) => {
      gearParams.minSpeed = parseFloat(e.target.value);
      document.getElementById('val-gear-minspeed').innerText = gearParams.minSpeed.toFixed(1) + ' Hz';
      saveGearSettings();
      computeAndRenderGear();
    });
    document.getElementById('slider-gear-minrpm').addEventListener('input', (e) => {
      gearParams.minRpm = parseFloat(e.target.value);
      document.getElementById('val-gear-minrpm').innerText = gearParams.minRpm.toFixed(1) + ' Hz';
      saveGearSettings();
      computeAndRenderGear();
    });
    document.getElementById('slider-gear-stab').addEventListener('input', (e) => {
      gearParams.stabGate = parseFloat(e.target.value);
      document.getElementById('val-gear-stab').innerText = gearParams.stabGate.toFixed(3);
      saveGearSettings();
      computeAndRenderGear();
    });
    document.getElementById('slider-gear-alpha').addEventListener('input', (e) => {
      gearParams.alpha = parseFloat(e.target.value);
      document.getElementById('val-gear-alpha').innerText = gearParams.alpha.toFixed(2);
      saveGearSettings();
      computeAndRenderGear();
    });
    document.getElementById('slider-gear-tol').addEventListener('input', (e) => {
      gearParams.tol = parseFloat(e.target.value);
      document.getElementById('val-gear-tol').innerText = '±' + gearParams.tol.toFixed(1) + '%';
      saveGearSettings();
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
      gearParams.minSpeed = 5.0;
      gearParams.minRpm = 25.0;
      gearParams.stabGate = 0.050;
      gearParams.alpha = 0.15;
      gearParams.tol = 8.0;
      gearParams.r = [1.82, 2.73, 3.76, 4.54, 5.25];
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
        if (v >= 1.0 && v <= 8.0) {
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
      const histRatios = [];

      let currentEma = null;
      let prevRaw = null;
      let activeCount = 0;
      let totalEvalCount = 0;

      const gearTimeCounts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0};

      for (let i = 0; i < n; i++) {
        const t = g.times[i];
        const sf = g.speed_freq[i];
        const rf = g.rpm_freq[i];
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

        let estGear = 0;
        if (currentEma !== null) {
          for (let gi = 0; gi < 5; gi++) {
            const nominal = gearParams.r[gi];
            const tolWindow = nominal * (gearParams.tol / 100.0);
            if (Math.abs(currentEma - nominal) <= tolWindow) {
              estGear = gi + 1;
              break;
            }
          }
        }

        if (t >= tMin && t <= tMax) {
          filteredTimes.push(t);
          rawRatios.push(isGatedActive ? ratio : null);
          smoothedRatios.push(currentEma);
          estimatedGears.push(estGear);
          groundTruthGears.push(gt);
          gearTimeCounts[estGear] = (gearTimeCounts[estGear] || 0) + 0.1;
        }
      }

      const activePct = totalEvalCount > 0 ? (activeCount / totalEvalCount * 100).toFixed(1) : '0.0';
      document.getElementById('sc-gear-active').innerText = activePct + '%';
      document.getElementById('sc-gear-time-1').innerText = (gearTimeCounts[1] || 0).toFixed(1) + 's';
      document.getElementById('sc-gear-time-2').innerText = (gearTimeCounts[2] || 0).toFixed(1) + 's';
      document.getElementById('sc-gear-time-3').innerText = (gearTimeCounts[3] || 0).toFixed(1) + 's';
      document.getElementById('sc-gear-time-4').innerText = (gearTimeCounts[4] || 0).toFixed(1) + 's';
      document.getElementById('sc-gear-time-5').innerText = (gearTimeCounts[5] || 0).toFixed(1) + 's';

      const theme = getPlotlyLayoutTheme();

      const histShapes = [];
      const gearColors = ['#94a3b8', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'];
      for (let gi = 0; gi < 5; gi++) {
        const nom = gearParams.r[gi];
        const span = nom * (gearParams.tol / 100.0);
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
        xaxis: { title: 'Speed Freq / RPM Freq Ratio', gridcolor: theme.gridcolor, range: [1.0, 7.0] },
        yaxis: { title: 'Samples', gridcolor: theme.gridcolor },
        shapes: histShapes,
        showlegend: false
      }, { responsive: true });

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
    }

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
        });
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

            else:
                self.send_error(404, "Not Found")

        except Exception as e:
            self.send_error(500, str(e))


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


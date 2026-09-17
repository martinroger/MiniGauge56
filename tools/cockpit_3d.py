#!/usr/bin/env python3
"""
MiniGauge 3D Cyber-Cockpit & Drive Trajectory Replayer
======================================================
Interactive browser-based 3D trajectory visualization and realistic
cyberpunk instrument cluster replayer for MiniGauge CAN bus binary logs (*.bin).

Features:
  - Three.js WebGL hardware-accelerated 3D trajectory with local ENU metric coordinates
  - Past/present trajectory heatmapped to speed, future points greyed out
  - Uncontainerized dual-screen instrument cluster inspired by vx-binocle-espidf
  - Needle-less perimeter progress arcs (RPM & Speed)
  - Speed warp particle system & dynamic G-force camera roll
  - Collapsible storytelling HUD (toggle via button or 'H' key)
  - Live vertical elevation exaggeration slider (1.0x to 5.0x)
  - Zero external pip dependencies (Python 3 stdlib only)
"""

import sys
import os
import glob
import json
import socket
import argparse
import webbrowser
import math
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

# Global caches
COCKPIT_CACHE: Dict[str, Dict[str, Any]] = {}
DBC_PATH: Optional[Path] = SCRIPT_DIR / "binocan.dbc"
INITIAL_LOG_FILE: Optional[Path] = None

GEAR_MAP = {
    0: "N",
    1: "1",
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    14: "?",
    15: "R",
}

STATUS_MAP = {
    0: "OFF",
    1: "INIT",
    2: "OK",
    3: "DEGRADED",
    4: "FAULT",
    5: "OTA",
    7: "FACTORY",
}


def lat_lon_to_enu(lat: float, lon: float, alt: float,
                   lat0: float, lon0: float, alt0: float) -> tuple[float, float, float]:
    """Converts WGS84 (lat, lon, alt) to local East-North-Up (ENU) coordinates in meters."""
    R = 6371000.0  # Mean Earth radius in meters
    rad = math.pi / 180.0
    d_lat = (lat - lat0) * rad
    d_lon = (lon - lon0) * rad
    lat_avg = ((lat + lat0) / 2.0) * rad

    x = R * d_lon * math.cos(lat_avg)  # East
    y = R * d_lat                      # North
    z = alt - alt0                     # Up
    return x, y, z


def extract_cockpit_trajectory(log_path: Path, db: DbcDatabase, downsample: int = 1) -> Dict[str, Any]:
    """Reads and decodes a .bin log into 3D ENU trajectory points and synchronized telemetry."""
    key = f"{log_path.resolve()}::{downsample}"
    mtime = log_path.stat().st_mtime
    if key in COCKPIT_CACHE and COCKPIT_CACHE[key]["mtime"] == mtime:
        return COCKPIT_CACHE[key]["data"]

    frames = read_bin_file(log_path)
    if not frames:
        empty = {
            "filename": log_path.name,
            "duration_s": 0.0,
            "frame_count": 0,
            "has_gps": False,
            "point_count": 0,
            "points": [],
            "stats": {
                "min_alt": 0.0, "max_alt": 0.0, "total_gain": 0.0,
                "min_speed": 0.0, "max_speed": 0.0, "avg_speed": 0.0,
                "distance_km": 0.0,
                "avg_g": 0.0, "max_g": 1.0, "g_thresh": 0.75, "g_bound": 1.1, "g_mid": 0.5
            }
        }
        COCKPIT_CACHE[key] = {"mtime": mtime, "data": empty}
        return empty

    duration_s = round(frames[-1].time_rel_s, 3)

    # Telemetry state tracker
    cur_gps_speed = 0.0
    cur_gps_heading = 0.0
    cur_gps_alt = 0.0
    cur_ind_speed = 0.0
    cur_rpm = 0.0
    cur_gear_st = 0
    cur_coolant = 70.0
    cur_fuel = 0.0
    cur_batt = 12.0
    cur_oil_p = 0.0
    cur_oil_t = 0.0
    cur_accel_x = 0.0
    cur_accel_y = 0.0
    cur_accel_z = 0.0
    cur_rot_z = 0.0
    cur_status_l = "OK"
    cur_status_r = "OK"

    tell_tales = {
        "turn_l": False,
        "turn_r": False,
        "high_beam": False,
        "park_brake": False,
        "brake_low": False,
        "abs": False,
        "airbag": False,
        "oil_pressure": False,
        "coolant_low": False,
        "battery": False,
        "cel": False,
        "fuel_low": False,
    }

    raw_points: List[Dict[str, Any]] = []
    lat0: Optional[float] = None
    lon0: Optional[float] = None
    alt0: Optional[float] = None

    for frame in frames:
        msg_def = db.get_message(frame.can_id)
        if not msg_def:
            continue
        decoded = msg_def.decode(frame.data)
        t = round(frame.time_rel_s, 4)

        # 1. GPS Speed & Heading (0x600 / 1536)
        if "RBX_speed_kph" in decoded:
            cur_gps_speed = float(decoded["RBX_speed_kph"]["value"])
        if "RBX_heading_deg" in decoded:
            cur_gps_heading = float(decoded["RBX_heading_deg"]["value"])

        # 2. GPS Altitude (0x602 / 1538)
        if "RBX_msl_altitude_m" in decoded:
            cur_gps_alt = float(decoded["RBX_msl_altitude_m"]["value"])

        # 3. IMU Dynamics (0x603 / 1539, 0x604 / 1540)
        if "RBX_accel_X_g" in decoded:
            cur_accel_x = float(decoded["RBX_accel_X_g"]["value"])
        if "RBX_accel_Y_g" in decoded:
            cur_accel_y = float(decoded["RBX_accel_Y_g"]["value"])
        if "RBX_accel_Z_g" in decoded:
            cur_accel_z = float(decoded["RBX_accel_Z_g"]["value"])
        if "RBX_rot_rate_Z" in decoded:
            cur_rot_z = float(decoded["RBX_rot_rate_Z"]["value"])

        # 4. Vehicle Fast Metrics (0x100 / 256)
        if "ITF_speed_kph" in decoded:
            cur_ind_speed = float(decoded["ITF_speed_kph"]["value"])
        if "ITF_rpm" in decoded:
            cur_rpm = float(decoded["ITF_rpm"]["value"])
        if "ITF_gear_position_ST" in decoded:
            cur_gear_st = int(decoded["ITF_gear_position_ST"]["value"])

        # 5. Vehicle Slow Metrics (0x110 / 272)
        if "ITF_coolant_temp" in decoded:
            cur_coolant = float(decoded["ITF_coolant_temp"]["value"])
        if "ITF_fuel_level_pc" in decoded:
            cur_fuel = float(decoded["ITF_fuel_level_pc"]["value"])
        if "ITF_lv_voltage_v" in decoded:
            cur_batt = float(decoded["ITF_lv_voltage_v"]["value"])

        # 6. External Oil Metrics (0x200 / 512)
        if "EXT_oil_pressure" in decoded:
            cur_oil_p = float(decoded["EXT_oil_pressure"]["value"])
        if "EXT_oil_temperature" in decoded:
            cur_oil_t = float(decoded["EXT_oil_temperature"]["value"])

        # 7. Tell-Tales & Active Alarms (0x101 / 257)
        if "ITF_left_turn_AH_TT" in decoded:
            tell_tales["turn_l"] = bool(decoded["ITF_left_turn_AH_TT"]["value"])
        if "ITF_right_turn_AH_TT" in decoded:
            tell_tales["turn_r"] = bool(decoded["ITF_right_turn_AH_TT"]["value"])
        if "ITF_hi_beams_AH_TT" in decoded:
            tell_tales["high_beam"] = bool(decoded["ITF_hi_beams_AH_TT"]["value"])
        if "ITF_parking_brake_AL_TT" in decoded:
            tell_tales["park_brake"] = bool(decoded["ITF_parking_brake_AL_TT"]["value"])
        if "ITF_brake_low_AL_TT" in decoded:
            tell_tales["brake_low"] = bool(decoded["ITF_brake_low_AL_TT"]["value"])
        if "ITF_abs_AL_TT" in decoded:
            tell_tales["abs"] = bool(decoded["ITF_abs_AL_TT"]["value"])
        if "ITF_airbag_AL_TT" in decoded:
            tell_tales["airbag"] = bool(decoded["ITF_airbag_AL_TT"]["value"])
        if "ITF_oil_pressure_AL_TT" in decoded:
            tell_tales["oil_pressure"] = bool(decoded["ITF_oil_pressure_AL_TT"]["value"])
        if "ITF_coolant_low_AH_TT" in decoded:
            tell_tales["coolant_low"] = bool(decoded["ITF_coolant_low_AH_TT"]["value"])
        if "ITF_alternator_AL_TT" in decoded:
            tell_tales["battery"] = bool(decoded["ITF_alternator_AL_TT"]["value"])
        if "ITF_CEL_AL_TT" in decoded:
            tell_tales["cel"] = bool(decoded["ITF_CEL_AL_TT"]["value"])
        if "ITF_fuel_low_TT" in decoded:
            tell_tales["fuel_low"] = bool(decoded["ITF_fuel_low_TT"]["value"])

        # 8. Board Status (0x121 / 289 LDB, 0x122 / 290 RDB)
        if "LDB_status" in decoded:
            cur_status_l = STATUS_MAP.get(int(decoded["LDB_status"]["value"]), "OK")
        if "RDB_status" in decoded:
            cur_status_r = STATUS_MAP.get(int(decoded["RDB_status"]["value"]), "OK")

        # 9. GPS Lat/Lon Fix (0x601 / 1537) -> Records 3D Trajectory Point
        if "RBX_latitude_deg" in decoded and "RBX_longitude_deg" in decoded:
            lat = float(decoded["RBX_latitude_deg"]["value"])
            lon = float(decoded["RBX_longitude_deg"]["value"])

            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and (lat != 0.0 or lon != 0.0):
                if lat0 is None:
                    lat0 = lat
                    lon0 = lon
                    alt0 = cur_gps_alt

                enu_x, enu_y, enu_z = lat_lon_to_enu(lat, lon, cur_gps_alt, lat0, lon0, alt0)

                # Active speed priority: indicated cluster speed if non-zero, otherwise GPS ground speed
                active_speed = cur_ind_speed if cur_ind_speed > 0.0 else cur_gps_speed

                raw_points.append({
                    "t": t,
                    "x": round(enu_x, 2),
                    "y": round(enu_y, 2),
                    "z": round(enu_z, 2),
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "alt": round(cur_gps_alt, 1),
                    "speed": round(active_speed, 1),
                    "gps_speed": round(cur_gps_speed, 1),
                    "heading": round(cur_gps_heading, 1),
                    "rpm": round(cur_rpm, 0),
                    "gear": cur_gear_st,
                    "gear_txt": GEAR_MAP.get(cur_gear_st, "N"),
                    "coolant": round(cur_coolant, 1),
                    "fuel": round(cur_fuel, 1),
                    "battery": round(cur_batt, 1),
                    "oil_p": round(cur_oil_p, 1),
                    "oil_t": round(cur_oil_t, 1),
                    "g_lat": round(-cur_accel_y + 0.0, 3), # Lateral G (+ right, - left)
                    "g_lon": round(cur_accel_x, 3),        # Longitudinal G (+ accel, - brake)
                    "g_vert": round(cur_accel_z, 3),       # Vertical G
                    "grade": 0.0,                          # Local road slope grade (%)
                    "status_l": cur_status_l,
                    "status_r": cur_status_r,
                    "tell_tales": dict(tell_tales),
                })

    # Ensure alt0 is set to the first valid non-zero altitude fix
    if alt0 is None or alt0 == 0.0:
        alt0 = next((p["alt"] for p in raw_points if p["alt"] > 0.0), 0.0)

    # Re-normalize initial point altitude and all z values so the trajectory begins cleanly at z = 0.0
    for p in raw_points:
        if p["alt"] == 0.0 and alt0 > 0.0:
            p["alt"] = round(alt0, 1)
        p["z"] = round(p["alt"] - alt0, 2)

    # Pre-smooth trajectory coordinates (x, y, z) using Gaussian smoothing filter to eliminate GPS lateral jitter
    if len(raw_points) > 5:
        win = 11
        sigma = 4.0
        n_pts = len(raw_points)
        sx = [0.0] * n_pts
        sy = [0.0] * n_pts
        sz = [0.0] * n_pts
        for i in range(n_pts):
            nx, ny, nz, den = 0.0, 0.0, 0.0, 0.0
            for j in range(max(0, i - win), min(n_pts, i + win + 1)):
                d = j - i
                w = math.exp(-0.5 * (d / sigma) ** 2)
                nx += raw_points[j]["x"] * w
                ny += raw_points[j]["y"] * w
                nz += raw_points[j]["z"] * w
                den += w
            sx[i] = round(nx / den, 2)
            sy[i] = round(ny / den, 2)
            sz[i] = round(nz / den, 2)

        # Preserve exact origin (0, 0, 0) on initial point
        sx[0] = 0.0
        sy[0] = 0.0
        sz[0] = 0.0

        for i in range(n_pts):
            raw_points[i]["x"] = sx[i]
            raw_points[i]["y"] = sy[i]
            raw_points[i]["z"] = sz[i]

    # Compute smoothed local road slope grade (%) using a rolling spatial distance window (+-25m)
    n_raw = len(raw_points)
    if n_raw > 1:
        cum_dist = [0.0] * n_raw
        for i in range(1, n_raw):
            dx = raw_points[i]["x"] - raw_points[i - 1]["x"]
            dy = raw_points[i]["y"] - raw_points[i - 1]["y"]
            cum_dist[i] = cum_dist[i - 1] + math.hypot(dx, dy)

        win_dist = 25.0
        j_b = 0
        j_f = 0
        for i in range(n_raw):
            s_cur = cum_dist[i]
            while j_b < i and (s_cur - cum_dist[j_b]) > win_dist:
                j_b += 1
            while j_f < n_raw - 1 and (cum_dist[j_f + 1] - s_cur) <= win_dist:
                j_f += 1

            ds = cum_dist[j_f] - cum_dist[j_b]
            dz = raw_points[j_f]["z"] - raw_points[j_b]["z"]
            if ds >= 6.0:
                raw_points[i]["grade"] = round((dz / ds) * 100.0, 1)
            else:
                raw_points[i]["grade"] = 0.0

    # Apply downsampling step if requested (> 1)
    if downsample > 1 and len(raw_points) > downsample:
        sampled_points = raw_points[::downsample]
        # Always preserve the final point
        if raw_points and sampled_points[-1] != raw_points[-1]:
            sampled_points.append(raw_points[-1])
    else:
        sampled_points = raw_points

    # Calculate aggregate trajectory statistics
    if sampled_points:
        alts = [p["alt"] for p in sampled_points]
        speeds = [p["speed"] for p in sampled_points]
        min_alt = min(alts)
        max_alt = max(alts)

        # Compute cumulative distance and elevation gain
        dist_m = 0.0
        elev_gain_m = 0.0
        for i in range(len(sampled_points) - 1):
            p1 = sampled_points[i]
            p2 = sampled_points[i + 1]
            dx = p2["x"] - p1["x"]
            dy = p2["y"] - p1["y"]
            dz = p2["z"] - p1["z"]
            dist_m += math.hypot(dx, dy)
            if dz > 0:
                elev_gain_m += dz

        g_norms = [math.hypot(p["g_lat"], p["g_lon"]) for p in sampled_points]
        avg_g = sum(g_norms) / len(g_norms) if g_norms else 0.2
        max_g = max(g_norms) if g_norms else 1.0
        if max_g <= 0.01:
            max_g = 1.0
        g_thresh = max_g * 0.75
        g_bound = max_g * 1.1
        g_mid = max_g * 0.5

        stats = {
            "min_alt": round(min_alt, 1),
            "max_alt": round(max_alt, 1),
            "total_gain": round(elev_gain_m, 1),
            "min_speed": round(min(speeds), 1),
            "max_speed": round(max(speeds), 1),
            "avg_speed": round(sum(speeds) / len(speeds), 1),
            "distance_km": round(dist_m / 1000.0, 2),
            "avg_g": round(avg_g, 3),
            "max_g": round(max_g, 3),
            "g_thresh": round(g_thresh, 3),
            "g_bound": round(g_bound, 3),
            "g_mid": round(g_mid, 3),
        }
    else:
        stats = {
            "min_alt": 0.0, "max_alt": 0.0, "total_gain": 0.0,
            "min_speed": 0.0, "max_speed": 0.0, "avg_speed": 0.0,
            "distance_km": 0.0,
            "avg_g": 0.0, "max_g": 1.0, "g_thresh": 0.75, "g_bound": 1.1, "g_mid": 0.5
        }

    result = {
        "filename": log_path.name,
        "size": log_path.stat().st_size,
        "duration_s": duration_s,
        "frame_count": len(frames),
        "has_gps": len(sampled_points) > 0,
        "point_count": len(sampled_points),
        "points": sampled_points,
        "stats": stats,
    }

    COCKPIT_CACHE[key] = {"mtime": mtime, "data": result}
    return result


class CockpitHandler(BaseAppHandler):
    """HTTP request handler for the 3D Cockpit Replayer."""

    def do_GET(self) -> None:
        path, _ = self.parse_query()

        if path.startswith("/static/"):
            if self.serve_static(path):
                return
            self.send_error(404, f"Static asset not found: {path}")
            return

        try:
            if path in ("/", "/index.html"):
                template_path = SCRIPT_DIR / "web" / "templates" / "cockpit_3d.html"
                if not template_path.is_file():
                    self.send_error(404, "Template cockpit_3d.html not found")
                    return
                html = template_path.read_text(encoding="utf-8")
                self.send_html(html)

            elif path == "/favicon.ico":
                # Minimalist SVG gauge favicon
                svg_icon = (
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                    '<circle cx="16" cy="16" r="14" fill="#05070c" stroke="#00f0ff" stroke-width="2"/>'
                    '<path d="M 8 22 A 10 10 0 1 1 24 22" fill="none" stroke="#00ff66" stroke-width="2.5" stroke-linecap="round"/>'
                    '<line x1="16" y1="16" x2="21" y2="10" stroke="#ff2a55" stroke-width="2" stroke-linecap="round"/>'
                    '<circle cx="16" cy="16" r="2.5" fill="#00f0ff"/>'
                    '</svg>'
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(svg_icon)))
                self.end_headers()
                self.wfile.write(svg_icon)

            elif path == "/api/logs":
                bin_files = find_bin_files(SCRIPT_DIR)
                logs_info = []
                for p in bin_files:
                    logs_info.append({
                        "filename": p.name,
                        "size": p.stat().st_size,
                        "mtime": p.stat().st_mtime,
                        "is_initial": bool(INITIAL_LOG_FILE and INITIAL_LOG_FILE.name == p.name),
                    })
                self.send_json(logs_info)

            elif path == "/api/trajectory":
                filename = self.get_query_param("file")
                downsample = int(self.get_query_param("downsample", "1") or "1")
                if downsample < 1:
                    downsample = 1

                if not filename:
                    if INITIAL_LOG_FILE and INITIAL_LOG_FILE.is_file():
                        p = INITIAL_LOG_FILE
                    else:
                        bin_files = find_bin_files(SCRIPT_DIR)
                        if not bin_files:
                            self.send_error(404, "No .bin log files found")
                            return
                        p = bin_files[0]
                else:
                    p = resolve_bin_file(filename, [SCRIPT_DIR])
                    if not p and INITIAL_LOG_FILE and INITIAL_LOG_FILE.name == filename:
                        p = INITIAL_LOG_FILE
                    if not p or not p.is_file():
                        self.send_error(404, f"Log file {filename} not found")
                        return

                db = get_dbc(DBC_PATH)
                traj_data = extract_cockpit_trajectory(p, db, downsample=downsample)
                self.send_json(traj_data)

            else:
                self.send_error(404, "Not Found")

        except Exception as ex:
            self.send_error(500, f"Internal Server Error: {str(ex)}")


def main():
    parser = argparse.ArgumentParser(description="MiniGauge 3D Cyber-Cockpit & Drive Trajectory Replayer")
    parser.add_argument("log_file", nargs="?", help="Specific .bin CAN log file to open initially")
    parser.add_argument("--dbc", "-d", help="Path to DBC database file (default: binocan.dbc)")
    parser.add_argument("--port", "-p", type=int, default=8089, help="HTTP server port (default: 8089)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open web browser")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose HTTP request logging")
    args = parser.parse_args()

    global INITIAL_LOG_FILE, DBC_PATH
    if args.dbc:
        DBC_PATH = Path(args.dbc)

    if args.log_file:
        p = Path(args.log_file)
        if p.is_file():
            INITIAL_LOG_FILE = p.resolve()
        elif (SCRIPT_DIR / args.log_file).is_file():
            INITIAL_LOG_FILE = (SCRIPT_DIR / args.log_file).resolve()
        else:
            print(f"[-] Warning: Specified log file '{args.log_file}' was not found.")

    # Validate DBC
    try:
        db = get_dbc(DBC_PATH)
        print(f"[+] Loaded CAN DBC database: {DBC_PATH.name} ({len(db.messages)} message definitions)")
    except Exception as ex:
        print(f"[-] Error loading DBC: {ex}")
        sys.exit(1)

    CockpitHandler.verbose_logging = args.verbose

    start_server(
        CockpitHandler,
        port=args.port,
        open_browser=not args.no_browser,
        server_name="MiniGauge 3D Cyber-Cockpit Replayer",
    )


if __name__ == "__main__":
    main()

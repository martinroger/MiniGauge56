#!/usr/bin/env python3
"""
MiniGauge CAN Binary Log Trimmer & Slicer
=========================================
A lightweight zero-dependency tool to trim, recut, and extract clean snippets
from MiniGauge 16-byte packed binary CAN logs (*.bin).

Features:
- Slicing by time bounds (--start <sec> --end <sec>) or frame index (--from-frame <N> --to-frame <M>).
- Automatic timestamp zero-rebasing by default (starts at t = 0.0s) with --preserve-timestamps flag.
- Optional CAN arbitration ID filtering (--ids 0x100,0x301).
- Strict non-destructive invariant: Never overwrites the source log file.
- Automatic suffixing with collision prevention (<stem>_cut_<start>s_<end>s.bin).
- Dual interface: Fast CLI utility and interactive browser GUI (--gui / --browser).
"""

import argparse
import glob
import json
import os
import re
import struct
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
try:
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
except ImportError:
    from http.server import HTTPServer as ThreadingHTTPServer, BaseHTTPRequestHandler
import urllib.parse
import webbrowser

SCRIPT_DIR = Path(__file__).resolve().parent
RECORD_STRUCT = struct.Struct("<IHB8sx")
RECORD_SIZE = 16


class RawCanFrame:
    __slots__ = ("ts_ms", "can_id", "dlc", "data", "rel_s")

    def __init__(self, ts_ms: int, can_id: int, dlc: int, data: bytes, rel_s: float = 0.0):
        self.ts_ms = ts_ms
        self.can_id = can_id
        self.dlc = dlc
        self.data = data
        self.rel_s = rel_s


def read_raw_log(filepath: Path) -> List[RawCanFrame]:
    """Reads raw 16-byte binary CAN frames from disk."""
    if not filepath.is_file():
        return []
    raw = filepath.read_bytes()
    num = len(raw) // RECORD_SIZE
    frames: List[RawCanFrame] = []
    first_ts: Optional[int] = None

    for i in range(num):
        chunk = raw[i * RECORD_SIZE : (i + 1) * RECORD_SIZE]
        ts_ms, can_id, dlc, payload = RECORD_STRUCT.unpack(chunk)
        if first_ts is None:
            first_ts = ts_ms
        rel_s = (ts_ms - first_ts) / 1000.0
        frames.append(RawCanFrame(ts_ms, can_id, dlc, payload[:dlc], rel_s))

    return frames


def generate_safe_output_path(input_path: Path, start_s: float, end_s: float, explicit_out: Optional[Path] = None) -> Path:
    """Generates a safe non-colliding output path ensuring input is NEVER overwritten."""
    input_res = input_path.resolve()
    if explicit_out:
        out_res = explicit_out.resolve()
        if out_res == input_res:
            raise ValueError(f"Safety Violation: Target '{explicit_out}' is the same as source file. Refusing to overwrite original log.")
        return explicit_out

    stem = input_path.stem
    parent = input_path.parent
    base_name = f"{stem}_cut_{start_s:.1f}s_{end_s:.1f}s.bin"
    candidate = parent / base_name

    if candidate.resolve() == input_res:
        candidate = parent / f"{stem}_cut_{start_s:.1f}s_{end_s:.1f}s_01.bin"

    counter = 1
    while candidate.exists():
        if candidate.resolve() == input_res:
            pass
        candidate = parent / f"{stem}_cut_{start_s:.1f}s_{end_s:.1f}s_{counter:02d}.bin"
        counter += 1

    return candidate


def trim_log(
    input_path: Path,
    output_path: Optional[Path] = None,
    start_s: Optional[float] = None,
    end_s: Optional[float] = None,
    from_frame: Optional[int] = None,
    to_frame: Optional[int] = None,
    rebase_zero: bool = True,
    allowed_ids: Optional[List[int]] = None,
) -> Tuple[Path, int, float]:
    """
    Trims a binary CAN log and writes the cut to disk.
    Returns: (output_path, num_frames_written, duration_s)
    """
    if not input_path.is_file():
        raise FileNotFoundError(f"Input log file not found: {input_path}")

    frames = read_raw_log(input_path)
    if not frames:
        raise ValueError(f"Log file is empty or corrupt: {input_path}")

    total_frames = len(frames)
    max_duration_s = frames[-1].rel_s

    # Resolve frame index boundaries
    start_idx = 0
    end_idx = total_frames - 1

    if from_frame is not None:
        start_idx = max(0, min(total_frames - 1, from_frame))
    elif start_s is not None:
        start_idx = next((i for i, f in enumerate(frames) if f.rel_s >= start_s), total_frames - 1)

    if to_frame is not None:
        end_idx = max(0, min(total_frames - 1, to_frame))
    elif end_s is not None:
        end_idx = next((i for i, f in enumerate(frames) if f.rel_s > end_s), total_frames) - 1
        end_idx = max(start_idx, end_idx)

    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx

    actual_start_s = frames[start_idx].rel_s
    actual_end_s = frames[end_idx].rel_s

    out_file = generate_safe_output_path(input_path, actual_start_s, actual_end_s, output_path)

    # Filter frames
    id_set = set(allowed_ids) if allowed_ids else None
    selected_frames = []
    for i in range(start_idx, end_idx + 1):
        f = frames[i]
        if id_set is not None and f.can_id not in id_set:
            continue
        selected_frames.append(f)

    if not selected_frames:
        raise ValueError("Zero frames matched the requested time/ID criteria.")

    base_ts = selected_frames[0].ts_ms if rebase_zero else 0

    # Pack and write records
    out_bytes = bytearray()
    for f in selected_frames:
        out_ts = (f.ts_ms - base_ts) if rebase_zero else f.ts_ms
        payload = f.data[:8].ljust(8, b"\x00")
        out_bytes.extend(RECORD_STRUCT.pack(out_ts, f.can_id, f.dlc, payload))

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(out_bytes)

    duration_s = (selected_frames[-1].ts_ms - selected_frames[0].ts_ms) / 1000.0
    return out_file, len(selected_frames), duration_s


def get_preview_data(filepath: Path, max_samples: int = 400) -> Dict[str, Any]:
    """Extracts decimated waveform summary and GPS telemetry for GUI slider preview."""
    frames = read_raw_log(filepath)
    if not frames:
        return {"duration_s": 0.0, "total_frames": 0, "times": [], "speeds": [], "rpms": [], "gps": []}

    duration_s = frames[-1].rel_s
    total_frames = len(frames)

    raw_gps = []
    times = []
    speeds = []
    rpms = []

    cur_speed = 0.0
    cur_rpm = 0.0

    step = max(1, len(frames) // max_samples)
    for i, f in enumerate(frames):
        # Heuristic decoding of speed/RPM frequencies if present
        if f.can_id == 0x300 and len(f.data) >= 4:
            try:
                cur_speed = struct.unpack("<f", f.data[:4])[0] * 0.2444
            except Exception:
                pass
        elif f.can_id == 0x301 and len(f.data) >= 4:
            try:
                cur_rpm = struct.unpack("<f", f.data[:4])[0] * 30.0
            except Exception:
                pass
        elif f.can_id == 0x601 and len(f.data) >= 8:
            # RaceBox GPS Latitude & Longitude (32-bit signed int, 1e-7 deg scale)
            try:
                lat_raw, lon_raw = struct.unpack("<ii", f.data[:8])
                lat, lon = lat_raw * 1e-7, lon_raw * 1e-7
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and (lat != 0.0 or lon != 0.0):
                    raw_gps.append({
                        "t": round(f.rel_s, 2),
                        "lat": round(lat, 6),
                        "lon": round(lon, 6),
                    })
            except Exception:
                pass

        if i % step == 0:
            times.append(round(f.rel_s, 2))
            speeds.append(round(max(0.0, cur_speed), 1))
            rpms.append(round(max(0.0, cur_rpm), 0))

    # Decimate GPS track to at most ~1200 points for smooth map rendering
    if len(raw_gps) > 1200:
        step_gps = max(1, len(raw_gps) // 1200)
        gps_points = raw_gps[::step_gps]
        if raw_gps[-1] != gps_points[-1]:
            gps_points.append(raw_gps[-1])
    else:
        gps_points = raw_gps

    return {
        "filename": filepath.name,
        "duration_s": round(duration_s, 2),
        "total_frames": total_frames,
        "times": times,
        "speeds": speeds,
        "rpms": rpms,
        "gps": gps_points,
    }


# ==============================================================================
# BROWSER GUI HTTP SERVER
# ==============================================================================

class TrimmerHttpHandler(BaseHTTPRequestHandler):
    def send_json(self, data: Any, code: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(build_trimmer_html().encode("utf-8"))

        elif parsed.path == "/api/logs":
            logs = []
            seen = set()
            for d in [SCRIPT_DIR, Path(".").resolve()]:
                for p in d.glob("*.bin"):
                    res = p.resolve()
                    if res not in seen and p.is_file():
                        seen.add(res)
                        logs.append({"filename": p.name, "size": p.stat().st_size})
            logs.sort(key=lambda x: x["filename"])
            self.send_json(logs)

        elif parsed.path == "/api/preview":
            query = urllib.parse.parse_qs(parsed.query)
            fn = query.get("file", [""])[0]
            target = SCRIPT_DIR / fn
            if not target.is_file():
                target = Path(fn)
            if not target.is_file():
                self.send_json({"error": "Log file not found"}, code=404)
                return
            self.send_json(get_preview_data(target))

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/trim":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                params = json.loads(body.decode("utf-8"))
                filename = params.get("filename", "")
                start_s = float(params.get("start_s", 0.0))
                end_s = float(params.get("end_s", 0.0))
                rebase_zero = bool(params.get("rebase_zero", True))
                ids_str = params.get("ids", "").strip()

                allowed_ids = None
                if ids_str:
                    allowed_ids = [int(x.strip(), 16) if x.strip().lower().startswith("0x") else int(x.strip()) for x in ids_str.split(",") if x.strip()]

                src_path = SCRIPT_DIR / filename
                if not src_path.is_file():
                    src_path = Path(filename)

                out_path, n_frames, dur = trim_log(
                    src_path,
                    start_s=start_s,
                    end_s=end_s,
                    rebase_zero=rebase_zero,
                    allowed_ids=allowed_ids,
                )

                self.send_json({
                    "status": "ok",
                    "output_file": out_path.name,
                    "output_path": str(out_path),
                    "frames": n_frames,
                    "duration_s": round(dur, 2),
                    "size_bytes": out_path.stat().st_size,
                })
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, code=400)
        else:
            self.send_error(404, "Not Found")

    def log_message(self, format, *args):
        pass


def build_trimmer_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>MiniGauge CAN Log Trimmer & Slicer</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    :root {
      --app-bg: #0a0a0a;
      --card-bg: #181818;
      --card-border: rgba(221, 107, 61, 0.40);
      --card-border-active: #dd6b3d;
      --text-main: #f5f5f5;
      --text-muted: #9ca3af;
      --accent: #dd6b3d;
      --accent-hover: #e87a4d;
      --divider: rgba(221, 107, 61, 0.25);
      --input-bg: #141414;
      --input-border: rgba(221, 107, 61, 0.40);
      --slider-track-bg: #222222;
      --slider-track-border: rgba(221, 107, 61, 0.45);
      --thumb-ring: #1a1a1a;
    }

    [data-theme="light"] {
      --app-bg: #f8fafc;
      --card-bg: #ffffff;
      --card-border: rgba(43, 92, 146, 0.38);
      --card-border-active: #2b5c92;
      --text-main: #0f172a;
      --text-muted: #64748b;
      --accent: #2b5c92;
      --accent-hover: #376ea8;
      --divider: rgba(43, 92, 146, 0.25);
      --input-bg: #ffffff;
      --input-border: rgba(43, 92, 146, 0.35);
      --slider-track-bg: #ffffff;
      --slider-track-border: rgba(43, 92, 146, 0.45);
      --thumb-ring: #ffffff;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--app-bg);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      padding: 1.5rem;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      transition: background-color 0.2s ease, color 0.2s ease;
    }

    .app-layout {
      width: 100%;
      max-width: 1380px;
      display: flex;
      gap: 1.25rem;
      align-items: stretch;
      justify-content: center;
    }

    .main-pane {
      flex: 1;
      min-width: 320px;
      max-width: 860px;
      display: flex;
      flex-direction: column;
      gap: 1.25rem;
    }

    .map-pane {
      width: 480px;
      min-width: 320px;
      display: flex;
      flex-direction: column;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      overflow: hidden;
      position: relative;
      box-shadow: 0 4px 20px rgba(0,0,0,0.15);
      transition: width 0.2s ease, opacity 0.2s ease;
    }

    .map-pane.collapsed {
      display: none;
    }

    .map-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--divider);
      background: rgba(0,0,0,0.06);
    }

    .map-header-title {
      font-size: 0.85rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }

    #map-view {
      flex: 1;
      min-height: 480px;
      width: 100%;
      background: var(--input-bg);
    }

    .no-gps-card {
      flex: 1;
      min-height: 480px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 2rem;
      color: var(--text-muted);
      text-align: center;
      background: var(--card-bg);
    }

    .btn-toggle-map {
      height: 32px;
      padding: 0 0.65rem;
      border-radius: 6px;
      border: 1px solid var(--card-border);
      background: var(--card-bg);
      color: var(--text-main);
      cursor: pointer;
      font-size: 0.8rem;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 0.35rem;
      transition: border-color 0.15s ease, color 0.15s ease;
    }
    .btn-toggle-map.active {
      border-color: var(--accent);
      color: var(--accent);
    }
    .btn-toggle-map:hover {
      opacity: 0.9;
    }

    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--divider);
    }
    .header-brand {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .badge-icon {
      width: 32px;
      height: 32px;
      border-radius: 6px;
      background: var(--accent);
      color: white;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 900;
      font-size: 0.85rem;
    }
    .header-title { font-size: 1.1rem; font-weight: 700; }
    .header-sub { font-size: 0.75rem; color: var(--text-muted); font-family: monospace; }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }

    .theme-toggle-btn {
      width: 32px;
      height: 32px;
      border-radius: 6px;
      border: 1px solid var(--card-border);
      background: var(--card-bg);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.95rem;
    }

    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
      position: relative;
    }
    .card.active-accent::before {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 3px;
      background: var(--accent);
      border-top-left-radius: 9px;
      border-top-right-radius: 9px;
    }

    .ctrl-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
    }
    .ctrl-label { font-size: 0.82rem; font-weight: 600; color: var(--text-main); }
    .ctrl-val { font-size: 0.85rem; font-family: monospace; font-weight: 700; color: var(--accent); }

    input[type="range"] {
      -webkit-appearance: none;
      appearance: none;
      width: 100%;
      height: 8px;
      border-radius: 9999px;
      background: linear-gradient(
        to right,
        var(--slider-track-bg) 0%,
        var(--slider-track-bg) var(--start-pct, 0%),
        var(--accent) var(--start-pct, 0%),
        var(--accent) var(--end-pct, 100%),
        var(--slider-track-bg) var(--end-pct, 100%),
        var(--slider-track-bg) 100%
      );
      border: 1px solid var(--slider-track-border);
      outline: none;
      cursor: pointer;
    }

    input[type="range"]::-webkit-slider-thumb {
      -webkit-appearance: none;
      appearance: none;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: var(--accent);
      cursor: pointer;
      border: 2px solid var(--thumb-ring);
      box-shadow: 0 1px 4px rgba(0,0,0,0.3);
    }

    select, input[type="text"], input[type="number"] {
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      color: var(--text-main);
      padding: 0.4rem 0.6rem;
      border-radius: 6px;
      font-size: 0.8rem;
      font-family: inherit;
    }

    .btn-primary {
      background: var(--accent);
      color: white;
      border: none;
      padding: 0.6rem 1.2rem;
      border-radius: 6px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      transition: opacity 0.15s ease;
    }
    .btn-primary:hover { opacity: 0.9; }

    .waveform-preview {
      width: 100%;
      height: 100px;
      border-radius: 6px;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      overflow: hidden;
    }

    .toast {
      padding: 0.75rem 1rem;
      border-radius: 6px;
      font-size: 0.8rem;
      display: none;
      margin-top: 0.5rem;
    }
    .toast.success { background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #10b981; }
    .toast.error { background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #ef4444; }
  </style>
</head>
<body>

<div class="app-layout">
  <!-- Left Column: Controls & Waveform -->
  <div class="main-pane">
    <header class="header">
      <div class="header-brand">
        <div class="badge-icon">✂️</div>
        <div>
          <div class="header-title">MiniGauge CAN Log Trimmer</div>
          <div class="header-sub">Binary Dataset Slicer & Recutter</div>
        </div>
      </div>
      <div class="header-actions">
        <button id="btn-toggle-map" class="btn-toggle-map active" title="Toggle GPS Map Drawer">🗺️ Map</button>
        <select id="sel-log" title="Select binary log to trim"></select>
        <button id="btn-theme" class="theme-toggle-btn" title="Toggle Theme (🌓)">🌓</button>
      </div>
    </header>

    <!-- Waveform & Dual Slicing Card -->
    <div class="card active-accent">
      <div class="ctrl-row">
        <span class="ctrl-label">Drive Waveform Preview & Selected Cut Window</span>
        <span class="ctrl-val" id="val-window-span">0.0s - 0.0s (Span: 0.0s)</span>
      </div>

      <svg id="preview-svg" class="waveform-preview" viewBox="0 0 800 100" preserveAspectRatio="none">
        <line x1="0" y1="50" x2="800" y2="50" stroke="currentColor" stroke-opacity="0.1" />
        <path id="svg-speed-path" d="" fill="none" stroke="var(--accent)" stroke-width="2" />
      </svg>

      <!-- Start Slider -->
      <div>
        <div class="ctrl-row" style="margin-bottom: 0.3rem;">
          <span class="ctrl-label" style="font-size:0.75rem; color:var(--text-muted);">Start Cut Time (t_start):</span>
          <span class="ctrl-val" id="val-start">0.0 s</span>
        </div>
        <input type="range" id="slider-start" min="0" max="100" step="0.1" value="0">
      </div>

      <!-- End Slider -->
      <div>
        <div class="ctrl-row" style="margin-bottom: 0.3rem;">
          <span class="ctrl-label" style="font-size:0.75rem; color:var(--text-muted);">End Cut Time (t_end):</span>
          <span class="ctrl-val" id="val-end">100.0 s</span>
        </div>
        <input type="range" id="slider-end" min="0" max="100" step="0.1" value="100">
      </div>
    </div>

    <!-- Slicing Options Card -->
    <div class="card">
      <div class="ctrl-row">
        <label style="display:flex; align-items:center; gap:0.5rem; font-size:0.8rem; cursor:pointer;">
          <input type="checkbox" id="chk-rebase" checked>
          <span>Zero-rebase timestamps (first frame starts at <code>t = 0.0s</code>)</span>
        </label>
      </div>

      <div class="ctrl-row">
        <div style="display:flex; flex-direction:column; gap:0.3rem; flex:1;">
          <span class="ctrl-label">Filter CAN Message IDs (optional):</span>
          <input type="text" id="txt-ids" placeholder="e.g. 0x100, 0x301 (leave empty for all messages)">
        </div>
      </div>

      <button id="btn-cut" class="btn-primary" style="margin-top:0.5rem;">
        <span>✂️</span>
        <span>Export Trimmed Log</span>
      </button>

      <div id="toast-msg" class="toast"></div>
    </div>
  </div>

  <!-- Right Column: GPS Map Drawer -->
  <div id="map-pane" class="map-pane">
    <div class="map-header">
      <div class="map-header-title">
        <span>🗺️</span>
        <span>GPS Route Preview</span>
      </div>
      <span id="gps-points-count" style="font-size:0.75rem; color:var(--text-muted); font-family:monospace;">0 pts</span>
    </div>
    <div id="map-view"></div>
    <div id="no-gps-card" class="no-gps-card" style="display:none;">
      <div style="font-size:2.5rem; margin-bottom:0.5rem;">📡</div>
      <div style="font-weight:600; font-size:0.95rem; margin-bottom:0.25rem;">No GPS Telemetry</div>
      <div style="font-size:0.75rem; color:var(--text-muted); max-width:260px;">This log capture does not contain RaceBox GPS coordinates (ID 0x601).</div>
    </div>
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  let currentLog = "";
  let logData = null;
  let gpsData = [];
  let leafletMap = null;
  let fullTrackLayer = null;
  let sliceTrackLayer = null;
  let startMarker = null;
  let endMarker = null;

  // OS System Theme Auto-Detection
  const osLight = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
  let savedTheme = localStorage.getItem('minigauge_theme') || (osLight ? 'light' : 'dark');
  document.documentElement.setAttribute('data-theme', savedTheme);

  document.getElementById('btn-theme').addEventListener('click', () => {
    savedTheme = savedTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    localStorage.setItem('minigauge_theme', savedTheme);
    updateMapSlice();
  });

  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
      if (!localStorage.getItem('minigauge_theme')) {
        savedTheme = e.matches ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', savedTheme);
        updateMapSlice();
      }
    });
  }

  // Toggle Map View
  document.getElementById('btn-toggle-map').addEventListener('click', () => {
    const mapPane = document.getElementById('map-pane');
    const btn = document.getElementById('btn-toggle-map');
    mapPane.classList.toggle('collapsed');
    const isCollapsed = mapPane.classList.contains('collapsed');
    btn.classList.toggle('active', !isCollapsed);
    if (!isCollapsed && leafletMap) {
      setTimeout(() => leafletMap.invalidateSize(), 200);
    }
  });

  async function loadLogs() {
    const res = await fetch('/api/logs');
    const logs = await res.json();
    const sel = document.getElementById('sel-log');
    sel.innerHTML = '';
    logs.forEach(l => {
      const opt = document.createElement('option');
      opt.value = l.filename;
      opt.textContent = `${l.filename} (${(l.size / 1024 / 1024).toFixed(1)} MB)`;
      sel.appendChild(opt);
    });
    if (logs.length > 0) {
      currentLog = logs[0].filename;
      loadPreview(currentLog);
    }
  }

  async function loadPreview(fn) {
    const res = await fetch(`/api/preview?file=${encodeURIComponent(fn)}`);
    logData = await res.json();
    gpsData = logData.gps || [];

    const sSlider = document.getElementById('slider-start');
    const eSlider = document.getElementById('slider-end');
    sSlider.max = logData.duration_s;
    eSlider.max = logData.duration_s;
    sSlider.value = 0;
    eSlider.value = logData.duration_s;

    updateSliderVisuals();
    renderWaveform();
    renderGpsMap();
  }

  function renderGpsMap() {
    const mapEl = document.getElementById('map-view');
    const noGpsEl = document.getElementById('no-gps-card');
    const ptsCountEl = document.getElementById('gps-points-count');

    if (!gpsData || gpsData.length === 0) {
      mapEl.style.display = 'none';
      noGpsEl.style.display = 'flex';
      ptsCountEl.textContent = '0 pts';
      return;
    }

    mapEl.style.display = 'block';
    noGpsEl.style.display = 'none';
    ptsCountEl.textContent = `${gpsData.length} pts`;

    if (!leafletMap) {
      leafletMap = L.map('map-view', { zoomControl: true });
      L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        attribution: '© OpenStreetMap, © CARTO'
      }).addTo(leafletMap);
    }

    if (fullTrackLayer) leafletMap.removeLayer(fullTrackLayer);
    if (sliceTrackLayer) leafletMap.removeLayer(sliceTrackLayer);
    if (startMarker) leafletMap.removeLayer(startMarker);
    if (endMarker) leafletMap.removeLayer(endMarker);
    startMarker = null;
    endMarker = null;

    const fullLatLngs = gpsData.map(p => [p.lat, p.lon]);
    fullTrackLayer = L.polyline(fullLatLngs, {
      color: '#64748b',
      weight: 4,
      opacity: 0.45,
      lineCap: 'round',
      lineJoin: 'round'
    }).addTo(leafletMap);

    const accentColor = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#dd6b3d';
    sliceTrackLayer = L.polyline(fullLatLngs, {
      color: accentColor,
      weight: 5,
      opacity: 0.95,
      lineCap: 'round',
      lineJoin: 'round'
    }).addTo(leafletMap);

    // Clicking anywhere on route snaps closest slider
    function onRouteClick(e) {
      if (!gpsData || gpsData.length === 0) return;
      let closest = gpsData[0];
      let minDist = Infinity;
      for (const pt of gpsData) {
        const d = Math.hypot(pt.lat - e.latlng.lat, pt.lon - e.latlng.lng);
        if (d < minDist) {
          minDist = d;
          closest = pt;
        }
      }
      const sVal = parseFloat(document.getElementById('slider-start').value);
      const eVal = parseFloat(document.getElementById('slider-end').value);
      if (Math.abs(closest.t - sVal) <= Math.abs(closest.t - eVal)) {
        document.getElementById('slider-start').value = closest.t;
      } else {
        document.getElementById('slider-end').value = closest.t;
      }
      updateSliderVisuals();
    }

    fullTrackLayer.on('click', onRouteClick);
    sliceTrackLayer.on('click', onRouteClick);

    leafletMap.fitBounds(fullTrackLayer.getBounds(), { padding: [25, 25] });
    updateMapSlice();
  }

  function updateMapSlice() {
    if (!gpsData || gpsData.length === 0 || !sliceTrackLayer) return;
    const s = parseFloat(document.getElementById('slider-start').value);
    const e = parseFloat(document.getElementById('slider-end').value);

    const sliced = gpsData.filter(p => p.t >= s && p.t <= e);
    const sliceCoords = sliced.map(p => [p.lat, p.lon]);
    sliceTrackLayer.setLatLngs(sliceCoords);

    const accentColor = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#dd6b3d';
    sliceTrackLayer.setStyle({ color: accentColor });

    if (sliceCoords.length > 0) {
      const startCoord = sliceCoords[0];
      const endCoord = sliceCoords[sliceCoords.length - 1];

      if (!startMarker) {
        startMarker = L.circleMarker(startCoord, {
          radius: 7,
          fillColor: '#10b981',
          color: '#ffffff',
          weight: 2,
          fillOpacity: 1
        }).addTo(leafletMap);
        startMarker.bindTooltip("Start Cut (t_start)");
      } else {
        startMarker.setLatLng(startCoord);
      }

      if (!endMarker) {
        endMarker = L.circleMarker(endCoord, {
          radius: 7,
          fillColor: '#ef4444',
          color: '#ffffff',
          weight: 2,
          fillOpacity: 1
        }).addTo(leafletMap);
        endMarker.bindTooltip("End Cut (t_end)");
      } else {
        endMarker.setLatLng(endCoord);
      }
    }
  }

  function updateSliderVisuals() {
    if (!logData) return;
    let s = parseFloat(document.getElementById('slider-start').value);
    let e = parseFloat(document.getElementById('slider-end').value);
    if (s > e) {
      e = s;
      document.getElementById('slider-end').value = e;
    }

    const max = logData.duration_s || 1;
    const sPct = (s / max) * 100;
    const ePct = (e / max) * 100;

    document.getElementById('slider-start').style.setProperty('--start-pct', `${sPct}%`);
    document.getElementById('slider-start').style.setProperty('--end-pct', `${ePct}%`);
    document.getElementById('slider-end').style.setProperty('--start-pct', `${sPct}%`);
    document.getElementById('slider-end').style.setProperty('--end-pct', `${ePct}%`);

    document.getElementById('val-start').textContent = `${s.toFixed(1)} s`;
    document.getElementById('val-end').textContent = `${e.toFixed(1)} s`;
    document.getElementById('val-window-span').textContent = `${s.toFixed(1)}s - ${e.toFixed(1)}s (Span: ${(e - s).toFixed(1)}s)`;

    updateMapSlice();
  }

  function renderWaveform() {
    if (!logData || !logData.speeds || logData.speeds.length === 0) return;
    const speeds = logData.speeds;
    const maxSpd = Math.max(10, Math.max(...speeds));
    const n = speeds.length;
    let d = `M 0,${100 - (speeds[0] / maxSpd) * 90}`;

    for (let i = 1; i < n; i++) {
      const x = (i / (n - 1)) * 800;
      const y = 100 - (speeds[i] / maxSpd) * 90;
      d += ` L ${x.toFixed(1)},${y.toFixed(1)}`;
    }
    document.getElementById('svg-speed-path').setAttribute('d', d);
  }

  document.getElementById('slider-start').addEventListener('input', updateSliderVisuals);
  document.getElementById('slider-end').addEventListener('input', updateSliderVisuals);
  document.getElementById('sel-log').addEventListener('change', (e) => {
    currentLog = e.target.value;
    loadPreview(currentLog);
  });

  document.getElementById('btn-cut').addEventListener('click', async () => {
    const btn = document.getElementById('btn-cut');
    const toast = document.getElementById('toast-msg');
    btn.disabled = true;
    btn.textContent = "Processing cut...";

    try {
      const payload = {
        filename: currentLog,
        start_s: parseFloat(document.getElementById('slider-start').value),
        end_s: parseFloat(document.getElementById('slider-end').value),
        rebase_zero: document.getElementById('chk-rebase').checked,
        ids: document.getElementById('txt-ids').value
      };

      const resp = await fetch('/api/trim', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await resp.json();

      if (data.status === 'ok') {
        toast.className = "toast success";
        toast.style.display = "block";
        toast.innerHTML = `✓ Successfully exported: <b>${data.output_file}</b> (${data.frames} frames, ${data.duration_s}s, ${(data.size_bytes / 1024).toFixed(1)} KB)`;
      } else {
        toast.className = "toast error";
        toast.style.display = "block";
        toast.textContent = `Error: ${data.message || 'Cut failed'}`;
      }
    } catch (err) {
      toast.className = "toast error";
      toast.style.display = "block";
      toast.textContent = `Request failed: ${err.message}`;
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<span>✂️</span><span>Export Trimmed Log</span>`;
    }
  });

  loadLogs();
</script>
</body>
</html>
"""


# ==============================================================================
# CLI ENTRY POINT
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="MiniGauge CAN Binary Log Trimmer & Slicer")
    parser.add_argument("input", nargs="?", type=Path, help="Input *.bin CAN log file")
    parser.add_argument("--start", "-s", type=float, help="Start time in seconds")
    parser.add_argument("--end", "-e", type=float, help="End time in seconds")
    parser.add_argument("--from-frame", type=int, help="Start frame index (0-based)")
    parser.add_argument("--to-frame", type=int, help="End frame index (inclusive)")
    parser.add_argument("--output", "-o", type=Path, help="Output *.bin file path")
    parser.add_argument("--preserve-timestamps", action="store_true", help="Keep raw hardware timestamps (default: zero-rebase)")
    parser.add_argument("--ids", type=str, help="Comma-separated CAN IDs to include (e.g. 0x100,0x301)")
    parser.add_argument("--gui", "--browser", "--web", action="store_true", help="Launch interactive browser GUI")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    parser.add_argument("--port", "-p", type=int, default=8199, help="GUI HTTP server port (default: 8199)")

    args = parser.parse_args()

    if args.gui or not args.input:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), TrimmerHttpHandler)
        url = f"http://127.0.0.1:{args.port}/"
        print(f"MiniGauge Log Trimmer GUI running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down Trimmer GUI server.")
        return

    allowed_ids = None
    if args.ids:
        allowed_ids = [int(x.strip(), 16) if x.strip().lower().startswith("0x") else int(x.strip()) for x in args.ids.split(",") if x.strip()]

    rebase_zero = not args.preserve_timestamps

    try:
        out_path, n_frames, dur = trim_log(
            args.input,
            output_path=args.output,
            start_s=args.start,
            end_s=args.end,
            from_frame=args.from_frame,
            to_frame=args.to_frame,
            rebase_zero=rebase_zero,
            allowed_ids=allowed_ids,
        )
        print(f"✓ Trimmed log successfully created: {out_path}")
        print(f"  Frames: {n_frames} | Duration: {dur:.2f}s | Size: {out_path.stat().st_size / 1024:.1f} KB")
        print(f"  Zero-rebased: {rebase_zero}")
    except Exception as e:
        print(f"Error trimming log: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()


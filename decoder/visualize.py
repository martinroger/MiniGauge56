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


# Global caches for decoded logs
LOG_CACHE: Dict[str, Dict[str, Any]] = {}
DBC_INSTANCE: Optional[DbcDatabase] = None
DBC_PATH: Optional[Path] = None
INITIAL_LOG_FILE: Optional[Path] = None


def natural_sort_key(p: Path):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', p.name)]


def find_bin_files(initial: Optional[Path] = None) -> List[Path]:
    """Finds all *.bin files in SCRIPT_DIR and CWD, including files starting with numbers."""
    seen = set()
    files: List[Path] = []

    # If an initial file was explicitly passed, make sure it is first
    if initial and initial.is_file():
        seen.add(initial.resolve())
        files.append(initial)

    # Search directories: SCRIPT_DIR and current directory
    search_dirs = [SCRIPT_DIR]
    cwd = Path(".").resolve()
    if cwd != SCRIPT_DIR.resolve():
        search_dirs.append(Path("."))

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
        }
        LOG_CACHE[key] = result
        return result

    duration_s = frames[-1].time_rel_s
    signals_data: Dict[str, Dict[str, Any]] = {}
    message_meta: Dict[str, Dict[str, Any]] = {}

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

    result = {
        "mtime": mtime,
        "filename": log_path.name,
        "size": log_path.stat().st_size,
        "frame_count": len(frames),
        "duration_s": duration_s,
        "signals": signals_data,
        "messages": message_meta,
    }
    LOG_CACHE[key] = result
    return result


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MiniGauge CAN Signal Visualizer</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {
      --bg: #121417;
      --card-bg: #1a1d23;
      --panel-border: #2c323d;
      --text: #e2e8f0;
      --text-muted: #94a3b8;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --accent: #10b981;
      --danger: #ef4444;
      --tag-bg: #222731;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }
    header {
      background: var(--card-bg);
      border-bottom: 1px solid var(--panel-border);
      padding: 0.5rem 1.25rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      flex-wrap: wrap;
    }
    .header-left {
      display: flex;
      align-items: center;
      gap: 0.8rem;
    }
    .logo {
      font-weight: 700;
      font-size: 1.05rem;
      color: #60a5fa;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .logo-badge {
      font-size: 0.7rem;
      background: #1e3a8a;
      color: #93c5fd;
      padding: 2px 6px;
      border-radius: 4px;
      font-weight: normal;
    }
    .log-selector {
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }
    select, input[type="text"], input[type="number"] {
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--panel-border);
      border-radius: 6px;
      padding: 0.35rem 0.65rem;
      font-size: 0.85rem;
      outline: none;
    }
    select:focus, input[type="text"]:focus, input[type="number"]:focus {
      border-color: var(--primary);
    }
    .header-controls {
      display: flex;
      align-items: center;
      gap: 0.55rem;
      flex-wrap: wrap;
    }
    .segmented-control {
      display: flex;
      background: var(--bg);
      border-radius: 6px;
      border: 1px solid var(--panel-border);
      padding: 2px;
    }
    .segmented-control button {
      border: none;
      background: transparent;
      padding: 0.25rem 0.6rem;
      border-radius: 4px;
      font-size: 0.78rem;
      cursor: pointer;
      color: var(--text-muted);
    }
    .segmented-control button:hover {
      color: var(--text);
    }
    .segmented-control button.active {
      background: var(--primary);
      color: white;
    }
    .time-controls {
      display: flex;
      align-items: center;
      gap: 0.35rem;
      background: var(--bg);
      padding: 2px 6px;
      border-radius: 6px;
      border: 1px solid var(--panel-border);
    }
    .time-controls label {
      font-size: 0.78rem;
      color: var(--text-muted);
    }
    .time-input {
      width: 65px;
      padding: 0.25rem 0.4rem !important;
      font-size: 0.8rem !important;
      text-align: right;
    }
    button {
      background: var(--card-bg);
      color: var(--text);
      border: 1px solid var(--panel-border);
      border-radius: 6px;
      padding: 0.35rem 0.7rem;
      font-size: 0.82rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      transition: all 0.15s ease;
    }
    button:hover {
      background: #28303d;
      border-color: var(--primary);
    }
    button.primary {
      background: var(--primary);
      border-color: var(--primary);
      color: white;
    }
    button.primary:hover {
      background: var(--primary-hover);
    }
    .btn-icon {
      padding: 0.35rem 0.55rem;
      font-weight: bold;
    }
    .btn-active-toggle {
      background: #1e3a8a;
      border-color: #3b82f6;
      color: #93c5fd;
    }
    .main-container {
      display: flex;
      flex: 1;
      overflow: hidden;
      position: relative;
    }
    .sidebar {
      width: 320px;
      background: var(--card-bg);
      border-right: 1px solid var(--panel-border);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
    }
    .sidebar-header {
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--panel-border);
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
    }
    .search-box {
      width: 100%;
    }
    .presets-row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
    }
    .preset-pill {
      font-size: 0.72rem;
      padding: 2px 8px;
      border-radius: 12px;
      background: var(--tag-bg);
      border: 1px solid var(--panel-border);
      cursor: pointer;
      color: var(--text-muted);
    }
    .preset-pill:hover {
      color: var(--text);
      border-color: var(--primary);
    }
    .signal-actions {
      display: flex;
      justify-content: space-between;
      font-size: 0.78rem;
      color: var(--text-muted);
      padding: 0.25rem 0;
      align-items: center;
    }
    .signal-actions a {
      color: var(--primary);
      text-decoration: none;
      cursor: pointer;
    }
    .signal-actions a:hover {
      text-decoration: underline;
    }
    .signal-list {
      flex: 1;
      overflow-y: auto;
      padding: 0.5rem 0;
    }
    .msg-group {
      margin-bottom: 0.25rem;
    }
    .msg-title {
      padding: 0.35rem 0.75rem;
      font-size: 0.75rem;
      font-weight: 600;
      letter-spacing: 0.03em;
      color: var(--text-muted);
      background: rgba(255, 255, 255, 0.02);
      display: flex;
      justify-content: space-between;
      align-items: center;
      cursor: pointer;
      user-select: none;
      transition: background 0.1s;
    }
    .msg-title:hover {
      color: var(--text);
      background: rgba(255, 255, 255, 0.05);
    }
    .msg-title-left {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
    }
    .chevron {
      font-size: 0.65rem;
      color: var(--text-muted);
      display: inline-block;
      width: 14px;
      text-align: center;
      transition: transform 0.15s ease;
    }
    .group-select-cb {
      cursor: pointer;
      margin-right: 2px;
    }
    .msg-count-badge {
      font-size: 0.7rem;
      background: var(--tag-bg);
      padding: 1px 6px;
      border-radius: 10px;
      color: var(--text-muted);
      font-weight: normal;
    }
    .msg-count-badge.has-selected {
      background: #1e3a8a;
      color: #93c5fd;
      font-weight: 600;
    }
    .msg-sigs-container {
      display: block;
    }
    .sig-item {
      padding: 0.3rem 0.75rem 0.3rem 2rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.85rem;
      cursor: pointer;
      transition: background 0.1s;
    }
    .sig-item:hover {
      background: rgba(255, 255, 255, 0.04);
    }
    .sig-item input[type="checkbox"] {
      cursor: pointer;
    }
    .sig-name {
      flex: 1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .sig-unit {
      font-size: 0.75rem;
      color: var(--text-muted);
      background: var(--tag-bg);
      padding: 1px 5px;
      border-radius: 4px;
    }
    .chart-container {
      flex: 1;
      display: flex;
      flex-direction: column;
      background: var(--bg);
      position: relative;
    }
    #plot {
      width: 100%;
      height: 100%;
    }
    .empty-state {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      text-align: center;
      color: var(--text-muted);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 1rem;
    }
    .empty-state svg {
      width: 64px;
      height: 64px;
      stroke: var(--panel-border);
    }
    .stats-footer {
      background: var(--card-bg);
      border-top: 1px solid var(--panel-border);
      padding: 0.35rem 1rem;
      display: flex;
      gap: 1.5rem;
      font-size: 0.78rem;
      color: var(--text-muted);
      align-items: center;
    }
    .stats-footer span strong {
      color: var(--text);
    }

    /* Axis Scales Drawer Modal */
    .modal-overlay {
      display: none;
      position: absolute;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.5);
      z-index: 100;
      justify-content: flex-end;
    }
    .modal-panel {
      width: 420px;
      height: 100%;
      background: var(--card-bg);
      border-left: 1px solid var(--panel-border);
      display: flex;
      flex-direction: column;
      box-shadow: -4px 0 20px rgba(0, 0, 0, 0.4);
    }
    .modal-header {
      padding: 0.9rem 1.25rem;
      border-bottom: 1px solid var(--panel-border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-title {
      font-weight: 600;
      font-size: 0.95rem;
    }
    .modal-body {
      flex: 1;
      overflow-y: auto;
      padding: 1rem;
      display: flex;
      flex-direction: column;
      gap: 0.85rem;
    }
    .axis-config-card {
      background: var(--bg);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      padding: 0.75rem;
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
    }
    .axis-card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .axis-card-title {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.88rem;
      font-weight: 600;
    }
    .color-pill {
      width: 12px;
      height: 12px;
      border-radius: 50%;
      display: inline-block;
    }
    .axis-quick-actions {
      display: flex;
      gap: 0.3rem;
    }
    .axis-btn-mini {
      padding: 0.15rem 0.45rem;
      font-size: 0.75rem;
      background: var(--card-bg);
      border: 1px solid var(--panel-border);
      border-radius: 4px;
    }
    .axis-btn-mini:hover {
      background: #2a313d;
      border-color: var(--primary);
    }
    .axis-inputs-row {
      display: flex;
      gap: 0.5rem;
      align-items: center;
    }
    .axis-inputs-row label {
      font-size: 0.75rem;
      color: var(--text-muted);
    }
    .axis-inputs-row input {
      width: 75px;
    }
    .modal-footer {
      padding: 0.75rem 1rem;
      border-top: 1px solid var(--panel-border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  </style>
</head>
<body>
  <header>
    <div class="header-left">
      <div class="logo">
        MiniGauge CAN
        <span class="logo-badge">Visualizer</span>
      </div>
      <div class="log-selector">
        <label for="logFileSelect" style="font-size: 0.82rem; color: var(--text-muted);">Log:</label>
        <select id="logFileSelect"></select>
      </div>
    </div>

    <div class="header-controls">
      <!-- Mouse Drag Tool Switcher: Pan vs Box Zoom -->
      <div class="segmented-control">
        <button id="btnToolPan" class="active" title="Pan mode: click and drag anywhere to move X & Y freely">✋ Pan</button>
        <button id="btnToolZoom" title="Box Zoom mode: click and drag to draw a zoom box">🔍 Zoom</button>
      </div>

      <!-- Time interval zoom controls -->
      <div class="time-controls">
        <label>Time (s):</label>
        <input type="number" id="timeFrom" class="time-input" placeholder="0.0" step="any">
        <label>to</label>
        <input type="number" id="timeTo" class="time-input" placeholder="max" step="any">
        <button id="btnApplyTime" title="Set specific time window">Apply</button>
        <button id="btnZoomIn" class="btn-icon" title="Zoom in 2x around center">+</button>
        <button id="btnZoomOut" class="btn-icon" title="Zoom out 2x around center">&minus;</button>
        <button id="btnResetZoom" title="Reset to full log duration">Fit</button>
      </div>

      <!-- Mode toggle -->
      <div class="segmented-control">
        <button id="btnOverlay" class="active" title="Overlay multiple signals with dedicated Y-axes">Multi-Axis</button>
        <button id="btnSubplots" title="Stack signals vertically sharing time axis">Subplots</button>
      </div>

      <!-- Y Axis scale modal button -->
      <button id="btnOpenAxisModal" title="Configure manual Min/Max scales and panning for Y-axes">
        <span>Y Scales</span>
      </button>

      <!-- Range Slider Toggle -->
      <button id="btnToggleSlider" title="Toggle bottom timeline range slider (when hidden, 2D Y-panning is fully unlocked)">
        <span>⇋ Slider</span>
      </button>

      <button id="btnExportPng">Export PNG</button>
    </div>
  </header>

  <div class="main-container">
    <div class="sidebar">
      <div class="sidebar-header">
        <input type="text" id="signalSearch" class="search-box" placeholder="Search signals (e.g. rpm, temp)...">
        <div class="presets-row">
          <div class="preset-pill" data-preset="speed">Speed & RPM</div>
          <div class="preset-pill" data-preset="coolant">Coolant & Temp</div>
          <div class="preset-pill" data-preset="fuel">Fuel & Power</div>
          <div class="preset-pill" data-preset="telltales">Telltales</div>
          <div class="preset-pill" data-preset="gps">GPS & IMU</div>
        </div>
        <div class="signal-actions">
          <span id="selectedCount">0 selected</span>
          <div>
            <a id="btnSelectAll">All</a> &bull;
            <a id="btnClearAll">Clear</a> &bull;
            <a id="btnCollapseAll" title="Collapse all message groups">Collapse</a> &bull;
            <a id="btnExpandAll" title="Expand all message groups">Expand</a>
          </div>
        </div>
      </div>
      <div class="signal-list" id="signalList"></div>
    </div>

    <div class="chart-container">
      <div id="plot"></div>
      <div class="empty-state" id="emptyState">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M3 3v18h18" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M19 9l-5 5-4-4-3 3" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <p>No signals selected. Pick one or more signals from the left sidebar to plot.</p>
      </div>
    </div>

    <!-- Axis Scales Drawer -->
    <div class="modal-overlay" id="axisModal">
      <div class="modal-panel">
        <div class="modal-header">
          <div class="modal-title">Y-Axis Scale & Pan Controls</div>
          <button id="btnCloseAxisModal">&times;</button>
        </div>
        <div class="modal-body" id="axisModalBody">
          <!-- Dynamically populated for each active axis/unit -->
        </div>
        <div class="modal-footer">
          <button id="btnResetAllAxes">Auto All Axes</button>
          <button class="primary" id="btnApplyAllAxes">Apply Changes</button>
        </div>
      </div>
    </div>
  </div>

  <div class="stats-footer">
    <span>File: <strong id="statFile">-</strong></span>
    <span>Frames: <strong id="statFrames">-</strong></span>
    <span>Duration: <strong id="statDuration">-</strong></span>
    <span>Size: <strong id="statSize">-</strong></span>
    <span>Plotted points: <strong id="statPoints">0</strong></span>
    <span style="margin-left:auto; color: #64748b; font-size: 0.74rem;">
      <strong>Pan:</strong> Drag anywhere &bull; <strong>Zoom Time:</strong> Wheel &bull; <strong>Pan Time:</strong> Shift+Wheel &bull; <strong>Pan Y:</strong> Alt+Wheel &bull; <strong>Zoom Y:</strong> Ctrl+Wheel
    </span>
  </div>

  <script>
    let currentLog = "";
    let availableSignals = {};
    let selectedSignals = new Set();
    let currentMode = "overlay"; // "overlay" or "subplots"
    let currentDragTool = "pan"; // "pan" or "zoom"
    let isRangeSliderVisible = false; // default false to allow free 2D Y-panning
    let currentDuration = 0.0;
    let customYRanges = {}; // { [unit]: { min: number|null, max: number|null, auto: boolean } }
    let currentTimeRange = [0, null]; // [x0, x1]
    let activeUnitsList = []; // active units and their assigned colors
    let collapsedGroups = new Set();
    let isSyncingAxes = false;
    let lastBaseYRange = null;

    const COLORS = [
      '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
      '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#a855f7',
      '#14b8a6', '#6366f1', '#e11d48', '#d946ef', '#eab308',
      '#22c55e', '#0284c7', '#f43f5e', '#38bdf8', '#4ade80',
      '#fb923c', '#c084fc', '#2dd4bf', '#fb7185', '#a3e635',
      '#818cf8', '#facc15', '#34d399', '#f472b6', '#60a5fa',
      '#38bdf8', '#fbbf24'
    ];

    async function init() {
      await loadLogs();
      setupEventListeners();
      setupInteractiveWheelController();
    }

    async function loadLogs() {
      try {
        const res = await fetch('/api/logs');
        const logs = await res.json();
        const select = document.getElementById('logFileSelect');
        select.innerHTML = '';

        if (logs.length === 0) {
          select.innerHTML = '<option>No .bin files found</option>';
          return;
        }

        logs.forEach((log) => {
          const opt = document.createElement('option');
          opt.value = log.filename;
          opt.textContent = `${log.filename} (${(log.size / 1024).toFixed(1)} KB, ${log.duration_s.toFixed(1)}s)`;
          select.appendChild(opt);
        });

        currentLog = logs[0].filename;
        await loadSignals(currentLog);
      } catch (err) {
        console.error('Failed to load logs:', err);
      }
    }

    async function loadSignals(filename) {
      try {
        const res = await fetch(`/api/signals?file=${encodeURIComponent(filename)}`);
        const data = await res.json();

        currentDuration = data.duration_s;
        currentTimeRange = [0, currentDuration];
        document.getElementById('timeFrom').value = "0.0";
        document.getElementById('timeTo').value = currentDuration.toFixed(2);

        document.getElementById('statFile').textContent = data.filename;
        document.getElementById('statFrames').textContent = data.frame_count.toLocaleString();
        document.getElementById('statDuration').textContent = `${data.duration_s.toFixed(2)}s`;
        document.getElementById('statSize').textContent = `${(data.size / 1024).toFixed(1)} KB`;

        availableSignals = data.signals;
        renderSignalList();
        
        // Retain selections if they exist in new log, or pick default
        const validSelections = new Set([...selectedSignals].filter(s => availableSignals[s]));
        if (validSelections.size === 0) {
          const sigKeys = Object.keys(availableSignals);
          if (sigKeys.length > 0) {
            validSelections.add(sigKeys[0]);
            if (sigKeys.length > 1) validSelections.add(sigKeys[1]);
          }
        }
        selectedSignals = validSelections;
        updateCheckboxes();
        await updatePlot();
      } catch (err) {
        console.error('Failed to load signals:', err);
      }
    }

    function renderSignalList() {
      const container = document.getElementById('signalList');
      container.innerHTML = '';
      const filter = document.getElementById('signalSearch').value.toLowerCase();

      const groups = {};
      for (const [name, info] of Object.entries(availableSignals)) {
        if (filter && !name.toLowerCase().includes(filter) && !info.message.toLowerCase().includes(filter)) {
          continue;
        }
        if (!groups[info.message]) {
          groups[info.message] = [];
        }
        groups[info.message].push({ name, ...info });
      }

      for (const [msgName, sigs] of Object.entries(groups)) {
        const groupEl = document.createElement('div');
        groupEl.className = 'msg-group';
        const isCollapsed = collapsedGroups.has(msgName);

        const selectedInGroup = sigs.filter(s => selectedSignals.has(s.name)).length;

        // Group Header
        const titleEl = document.createElement('div');
        titleEl.className = 'msg-title';

        // Left section of title (chevron, checkbox, name)
        const leftEl = document.createElement('div');
        leftEl.className = 'msg-title-left';

        const chevron = document.createElement('span');
        chevron.className = 'chevron';
        chevron.textContent = isCollapsed ? '▶' : '▼';

        const groupCb = document.createElement('input');
        groupCb.type = 'checkbox';
        groupCb.className = 'group-select-cb';
        groupCb.checked = selectedInGroup === sigs.length && sigs.length > 0;
        groupCb.indeterminate = selectedInGroup > 0 && selectedInGroup < sigs.length;
        groupCb.title = 'Select/Deselect all signals in this message';
        groupCb.onclick = (e) => {
          e.stopPropagation();
          const checkAll = e.target.checked;
          sigs.forEach(s => {
            if (checkAll) selectedSignals.add(s.name);
            else selectedSignals.delete(s.name);
          });
          updateCheckboxes();
          updatePlot();
        };

        const nameSpan = document.createElement('span');
        nameSpan.textContent = msgName;

        leftEl.appendChild(chevron);
        leftEl.appendChild(groupCb);
        leftEl.appendChild(nameSpan);

        // Right badge
        const badge = document.createElement('span');
        badge.className = `msg-count-badge ${selectedInGroup > 0 ? 'has-selected' : ''}`;
        badge.textContent = `${selectedInGroup}/${sigs.length}`;

        titleEl.appendChild(leftEl);
        titleEl.appendChild(badge);

        // Clicking title row toggles collapse
        titleEl.onclick = (e) => {
          if (e.target === groupCb) return;
          if (collapsedGroups.has(msgName)) {
            collapsedGroups.delete(msgName);
          } else {
            collapsedGroups.add(msgName);
          }
          renderSignalList();
        };

        groupEl.appendChild(titleEl);

        // Signals container
        const sigsContainer = document.createElement('div');
        sigsContainer.className = 'msg-sigs-container';
        sigsContainer.style.display = isCollapsed ? 'none' : 'block';

        sigs.forEach(sig => {
          const itemEl = document.createElement('label');
          itemEl.className = 'sig-item';

          const cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.value = sig.name;
          cb.checked = selectedSignals.has(sig.name);
          cb.onchange = (e) => {
            if (e.target.checked) selectedSignals.add(sig.name);
            else selectedSignals.delete(sig.name);
            updateSelectedCount();
            renderSignalList();
            updatePlot();
          };

          const sName = document.createElement('span');
          sName.className = 'sig-name';
          sName.textContent = sig.name;
          sName.title = sig.name;

          itemEl.appendChild(cb);
          itemEl.appendChild(sName);

          if (sig.unit) {
            const unitSpan = document.createElement('span');
            unitSpan.className = 'sig-unit';
            unitSpan.textContent = sig.unit;
            itemEl.appendChild(unitSpan);
          }

          sigsContainer.appendChild(itemEl);
        });

        groupEl.appendChild(sigsContainer);
        container.appendChild(groupEl);
      }
      updateSelectedCount();
    }

    function updateCheckboxes() {
      document.querySelectorAll('#signalList input[type="checkbox"]').forEach(cb => {
        if (cb.classList.contains('group-select-cb')) return;
        cb.checked = selectedSignals.has(cb.value);
      });
      updateSelectedCount();
    }

    function updateSelectedCount() {
      document.getElementById('selectedCount').textContent = `${selectedSignals.size} selected`;
    }

    async function updatePlot() {
      const emptyState = document.getElementById('emptyState');
      const plotDiv = document.getElementById('plot');

      if (selectedSignals.size === 0) {
        emptyState.style.display = 'flex';
        Plotly.purge(plotDiv);
        document.getElementById('statPoints').textContent = '0';
        return;
      }
      emptyState.style.display = 'none';

      const sigList = Array.from(selectedSignals).join(',');
      const res = await fetch(`/api/data?file=${encodeURIComponent(currentLog)}&signals=${encodeURIComponent(sigList)}`);
      const data = await res.json();

      let totalPoints = 0;
      const traces = [];
      const layout = {
        paper_bgcolor: '#121417',
        plot_bgcolor: '#16191f',
        margin: { t: 40, r: 60, b: 60, l: 60 },
        hovermode: 'x unified',
        dragmode: currentDragTool, // 'pan' or 'zoom'
        showlegend: true,
        legend: {
          orientation: 'h',
          y: 1.14,
          x: 0,
          font: { color: '#e2e8f0', size: 11 }
        },
        xaxis: {
          title: { text: 'Time (seconds)', font: { color: '#94a3b8' } },
          gridcolor: '#242a35',
          zerolinecolor: '#2c323d',
          tickfont: { color: '#94a3b8' },
          rangeslider: {
            visible: isRangeSliderVisible,
            thickness: 0.07,
            bgcolor: '#16191f',
            bordercolor: '#2c323d'
          }
        }
      };

      if (currentTimeRange[0] !== null && currentTimeRange[1] !== null) {
        layout.xaxis.range = [currentTimeRange[0], currentTimeRange[1]];
      }

      activeUnitsList = [];

      if (currentMode === "overlay") {
        // Multi-axis overlay mode
        const units = [];
        const unitToAxis = {};

        Object.entries(data).forEach(([sigName, sigData]) => {
          const unit = sigData.unit || 'raw';
          if (!unitToAxis[unit]) {
            units.push(unit);
            unitToAxis[unit] = units.length === 1 ? 'y' : `y${units.length}`;
            activeUnitsList.push({
              unit: unit,
              color: COLORS[(units.length - 1) % COLORS.length],
              axisKey: units.length === 1 ? 'yaxis' : `yaxis${units.length}`
            });
          }
        });

        // Configure Y axes in layout
        units.forEach((unit, idx) => {
          const axisKey = idx === 0 ? 'yaxis' : `yaxis${idx + 1}`;
          const isRight = idx > 0;
          const axisColor = COLORS[idx % COLORS.length];

          const axisConfig = {
            title: { text: unit !== 'raw' ? unit : '', font: { color: axisColor } },
            tickfont: { color: axisColor },
            gridcolor: idx === 0 ? '#242a35' : 'transparent',
            zerolinecolor: idx === 0 ? '#2c323d' : 'transparent',
            overlaying: idx === 0 ? undefined : 'y',
            side: isRight ? 'right' : 'left',
            position: isRight ? Math.max(0.85, 1.0 - (idx - 1) * 0.05) : undefined,
            fixedrange: isRangeSliderVisible ? true : false // unfix when slider is off to allow free Y-pan
          };

          if (customYRanges[unit] && !customYRanges[unit].auto) {
            const rMin = customYRanges[unit].min;
            const rMax = customYRanges[unit].max;
            if (rMin !== null && rMax !== null && rMin < rMax) {
              axisConfig.range = [rMin, rMax];
              axisConfig.autorange = false;
            }
          }

          layout[axisKey] = axisConfig;
        });

        // Configure traces with distinct color per signal
        const sigNames = Object.keys(data);
        sigNames.forEach((sigName, sigIdx) => {
          const sigData = data[sigName];
          totalPoints += sigData.times.length;
          const yaxis = unitToAxis[sigData.unit || 'raw'];
          // Use sigIdx to guarantee every signal gets a distinct color
          const color = COLORS[sigIdx % COLORS.length];

          // Format hover values showing interpreted enum states when available
          const hoverDisplay = sigData.states.map((st, i) => {
            const v = sigData.values[i];
            const u = sigData.unit ? ` ${sigData.unit}` : '';
            if (st && st.trim() !== '') {
              return `${st} (${v}${u})`;
            }
            return `${v}${u}`;
          });

          traces.push({
            name: sigData.unit ? `${sigName} (${sigData.unit})` : sigName,
            x: sigData.times,
            y: sigData.values,
            yaxis: yaxis,
            customdata: hoverDisplay,
            text: hoverDisplay,
            hovertemplate: '%{fullData.name}: %{customdata}<extra></extra>',
            mode: 'lines',
            line: { width: 1.8, color: color },
            type: 'scatter'
          });
        });
      } else {
        // Stacked subplots mode
        const sigKeys = Object.keys(data);
        const count = sigKeys.length;
        layout.grid = { rows: count, columns: 1, pattern: 'independent' };

        // Top subplot xaxis rangeslider must be disabled when multiple subplots exist
        if (count > 1) {
          layout.xaxis = {
            gridcolor: '#242a35',
            tickfont: { color: '#94a3b8' },
            showticklabels: false,
            rangeslider: { visible: false }
          };
          if (currentTimeRange[0] !== null && currentTimeRange[1] !== null) {
            layout.xaxis.range = [currentTimeRange[0], currentTimeRange[1]];
          }
        }

        sigKeys.forEach((sigName, idx) => {
          const sigData = data[sigName];
          totalPoints += sigData.times.length;
          const axisNum = idx + 1;
          const yaxisKey = axisNum === 1 ? 'yaxis' : `yaxis${axisNum}`;
          const xaxisKey = axisNum === 1 ? 'xaxis' : `xaxis${axisNum}`;
          const color = COLORS[idx % COLORS.length];
          const isBottom = axisNum === count;

          const unitKey = sigData.unit || sigName;
          activeUnitsList.push({ unit: unitKey, color: color, axisKey: yaxisKey });

          const yaxisConfig = {
            title: { text: sigData.unit || sigName, font: { color: color, size: 10 } },
            tickfont: { color: color, size: 9 },
            gridcolor: '#242a35',
            fixedrange: isRangeSliderVisible ? true : false
          };

          // If signal has discrete states/value table, show tick labels on Y axis
          const uniqueStatesMap = new Map();
          for (let i = 0; i < sigData.values.length; i++) {
            const v = sigData.values[i];
            const st = sigData.states[i];
            if (st && st.trim() !== '' && !uniqueStatesMap.has(v)) {
              uniqueStatesMap.set(v, st);
            }
          }
          if (uniqueStatesMap.size > 0 && uniqueStatesMap.size <= 16) {
            const sortedVals = Array.from(uniqueStatesMap.keys()).sort((a,b) => a - b);
            yaxisConfig.tickmode = 'array';
            yaxisConfig.tickvals = sortedVals;
            yaxisConfig.ticktext = sortedVals.map(v => uniqueStatesMap.get(v));
          }

          if (customYRanges[unitKey] && !customYRanges[unitKey].auto) {
            const rMin = customYRanges[unitKey].min;
            const rMax = customYRanges[unitKey].max;
            if (rMin !== null && rMax !== null && rMin < rMax) {
              yaxisConfig.range = [rMin, rMax];
              yaxisConfig.autorange = false;
            }
          }

          layout[yaxisKey] = yaxisConfig;

          // X-axis configuration: only bottommost scope gets the tick labels, title, and slider
          layout[xaxisKey] = {
            matches: axisNum > 1 ? 'x' : undefined,
            gridcolor: '#242a35',
            tickfont: { color: '#94a3b8' },
            showticklabels: isBottom,
            title: isBottom ? { text: 'Time (seconds)', font: { color: '#94a3b8' } } : undefined,
            rangeslider: {
              visible: isBottom ? isRangeSliderVisible : false,
              thickness: 0.08,
              bgcolor: '#16191f',
              bordercolor: '#2c323d'
            }
          };

          if (axisNum === 1 && currentTimeRange[0] !== null && currentTimeRange[1] !== null) {
            layout[xaxisKey].range = [currentTimeRange[0], currentTimeRange[1]];
          }

          // Format hover values showing interpreted enum states when available
          const hoverDisplay = sigData.states.map((st, i) => {
            const v = sigData.values[i];
            const u = sigData.unit ? ` ${sigData.unit}` : '';
            if (st && st.trim() !== '') {
              return `${st} (${v}${u})`;
            }
            return `${v}${u}`;
          });

          traces.push({
            name: sigData.unit ? `${sigName} (${sigData.unit})` : sigName,
            x: sigData.times,
            y: sigData.values,
            xaxis: axisNum === 1 ? 'x' : `x${axisNum}`,
            yaxis: axisNum === 1 ? 'y' : `y${axisNum}`,
            customdata: hoverDisplay,
            text: hoverDisplay,
            hovertemplate: '<b>%{fullData.name}</b>: %{customdata}<extra></extra>',
            mode: 'lines',
            line: { width: 1.8, color: color },
            type: 'scatter'
          });
        });
      }

      document.getElementById('statPoints').textContent = totalPoints.toLocaleString();
      await Plotly.react(plotDiv, traces, layout, { responsive: true, displayModeBar: false });

      // Save initial base range
      if (plotDiv._fullLayout && plotDiv._fullLayout.yaxis && plotDiv._fullLayout.yaxis.range) {
        lastBaseYRange = [...plotDiv._fullLayout.yaxis.range];
      }

      // Synchronize relayout events (zoom/pan) with numeric inputs & secondary axes
      plotDiv.removeAllListeners && plotDiv.removeAllListeners('plotly_relayout');
      plotDiv.on('plotly_relayout', (eventData) => {
        let x0 = null, x1 = null;
        if (eventData['xaxis.range[0]'] !== undefined) {
          x0 = Number(eventData['xaxis.range[0]']);
          x1 = Number(eventData['xaxis.range[1]']);
        } else if (eventData['xaxis.range'] !== undefined) {
          x0 = Number(eventData['xaxis.range'][0]);
          x1 = Number(eventData['xaxis.range'][1]);
        } else if (eventData['xaxis.autorange'] === true) {
          x0 = 0.0;
          x1 = currentDuration;
        }

        if (x0 !== null && x1 !== null && !isNaN(x0) && !isNaN(x1)) {
          currentTimeRange = [x0, x1];
          document.getElementById('timeFrom').value = x0.toFixed(2);
          document.getElementById('timeTo').value = x1.toFixed(2);
        }

        // Multi-axis 2D Pan synchronization:
        // When the primary yaxis is panned/scaled, shift secondary axes proportionally
        if (!isSyncingAxes && eventData['yaxis.range[0]'] !== undefined && lastBaseYRange) {
          const newY0 = eventData['yaxis.range[0]'];
          const newY1 = eventData['yaxis.range[1]'];
          const oldSpan = lastBaseYRange[1] - lastBaseYRange[0];
          const newSpan = newY1 - newY0;
          const shiftFraction = ((newY0 + newY1) / 2 - (lastBaseYRange[0] + lastBaseYRange[1]) / 2) / (oldSpan || 1);
          const spanRatio = newSpan / (oldSpan || 1);
          lastBaseYRange = [newY0, newY1];

          if (activeUnitsList.length > 1 && currentMode === "overlay") {
            isSyncingAxes = true;
            const syncUpdate = {};
            activeUnitsList.slice(1).forEach(item => {
              const axLayout = plotDiv._fullLayout[item.axisKey];
              if (axLayout && axLayout.range) {
                const [sy0, sy1] = axLayout.range;
                const sSpan = sy1 - sy0;
                const sCenter = (sy0 + sy1) / 2 + sSpan * shiftFraction;
                const sNewSpan = sSpan * spanRatio;
                const n0 = sCenter - sNewSpan / 2;
                const n1 = sCenter + sNewSpan / 2;
                syncUpdate[`${item.axisKey}.range`] = [n0, n1];
                customYRanges[item.unit] = {
                  min: Number(n0.toFixed(3)),
                  max: Number(n1.toFixed(3)),
                  auto: false
                };
              }
            });
            Plotly.relayout(plotDiv, syncUpdate).then(() => {
              isSyncingAxes = false;
            });
          }
        }

        // Update customYRanges from relayout
        activeUnitsList.forEach(item => {
          const key0 = `${item.axisKey}.range[0]`;
          const key1 = `${item.axisKey}.range[1]`;
          if (eventData[key0] !== undefined && eventData[key1] !== undefined) {
            customYRanges[item.unit] = {
              min: Number(eventData[key0].toFixed(3)),
              max: Number(eventData[key1].toFixed(3)),
              auto: false
            };
          }
        });
      });
    }

    // Time Zoom helpers
    function setTimeWindow(x0, x1) {
      if (x0 < 0) x0 = 0;
      if (x1 > currentDuration && currentDuration > 0) x1 = currentDuration;
      if (x1 <= x0) x1 = x0 + 0.1;

      currentTimeRange = [x0, x1];
      document.getElementById('timeFrom').value = x0.toFixed(2);
      document.getElementById('timeTo').value = x1.toFixed(2);

      const plotDiv = document.getElementById('plot');
      Plotly.relayout(plotDiv, {
        'xaxis.range[0]': x0,
        'xaxis.range[1]': x1
      });
    }

    function zoomIn() {
      let [x0, x1] = currentTimeRange;
      if (x0 === null) x0 = 0;
      if (x1 === null) x1 = currentDuration;
      const center = (x0 + x1) / 2;
      const span = (x1 - x0) / 2;
      setTimeWindow(center - span / 2, center + span / 2);
    }

    function zoomOut() {
      let [x0, x1] = currentTimeRange;
      if (x0 === null) x0 = 0;
      if (x1 === null) x1 = currentDuration;
      const center = (x0 + x1) / 2;
      const span = (x1 - x0) * 2;
      setTimeWindow(center - span / 2, center + span / 2);
    }

    // Independent Axis Panning and Scaling
    function nudgeAxis(unit, panDeltaPercent, zoomScaleFactor) {
      const plotDiv = document.getElementById('plot');
      if (!plotDiv._fullLayout) return;

      const item = activeUnitsList.find(u => u.unit === unit);
      if (!item) return;

      const axisLayout = plotDiv._fullLayout[item.axisKey];
      if (!axisLayout || !axisLayout.range) return;

      let [y0, y1] = axisLayout.range;
      const span = (y1 - y0);

      if (panDeltaPercent !== 0) {
        const shift = span * panDeltaPercent;
        y0 += shift;
        y1 += shift;
      }

      if (zoomScaleFactor !== 1) {
        const center = (y0 + y1) / 2;
        const newSpan = span * zoomScaleFactor;
        y0 = center - newSpan / 2;
        y1 = center + newSpan / 2;
      }

      customYRanges[unit] = {
        min: Number(y0.toFixed(3)),
        max: Number(y1.toFixed(3)),
        auto: false
      };

      Plotly.relayout(plotDiv, {
        [`${item.axisKey}.range`]: [y0, y1],
        [`${item.axisKey}.autorange`]: false
      });

      renderAxisModal();
    }

    // Cursor-centered Wheel and Pan Controller
    function setupInteractiveWheelController() {
      const plotDiv = document.getElementById('plot');

      plotDiv.addEventListener('wheel', (e) => {
        e.preventDefault();
        if (!plotDiv._fullLayout) return;

        const rect = plotDiv.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;

        // Determine target axis based on horizontal cursor proximity
        let targetItem = activeUnitsList[0];
        if (activeUnitsList.length > 1) {
          const rightMargin = rect.width * 0.85;
          if (mouseX >= rightMargin) {
            const rightIdx = Math.min(
              activeUnitsList.length - 1,
              1 + Math.floor(((mouseX - rightMargin) / (rect.width - rightMargin)) * (activeUnitsList.length - 1))
            );
            targetItem = activeUnitsList[rightIdx];
          }
        }

        // Alt + Wheel: Pan Y-Scale up and down
        if (e.altKey) {
          const panPercent = e.deltaY < 0 ? 0.1 : -0.1;
          if (targetItem) {
            nudgeAxis(targetItem.unit, panPercent, 1.0);
          }
          return;
        }

        // Shift + Wheel: Pan Time horizontally
        if (e.shiftKey) {
          let [x0, x1] = currentTimeRange;
          if (x0 === null) x0 = 0;
          if (x1 === null) x1 = currentDuration;
          const span = x1 - x0;
          const shift = span * 0.1 * (e.deltaY < 0 ? -1 : 1);
          setTimeWindow(x0 + shift, x1 + shift);
          return;
        }

        // Ctrl + Wheel: Zoom Y-Axis Scale in/out
        if (e.ctrlKey) {
          const factor = e.deltaY < 0 ? 0.8 : 1.25;
          if (targetItem) {
            nudgeAxis(targetItem.unit, 0.0, factor);
          }
          return;
        }

        // Normal Wheel (no modifiers): Zoom Time (X) centered at mouse cursor!
        let [x0, x1] = currentTimeRange;
        if (x0 === null) x0 = 0;
        if (x1 === null) x1 = currentDuration;

        const plotWidth = rect.width - 120;
        const plotLeft = 60;
        const cursorRatio = Math.max(0, Math.min(1, (mouseX - plotLeft) / plotWidth));
        const cursorTime = x0 + (x1 - x0) * cursorRatio;

        const factor = e.deltaY < 0 ? 0.8 : 1.25;
        const newSpan = (x1 - x0) * factor;
        const newX0 = cursorTime - newSpan * cursorRatio;
        const newX1 = cursorTime + newSpan * (1 - cursorRatio);

        setTimeWindow(newX0, newX1);
      }, { passive: false });

      // Double-click resets view to full fit
      plotDiv.addEventListener('dblclick', () => {
        setTimeWindow(0, currentDuration);
      });
    }

    function renderAxisModal() {
      const container = document.getElementById('axisModalBody');
      container.innerHTML = '';

      if (activeUnitsList.length === 0) {
        container.innerHTML = '<p style="color:var(--text-muted);">No signals currently plotted.</p>';
        return;
      }

      activeUnitsList.forEach(item => {
        const u = item.unit;
        const color = item.color;
        const currentRange = customYRanges[u] || { min: '', max: '', auto: true };

        const card = document.createElement('div');
        card.className = 'axis-config-card';
        card.innerHTML = `
          <div class="axis-card-header">
            <div class="axis-card-title">
              <span class="color-pill" style="background:${color};"></span>
              <span>Axis: <strong>${u}</strong></span>
            </div>
            <div class="axis-quick-actions">
              <button class="axis-btn-mini btn-pan-up" title="Pan scale up 10%">▲ Up</button>
              <button class="axis-btn-mini btn-pan-down" title="Pan scale down 10%">▼ Down</button>
              <button class="axis-btn-mini btn-zoom-in" title="Zoom in scale 20%">+ In</button>
              <button class="axis-btn-mini btn-zoom-out" title="Zoom out scale 20%">&minus; Out</button>
            </div>
          </div>
          <div class="axis-inputs-row">
            <label>Min:</label>
            <input type="number" step="any" class="axis-min-input" data-unit="${u}" value="${currentRange.min !== null && currentRange.min !== undefined ? currentRange.min : ''}" ${currentRange.auto ? 'disabled' : ''}>
            <label>Max:</label>
            <input type="number" step="any" class="axis-max-input" data-unit="${u}" value="${currentRange.max !== null && currentRange.max !== undefined ? currentRange.max : ''}" ${currentRange.auto ? 'disabled' : ''}>
            <label style="margin-left:auto; display:flex; align-items:center; gap:0.25rem;">
              <input type="checkbox" class="axis-auto-cb" data-unit="${u}" ${currentRange.auto ? 'checked' : ''}> Auto
            </label>
          </div>
        `;

        card.querySelector('.btn-pan-up').onclick = () => nudgeAxis(u, 0.1, 1.0);
        card.querySelector('.btn-pan-down').onclick = () => nudgeAxis(u, -0.1, 1.0);
        card.querySelector('.btn-zoom-in').onclick = () => nudgeAxis(u, 0.0, 0.8);
        card.querySelector('.btn-zoom-out').onclick = () => nudgeAxis(u, 0.0, 1.25);

        const autoCb = card.querySelector('.axis-auto-cb');
        const minInp = card.querySelector('.axis-min-input');
        const maxInp = card.querySelector('.axis-max-input');

        autoCb.addEventListener('change', (e) => {
          const isAuto = e.target.checked;
          minInp.disabled = isAuto;
          maxInp.disabled = isAuto;
          if (isAuto) {
            customYRanges[u] = { min: null, max: null, auto: true };
          }
        });

        container.appendChild(card);
      });
    }

    function setupEventListeners() {
      document.getElementById('logFileSelect').addEventListener('change', async (e) => {
        currentLog = e.target.value;
        await loadSignals(currentLog);
      });

      document.getElementById('signalSearch').addEventListener('input', renderSignalList);

      document.getElementById('btnSelectAll').addEventListener('click', () => {
        Object.keys(availableSignals).forEach(s => selectedSignals.add(s));
        updateCheckboxes();
        renderSignalList();
        updatePlot();
      });

      document.getElementById('btnClearAll').addEventListener('click', () => {
        selectedSignals.clear();
        updateCheckboxes();
        renderSignalList();
        updatePlot();
      });

      document.getElementById('btnCollapseAll').addEventListener('click', () => {
        for (const info of Object.values(availableSignals)) {
          collapsedGroups.add(info.message);
        }
        renderSignalList();
      });

      document.getElementById('btnExpandAll').addEventListener('click', () => {
        collapsedGroups.clear();
        renderSignalList();
      });

      // Drag Tool Switcher: Pan vs Zoom
      document.getElementById('btnToolPan').addEventListener('click', () => {
        currentDragTool = "pan";
        document.getElementById('btnToolPan').classList.add('active');
        document.getElementById('btnToolZoom').classList.remove('active');
        Plotly.relayout(document.getElementById('plot'), { dragmode: 'pan' });
      });

      document.getElementById('btnToolZoom').addEventListener('click', () => {
        currentDragTool = "zoom";
        document.getElementById('btnToolZoom').classList.add('active');
        document.getElementById('btnToolPan').classList.remove('active');
        Plotly.relayout(document.getElementById('plot'), { dragmode: 'zoom' });
      });

      // Range Slider Toggle
      document.getElementById('btnToggleSlider').addEventListener('click', () => {
        isRangeSliderVisible = !isRangeSliderVisible;
        const btn = document.getElementById('btnToggleSlider');
        if (isRangeSliderVisible) {
          btn.classList.add('btn-active-toggle');
        } else {
          btn.classList.remove('btn-active-toggle');
        }
        updatePlot();
      });

      // Time Interval Controls
      document.getElementById('btnApplyTime').addEventListener('click', () => {
        const fromVal = parseFloat(document.getElementById('timeFrom').value);
        const toVal = parseFloat(document.getElementById('timeTo').value);
        if (!isNaN(fromVal) && !isNaN(toVal)) {
          setTimeWindow(fromVal, toVal);
        }
      });

      document.getElementById('timeFrom').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') document.getElementById('btnApplyTime').click();
      });
      document.getElementById('timeTo').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') document.getElementById('btnApplyTime').click();
      });

      document.getElementById('btnZoomIn').addEventListener('click', zoomIn);
      document.getElementById('btnZoomOut').addEventListener('click', zoomOut);

      document.getElementById('btnResetZoom').addEventListener('click', () => {
        setTimeWindow(0, currentDuration);
      });

      document.getElementById('btnExportPng').addEventListener('click', () => {
        const plotDiv = document.getElementById('plot');
        Plotly.downloadImage(plotDiv, {
          format: 'png',
          filename: `${currentLog.replace('.bin', '')}_signals`
        });
      });

      document.getElementById('btnOverlay').addEventListener('click', () => {
        currentMode = "overlay";
        document.getElementById('btnOverlay').classList.add('active');
        document.getElementById('btnSubplots').classList.remove('active');
        updatePlot();
      });

      document.getElementById('btnSubplots').addEventListener('click', () => {
        currentMode = "subplots";
        document.getElementById('btnSubplots').classList.add('active');
        document.getElementById('btnOverlay').classList.remove('active');
        updatePlot();
      });

      // Axis Scales Modal
      document.getElementById('btnOpenAxisModal').addEventListener('click', () => {
        renderAxisModal();
        document.getElementById('axisModal').style.display = 'flex';
      });

      document.getElementById('btnCloseAxisModal').addEventListener('click', () => {
        document.getElementById('axisModal').style.display = 'none';
      });

      document.getElementById('btnApplyAllAxes').addEventListener('click', () => {
        document.querySelectorAll('#axisModalBody .axis-config-card').forEach(card => {
          const autoCb = card.querySelector('.axis-auto-cb');
          const minInp = card.querySelector('.axis-min-input');
          const maxInp = card.querySelector('.axis-max-input');
          const u = autoCb.getAttribute('data-unit');

          if (autoCb.checked) {
            customYRanges[u] = { min: null, max: null, auto: true };
          } else {
            const minV = parseFloat(minInp.value);
            const maxV = parseFloat(maxInp.value);
            customYRanges[u] = {
              min: !isNaN(minV) ? minV : null,
              max: !isNaN(maxV) ? maxV : null,
              auto: false
            };
          }
        });
        document.getElementById('axisModal').style.display = 'none';
        updatePlot();
      });

      document.getElementById('btnResetAllAxes').addEventListener('click', () => {
        customYRanges = {};
        renderAxisModal();
        updatePlot();
      });

      // Presets
      document.querySelectorAll('.preset-pill').forEach(pill => {
        pill.addEventListener('click', () => {
          const preset = pill.getAttribute('data-preset');
          selectedSignals.clear();
          const all = Object.keys(availableSignals);

          if (preset === 'speed') {
            const preferred = ['ITF_speed_kph', 'ITF_rpm', 'ITF_gear_position_ST', 'RBX_speed_kph', 'DBG_speed_freq', 'DBG_RPM_freq'];
            const matched = all.filter(s => preferred.includes(s));
            if (matched.length > 0) {
              matched.forEach(s => selectedSignals.add(s));
            } else {
              all.filter(s => (s.toLowerCase().includes('speed') || s.toLowerCase().includes('rpm') || s.toLowerCase().includes('gear'))
                && !s.toLowerCase().includes('pulse')
                && !s.toLowerCase().includes('accuracy')).forEach(s => selectedSignals.add(s));
            }
          } else if (preset === 'coolant') {
            const preferred = ['ITF_coolant_temp', 'EXT_oil_temperature', 'ITF_MCU_temp', 'EXT_charge_coolant_temp_in', 'EXT_charge_coolant_temp_out', 'DBG_coolant_freq', 'DBG_coolant_duty'];
            const matched = all.filter(s => preferred.includes(s));
            if (matched.length > 0) {
              matched.forEach(s => selectedSignals.add(s));
            } else {
              all.filter(s => (s.toLowerCase().includes('coolant') || s.toLowerCase().includes('temp'))
                && !s.endsWith('_TT') && !s.includes('_TT_')).forEach(s => selectedSignals.add(s));
            }
          } else if (preset === 'fuel') {
            const preferred = ['ITF_fuel_level_pc', 'ITF_lv_voltage_v', 'DBG_12V_raw_v', 'DBG_3V3_raw_v', 'DBG_fuel_r', 'DBG_fuel_raw_v', 'RBX_battery_pc'];
            const matched = all.filter(s => preferred.includes(s));
            if (matched.length > 0) {
              matched.forEach(s => selectedSignals.add(s));
            } else {
              all.filter(s => (s.toLowerCase().includes('fuel') || s.toLowerCase().includes('volt') || s.toLowerCase().includes('12v'))
                && !s.endsWith('_TT') && !s.includes('_TT_')).forEach(s => selectedSignals.add(s));
            }
          } else if (preset === 'telltales' || preset === 'all_active') {
            // Select all warning telltales and status indicators
            all.filter(s => s.endsWith('_TT') || s.includes('_TT') || s === 'ITF_alarm_AH' || s === 'ITF_backlight_AH' || s === 'ITF_ignition_AH_ST')
               .forEach(s => selectedSignals.add(s));
          } else if (preset === 'gps') {
            // RaceBox GPS and IMU motion telemetry
            const preferred = ['RBX_speed_kph', 'RBX_accel_X_g', 'RBX_accel_Y_g', 'RBX_accel_Z_g', 'RBX_rot_rate_Z', 'RBX_fix_ST'];
            const matched = all.filter(s => preferred.includes(s));
            if (matched.length > 0) {
              matched.forEach(s => selectedSignals.add(s));
            } else {
              all.filter(s => s.startsWith('RBX_') && !s.includes('accuracy') && !s.includes('valid_') && !s.includes('counter'))
                 .forEach(s => selectedSignals.add(s));
            }
          }

          updateCheckboxes();
          renderSignalList();
          updatePlot();
        });
      });
    }

    window.addEventListener('DOMContentLoaded', init);
  </script>
</body>
</html>
"""


class VisualizerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/" or path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(HTML_PAGE.encode("utf-8"))

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
                decoded_info = load_and_decode_log(p, db)
                summary = {
                    "filename": decoded_info["filename"],
                    "size": decoded_info["size"],
                    "frame_count": decoded_info["frame_count"],
                    "duration_s": decoded_info["duration_s"],
                    "signals": {
                        name: {"message": data["message"], "unit": data["unit"]}
                        for name, data in decoded_info["signals"].items()
                    },
                }
                self.send_json(summary)

            elif path == "/api/data":
                filename = query.get("file", [""])[0]
                signals_req = query.get("signals", [""])[0].split(",")
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


def find_free_port(start_port: int = 8080) -> int:
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    return start_port


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

    port = find_free_port(args.port)
    server = HTTPServer(("127.0.0.1", port), VisualizerHandler)
    url = f"http://localhost:{port}"

    print("=" * 60)
    print(f"  MiniGauge CAN Signal Visualizer running at:")
    print(f"  --> {url}")
    print("  Press Ctrl+C to stop the server.")
    print("=" * 60)

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping visualizer server...")
        server.server_close()


if __name__ == "__main__":
    main()

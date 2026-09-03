#!/usr/bin/env python3
"""
CAN Bus Signal Visualizer
=========================
Interactive browser-based visualization tool for MiniGauge CAN bus binary logs.
Decodes .bin files using the DBC database and plots multiple signals against time
with multi-axis auto-scaling, hover tooltips, and subplots/overlay views.
"""

import sys
import os
import glob
import json
import socket
import argparse
import webbrowser
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
    # If decode.py is in current working directory
    from decode import DbcDatabase, read_bin_file, CanFrame


# Global caches for decoded logs
LOG_CACHE: Dict[str, Dict[str, Any]] = {}
DBC_INSTANCE: Optional[DbcDatabase] = None
DBC_PATH: Optional[Path] = None


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
    # Extract signals
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
      padding: 0.75rem 1.5rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
    }
    .header-left {
      display: flex;
      align-items: center;
      gap: 1rem;
    }
    .logo {
      font-weight: 700;
      font-size: 1.15rem;
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
      gap: 0.5rem;
    }
    select, input[type="text"] {
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--panel-border);
      border-radius: 6px;
      padding: 0.4rem 0.75rem;
      font-size: 0.9rem;
      outline: none;
    }
    select:focus, input[type="text"]:focus {
      border-color: var(--primary);
    }
    .header-controls {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    button {
      background: var(--card-bg);
      color: var(--text);
      border: 1px solid var(--panel-border);
      border-radius: 6px;
      padding: 0.4rem 0.8rem;
      font-size: 0.85rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
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
    .view-mode-toggle {
      display: flex;
      background: var(--bg);
      border-radius: 6px;
      border: 1px solid var(--panel-border);
      padding: 2px;
    }
    .view-mode-toggle button {
      border: none;
      background: transparent;
      padding: 0.25rem 0.6rem;
      border-radius: 4px;
      font-size: 0.8rem;
    }
    .view-mode-toggle button.active {
      background: var(--primary);
      color: white;
    }
    .main-container {
      display: flex;
      flex: 1;
      overflow: hidden;
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
      margin-bottom: 0.5rem;
    }
    .msg-title {
      padding: 0.35rem 1rem;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      background: rgba(255, 255, 255, 0.02);
      display: flex;
      justify-content: space-between;
      align-items: center;
      cursor: pointer;
    }
    .msg-title:hover {
      color: var(--text);
    }
    .sig-item {
      padding: 0.35rem 1rem 0.35rem 1.75rem;
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
      padding: 0.4rem 1rem;
      display: flex;
      gap: 1.5rem;
      font-size: 0.78rem;
      color: var(--text-muted);
    }
    .stats-footer span strong {
      color: var(--text);
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
        <label for="logFileSelect" style="font-size: 0.85rem; color: var(--text-muted);">Log:</label>
        <select id="logFileSelect"></select>
      </div>
    </div>

    <div class="header-controls">
      <div class="view-mode-toggle">
        <button id="btnOverlay" class="active" title="Overlay multiple signals with dedicated Y-axes">Multi-Axis Overlay</button>
        <button id="btnSubplots" title="Stack signals vertically sharing time axis">Stacked Subplots</button>
      </div>
      <button id="btnResetZoom">Reset View</button>
      <button id="btnExportPng">Export PNG</button>
    </div>
  </header>

  <div class="main-container">
    <div class="sidebar">
      <div class="sidebar-header">
        <input type="text" id="signalSearch" class="search-box" placeholder="Search signals (e.g. rpm, temp)...">
        <div class="presets-row">
          <div class="preset-pill" data-preset="fuel">Fuel & Power</div>
          <div class="preset-pill" data-preset="coolant">Coolant & Temp</div>
          <div class="preset-pill" data-preset="speed">Speed & RPM</div>
          <div class="preset-pill" data-preset="all_active">Telltales</div>
        </div>
        <div class="signal-actions">
          <span id="selectedCount">0 selected</span>
          <div>
            <a id="btnSelectAll">Select All</a> &bull; <a id="btnClearAll">Clear</a>
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
  </div>

  <div class="stats-footer">
    <span>File: <strong id="statFile">-</strong></span>
    <span>Frames: <strong id="statFrames">-</strong></span>
    <span>Duration: <strong id="statDuration">-</strong></span>
    <span>Size: <strong id="statSize">-</strong></span>
    <span>Plotted points: <strong id="statPoints">0</strong></span>
  </div>

  <script>
    let currentLog = "";
    let availableSignals = {};
    let selectedSignals = new Set();
    let currentMode = "overlay"; // "overlay" or "subplots"

    const COLORS = [
      '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
      '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#a855f7',
      '#14b8a6', '#6366f1', '#eab308', '#d946ef', '#64748b'
    ];

    async function init() {
      await loadLogs();
      setupEventListeners();
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

        logs.forEach((log, idx) => {
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

        document.getElementById('statFile').textContent = data.filename;
        document.getElementById('statFrames').textContent = data.frame_count.toLocaleString();
        document.getElementById('statDuration').textContent = `${data.duration_s.toFixed(2)}s`;
        document.getElementById('statSize').textContent = `${(data.size / 1024).toFixed(1)} KB`;

        availableSignals = data.signals;
        renderSignalList();
        
        // Retain selections if they exist in new log, or pick top 2 defaults
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

      // Group signals by message
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

        const titleEl = document.createElement('div');
        titleEl.className = 'msg-title';
        titleEl.innerHTML = `<span>${msgName}</span> <span>${sigs.length}</span>`;
        titleEl.onclick = () => {
          const allInGroupSelected = sigs.every(s => selectedSignals.has(s.name));
          sigs.forEach(s => {
            if (allInGroupSelected) selectedSignals.delete(s.name);
            else selectedSignals.add(s.name);
          });
          updateCheckboxes();
          updatePlot();
        };
        groupEl.appendChild(titleEl);

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
            updatePlot();
          };

          const nameSpan = document.createElement('span');
          nameSpan.className = 'sig-name';
          nameSpan.textContent = sig.name;
          nameSpan.title = sig.name;

          itemEl.appendChild(cb);
          itemEl.appendChild(nameSpan);

          if (sig.unit) {
            const unitSpan = document.createElement('span');
            unitSpan.className = 'sig-unit';
            unitSpan.textContent = sig.unit;
            itemEl.appendChild(unitSpan);
          }

          groupEl.appendChild(itemEl);
        });

        container.appendChild(groupEl);
      }
      updateSelectedCount();
    }

    function updateCheckboxes() {
      document.querySelectorAll('#signalList input[type="checkbox"]').forEach(cb => {
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
        showlegend: true,
        legend: {
          orientation: 'h',
          y: 1.12,
          x: 0,
          font: { color: '#e2e8f0', size: 11 }
        },
        xaxis: {
          title: { text: 'Time (seconds)', font: { color: '#94a3b8' } },
          gridcolor: '#242a35',
          zerolinecolor: '#2c323d',
          tickfont: { color: '#94a3b8' }
        }
      };

      if (currentMode === "overlay") {
        // Multi-axis overlay
        // Group signals by unit to share Y axes
        const units = [];
        const unitToAxis = {};

        Object.entries(data).forEach(([sigName, sigData], idx) => {
          const unit = sigData.unit || 'raw';
          if (!unitToAxis[unit]) {
            units.push(unit);
            unitToAxis[unit] = units.length === 1 ? 'y' : `y${units.length}`;
          }
        });

        // Configure axes in layout
        units.forEach((unit, idx) => {
          const axisKey = idx === 0 ? 'yaxis' : `yaxis${idx + 1}`;
          const isRight = idx > 0;
          const color = COLORS[idx % COLORS.length];

          layout[axisKey] = {
            title: { text: unit !== 'raw' ? unit : '', font: { color: color } },
            tickfont: { color: color },
            gridcolor: idx === 0 ? '#242a35' : 'transparent',
            zerolinecolor: idx === 0 ? '#2c323d' : 'transparent',
            overlaying: idx === 0 ? undefined : 'y',
            side: isRight ? 'right' : 'left',
            position: isRight ? Math.max(0.85, 1.0 - (idx - 1) * 0.05) : undefined
          };
        });

        Object.entries(data).forEach(([sigName, sigData], idx) => {
          totalPoints += sigData.times.length;
          const yaxis = unitToAxis[sigData.unit || 'raw'];
          const color = COLORS[idx % COLORS.length];

          // Text tooltip values with enum state
          const hoverText = sigData.states.map((st, i) => {
            const v = sigData.values[i];
            const u = sigData.unit ? ` ${sigData.unit}` : '';
            return st ? `${v}${u} (${st})` : `${v}${u}`;
          });

          traces.push({
            name: sigData.unit ? `${sigName} (${sigData.unit})` : sigName,
            x: sigData.times,
            y: sigData.values,
            yaxis: yaxis,
            text: hoverText,
            hovertemplate: `%{text}<extra>${sigName}</extra>`,
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

        sigKeys.forEach((sigName, idx) => {
          const sigData = data[sigName];
          totalPoints += sigData.times.length;
          const axisNum = idx + 1;
          const yaxisKey = axisNum === 1 ? 'yaxis' : `yaxis${axisNum}`;
          const xaxisKey = axisNum === 1 ? 'xaxis' : `xaxis${axisNum}`;
          const color = COLORS[idx % COLORS.length];

          layout[yaxisKey] = {
            title: { text: sigData.unit || sigName, font: { color: color, size: 10 } },
            tickfont: { color: color, size: 9 },
            gridcolor: '#242a35'
          };
          if (axisNum > 1) {
            layout[xaxisKey] = {
              matches: 'x',
              gridcolor: '#242a35',
              tickfont: { color: '#94a3b8' }
            };
          }

          const hoverText = sigData.states.map((st, i) => {
            const v = sigData.values[i];
            const u = sigData.unit ? ` ${sigData.unit}` : '';
            return st ? `${v}${u} (${st})` : `${v}${u}`;
          });

          traces.push({
            name: sigData.unit ? `${sigName} (${sigData.unit})` : sigName,
            x: sigData.times,
            y: sigData.values,
            xaxis: axisNum === 1 ? 'x' : `x${axisNum}`,
            yaxis: axisNum === 1 ? 'y' : `y${axisNum}`,
            text: hoverText,
            hovertemplate: `%{text}<extra>${sigName}</extra>`,
            mode: 'lines',
            line: { width: 1.8, color: color },
            type: 'scatter'
          });
        });
      }

      document.getElementById('statPoints').textContent = totalPoints.toLocaleString();
      Plotly.react(plotDiv, traces, layout, { responsive: true, displayModeBar: false });
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
        updatePlot();
      });

      document.getElementById('btnClearAll').addEventListener('click', () => {
        selectedSignals.clear();
        updateCheckboxes();
        updatePlot();
      });

      document.getElementById('btnResetZoom').addEventListener('click', () => {
        const plotDiv = document.getElementById('plot');
        Plotly.relayout(plotDiv, {
          'xaxis.autorange': true,
          'yaxis.autorange': true
        });
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

      // Presets
      document.querySelectorAll('.preset-pill').forEach(pill => {
        pill.addEventListener('click', () => {
          const preset = pill.getAttribute('data-preset');
          selectedSignals.clear();
          const all = Object.keys(availableSignals);

          if (preset === 'fuel') {
            all.filter(s => s.toLowerCase().includes('fuel') || s.toLowerCase().includes('volt') || s.toLowerCase().includes('12v')).forEach(s => selectedSignals.add(s));
          } else if (preset === 'coolant') {
            all.filter(s => s.toLowerCase().includes('coolant') || s.toLowerCase().includes('temp')).forEach(s => selectedSignals.add(s));
          } else if (preset === 'speed') {
            all.filter(s => s.toLowerCase().includes('speed') || s.toLowerCase().includes('rpm') || s.toLowerCase().includes('gear')).forEach(s => selectedSignals.add(s));
          } else if (preset === 'all_active') {
            all.filter(s => s.toLowerCase().includes('itf_') && (s.toLowerCase().includes('_ah') || s.toLowerCase().includes('_al') || s.toLowerCase().includes('_st'))).slice(0, 8).forEach(s => selectedSignals.add(s));
          }

          updateCheckboxes();
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
        # Silence default request spam
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
                candidates = sorted(SCRIPT_DIR.glob("log_*.bin"))
                if not candidates:
                    candidates = sorted(Path(".").glob("log_*.bin"))

                logs_meta = []
                for p in candidates:
                    if p.stat().st_size == 0:
                        continue
                    # Quick read duration
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


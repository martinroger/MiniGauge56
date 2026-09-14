# MiniGauge Decoder Toolset — Theory of Operation (TOO.MD)

## 1. System Overview & Architecture

The MiniGauge Decoder Toolset is an offline telemetry analysis, algorithm engineering, and log manipulation workstation. It is engineered to process binary CAN bus captures (`*.bin`) recorded by the MiniGauge ESP32 firmware and provide interactive, real-time visualization, calibration, and firmware C99 code generation.

### 1.1 Architectural Decoupling & Modularity

The toolset follows a modular layered architecture:

```
+-------------------------------------------------------------------------------+
|                            BROWSER CLIENT INTERFACE                           |
|  [HTML5 Templates]        [Centralized CSS Design System]   [Modular JS Libs] |
|  - visualize.html         - theme.css (Dark/Light tokens)   - theme.js        |
|  - tuner.html             - base.css (Layout, Reset)        - toast.js        |
|  - gear_lab.html          - components.css (Cards, Sliders) - leaflet_map.js  |
|  - trim_log.html          - map.css (GPS Drawer, HUD)       - plotly_theme.js |
|  - cockpit_3d.html        - cockpit_3d.css (HUD, Glow)      - cockpit_3d.js   |
+---------------------------------------+---------------------------------------+
                                        | HTTP / JSON / Static Assets
+---------------------------------------v---------------------------------------+
|                       PYTHON OFFLINE APPLICATION LAYER                        |
|   visualize.py    tuner.py      gear_lab.py     trim_log.py    cockpit_3d.py  |
+---------------------------------------+---------------------------------------+
                                        | Shared Services
+---------------------------------------v---------------------------------------+
|                          DECODER COMMON LIBRARY (common/)                     |
|   can_core.py            dbc.py             calibration.py    http_server.py  |
|   - CanFrame             - DbcDatabase      - load_cal        - BaseAppHandler|
|   - read_bin_file        - SignalDef        - save_cal        - start_server  |
|   - find_bin_files       - MessageDef       - sync aliases    - MIME / routing|
+---------------------------------------+---------------------------------------+
                                        | Binary Unpacking & Database
+---------------------------------------v---------------------------------------+
|  Hardware Logs (*.bin)                 CAN Database (binocan.dbc)             |
|  16-byte Little-Endian Frames          Motorola / Intel Packed Signals        |
+-------------------------------------------------------------------------------+
```

---

## 2. Core Components

### 2.1 Low-Level CAN Engine (`decoder/common/can_core.py`)
- **`CanFrame`**: Immutable record container representing a single hardware frame. Supports both 4-argument and 5-argument constructors, exposing canonical attributes `timestamp_ms`, `can_id`, `dlc`, `data`, and calculated time offsets `time_rel_s`.
- **`read_bin_file`**: Fast binary parser reading consecutive 16-byte records formatted as `<IHB8sx` (4-byte timestamp in ms, 2-byte CAN arbitration ID, 1-byte DLC, 8 bytes data payload, and 1-byte padding).
- **`find_bin_files`**: Multi-file discoverer with natural sorting (`log_2.bin` before `log_10.bin`).

### 2.2 CAN Database Parser (`decoder/common/dbc.py`)
- **`DbcDatabase`**: Zero-dependency parser for standard Vector DBC files. Resolves `BO_` (Message definitions), `SG_` (Signal definitions), `VAL_` (Enumerated value tables), and `SIG_VALTYPE_` (IEEE 754 floating point markers).
- **`MessageDef` & `SignalDef`**: Decode bitfields packed across byte boundaries supporting both Motorola (Big Endian) and Intel (Little Endian) schemes, physical linear conversions (`y = mx + b`), min/max clamping, and string value mappings. Aliased as `DbcMessage` and `DbcSignal` for backward compatibility.

### 2.3 Shared Calibration Store (`decoder/common/calibration.py`)
- Manages cross-tool algorithm synchronization via `decoder/gear_calibration.json`.
- Implements atomic file persistence with ISO-8601 timestamps and parameter aliasing between heuristic and Bayesian nomenclature (`tolerance` <=> `tolerance_abs`, `latch_ms` <=> `latch_time_ms`).

### 2.4 Reusable HTTP Server Framework (`decoder/common/http_server.py`)
- **`BaseAppHandler`**: Extends Python's `BaseHTTPRequestHandler` with convenience helpers for CORS preflight, JSON request extraction (`read_json_body`), response formatting (`send_json`), template streaming (`send_html`), and static file routing (`serve_static`).
- **`start_server`**: Threading HTTP server launcher featuring collision-free dynamic TCP port allocation, terminal diagnostic banners, and browser auto-launching.

### 2.5 3D Cyber-Cockpit & Trajectory Replayer (`decoder/cockpit_3d.py`)
- **`lat_lon_to_enu`**: High-precision local East-North-Up coordinate conversion relative to initial GPS anchor point, translating WGS84 coordinates to local meters with sub-millimeter precision.
- **`extract_cockpit_trajectory`**: Decodes CAN binary records into 3D spatial points with synchronized engine (RPM, gear, temps), dynamic (speed, G-force, roll/pitch), and electrical telemetry (battery voltage, tell-tales).
- **Three.js WebGL Graphics Pipeline**: Renders 3D trajectory ribbons with instantaneous speed heatmapping, greyed-out future horizon, vertical reference stanchions extending to the $0\text{m}$ ground plane, vehicle frame 3D G-vector arrows, fixed-frustum non-culling 1200-particle trail, distance-smoothed lookahead chase camera ($45,000\text{m}$ render distance), tethered orbit camera tracking (preserving constant orbit radius), local smoothed road grade estimation ($\pm 25\text{m}$ spatial window), and live vertical exaggeration ($1.0\times$ to $5.0\times$).
- **`vx-binocle-espidf` Instrument Cluster**: Pure SVG needle-less perimeter gauges mathematically aligned with graduations for RPM (0–80 with $\times 100$ RPM sub-label) and Speed (0–240 KPH), centered numeric RPM and speed readouts, centered lower diagnostic readouts (`COOL`, `FUEL`), floating bottom gear dock, enlarged $192\text{px}$ uncontainerized G-meter with additive blending/summing dwell heatmap, red indicator dot, automatic red alert thresholding, and collapsible HUD controls.

---

## 3. Web Asset Delivery Strategy

Assets are organized into dedicated directories:
- **`decoder/web/static/css/`**:
  - `theme.css`: Color tokens for Ubuntu Yaru Dark and Cold White Light, supporting live switching via CSS custom properties.
  - `base.css`: CSS reset, typography, responsive flexbox layout, and headers.
  - `components.css`: Reusable UI controls including buttons, dynamic-gradient sliders, cards, data tables, and badges.
  - `map.css`: Collapsible Leaflet GPS drawer, velocity HUD, and rotating compass styling.
  - `cockpit_3d.css`: Cyberpunk negative-space HUD layout, glassmorphic panels, neon glow filters, and collapsible bar animations.
- **`decoder/web/static/js/`**:
  - `theme.js`: OS `prefers-color-scheme` listener with `localStorage` persistence and `minigauge-theme-changed` dispatch.
  - `toast.js`: Non-intrusive notification banner manager.
  - `plotly_theme.js`: Plotly layout generators syncing dark/light modes and container ResizeObservers.
  - `leaflet_map.js`: Leaflet GPS track drawer with binary search telemetry synchronization.
  - `cockpit_3d.js`: Three.js WebGL scene lifecycle, speed heatmap shader, warp particle system, G-force camera roll, and dual-screen SVG gauge updating.
- **`decoder/web/templates/`**:
  - `visualize.html`, `tuner.html`, `gear_lab.html`, `trim_log.html`, and `cockpit_3d.html`.
  - Clean HTML5 documents containing zero inline style blocks or embedded third-party script definitions.

---

## 4. Sequence Diagrams

### 4.1 Server Startup & Dynamic Port Allocation

```mermaid
sequenceDiagram
    autonumber
    participant CLI as Terminal / User
    participant App as Application (visualize.py)
    participant Srv as http_server.start_server
    participant OS as Host OS TCP Stack
    participant Browser as Web Browser

    CLI->>App: python3 visualize.py --port 8080
    App->>Srv: start_server(VisualizeHandler, port=8080)
    Srv->>OS: Probe socket bind 127.0.0.1:8080
    alt Port Available
        OS-->>Srv: Bind Success
    else Port In Use
        OS-->>Srv: Errno 48 (Address in use)
        Srv->>OS: Probe socket bind 127.0.0.1:8081
        OS-->>Srv: Bind Success
    end
    Srv->>CLI: Print banner (Listening on http://127.0.0.1:PORT)
    Srv->>Browser: webbrowser.open(url)
    Browser->>Srv: GET /
    Srv->>Browser: 200 OK (HTML Template)
    Browser->>Srv: GET /static/css/theme.css
    Srv->>Browser: 200 OK (text/css)
```

### 4.2 Telemetry Ingestion & GPS Synchronization Loop

```mermaid
sequenceDiagram
    autonumber
    participant UI as Browser (Plotly & Leaflet)
    participant Handler as TunerHandler (BaseAppHandler)
    participant Core as can_core & dbc
    participant Disk as Hardware Log (*.bin)

    UI->>Handler: GET /api/algo_data?file=log_1.bin
    Handler->>Core: read_bin_file(log_1.bin)
    Core->>Disk: Read 16-byte frames
    Disk-->>Core: Byte stream
    Core-->>Handler: List[CanFrame]
    Handler->>Core: DbcDatabase.decode(frames)
    Core-->>Handler: Decoded dynamics & GPS series
    Handler->>UI: 200 OK (JSON timeseries & GPS track)
    UI->>UI: Render Plotly scopes & Leaflet polyline
    Note over UI: User moves cursor over telemetry plot
    UI->>UI: Binary search GPS timestamp (O(log N))
    UI->>UI: Update vehicle marker & compass heading
```

### 4.3 Cross-Tool Parameter Tuning & Calibration Sync

```mermaid
sequenceDiagram
    autonumber
    participant Tuner as tuner.py Web UI
    participant Handler as TunerHandler
    participant CalStore as calibration.py
    participant Disk as gear_calibration.json
    participant GearLab as gear_lab.py Web UI

    Note over Tuner: Engineer adjusts Bayesian prior decay slider
    Tuner->>Handler: POST /api/calibration {"m2_decay": 0.96, "m2_inertia": 0.98, "m2_latch_ms": 225}
    Handler->>CalStore: save_calibration(data, source="tuner")
    CalStore->>Disk: Write formatted JSON with updated_at timestamp
    Disk-->>CalStore: Success
    CalStore-->>Handler: Updated Path
    Handler->>Tuner: 200 OK {"status": "ok", "saved": {...}}
    Note over GearLab: User switches to Gear Estimator Lab
    GearLab->>Disk: GET /api/calibration
    Disk-->>GearLab: 200 OK (Synchronized parameters loaded)
```

### 4.4 Embedded C Header Generation & GCC Verification

```mermaid
sequenceDiagram
    autonumber
    participant UI as gear_lab.py Web UI
    participant Handler as GearLabHandler
    participant Gen as generate_esp32_c_header()
    participant GCC as Host GCC Compiler
    participant MCU as ESP32 Firmware

    UI->>Handler: GET /api/export_c
    Handler->>Gen: Build header from Gaussian fits & transition matrix
    Gen-->>Handler: C header string (gear_estimator_params.h)
    Handler->>UI: 200 OK (attachment: gear_estimator_params.h)
    Note over GCC: Automated Test Verification (test_gear_lab.py)
    GCC->>GCC: gcc -Wall -Wextra -Werror -O2 verify.c -lm
    GCC-->>UI: Zero warnings, Clean exit
    Note over MCU: Turnkey include into main/gear_estimator.c
```

### 4.5 3D Cyber-Cockpit, G-Meter Normalization & Friction Circle Heatmap

```mermaid
sequenceDiagram
    autonumber
    participant UI as cockpit_3d.js
    participant Server as CockpitHandler
    participant Core as can_core / dbc
    participant Canvas as #g-heatmap-canvas
    participant Three as Three.js WebGL

    UI->>Server: GET /api/trajectory?file=log.bin&downsample=1
    Server->>Core: read_bin_file() & decode()
    Core-->>Server: GPS fixes & IMU accelerations (g_lat: -accel_Y, g_lon: accel_X)
    Server->>Server: Calculate ENU (z0=0), Gmax, Gbound=1.1*Gmax, Gmid=0.5*Gmax, Gthresh=0.75*Gmax
    Server-->>UI: 200 OK JSON {points, stats: {max_g, g_thresh, g_bound, g_mid}}
    UI->>Canvas: renderGHeatmap(): 2D dwell density grid & radial splats
    UI->>UI: updateGScaleUI(): size intermediate ring (50%) & update scale labels
    UI->>Three: buildTrajectoryGeometry() & initVehicleParticles()
    Note over UI: Telemetry Replay Loop (60 FPS)
    UI->>Three: updateCamera(), lerp smoothDir, scale G-vectors (110x, renderOrder=999)
    UI->>UI: updateHUD(): gTot >= gThresh ? trigger alert-red flashing : normal
    UI->>UI: Clamp & position G-ball relative to g_bound
```

---

## 5. Security & Operational Boundaries

1. **Localhost Binding Invariant**: By default, all HTTP services bind strictly to loopback (`127.0.0.1`), ensuring services are never exposed to external networks without deliberate intent.
2. **Directory Traversal Protection**: `BaseAppHandler.serve_static` enforces strict path resolution relative to `decoder/web/static`. Any requested path resolving outside the static asset root is rejected with `HTTP 403 Forbidden`.
3. **No External Runtime Fetch**: All client libraries (Leaflet, Plotly) fall back to local assets or CDN links gracefully, and zero pip packages are loaded on the host runtime.


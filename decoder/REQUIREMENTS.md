# MiniGauge Decoder Toolset Requirements Specification

This document defines the functional, technical, and architectural requirements for the Python 3 offline diagnostic, calibration, and slicing toolset located in `decoder/`. The toolset consists of 5 modular utilities:
1. **Batch Decoder & Exporter (`decode.py`)**
2. **Interactive Signal Visualizer (`visualize.py`)**
3. **Algorithm Calibration & Tuning Lab (`tuner.py`)**
4. **Dedicated Gear Estimator Lab & Model Trainer (`gear_lab.py`)**
5. **CAN Log Trimmer & Slicer (`trim_log.py`)**

---

## 1. System-Wide Architectural Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-SYS-001** | Zero Pip Dependencies | All decoder utilities MUST operate strictly using the Python 3 standard library (`struct`, `json`, `http.server`, `urllib`, `pathlib`, etc.). No external pip package installations (`pandas`, `numpy`, `cantools`) shall be required. |
| **REQ-SYS-002** | Binary Frame Layout | Tools MUST correctly unpack the 16-byte packed CAN frame format emitted by `main/logging.cpp`: 4-byte uptime timestamp (ms), 2-byte CAN ID (little-endian), 1-byte DLC, 8-byte payload, and 1-byte padding. |
| **REQ-SYS-003** | DBC Parsing Fidelity | Tools MUST support parsing the official CAN database (`binocan.dbc`), decoding integer, float, signed/unsigned endianness (Intel little-endian and Motorola big-endian), scaling factors, offsets, min/max limits, unit strings, and discrete value enumeration tables. |
| **REQ-SYS-004** | Unified Design System & OS Theme Sync | All web-based interfaces MUST implement the unified design palette (Ubuntu Yaru Dark with faded orange accents and dark slider tracks; Cold White Light with faded royal blue accents, pure white slider tracks, and 1px container accent borders). All tools MUST automatically detect and adapt to the host OS color scheme (`prefers-color-scheme: light`) with live reactive updates and manual overrides persisted in `localStorage`. |
| **REQ-SYS-005** | Portable Relative Linking | All internal documentation references MUST use relative file paths without machine-specific absolute filesystem paths. |
| **REQ-SYS-006** | Interactive Parameter Tooltips | All algorithmic sliders, parameter inputs, and stage toggles in `tuner.py` and `gear_lab.py` MUST provide informative hover tooltips (using styled info badges `ⓘ` and native HTML attributes) detailing physical roles and operational effects. |
| **REQ-SYS-007** | Automated Regression & DOM Verification Suite | The decoder toolset MUST maintain automated, repeatable integration test suites in `decoder/tests/` verifying server lifecycles, API endpoints, C99 export compilation with GCC (`-Wall -Wextra -Werror`), DOM ID integrity between client-side JavaScript and HTML templates, and algorithm offline simulations without leaving working tree artifacts. |
| **REQ-SYS-008** | Modular Package Architecture & Static Asset Separation | Core CAN parsing (`can_core.py`), DBC interpretation (`dbc.py`), calibration persistence (`calibration.py`), and HTTP request handling (`http_server.py`) MUST be decoupled into the `decoder/common/` package. All shared web styling (`*.css`) and client-side scripts (`*.js`) MUST reside in `decoder/web/static/`, and semantic HTML structures MUST reside in `decoder/web/templates/`, eliminating embedded CSS/HTML strings from Python application files. |

---

## 2. Batch Decoder (`decode.py`) Requirements

### 2.1 Scope & Purpose
`decode.py` provides non-interactive command-line conversion of binary `.bin` log captures into industry-standard formats for downstream analysis in third-party tools (Vector CANoe, SavvyCAN, MATLAB) or relational databases.

### 2.2 Functional Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-DEC-001** | Vector ASCII (.asc) Export | The tool MUST generate Vector ASCII format logs containing standard headers, timestamps in seconds relative to log start, hexadecimal CAN IDs, DLC, and space-separated hexadecimal data bytes. |
| **REQ-DEC-002** | Decoded Message CSV | The tool MUST generate a tabular message log with columns: `timestamp_ms`, `time_s`, `can_id`, `can_id_dec`, `message_name`, `dlc`, `data_hex`, human-readable signal values, and raw `signals_json`. |
| **REQ-DEC-003** | Flat Signal Time-Series (`--signals`) | When invoked with `--signals` / `-s`, the tool MUST generate a normalized time-series table (`_signals.csv`) with columns: `timestamp_ms`, `time_s`, `can_id`, `message_name`, `signal_name`, `value`, `unit`, `state`. |
| **REQ-DEC-004** | Wide Matrix Export (`--wide`) | When invoked with `--wide` / `-w`, the tool MUST generate a wide matrix (`_wide.csv`) where each distinct decoded signal occupies an individual column, facilitating direct import into spreadsheet or statistical software. |
| **REQ-DEC-005** | Batch Discovery & Multi-File Processing | The tool MUST accept individual file paths, wildcards, or automatically scan the current directory for all `*.bin` files if no arguments are provided. |
| **REQ-DEC-006** | Custom Output Routing | The tool MUST support specifying an alternative destination directory via `--output-dir` / `-o`. |

---

## 3. Interactive Signal Visualizer (`visualize.py`) Requirements

### 3.1 Scope & Purpose
`visualize.py` provides an interactive, browser-based inspection workstation for multi-signal CAN bus telemetry, equipped with synchronized 2D graph navigation and GPS track geospatial rendering.

### 3.2 Functional Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-VIS-001** | Local Web Server | The tool MUST start a lightweight, zero-dependency `http.server` (default port 8080) and auto-open the default browser unless `--no-browser` is specified. |
| **REQ-VIS-002** | Log Switcher & Initial Load | The dashboard MUST provide an immediate dropdown to switch between discovered log files without restarting the server, defaulting upon selection to the vehicle dynamics baseline (`ITF_speed_kph` and `ITF_rpm`). |
| **REQ-VIS-003** | Signal Browser & Presets | The left sidebar MUST list all decoded CAN messages alphabetically, allowing search by name/unit and providing 1-click domain presets (Speed & RPM, Coolant & Temp, Fuel & Power, Telltales, GPS & IMU, G-Forces & Dynamics). |
| **REQ-VIS-004** | Multi-Axis Unit Segregation | Traces sharing different engineering units (`km/h`, `RPM`, `V`, `Hz`, `Ohm`, `degC`) MUST be assigned independent, color-coordinated Y-axes to prevent vertical distortion and scale compression. |
| **REQ-VIS-005** | Stacked Subplots Mode | The UI MUST support toggling between overlaid multi-axis charting and vertically stacked, time-synchronized subplots with discrete state labels on categorical axes. |
| **REQ-VIS-006** | 2D Pan & Zoom Navigation | Chart navigation MUST provide concurrent 2D panning (click-and-drag in X and Y), centered cursor mouse-wheel zooming, horizontal scroll (`Shift + Wheel`), per-axis vertical pan (`Alt + Wheel`), and per-axis vertical zoom (`Ctrl + Wheel`). |
| **REQ-VIS-007** | Independent Y-Scales Drawer | The UI MUST feature an expandable drawer with per-axis nudge buttons (`▲`, `▼`, `+`, `−`), direct min/max numeric inputs, and dynamic autoscale toggles. |
| **REQ-VIS-008** | GPS Track Map Drawer | The UI MUST incorporate a collapsible, resizable right-hand map drawer displaying the vehicle GPS driving course on CartoDB tiles with a 10-bin velocity turbo colormap, start/finish pins, and a rotating compass heading indicator. |
| **REQ-VIS-009** | Bi-Directional Telemetry Sync | Hovering over telemetry plots MUST move the vehicle marker along the GPS track via binary search ($O(\log N)$); clicking the track polyline MUST center the telemetry scope around that timestamp. |

---

## 4. Algorithm Calibration & Tuning Lab (`tuner.py`) Requirements

### 4.1 Scope & Purpose
`tuner.py` is an algorithm engineering workbench providing client-side interactive parameter tuning (60fps dynamic recomputation) and validation for embedded firmware algorithms.

### 4.2 Tab 1: Gear Position Estimator Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-TUN-GEAR-001** | Kinematic-Conditioned Bayesian Model | The gear estimation tab MUST implement the Kinematic-Conditioned Bayesian Model (Model 2 from `gear_lab.py`), calculating posterior probability distributions over gears at 60 FPS client-side during parameter adjustments. |
| **REQ-TUN-GEAR-002** | Prior Decay & Inertia Weighting | The tool MUST provide sliders for Prior Decay factor (`m2_decay`, range 0.70 to 0.99) and Transition Inertia (`m2_inertia`, range 0.50 to 0.98) to control recursive state memory persistence and shift resistance. |
| **REQ-TUN-GEAR-003** | Physical Dual Cutoff Gating | The tool MUST enforce minimum vehicle speed (`slider-gear-minspeed`) and engine RPM (`slider-gear-minrpm`) cutoffs with dual-unit tooltips/labels (Hz and km/h / RPM). Samples below either cutoff MUST immediately transition to Neutral (0) without delay. |
| **REQ-TUN-GEAR-004** | Confidence Thresholding & State 14 | The tool MUST provide a confidence cutoff slider (`slider-m2-conf`, range 0.10 to 0.90). When posterior confidence fails the threshold, the output MUST report DBC State 14 (*Uncertain*) rather than spuriously holding stale gears. |
| **REQ-TUN-GEAR-005** | Ratio Tolerance & Cluster Peaks | The tool MUST support adjusting ratio tolerance (`slider-gear-tol`, range 0.05 to 0.60) and 5 individual gear center ratios (`gear-r-1` through `gear-r-5`), supported by 1-click **Auto-Detect Peaks** clustering. |
| **REQ-TUN-GEAR-006** | Temporal Output Latching | The tool MUST provide a temporal latch duration slider (`slider-m2-latch`, range 0 to 600 ms) to suppress transient shift chatter by requiring sustained probability commitment. |
| **REQ-TUN-GEAR-007** | Shared Calibration Auto-Loading & Persistence | The tool MUST automatically fetch and load `decoder/gear_calibration.json` via `GET /api/calibration` on startup if present, and support saving updated Bayesian parameters via `POST /api/calibration`. |
| **REQ-TUN-GEAR-008** | Dynamic Math Explainer | The sidebar MUST display a dynamic mathematical explainer card that rebuilds its formulas, active parameter values, and explanatory text in real time as presets or modular stage checkboxes change. |
| **REQ-TUN-GEAR-009** | Ratio Histogram & Auto-Peak Detection | The UI MUST display a sample ratio histogram with projected tolerance bands, accompanied by an **Auto-Detect Peaks** function that clusters driving ratios to seed nominal gear ratios $R_1..R_5$. |
| **REQ-TUN-GEAR-010** | Synchronized Dynamics Timeline | The UI MUST plot a synchronized dual-axis graph of `ITF_speed_kph` and `ITF_rpm` alongside the ratio and estimated gear curves, maintaining time synchronization with pan/zoom and the GPS track drawer. |
| **REQ-TUN-GEAR-011** | In-Scope Glitch Marker Annotations | The gear timeline scope MUST visually flag detected algorithm glitches directly on the plot: 🔴 Neutral Dropouts, 🟠 Micro-Dwell Chatter, and 🟣 Coast-Down Phantom Shifts with interactive hover diagnostics. |
| **REQ-TUN-GEAR-012** | Drive Replayer & Simulated Gear Gauge | The UI MUST incorporate an interactive drive playback player with play/pause, step controls, variable playback speed (0.25x to 10x), scrub bar, and a simulated gear position gauge card with a show/hide toggle. Playback MUST synchronize in real time with the vertical timeline needle, telemetry scope, and Leaflet GPS vehicle track marker. |
| **REQ-TUN-GEAR-013** | Cross-Tool Shared Calibration | The tool MUST provide standard `GET /api/calibration` and `POST /api/calibration` endpoints and UI buttons ("💾 Save Cal" / "📥 Load Cal") interoperating with `decoder/gear_calibration.json` to seamlessly exchange tuned parameters with `gear_lab.py`. |

### 4.3 Tab 2: Fuel Level Filter Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-TUN-FUEL-001** | Filter Algorithms | The tool MUST support user selection between Simple Moving Average (sliding window $1\text{ to }180\text{ s}$) and Exponential Moving Average (time constant $\tau \in [1, 180]\text{ s}$) applied to `DBG_fuel_level_unfiltered`. |
| **REQ-TUN-FUEL-002** | Quantization Simulation | The tool MUST provide simulation of discrete firmware rounding (Continuous, $0.5\%$, $1.0\%$) to model embedded ADC/CAN output quantization. |
| **REQ-TUN-FUEL-003** | Dynamic Autoscale with Zoom Retention | The fuel scope Y-axis MUST autoscale tightly around the active envelope of measured and simulated signals while preserving user-initiated zoom states across slider adjustments. |
| **REQ-TUN-FUEL-004** | Error & Jitter Diagnostics | The tool MUST calculate Residual Error ($\Delta = \text{Simulated} - \text{Recorded}$), MAE, RMSE, Maximum Slew Rate (%/s), and Maximum Sample-to-Sample Jitter (%) for both filter variants. |

### 4.4 Tab 3: Speed Correction & UNECE R39 Check Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-TUN-SPD-001** | Linear Calibration Equation | The tool MUST calculate corrected speedometer speed: $V_{\text{corr}} = k \cdot V_{\text{ind}} + c$ with configurable gain $k \in [0.800, 1.250]$ and offset $c \in [-10.0, +15.0]\text{ km/h}$. |
| **REQ-TUN-SPD-002** | UNECE Regulation 39 Compliance | The tool MUST evaluate compliance against the legal corridor: $V_{\text{GPS}} \le V_{\text{corr}} \le 1.10 \cdot V_{\text{GPS}} + 4.0\text{ km/h}$, flagging violations with red warning markers. |
| **REQ-TUN-SPD-003** | Automated Gain/Offset Optimizer | The tool MUST provide a 1-click calibration optimizer that determines optimal $k$ and $c$ parameters satisfying ECE R39 across 100% of valid driving points while minimizing over-reading. |
| **REQ-TUN-SPD-004** | GPS Fix Filtering | Speed evaluation MUST strictly exclude GPS points without valid 3D navigation fixes (`RBX_valid_fix == 0` or `RBX_fix_ST < 3`). |
| **REQ-TUN-SPD-005** | Dynamic Speed Change Rate Filter | The tool MUST provide a configurable slider ($0.5\text{ to }15.0\text{ km/h/s}$) and enable toggle to filter out samples where the speed rate of change $\max(|dv_{\text{GPS}}/dt|, |dv_{\text{ind}}/dt|)$ exceeds the threshold, eliminating artificial ECE R39 boundary violations caused by sensor phase lag during hard acceleration or braking. |

### 4.5 Tab 4: Signal & Bus Analytics Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-TUN-ANA-001** | Message Timing Metrics | The tool MUST compute for every CAN message: frame count, nominal cycle time, average cycle time, minimum cycle time, maximum cycle time, cycle jitter standard deviation ($\sigma_T$), bus frequency (Hz), and estimated frame drop %. |
| **REQ-TUN-ANA-002** | Signal Value & Slew Dispersion | The tool MUST compute for each individual decoded signal: sample count, unit, minimum, maximum, mean, median, standard deviation, and maximum slew rate ($|dx/dt|_{\max}$). |
| **REQ-TUN-ANA-003** | Tabular Search & CSV Export | The analytics view MUST feature search filtering, sortable column headers, collapsible message trees, and a 1-click **Export Analytics CSV** button. |

---

## 5. Dedicated Gear Estimator Lab (`gear_lab.py`) Requirements

### 5.1 Scope & Purpose
`gear_lab.py` is a dedicated algorithm development, machine learning, and calibration workstation designed to aggregate all available CAN binary logs, extract empirical global ratio distributions, train lightweight statistical models (Heuristic, Kinematic Bayesian, and Hidden Markov Model), benchmark glitch performance side-by-side, and export ready-to-compile C headers for ESP32 firmware.

### 5.2 Functional Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-LAB-001** | Multi-Log Dataset Aggregation | The tool MUST automatically scan and parse all valid `*.bin` log captures in the directory, aggregating valid driving pairs ($f_{\text{speed}} \ge 5.0\text{ Hz}, f_{\text{RPM}} \ge 25.0\text{ Hz}$) into a unified multi-log dataset. |
| **REQ-LAB-002** | Global Gaussian Mixture Clustering | The tool MUST fit 5 distinct Gaussian ratio cluster centers ($\mu_1..\mu_5$) and standard deviations ($\sigma_1..\sigma_5$) across the combined driving dataset to identify nominal ratios for 1st through 5th gear. |
| **REQ-LAB-003** | Kinematic-Conditioned Bayesian Filter | The tool MUST implement and evaluate a Kinematic Bayesian Classifier conditioned on $[V, \dot{V}, \text{RPM}, \dot{\text{RPM}}]$ that predicts shifting intent, models loss-of-fix transition probabilities (upshift bias on acceleration, downshift bias on braking), suppresses phantom shifts during clutch disengagement ($\dot{\text{RPM}} < -35\text{ Hz/s}$), and applies guarded temporal latching. |
| **REQ-LAB-004** | Hidden Markov Model (HMM) | The tool MUST implement a 6-state HMM using an empirical transition probability matrix $A_{6 \times 6}$ with high self-transition inertia, impossible skip penalties, and asymmetric engine-deceleration emission conditioning ($\Delta f_{\text{RPM}} < -40\text{ Hz/s}$) to eliminate clutch coast-down phantom upshifts. |
| **REQ-LAB-005** | Standardized Glitch Evaluation | The tool MUST evaluate and display side-by-side performance metrics across all models: <br>• Neutral Dropouts ($N_{\text{dropout}}$): $k \to 0 \to k$ in $< 450\text{ ms}$ at $V \ge 20\text{ km/h}$.<br>• Micro-Dwell Chatter ($N_{\text{chatter}}$): forward gear dwell $< 300\text{ ms}$.<br>• Coast-Down Phantom Shifts ($N_{\text{phantom}}$): upward gear jumps while $\frac{d\text{RPM}}{dt} < -1200\text{ RPM/s}$ and speed is non-accelerating.<br>• Unified Glitch-Free Quality Score ($0\text{ to }100\%$). |
| **REQ-LAB-006** | Turnkey ESP32 C Header Export | The tool MUST export a zero-heap-allocation, re-entrant C99 header (`gear_estimator_params.h`) containing calibrated ratio constants, variances, transition matrices, complete static inference routines (`gear_heuristic_update`, `gear_bayesian_update`, `gear_hmm_update`) that compile with GCC/Clang under `-Wall -Wextra -Werror`, and automatically embeds the active configuration/JSON calibration as a structured C comment block. |
| **REQ-LAB-007** | Concatenated Multi-Log Timeline | In aggregated mode, the tool MUST concatenate all individual drive sessions chronologically with a 5.0s separation buffer and dashed vertical boundary lines, while dynamically focusing strictly on single logs and recalculating isolated glitch scores when a specific log is selected. |
| **REQ-LAB-008** | Stacked vs. Shared Multi-Model Layout | The timeline scope MUST support toggling between Stacked Subplots (individual time-synchronized subplots for M1, M2, M3, and Ground Truth) and Shared Overlay (single timeline with interactive show/hide checkboxes per trace). |
| **REQ-LAB-009** | Interactive Model Tuning Drawer | The UI MUST feature an interactive tuning drawer permitting live adjustment of algorithmic parameters across all three models (M1: tolerance, latch time; M2: prior decay, inertia, latch time, confidence threshold; M3: transition inertia, clutch decel threshold) with instant 60fps re-simulation. |
| **REQ-LAB-010** | In-Scope Glitch Marker Annotations | All model timeline scopes MUST plot color-coded glyph markers at exact timestamps of detected glitches (🔴 Neutral Dropouts, 🟠 Chatter, 🟣 Coast Phantoms) with detailed hover cards. |
| **REQ-LAB-011** | Model Theory & Assumptions Panel | The UI MUST incorporate a collapsible sidebar panel summarizing core assumptions, mathematical formulas, state-space representations, and operational tradeoffs for each model. |
| **REQ-LAB-012** | Drive Replayer & Triple Gauge Pod | The UI MUST incorporate an interactive drive playback player with play/pause, step controls, variable playback speed (0.25x to 10x), scrub bar, and a Triple Simulated Gear Position Gauge Pod displaying M1 (Heuristic), M2 (Kinematic Bayes), and M3 (HMM) side-by-side with real-time gear, speed, RPM, and status. |
| **REQ-LAB-013** | Automated Parameter Grid Search Optimizer | The tool MUST provide a 1-click **⚡ Auto-Optimize Parameters** function (`POST /api/auto_tune`) executing automated grid search across algorithmic parameters to maximize the Glitch-Free Quality Score across logs. |
| **REQ-LAB-014** | Cross-Tool Shared Calibration | The tool MUST provide `GET /api/calibration` and `POST /api/calibration` endpoints and UI buttons ("💾 Save Shared Cal" / "📥 Load Shared Cal") interoperating with `decoder/gear_calibration.json`, and auto-load existing calibration upon page initialization. |
| **REQ-LAB-015** | Dedicated Submodel Tabs | The UI MUST provide dedicated tabs for each algorithm (M1 Heuristic, M2 Kinematic Bayes, M3 HMM State-Space) featuring focused dynamic visualizations, individual parameter calibration sliders, and two-way parameter synchronization with the main overview tab and JSON calibration. |
| **REQ-LAB-016** | DBC Uncertain State (State 14) Handling | The algorithms MUST distinguish between true Neutral (vehicle stationary or engine below idle) and Uncertain (State 14 in DBC: rolling vehicle above cutoff with engine above idle, e.g. mid-shift or unclassified ratio). |
| **REQ-LAB-017** | Dual-Chart Needle Synchronization | In all active tabs, the interactive playback timeline needle MUST scroll simultaneously across both the dynamics plot (speed/RPM) and the gear/model timeline plot with exact vertical pixel alignment. |

---

## 6. CAN Log Trimmer & Slicer (`trim_log.py`) Requirements

### 6.1 Scope & Purpose
`trim_log.py` provides non-destructive slicing, filtering, and inspection of 16-byte packed binary CAN logs (`*.bin`) via both CLI and an interactive browser-based UI (`--web`).

### 6.2 Functional Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-TRIM-001** | Zero-Pip Architecture & Interfaces | The trimmer MUST be implemented in standard Python 3 with zero pip dependencies, providing both an automated CLI and an interactive web GUI (`--web`). |
| **REQ-TRIM-002** | Temporal Slicing | The tool MUST support cutting logs by relative start time (`--start <sec>`) and end time (`--end <sec>`), strictly preserving frames within the requested temporal boundary. |
| **REQ-TRIM-003** | Frame Index Slicing | The tool MUST support cutting logs by exact start frame index (`--start-frame <N>`) and end frame index (`--end-frame <N>`). |
| **REQ-TRIM-004** | Timestamp Normalization & Rebasing | Output logs MUST rebase timestamps to start from `t = 0 ms` by default, while supporting `--preserve-timestamps` to retain raw ESP32 millisecond uptimes. |
| **REQ-TRIM-005** | CAN ID Whitelisting | The tool MUST support filtering frames by a comma-separated list of CAN arbitration IDs (`--ids`) specified in hex or decimal format. |
| **REQ-TRIM-006** | Safe Naming & Overwrite Protection | The tool MUST auto-generate descriptive non-colliding destination names (`<stem>_cut_...bin`), refuse to overwrite existing files unless `--force` / `-f` is specified, and strictly prohibit overwriting the input file. |
| **REQ-TRIM-007** | Interactive Browser GUI | When invoked with `--web`, the tool MUST serve an interactive Web interface allowing file upload/selection, live duration scrubbing, instant frame count feedback, CAN ID whitelisting, and direct binary download of sliced captures. |
| **REQ-TRIM-008** | Side-by-Side GPS Map & Interactive Snapping | The web interface MUST provide an integrated Leaflet GPS map drawer displaying the full trajectory, dynamically highlighting the active slice `[t_start, t_end]` at 60 FPS, rendering start/end circle pins, snapping the nearest slider when the route is clicked, and displaying a clean placeholder when no GPS data is present. |

---

## 7. Implementation Traceability Matrix

| Requirement ID | Implementing File | Function / Component / Handler | Verification Method |
|---|---|---|---|
| **REQ-SYS-001** | `decode.py`, `visualize.py`, `tuner.py`, `gear_lab.py`, `trim_log.py` | Top-level imports (stdlib only) | Automated headless test (no pip dependencies) |
| **REQ-SYS-002** | `decode.py`, `visualize.py`, `tuner.py`, `gear_lab.py`, `trim_log.py` | `read_bin_file()`, `CAN_FRAME_STRUCT`, `CANFrame` | Binary unpack test against `.bin` captures |
| **REQ-SYS-003** | `decode.py`, `visualize.py`, `tuner.py`, `gear_lab.py` | `DbcDatabase.parse()`, `DbcMessage.decode()` | DBC parse verification with signed/scale/enum/float |
| **REQ-SYS-004** | `visualize.py`, `tuner.py`, `gear_lab.py`, `trim_log.py` | CSS variables, `initTheme()`, `prefers-color-scheme` | Theme toggle & OS scheme auto-detection tests |
| **REQ-SYS-005** | All `.md` files | Markdown relative links | Static doc link validation |
| **REQ-SYS-006** | `tuner.py`, `gear_lab.py` | `.info-icon`, `title` attributes on controls | DOM verification of hover tooltips across all tabs |
| **REQ-SYS-007** | `decoder/tests/` | `test_trim_log.py`, `test_tuner.py`, `test_gear_lab.py`, `test_gear_algorithms.py` | Full test suite execution via `python3 -m unittest` |
| **REQ-DEC-001** | `decode.py` | `write_asc()` | Vector CANoe format validation test |
| **REQ-DEC-002** | `decode.py` | `write_csv()` | CSV column structure validation |
| **REQ-DEC-003** | `decode.py` | `write_signals_csv()` | Normalized time-series test with `-s` flag |
| **REQ-DEC-004** | `decode.py` | `write_wide_csv()` | Wide matrix test with `-w` flag |
| **REQ-DEC-005** | `decode.py` | `main()` argument parser | Multi-file and directory discovery tests |
| **REQ-DEC-006** | `decode.py` | `--output-dir` argument handling | Custom output path test |
| **REQ-VIS-001** | `visualize.py` | `ThreadingHTTPServer`, `DashboardHandler` | Server startup test on localhost:8080 |
| **REQ-VIS-002** | `visualize.py` | `loadLog()`, `select-log` listener | Dynamic log switching test |
| **REQ-VIS-003** | `visualize.py` | `renderSignalList()`, `applyPreset()` | Sidebar search and preset selection test |
| **REQ-VIS-004** | `visualize.py` | `updatePlot()`, dynamic Y-axis assignment | Multi-unit trace layout verification |
| **REQ-VIS-005** | `visualize.py` | `btn-toggle-subplots`, `updatePlot()` | Overlaid vs. stacked subplots toggle test |
| **REQ-VIS-006** | `visualize.py` | `handleWheel()`, `setupPlotListeners()` | Mouse navigation and 2D pan/zoom tests |
| **REQ-VIS-007** | `visualize.py` | `renderYScaleControls()`, drawer UI | Per-axis nudge and zoom test |
| **REQ-VIS-008** | `visualize.py` | `initMap()`, `renderGpsTrack()` | Leaflet map render and resize tests |
| **REQ-VIS-009** | `visualize.py` | `syncMapFromHover()`, map click listener | Bi-directional cursor synchronization test |
| **REQ-TUN-GEAR-001** | `tuner.py` | `computeAndRenderGear()` (Bayesian Model 2) | Bayesian inference calculation test |
| **REQ-TUN-GEAR-002** | `tuner.py` | `slider-m2-decay`, `slider-m2-inertia` listeners | Prior decay and transition inertia updates |
| **REQ-TUN-GEAR-003** | `tuner.py` | `slider-gear-minspeed`, `slider-gear-minrpm` | Dual-unit gating and standstill Neutral tests |
| **REQ-TUN-GEAR-004** | `tuner.py` | `slider-m2-conf`, state 14 emission | Confidence cutoff and Uncertain state test |
| **REQ-TUN-GEAR-005** | `tuner.py` | `slider-gear-tol`, `gear-r-1..5` inputs | Tolerance band and peak detection tests |
| **REQ-TUN-GEAR-006** | `tuner.py` | `slider-m2-latch`, latch state tracking | Temporal latching and debouncing verification |
| **REQ-TUN-GEAR-007** | `tuner.py` | `autoLoadSharedCal()`, `/api/calibration` | Startup auto-load and JSON save/load tests |
| **REQ-TUN-GEAR-008** | `tuner.py` | `renderGearMathExplanation()` | Dynamic math card DOM generation test |
| **REQ-TUN-GEAR-009** | `tuner.py` | `plot-gear-hist`, `btn-auto-gear-peaks` | Histogram render & peak detection test |
| **REQ-TUN-GEAR-010** | `tuner.py` | `plot-gear-dynamics`, relayout handlers | Dynamics plot synchronization test |
| **REQ-TUN-GEAR-011** | `tuner.py` | `computeAndRenderGear()` (glitch markers) | Visual glitch event markers on timeline |
| **REQ-TUN-GEAR-012** | `tuner.py` | `initTunerReplayer()`, `updateTunerReplayDisplay()` | Replayer playback, needle sync & GPS vehicle marker test |
| **REQ-TUN-GEAR-013** | `tuner.py` | `/api/calibration` GET & POST handlers | Shared calibration save/load test |
| **REQ-TUN-SPD-001** | `tuner.py` | `computeAndRenderSpeed()` ($k$ and $c$) | Speed correction formula test |
| **REQ-TUN-SPD-002** | `tuner.py` | `computeAndRenderSpeed()` (ECE R39 corridor) | Legal boundary and violation marker tests |
| **REQ-TUN-SPD-003** | `tuner.py` | `btn-auto-tune-speed` optimizer | Automated $k/c$ parameter solver test |
| **REQ-TUN-SPD-004** | `tuner.py` | `extract_algo_data()`, speed validity filter | GPS fix state rejection test |
| **REQ-TUN-SPD-005** | `tuner.py` | `getSpeedRateOfChange()`, `computeAndRenderSpeed()` | Dynamic acceleration filtering & sample qualification tests |
| **REQ-TUN-ANA-001** | `tuner.py` | `compute_analytics()` (cycle timing & jitter) | Bus timing and packet loss calculation tests |
| **REQ-TUN-ANA-002** | `tuner.py` | `compute_analytics()` (signal dispersion) | Slew rate and min/max/std dispersion tests |
| **REQ-TUN-ANA-003** | `tuner.py` | `renderAnalyticsTable()`, `/api/export_analytics`| Interactive table & CSV download tests |
| **REQ-LAB-001** | `gear_lab.py` | `build_aggregated_dataset()`, `extract_gear_log()`| Multi-log sample aggregation test (300k pts) |
| **REQ-LAB-002** | `gear_lab.py` | `fit_gear_clusters()` | Cluster center fitting test ($\mu_1..\mu_5$) |
| **REQ-LAB-003** | `gear_lab.py` | `run_model_2_bayesian()` | Kinematic Bayesian inference & clutch drop test |
| **REQ-LAB-004** | `gear_lab.py` | `run_model_3_hmm()`, `compute_empirical_transition_matrix()`| HMM transition matrix & clutch drop test |
| **REQ-LAB-005** | `tuner.py`, `gear_lab.py` | `evaluate_glitches()` | Dropouts, chatter, phantom shifts scorecards |
| **REQ-LAB-006** | `gear_lab.py` | `generate_esp32_c_header()`, `/api/export_c` | Automated GCC compilation test with comment block |
| **REQ-LAB-007** | `gear_lab.py` | `build_aggregated_dataset()`, `renderTimeline()`| Concatenated timeline & boundary markers test |
| **REQ-LAB-008** | `gear_lab.py` | `renderTimeline()`, layout mode toggle | Stacked subplots vs. shared overlay test |
| **REQ-LAB-009** | `gear_lab.py` | `recomputeAll()`, tuning drawer listeners | Live parameter tuning and 60fps update test |
| **REQ-LAB-010** | `gear_lab.py` | `buildGlitchTraces()`, `renderTimeline()` | Visual glitch markers on model timelines |
| **REQ-LAB-011** | `gear_lab.py` | Collapsible sidebar theory card | Theory & mathematical assumptions DOM check |
| **REQ-LAB-012** | `gear_lab.py` | `initReplayer()`, `updateReplayDisplay()` | Triple Gauge Pod and needle synchronization test |
| **REQ-LAB-013** | `gear_lab.py` | `optimize_parameters()`, `/api/auto_tune` | Automated parameter grid search test |
| **REQ-LAB-014** | `gear_lab.py` | `/api/calibration` GET & POST, startup load | Cross-tool JSON calibration exchange & auto-load |
| **REQ-LAB-015** | `gear_lab.py` | `switchTab()`, `renderActiveTabPlots()`, submodel tabs | Multi-tab UI and bidirectional parameter sync test |
| **REQ-LAB-016** | `gear_lab.py`, `tuner.py` | State 14 classification (`Uncertain`) | Neutral (0) vs. Uncertain (14) classification tests |
| **REQ-LAB-017** | `gear_lab.py` | `ensureNeedles()`, `updateReplayDisplay()` | Multi-plot needle positioning and margin sync test |
| **REQ-TRIM-001** | `trim_log.py` | `parse_args()`, `run_server()`, stdlib imports | Standalone execution and zero-pip verification |
| **REQ-TRIM-002** | `trim_log.py` | `trim_bin_log()` (`start_s`, `end_s`) | Temporal boundaries cutting test |
| **REQ-TRIM-003** | `trim_log.py` | `trim_bin_log()` (`start_frame`, `end_frame`) | Frame-index boundaries slicing test |
| **REQ-TRIM-004** | `trim_log.py` | `trim_bin_log()` (`rebase_timestamps`) | Timestamp rebasing and preservation tests |
| **REQ-TRIM-005** | `trim_log.py` | `trim_bin_log()` (`filter_ids`) | CAN ID whitelisting and rejection tests |
| **REQ-TRIM-006** | `trim_log.py` | `default_output_name()`, overwrite checks | Non-destructive naming & safety tests |
| **REQ-TRIM-007** | `trim_log.py` | `HTML_PAGE`, `TrimRequestHandler` | Web GUI endpoint and download validation |
| **REQ-TRIM-008** | `trim_log.py` | `renderGpsMap()`, `updateMapSlice()`, Leaflet | Side-by-side map drawer, route snapping & placeholder |
| **REQ-SYS-008** | `decoder/common/`, `decoder/web/` | `can_core.py`, `dbc.py`, `calibration.py`, `http_server.py`, static assets, templates | `test_common_components.py` suite (7 tests) & zero-pip imports |


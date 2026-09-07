# MiniGauge Decoder Toolset Requirements Specification

This document defines the functional, technical, and architectural requirements for the Python 3 offline diagnostic and calibration toolset located in `decoder/`. The toolset consists of three complementary programs:
1. **Batch Decoder & Exporter (`decode.py`)**
2. **Interactive Signal Visualizer (`visualize.py`)**
3. **Algorithm Calibration & Tuning Lab (`tuner.py`)**

---

## 1. System-Wide Architectural Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-SYS-001** | Zero Pip Dependencies | All decoder utilities MUST operate strictly using the Python 3 standard library (`struct`, `json`, `http.server`, `urllib`, `pathlib`, etc.). No external pip package installations (`pandas`, `numpy`, `cantools`) shall be required. |
| **REQ-SYS-002** | Binary Frame Layout | Tools MUST correctly unpack the 16-byte packed CAN frame format emitted by `main/logging.cpp`: 4-byte uptime timestamp (ms), 2-byte CAN ID (little-endian), 1-byte DLC, 8-byte payload, and 1-byte padding. |
| **REQ-SYS-003** | DBC Parsing Fidelity | Tools MUST support parsing the official CAN database (`binocan.dbc`), decoding integer, float, signed/unsigned endianness (Intel little-endian and Motorola big-endian), scaling factors, offsets, min/max limits, unit strings, and discrete value enumeration tables. |
| **REQ-SYS-004** | Dual Theme Support | All web-based interfaces MUST support automatic OS light/dark detection and dynamic manual switching (Auto / Light / Dark) without page reloads, persisting preference in `localStorage`. |
| **REQ-SYS-005** | Portable Relative Linking | All internal documentation references MUST use relative file paths without machine-specific absolute filesystem paths. |

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
| **REQ-TUN-GEAR-001** | Algorithm Formulations | The tool MUST provide three switchable algorithm configurations accessible via presets and modular sub-operation controls: <br>1. *Baseline*: Pure ratio gating and ratio-domain EMA.<br>2. *RPM Pre-Filtered*: Optional input pre-filtering (EMA or SMA) applied to `DBG_RPM_freq` prior to ratio computation.<br>3. *Latched Output*: Temporal latching/debouncing applied to the classified gear output. |
| **REQ-TUN-GEAR-002** | RPM Input Pre-Filter (Stage 1) | When enabled, the tool MUST smooth `DBG_RPM_freq` using either an Exponential Moving Average ($f_{\text{RPM,filt}}(t) = \alpha f + (1-\alpha) f_{\text{prev}}$ with time constant $\tau \in [0.02, 0.50]\text{ s}$) or a Simple Moving Average ($W \in [0.02, 0.50]\text{ s}$), feeding the filtered frequency into the ratio denominator. |
| **REQ-TUN-GEAR-003** | Triple Gating Corridor (Stage 2) | The ratio $r(t) = f_{\text{speed}} / f_{\text{RPM}}$ MUST only be processed when meeting three physical gates: <br>1. $f_{\text{speed}} \ge f_{\text{speed,min}}$ (rejects standstill).<br>2. $f_{\text{RPM}} \ge f_{\text{RPM,min}}$ (rejects engine stall/idle).<br>3. $\|dr/dt\| \le \text{Gate}_{\text{stab}}$ (rejects clutch slip and gear shift transients). |
| **REQ-TUN-GEAR-004** | Dual-Unit Cutoff Sliders | Gating sliders MUST display dual units in real-time: <br>• Speed cutoff: frequency in `Hz` and equivalent vehicle speed in `km/h` ($V = f \times 0.2444$).<br>• RPM cutoff: frequency in `Hz` and equivalent engine speed in `RPM` ($\text{RPM} = f \times 30.0$). |
| **REQ-TUN-GEAR-005** | Ratio-Domain Smoothing (Stage 3) | Primary smoothing MUST be applied directly to the ratio ($r_{\text{EMA}}(t) = \alpha r + (1-\alpha) r_{\text{EMA,prev}}$) to prevent artificial ratio spikes caused by engine vs. driveline inertia differential phase lag. |
| **REQ-TUN-GEAR-006** | 5-Speed + Neutral Classification | The tool MUST classify candidate gear $i \in \{1..5\}$ if $\|r_{\text{EMA}} - R_i\| \le \text{tol} \times R_i$. Values falling outside all gear bands or failing gating conditions MUST classify as Neutral (0). |
| **REQ-TUN-GEAR-007** | Output Latching & Debouncing (Stage 4) | When latching is enabled, a gear transition from $G_{\text{cur}}$ to $G_{\text{new}}$ MUST only take effect if $G_{\text{new}}$ is sustained continuously for at least $T_{\text{latch}}$ ms ($50\text{ to }600\text{ ms}$). If vehicle speed or RPM drops below absolute minimum gating thresholds, output MUST transition immediately to Neutral without delay. |
| **REQ-TUN-GEAR-008** | Dynamic Math Explainer | The sidebar MUST display a dynamic mathematical explainer card that rebuilds its formulas, active parameter values, and explanatory text in real time as presets or modular stage checkboxes change. |
| **REQ-TUN-GEAR-009** | Ratio Histogram & Auto-Peak Detection | The UI MUST display a sample ratio histogram with projected tolerance bands, accompanied by an **Auto-Detect Peaks** function that clusters driving ratios to seed nominal gear ratios $R_1..R_5$. |
| **REQ-TUN-GEAR-010** | Synchronized Dynamics Timeline | The UI MUST plot a synchronized dual-axis graph of `ITF_speed_kph` and `ITF_rpm` alongside the ratio and estimated gear curves, maintaining time synchronization with pan/zoom and the GPS track drawer. |

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

### 4.5 Tab 4: Signal & Bus Analytics Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-TUN-ANA-001** | Message Timing Metrics | The tool MUST compute for every CAN message: frame count, nominal cycle time, average cycle time, minimum cycle time, maximum cycle time, cycle jitter standard deviation ($\sigma_T$), bus frequency (Hz), and estimated frame drop %. |
| **REQ-TUN-ANA-002** | Signal Value & Slew Dispersion | The tool MUST compute for each individual decoded signal: sample count, unit, minimum, maximum, mean, median, standard deviation, and maximum slew rate ($|dx/dt|_{\max}$). |
| **REQ-TUN-ANA-003** | Tabular Search & CSV Export | The analytics view MUST feature search filtering, sortable column headers, collapsible message trees, and a 1-click **Export Analytics CSV** button. |

---

## 5. Implementation Traceability Matrix

| Requirement ID | Implementing File | Function / Component / Handler | Verification Method |
|---|---|---|---|
| **REQ-SYS-001** | `decode.py`, `visualize.py`, `tuner.py` | Top-level imports (stdlib only) | Automated headless test (no pip dependencies) |
| **REQ-SYS-002** | `decode.py`, `visualize.py`, `tuner.py` | `read_bin_file()`, `CAN_FRAME_STRUCT` | Binary unpack test against `.bin` captures |
| **REQ-SYS-003** | `decode.py`, `visualize.py`, `tuner.py` | `DbcDatabase.parse()`, `DbcMessage.decode()` | DBC parse verification with signed/scale/enum |
| **REQ-SYS-004** | `visualize.py`, `tuner.py` | `initTheme()`, `setTheme()`, CSS tokens | Theme toggle verification in browser |
| **REQ-SYS-005** | All `.md` files | Markdown relative links | Static doc link validation |
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
| **REQ-TUN-GEAR-001** | `tuner.py` | `select-gear-preset`, `computeAndRenderGear()` | Preset switcher & algorithm simulation tests |
| **REQ-TUN-GEAR-002** | `tuner.py` | `computeAndRenderGear()` (effRpmFreqs EMA/SMA) | Pre-filter calculation test against noisy RPM |
| **REQ-TUN-GEAR-003** | `tuner.py` | `computeAndRenderGear()` (triple gating logic) | Standstill and shift transient rejection tests |
| **REQ-TUN-GEAR-004** | `tuner.py` | `updateGearLabels()` (dual units: Hz + RPM/kph) | Real-time label string formatting verification |
| **REQ-TUN-GEAR-005** | `tuner.py` | `computeAndRenderGear()` (ratio-domain EMA) | Ratio smoothing & inertia test |
| **REQ-TUN-GEAR-006** | `tuner.py` | `computeAndRenderGear()` (band classification) | 5-speed + Neutral classification test |
| **REQ-TUN-GEAR-007** | `tuner.py` | `computeAndRenderGear()` (latching state machine) | Transient debouncing test (transitions 74 -> 17) |
| **REQ-TUN-GEAR-008** | `tuner.py` | `renderGearMathExplanation()` | Dynamic math card DOM generation test |
| **REQ-TUN-GEAR-009** | `tuner.py` | `plot-gear-hist`, `btn-auto-gear-peaks` | Histogram render & peak detection test |
| **REQ-TUN-GEAR-010** | `tuner.py` | `plot-gear-dynamics`, relayout handlers | Dynamics plot synchronization test |
| **REQ-TUN-FUEL-001** | `tuner.py` | `computeAndRenderFuel()` (SMA vs. EMA) | Fuel filter algorithm simulation test |
| **REQ-TUN-FUEL-002** | `tuner.py` | `computeAndRenderFuel()` (quantization step) | Discrete rounding simulation test |
| **REQ-TUN-FUEL-003** | `tuner.py` | `computeAndRenderFuel()` (tight autoscale) | Autoscale and zoom retention test |
| **REQ-TUN-FUEL-004** | `tuner.py` | `computeAndRenderFuel()` (slew & jitter metrics) | Error delta, slew rate, and jitter tests |
| **REQ-TUN-SPD-001** | `tuner.py` | `computeAndRenderSpeed()` ($k$ and $c$) | Speed correction formula test |
| **REQ-TUN-SPD-002** | `tuner.py` | `computeAndRenderSpeed()` (ECE R39 corridor) | Legal boundary and violation marker tests |
| **REQ-TUN-SPD-003** | `tuner.py` | `btn-auto-tune-speed` optimizer | Automated $k/c$ parameter solver test |
| **REQ-TUN-SPD-004** | `tuner.py` | `extract_algo_data()`, speed validity filter | GPS fix state rejection test |
| **REQ-TUN-ANA-001** | `tuner.py` | `compute_analytics()` (cycle timing & jitter) | Bus timing and packet loss calculation tests |
| **REQ-TUN-ANA-002** | `tuner.py` | `compute_analytics()` (signal dispersion) | Slew rate and min/max/std dispersion tests |
| **REQ-TUN-ANA-003** | `tuner.py` | `renderAnalyticsTable()`, `/api/export_analytics`| Interactive table & CSV download tests |

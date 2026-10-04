---
name: python-tools-ecosystem
description: Comprehensive guide and recipe for building zero-dependency Python tools in the MiniGauge tools/ directory, covering code reuse, data retention, cross-tool calibration persistence, atomic backups, and unified UI styling.
---

# Python Tools Ecosystem Recipe & Architectural Guide

This skill guides the creation and evolution of offline diagnostic, visualization, and calibration tools located in `tools/` within the MiniGauge workspace.

---

## 1. Core Architectural Constraints

1. **Zero External Pip Dependencies (`REQ-SYS-001`)**:
   - All tools MUST run strictly on the Python 3 standard library (`struct`, `json`, `http.server`, `urllib`, `pathlib`, `argparse`, `shutil`, `re`, `socket`, `webbrowser`, `tempfile`).
   - Never import external packages like `pandas`, `numpy`, `cantools`, or `flask`.
2. **Three-Tier Modular Architecture (`REQ-SYS-008`)**:
   - `tools/common/`: Shared, decoupled backend utilities (`can_core.py`, `http_server.py`, `calibration.py`, `log_loader.py`, `dbc.py`).
   - `tools/web/static/{css,js}`: Static styling and vanilla ES6+ scripts.
   - `tools/web/templates/`: Semantic HTML5 templates.
   - Root application scripts (`tools/<tool_name>.py`): Slim CLI entrypoints inheriting from `common.BaseAppHandler`.
3. **Automated Host Regression (`REQ-SYS-007`)**:
   - Every tool must have a companion test suite in `tools/tests/test_<tool_name>.py`.
   - Tests must exercise CLI argument parsing, API endpoints, serialization, validation, and server lifecycles using `unittest`.

---

## 2. Code Reuse Blueprint

When implementing a new tool, reuse existing core components rather than reinventing them:

### 2.1 Hardware Frame Ingestion (`tools/common/can_core.py`)
- **Binary Packing Format**: MiniGauge binary logs (`.bin`) use 16-byte packed records: `<IHB8sx`.
- **`CanFrame`**: Standard data container with dual constructor compatibility (4-arg and 5-arg) and aliases (`timestamp_ms`, `can_id`, `dlc`, `data`, `time_rel_s`).
- **`read_bin_file(path)`**: Ingests `.bin` files into a list of `CanFrame` records.
- **`find_bin_files()`**: Auto-discovers files across `tools/`, `tools/fixtures`, and current directory with natural numerical sorting (`natural_sort_key`).

### 2.2 Reusable HTTP Server Framework (`tools/common/http_server.py`)
- **`BaseAppHandler`**: Subclass this for application request dispatching:
  - `self.read_json_body()`: Safely parse incoming JSON bodies.
  - `self.send_json(data)`: Encode and emit JSON with CORS headers.
  - `self.send_html(content)`: Serve HTML pages with UTF-8 encoding.
  - `self.serve_static(path)`: Automatically resolve and stream files from `tools/web/static/` with proper MIME types (`MIME_TYPES`).
  - `self.parse_query()`: Parse URL paths and query parameters.
- **`start_server(HandlerClass, port=8080, open_browser=True)`**:
  - Dynamically finds available ports if conflict occurs (`find_available_port`).
  - Launches multi-threaded `ThreadingHTTPServer`.
  - Displays formatted console diagnostic banners.
  - Automatically launches the default system web browser unless disabled via `--no-browser`.

### 2.3 Shared Calibration & Data Store (`tools/common/calibration.py`)
- Used for cross-tool algorithm synchronization (e.g. `gear_calibration.json` between `tuner.py`, `gear_lab.py`, and C99 firmware header generation).

---

## 3. Data Retention & Configuration Persistence Protocol

To ensure seamless interoperability and prevent data loss across user sessions and multiple tools:

### 3.1 Centralized JSON Stores
- Place shared algorithm configurations in `tools/` (e.g., `gear_calibration.json`).
- Place diagnostic dictionaries and communication train definitions in `config/` (e.g., `dids.json`, `ddlis.json`).

### 3.2 Automated Atomic Backup Rotation
Before mutating any user configuration file on disk:
```python
def create_backup(target_file: Path) -> Optional[Path]:
    """Creates a timestamped backup before modifying a JSON configuration file."""
    if not target_file.is_file():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = target_file.with_name(f"{target_file.name}.bak_{timestamp}")
    shutil.copy2(target_file, backup_path)
    return backup_path
```

### 3.3 Atomic Disk Writes
Always ensure atomic persistence to avoid truncated JSON files upon abrupt termination:
- Format JSON with `indent=2`.
- Include standard metadata envelopes:
  - `source`: Tool or module that initiated the save.
  - `updated_at`: ISO-8601 UTC timestamp (`datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`).
  - `version`: Monotonic integer schema version.

### 3.4 Embedded Schema Guides
Provide an embedded `_schema_guide` object in top-level JSON configurations:
```json
{
  "_schema_guide": {
    "description": "Schema definition and valid ranges...",
    "keys": { ... }
  }
}
```
Application validation logic should skip `_schema_guide` keys when parsing configuration records.

### 3.5 Cross-Tool Parameter Aliasing
When multiple tools reference the same underlying parameters with different historical names or units, synchronize them bidirectionally in `load`/`save` handlers:
```python
# Bidirectional alias sync
if "tolerance" in data:
    current["tolerance"] = data["tolerance"]
    current["tolerance_abs"] = data["tolerance"]
if "min_speed_hz" in data and "min_speed_kph" not in data:
    current["min_speed_kph"] = round(data["min_speed_hz"] * 2.214, 3)
```

### 3.6 Client-Side Preference Persistence
- UI theme selections, active filter pills, and toggle states must be persisted in `localStorage` under predictable namespaces:
  - `minigauge_theme_pref`: Theme selection (`'auto'`, `'light'`, `'dark'`).
  - `minigauge_<tool>_<setting>`: Tool-specific view options.

---

## 4. UI & Design System Guidelines (`REQ-SYS-004`)

All web dashboards in `tools/` must share a unified visual identity:

### 4.1 Theme Tokens (`theme.css`)
- **Ubuntu Yaru Dark**:
  - Background: `#0a0a0a` / Cards: `#181818`.
  - Primary Accent: Faded warm orange `#dd6b3d` (`--primary`).
  - Secondary Accent: Steel blue / royal blue `#2b5c92` (`--accent`).
  - Panel Borders: `rgba(221, 107, 61, 0.40)` (1px subtle border).
- **Cold White Light**:
  - Background: `#f8fafc` / Cards: `#ffffff`.
  - Primary Accent: Faded royal blue `#2b5c92` (`--primary`).
  - Secondary Accent: Faded warm orange `#dd6b3d` (`--accent`).
  - Panel Borders: `rgba(43, 92, 146, 0.38)`.
  - Sliders: Pure white tracks with 1px border.

### 4.2 Standard Layout & Controls
1. **Header (`.app-header`)**:
   - Left: Logo icon + tool title with colored secondary badge.
   - Center: Navigation tabs or primary view selector.
   - Right: File badges, status indicators, and `#theme-toggle-btn`.
2. **Theme Manager (`theme.js`)**:
   - Always link `/static/js/theme.js` at the bottom of the HTML template.
   - Provides 3-state toggle: `Auto (follows OS)` -> `Light` -> `Dark` -> `Auto`.
   - Automatically synchronizes range sliders and dispatches `minigauge-theme-changed` events.
3. **Toasts (`toast.js`)**:
   - Use `showToast(msg, type)` for non-blocking success, warning, or error alerts.

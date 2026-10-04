# MiniGauge BMWP2000 Diagnostic Toolset Requirements Specification

This document defines the functional, technical, and architectural requirements for the Python 3 offline diagnostic and configuration tools located in `tools/`:
1. **BMWP2000 LID Composer (`lid_composer.py`)**
2. **BMWP2000 Diagnostic Exchange Viewer (`bmwp2000_viewer.py`)**

---

## 1. System-Wide Architectural Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-SYS-001** | Zero Pip Dependencies | All diagnostic utilities MUST operate strictly using the Python 3 standard library (`struct`, `json`, `http.server`, `urllib`, `pathlib`, etc.). No external pip package installations shall be required. |
| **REQ-SYS-002** | Binary Frame Layout | Tools MUST correctly unpack the 16-byte packed CAN frame format emitted by `main/logging.cpp`: 4-byte uptime timestamp (ms), 2-byte CAN ID (little-endian), 1-byte DLC, 8-byte payload, and 1-byte padding. |
| **REQ-SYS-003** | Unified Design System & OS Theme Sync | All web-based interfaces MUST implement the unified design palette (Ubuntu Yaru Dark with faded orange accents; Cold White Light with faded royal blue accents). All tools MUST automatically detect and adapt to the host OS color scheme with live reactive updates and manual overrides persisted in `localStorage`. |
| **REQ-SYS-004** | Portable Relative Linking | All internal documentation references MUST use relative file paths without machine-specific absolute filesystem paths. |
| **REQ-SYS-005** | Automated Regression Suite | The diagnostic toolset MUST maintain automated, repeatable unit and integration test suites in `tools/tests/` verifying server lifecycles, API endpoints, ISO-TP reassembly, and KWP2000 service dissection. |
| **REQ-SYS-006** | Modular Architecture & Static Asset Separation | Core CAN parsing (`can_core.py`), multi-format log loading (`log_loader.py`), ISO-TP / KWP2000 dissection (`isotp_kwp.py`), and HTTP request handling (`http_server.py`) MUST reside in `tools/common/`. Shared CSS/JS styling and scripts MUST reside in `tools/web/static/`, and semantic HTML templates in `tools/web/templates/`. |

---

## 2. BMWP2000 LID Composer (`lid_composer.py`) Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-COMP-001** | Standalone Zero-Pip Local Web Server | The tool MUST run with zero external pip dependencies, serving an interactive two-tab dashboard (LID Train Composer & Master CID Editor) on an ephemeral or user-selected port (`--port`, default 8092) with automatic browser opening. |
| **REQ-COMP-002** | Dual-File Dynamic Configuration Binding | The tool MUST bind to `config/cids.json` and `config/lids.json` by default, or alternate user-provided paths (`--cids`, `--lids`), preserving `_schema_guide` metadata objects across reads and writes. |
| **REQ-COMP-003** | Visual LID Sequence Composition & Reordering | The composer MUST provide a dual-column layout (available master CIDs palette on left, ordered active train sequence on right) with 1-click addition, reordering controls (Move Up, Move Down), signal removal, and train metadata editing (`local_id`, `name`, `transmission_mode`). |
| **REQ-COMP-004** | ISO-TP Framing & CAN Frame Capacity Inspector | The tool MUST compute and display real-time telemetry metrics: total RAM payload bytes, ISO 14230-3 positive response size (`+2B` for `0x61` SID and `local_id`), ISO 15765-2 framing (`Single Frame (SF)` vs. `Multi-Frame (1 FF + N CF)`), and total CAN frame count. |
| **REQ-COMP-005** | Master CID Dictionary Editor & Live Formula Preview | The tool MUST provide a searchable data table of all defined CIDs, an Add/Edit modal dialog with real-time formula string preview `((raw * mul) / div) + add [unit]`, and collision prevention on duplicate keys via automatic counter suffixing (`_1`, `_2`). |
| **REQ-COMP-006** | Automatic Timestamped Backup Persistence | Before modifying or writing to `config/lids.json` or `config/cids.json`, the backend MUST create a timestamped backup copy (`.bak_YYYYMMDD_HHMMSS`) in the same directory. |
| **REQ-COMP-007** | Strict Structural and Type Validation | The backend MUST validate incoming JSON payloads (`POST /api/lids`, `POST /api/cids`), rejecting invalid hexadecimal patterns, out-of-range memory sizes (1, 2, 4 bytes), zero divisors, duplicate local IDs, and invalid transmission modes with `HTTP 400 Bad Request`. |

---

## 3. BMWP2000 Diagnostic Exchange Viewer (`bmwp2000_viewer.py`) Requirements

| ID | Title | Requirement Statement |
|---|---|---|
| **REQ-VIEW-001** | Multi-Format CAN Log Ingestion | The tool MUST parse MiniGauge 16-byte `.bin` logs, SocketCAN `candump` logs (`.log`), and Vector ASCII (`.asc`) logs into unified `CanFrame` lists. |
| **REQ-VIEW-002** | ISO-TP Multi-Frame Reassembly | The tool MUST reassemble Single Frames (SF) and multi-frame sequences (First Frame FF + Consecutive Frames CF + Flow Control FC) into contiguous diagnostic payloads according to ISO 15765-2. |
| **REQ-VIEW-003** | KWP2000 Service Dissection | The tool MUST parse and dissect ISO 14230-3 diagnostic requests and responses, correlating query and response pairs across Services `0x10`, `0x1A`, `0x21`, `0x2C`, and `0x3E`. |
| **REQ-VIEW-004** | Negative Response Code (NRC) Flagging | The tool MUST detect Service `0x7F` negative responses, highlight them with distinctive color tokens, and decode canonical ISO 14230-3 NRC definitions. |
| **REQ-VIEW-005** | Dynamic LID Dissection & CID Scaling | The tool MUST unpack Service `0x2C` sub-mode `0x02` (`defineByCommonIdentifier`) sub-blocks, track dynamically defined LID payload layouts, unpack periodic broadcast frames, and scale decoded CID values using engineering formulas from `config/cids.json`. |
| **REQ-VIEW-006** | Visual Inspector & Memory Strip | The viewer inspector MUST feature a horizontal visual CID train memory layout strip and collapsible underlying CAN frames accordion without rendering glitches. |
| **REQ-VIEW-007** | Add to Master CIDs Modal | The tool MUST provide a modal interface to persist discovered/unregistered CIDs directly into `config/cids.json` with automatic backup creation. |

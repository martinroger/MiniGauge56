# Base Antigravity Rules & Core Constraints

## 1. Requirement Grilling & Planning Phase
- **Mandatory Interview**: Before generating multi-file implementations or writing code for non-trivial tasks, grill me on requirements!
- Ask targeted questions regarding:
  - Scope and core constraints.
  - Expected output formats or architecture patterns.
  - Potential edge cases or dependencies.

## 2. Error Diagnostics & Log Inspection
- Never form a diagnostic hypothesis for a runtime failure or test breakage without reading the full, un-truncated error log.
- Your very first action when an error occurs must be to fetch and read the exact logs.
- Do not apply superficial patches or mask symptoms. Fix the root cause.
- **Max Build Retry Safety Ceiling**: If a build or compilation command fails 10 consecutive times, STOP tool execution immediately. Present a concise summary of compilation failures and request user guidance before attempting further code modifications.

## 3. Code & Method Signature Integrity
- Maintain existing comments and docstrings unless explicitly asked to modify them.
- Verify method signatures and object properties before calling them.

## 4. Standard Protocol & Industry Specification Nomenclature
- **Standard Name Alignment**: When implementing code based on an established standard or industry specification (e.g. ISO 14230-3 / KWP2000, ISO 15765, HTTP), strictly adopt the official protocol service and parameter names (e.g., `readDataByLocalIdentifier`, `dynamicallyDefineLocalIdentifier`, `recordLocalIdentifier`, `transmissionMode`, `responseCode`) throughout method declarations and variable names.

## 5. Multi-Agent & Subagent Execution Standards
- **Sequential Build Enforcement**: Subagents are strictly prohibited from executing build, compilation, or flash commands concurrently. All verification builds must be run sequentially or yielded to the parent overseer agent to execute.
- **Workspace & Branch Isolation**: Subagents are strictly restricted to the workspace root directory (must not read, write, or inspect files outside the repository) and must operate on isolated feature branches, submitting work via Pull Requests or structured diff reviews for parent overseer merging.
# ESP-IDF & ESP32 Specific Project Rules

## 1. Hardware & Target Verification
- Ask or confirm target SoC: ESP32, ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6, ESP32-H2, etc.
- Ask or confirm target ESP-IDF version line (< v5.5, >= v5.5, or >= v6.0).

## 2. MCP Server & Documentation Protocol
- **Documentation Lookup**: If the `espressif-docs` MCP server is available, use `search_espressif_sources` as the authoritative source for command flags, `sdkconfig` options, and API specifications.
- **Build Execution**: Check if an ESP-IDF Build MCP server is available. If present, prefer using its native MCP tools for building, flashing, and configuring targets.

## 3. Virtual Environment Execution Standards & Build Commands
- **ESP-IDF Build Execution via `eim`**: If an ESP-IDF Build MCP server is NOT available, run `eim run "idf.py fullclean build"` (or `eim exec -- idf.py build`) from the project root directory. Because `eim` accesses toolchains and configurations stored in `~/.espressif`, `eim` commands MUST be executed in sandbox bypass mode (`BypassSandbox: true`).
- **ESP-IDF Environment Sourcing**: When direct `idf.py` is available in exported shell environments (`. $IDF_PATH/export.sh`), run `idf.py fullclean build`.
- **Kconfig / `sdkconfig` Mandatory `fullclean` Rule**: If any `Kconfig`, `Kconfig.projbuild`, `sdkconfig`, or `sdkconfig.*` defaults/override file is added, modified, or deleted, a `fullclean` build (`idf.py fullclean build` or `eim run "idf.py fullclean build"`) is **strictly mandatory** before building to ensure CMake cache re-evaluation.
- **Session Start & Branch Switch Clean Invariant (`fullclean`)**: At the start of a new development session, immediately after switching Git branches, or when changing target chip / SDK configuration, ALWAYS execute a full clean (`idf.py fullclean` or `eim run "idf.py fullclean" <env>`) prior to building (`idf.py build`). This purges stale CMake caches, outdated Kconfig generated headers, and Ninja build objects to prevent false compilation failures or linker mismatches.

## 4. Project File Output Standards & Directory Boundaries
- Always ensure ESP-IDF projects maintain standard structure:
  - `CMakeLists.txt` at root.
  - `main/CMakeLists.txt` registering components and sources.
  - `main/main.c` or `main/main.cpp`.
  - `sdkconfig.defaults` for reproducible configuration.
- **`managed_components/` Read-Only Boundary**: `managed_components/` is strictly READ-ONLY. Never modify, patch, or edit files inside `managed_components/`. Solve component dependency or build issues in main application code, wrapper files, `Kconfig`, or via `main/idf_component.yml`. Revert any accidental modifications inside `managed_components/` immediately.
- **Kconfig Embedded Asset Path Resolution**: When using Kconfig to specify custom relative file paths for embedded build assets (e.g., `EMBED_TXTFILES` or `EMBED_FILES`), CMake scripts MUST resolve paths relative to `${PROJECT_DIR}` and verify file existence before calling `target_add_binary_data()` to prevent silent build or linker failures.

## 5. Peripheral & Target-Specific Pinout Protocol
- Pinouts, I2C/SPI bus speeds, and UART baud rates MUST be explicitly defined in header macros or `Kconfig`.
- **Target-Specific Strapping Pin Verification**: Always check strapping GPIO assignments against the *active build target chip architecture* (e.g. ESP32: GPIO 0,2,5,12,15; ESP32-S3: GPIO 0,3,45,46; ESP32-C3: GPIO 2,8,9; ESP32-C6: GPIO 8,9,15). Do not apply a generic blanket strapping list across different MCUs.
- **FreeRTOS Core Pinning & Task Stack Allocation**:
  - Parametrize FreeRTOS task core allocations via `Kconfig` (e.g. Core 0 vs Core 1) to prevent race conditions and CPU spin loops on multi-core targets (e.g., ESP32 / ESP32-S3).
  - Verify task stack sizes for FreeRTOS tasks (minimum 2048–4096 bytes for tasks calling C stdlib/logging) to prevent stack overflow.
- **TWAI/CAN Bus-Off & Disconnected Hardware Recovery**: Protocol daemons and CAN/TWAI drivers MUST handle disconnected hardware states (`TWAI_STATE_BUS_OFF` or missing transceiver ACK) gracefully. Disconnected hardware or un-terminated bench setups must never cause infinite retry loops, watchdog resets, or task deadlocks. Drivers must include timeout limits, error state reporting, and automatic or manual recovery triggers (e.g. `twai_initiate_recovery()`).

## 6. Global README Sub-Project External Dependency Matrix
- **Dependency Summary Table**: For projects containing multiple sub-projects or component packages, the top-level repository `README.md` MUST contain and maintain a structured summary table of external dependencies across all sub-projects.
- **Required Columns**:
  - **Sub-Project**: Name of the sub-project directory.
  - **External Dependency**: Name of the component package invoked via `idf_component.yml`.
  - **Locally Installed Version**: Exact version tag or short git commit SHA currently installed in `managed_components` / `dependencies.lock`.
  - **Version Requirement**: The constraint or version specification declared in `idf_component.yml` (when available).

## 7. ESP-IDF HTTP Server URI Handler Capacity Check
- **URI Handler Counting**: When configuring `httpd_config_t` for `esp_http_server`, count the total number of URI handlers to be registered across all modules (REST API endpoints, static SPIFFS assets, and WebSocket `/ws` endpoints).
- **Explicit Capacity Allocation**: `HTTPD_DEFAULT_CONFIG()` defaults `httpd_cfg.max_uri_handlers = 8`. If the total number of registered URI handlers exceeds 8, explicitly set `httpd_cfg.max_uri_handlers` to a sufficient capacity (e.g., `httpd_cfg.max_uri_handlers = 16;`) before calling `httpd_start()` to prevent `W (httpd_uri): no slots left for registering handler` registration failures.
# Embedded Real-Time & High-Throughput System Rules

Rules and architectural constraints for high-throughput, latency-critical firmware projects (CAN/TWAI, BLE, USB, I2S, high-rate telemetry, and diagnostic daemons).

---

## 1. Zero Dynamic Allocation in Hot Path
- **Prohibition in Processing Loops**: In streaming telemetry pipelines (e.g. >= 10 Hz), never call dynamic memory allocation functions (`malloc`, `calloc`, `realloc`, `free`, `new`, `delete`) inside packet reception callbacks, interrupt handlers (ISRs), or high-rate transmission loops.
- **Static Storage & Pre-Allocation**:
  - Enforce statically sized FreeRTOS queues or fixed-capacity ring buffers initialized at boot.
  - Pass data by pointer or copy into pre-allocated buffer pools rather than allocating heap payloads per packet.
  - Sizing must account for maximum burst windows with safety margins.

---

## 2. Separation of Protocol from Hardware (Testability First)
- **Pure Protocol Logic**: Frame reassembly state machines, packet parsers, serialization routines, and checksum algorithms must remain pure C/C++, strictly decoupled from MCU-specific hardware headers (`esp_*.h`, FreeRTOS headers, or vendor SDKs).
- **Automated Host-Side Unit Testing**:
  - All protocol decoding and bit-packing logic must include automated host unit tests (e.g., using Unity or standard GCC/Clang suites with `-Wall -Wextra -Werror`).
  - Unit tests must be verified against actual binary captures (including fragmented packets, back-to-back concatenated frames, and deliberate bit-corruption vectors) on the host prior to flashing hardware.

---

## 3. Stream Boundary Robustness & Packet Framing
- **No 1-to-1 Frame Assumptions**: Streaming transports (BLE notifications, serial streams, TCP sockets) do not guarantee discrete packet boundaries. A single read/notification may contain partial frames, multi-frame concatenations, or arbitrary split boundaries.
- **Resynchronizing State Machines**:
  - Parser state machines must continuously search for canonical sync words (e.g. `0xB5 0x62`, magic headers, or SOP markers).
  - Checksums (Fletcher-8, CRC-16/32) must be validated over complete payload boundaries.
  - On checksum failure or synchronization loss, the parser must cleanly reject the corrupted frame, back up to the next potential sync byte, and resume scanning without dropping stream continuity.

---

## 4. Non-Blocking Telemetry Handoff (Producer Protection)
- **Handoff from High-Rate Producers**: High-rate data producers (BLE notifications, DMA callbacks, UART ISRs) must NEVER be blocked by downstream consumers (CAN transmission, file/SD logging, slow serial output, or network sockets).
- **Zero-Wait Queue Dispatch**:
  - Enforce bounded FreeRTOS queues with zero-wait timeouts (`xQueueSend(queue, &item, 0)`).
  - If a downstream queue is saturated (e.g. CAN bus congestion or bus-off recovery), drop the newest or oldest frame immediately and increment a monotonic frame-drop counter.
  - Stalling a producer thread causes transport timeouts (e.g., BLE connection supervision timeout / HCI Reason 520) or hardware FIFO overflows.

---

## 5. Zero-Overhead Compile-Time Diagnostic Toggles
- **Elimination of Hot-Path Overhead**: Diagnostic metrics (e.g., frame rate estimators, bus utilization %, queue high-water marks, drop rates) must be conditionally compiled via Kconfig options (`CONFIG_*_STATS_ENABLE`).
- **Preprocessor Elimination**: Use `#if CONFIG_*_ENABLE` guards so that in release/production builds, zero CPU cycles and zero RAM overhead are expended on statistical accounting in hot paths.
- **Safe Fallback**: Any public diagnostic query functions must return `ESP_ERR_NOT_SUPPORTED` when statistics compilation is disabled.

---

## 6. Disconnected Hardware & Bus-Off Recovery Protocol
- **Fault-Tolerant Transceivers**: Transceiver drivers (CAN/TWAI, I2C, SPI) must handle unplugged harnesses, floating buses, and un-terminated test benches without entering infinite retry loops, watchdog resets, or task deadlocks.
- **State Monitoring & Recovery**:
  - Monitor bus-off states (e.g. `TWAI_STATE_BUS_OFF`) and transceiver error counters.
  - Implement non-blocking back-off recovery procedures (e.g. initiating auto-recovery with exponential back-off).
# Documentation & Presentation Standards

## 1. Agent Scope, Constraints & Traceability Tracking (Markdown)
- **Markdown Requirement & Constraint Tracking**: Document and track requirements, scope boundaries, and operational constraints used by the agent in explicit Markdown files (e.g. `REQUIREMENTS.md`, `CONSTRAINTS.md`, or inside `docs/`). Focus primarily on agent scope, design rules, platform/tooling constraints, and operational boundaries rather than exhaustive end-user feature manuals.
- **Repo-Level Agent & Scope Summaries**: Maintain a top-level Markdown summary (`README.md` or `PROJECT_SUMMARY.md`) at the repository root detailing the project purpose, agent scope boundaries, technical constraints, and repo structure.
- **Implementation Traceability**: Maintain clear traceability between agent constraints/requirements and their corresponding code implementations (e.g. in a Traceability Matrix or doc references). Keep documentation updated whenever agent scope or project constraints evolve.

## 2. Formatted Markdown Presentation
- **Presentation Preference**: Whenever creating or updating a Markdown (`.md`) file in the workspace, always generate/update a corresponding **Artifact** (`user_facing: true`).
- **Formatted Preview**: Present the output to the user as a rendered Artifact rather than relying only on the raw file diff view, so the user can immediately view formatted headings, tables, alerts, and rendered Markdown directly in the UI pane. Render the Markdown content directly as native Markdown elements (do NOT wrap the entire preview inside markdown code blocks).
- **Workspace Sync**: Continue writing/updating the actual `.md` file in the workspace as requested, while maintaining the rendered Artifact for visual review.

## 3. Portable Relative Markdown Links
- **Relative Path Invariant**: All file references inside repository Markdown (`.md`) files MUST use relative file paths (e.g., `[TOO.MD](TOO.MD)` or `[main/main.cpp](main/main.cpp)`).
- **No Absolute Filesystem URLs**: NEVER commit absolute local filesystem URLs (e.g. `file:///home/user/...`) inside repository documentation to preserve author privacy and ensure links render correctly on GitHub.

## 4. Sub-Project & Module Documentation (`README.md` & `TOO.MD`)
- **Sub-Project `README.md` Content**: `README.md` files located at the root of individual sub-projects or modules MUST remain lightweight, technical, and human-focused. They should describe subproject purpose, target architecture, hardware/network configuration, and key capabilities.
- **Exclusion of Agent Instructions**: Sub-project `README.md` files MUST NOT contain agentic prompt instructions, internal rule citations (e.g., "Rule 6"), or AI operational constraint references. Agent-specific guidelines belong in repo-level files (`REQUIREMENTS.md`, top-level `README.md`, or `.geminirules`).
- **Theory of Operation (`TOO.MD`) Requirement**: Each active sub-project and major shared component MUST maintain a `TOO.MD` (or `OTA_TOO.MD`) detailing system architecture, hardware subsystems, signal processing, data/bus ingestion and dispatch loops, API endpoints, and sequence diagrams (including protocol handshakes and timeout/error escape points).

## 5. Doxygen & API Code Documentation
- **Explicit Default Value Explanations**: When writing Doxygen docstrings for functions with default parameter values, explicitly document the default value inside the `@param` tag (e.g., `@param[in] target_id Target ECU address byte (Default: 0x12)`).
- **Public Header Coverage**: All public headers and exported component interfaces must include Doxygen comments describing parameters, return values, thread-safety, and side effects.

## 6. State Machine & Protocol Sequence Diagrams (`SCENARIOS.md`)
- **Complex Flow Coverage**: Modules or components implementing non-trivial state machines, diagnostic daemons, or multi-step protocols MUST maintain sequence diagrams (e.g., inside `docs/SCENARIOS.md` or `TOO.MD`).
- **Mermaid Sequence Diagrams**: Include Mermaid time sequence diagrams detailing normal initialization/handshakes, stream loss/broadcast timeouts, active read timeouts, error response handling (`0x7F`), payload validation failures, and pending/busy state transitions (`0x78`).

## 7. Directory Structure & Root Folder Cleanliness
- **Subfolder Placement**: Project documentation MUST be organized within a `/docs/` subfolder. Likewise, any created ESP components (or custom project components) MUST reside in their respective subfolders (e.g. `/components/` or `/main/`).
- **Root Folder Restrictions**: In general, ONLY `README.md` and/or standard licensing files (e.g., `LICENSE`, `LICENSE.md`) are allowed at the root level of the project folder. All other Markdown documents, specifications, architecture docs, or sub-component documentation must be placed in `/docs/` or their respective component directory.

## 8. Post-Build & Pre-Commit Documentation Sync
- **Architectural Sync Verification**: When large architectural changes are made that might affect components or the main program structure, a documentation verification pass MUST be performed so that `.md` documents stay in sync with the codebase changes.
- **Verification Timing**: This documentation verification pass MUST be completed:
  1. **AFTER a successful build** (when applicable/adequate for the project).
  2. **ALWAYS before any git commit or git push** (when relevant).

## 9. Component Reusability Standards (`components/<name>/HOWTO.md`)
- **Standalone Reusability Guides**: Every reusable modular component (under `/components/`) must maintain a dedicated `HOWTO.md` guide enabling turnkey reuse in other firmware projects without reading the internal C/C++ source code.
- **Required Sections in `HOWTO.md`**:
  - **Capabilities & Scope**: Clear summary of what the component does and standalone operational guarantees.
  - **Dependencies & CMake `REQUIRES`**: Explicit list of required ESP-IDF components and external packages.
  - **Copy-Paste Integration Snippets**: Ready-to-use C/C++ initialization, dispatch, and callback wire-up code.
  - **Kconfig Configuration Matrix**: Complete table of configuration options, default values, and operational effects.

## 10. Markdown Math & KaTeX Hygiene
- **Avoid Raw Math Delimiters for Plain Text**: Do not use raw LaTeX math delimiters (`$...$`, `$$...$$`) for inequality signs, units, or simple formulas in chat responses and markdown documentation (e.g., use `< 250 RPM`, `!= 0`, `degC`, `1/30` instead of math blocks).
- **Prevent KaTeX Rendering Glitches**: Two unescaped `$` signs in the same paragraph inadvertently trigger math rendering mode in markdown engines, corrupting plain text, prices, and shell variable names. Always escape literal dollar signs as `\$` or wrap shell variables in inline code backticks (`$VAR`).


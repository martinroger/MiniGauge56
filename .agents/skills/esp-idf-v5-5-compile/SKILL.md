---
name: esp-idf-v5-5-compile
description: Skill to configure, build, and qualitatively analyze ESP-IDF projects using framework versions between v5.5.x (included) and v6.x (excluded). Includes support for export.sh, eim tool manager, MCP servers, and standardized build diagnostic reporting.
---

# ESP-IDF v5.5.x Compilation & Qualitative Analysis Skill

This skill provides step-by-step guidance for configuring, compiling, and qualitatively analyzing ESP-IDF firmware projects targeting **ESP-IDF v5.5.x up to v6.0 (excluded)**.

---

## 1. Environment Discovery & Setup

Before running compilation, determine the active environment mode in order of preference:

### Mode A: ESP-IDF Build MCP Server (Preferred if present)
If an ESP-IDF Build MCP server is active in the environment, use its native build tools instead of direct shell commands.

### Mode B: Espressif Installation Manager (`eim`)
If `eim` is installed and managing ESP-IDF toolchains:
1. Execute commands prefixed with `eim` from the project root directory:
   ```bash
   # Single-step clean & build execution from project root:
   eim run "idf.py fullclean build"
   ```
2. **Sandbox Requirement**: Because `eim` accesses toolchain binaries and configurations stored in `~/.espressif` (outside the standard workspace sandbox), invoking `eim` commands requires running in **sandbox bypass mode** (`BypassSandbox: true`).

---

## 2. Compilation Workflow

Execute the build sequence using the appropriate environment wrapper (`eim run "..."` or direct `idf.py`):

1. **Set Target MCU Architecture** (if changing or initializing target):
   ```bash
   idf.py set-target <target_mcu>
   # Supported targets: esp32, esp32s2, esp32s3, esp32c2, esp32c3, esp32c6, esp32h2, esp32p4
   ```

2. **Clean Build Execution**:
   > [!IMPORTANT]
   > **Kconfig & `sdkconfig` Mandatory Rule**: If any `Kconfig`, `Kconfig.projbuild`, `sdkconfig`, or `sdkconfig.*` defaults/override file is added, modified, or deleted, a `fullclean` build (`idf.py fullclean build` or `eim run "idf.py fullclean build"`) is **strictly mandatory** before building to ensure CMake cache re-evaluation.

   ```bash
   # Using direct idf.py (when IDF environment is exported):
   idf.py fullclean build

   # Or using eim wrapper from project root (requires BypassSandbox: true):
   eim run "idf.py fullclean build"
   ```

3. **Extract Binary Footprint & Component Sizes**:
   ```bash
   idf.py size
   idf.py size-components
   ```

---

## 3. Qualitative Compilation Analysis Protocol

After compilation, perform a systematic qualitative assessment across four key categories:

### Category 1: Binary Memory & Storage Analysis
- **DRAM (Data RAM)**: Monitor static memory usage. High DRAM usage (>80%) risks runtime stack/heap exhaustion.
- **IRAM (Instruction RAM)**: Check code placed in IRAM (interrupt service routines, fast-path code).
- **Flash (Code & Read-Only Data)**: Evaluate app binary partition occupation against partition table limits.
- **Top Memory Consumers**: Review `idf.py size-components` output to identify top 3 memory-heavy components.

### Category 2: Compiler Diagnostics & Warning Classification
Classify log warnings into actionable categories:
- **Deprecation Warnings**: Usage of legacy v4.x/v5.x driver APIs marked `IDF_DEPRECATED`.
- **C/C++ Type & Boundary Warnings**: Implicit conversions, signed/unsigned comparisons, uninitialized variables.
- **Header & Include Path Warnings**: Missing include guards, ambiguous header resolutions.

### Category 3: Target Architecture & Hardware Checks
- **Task Stack Allocation**: Ensure FreeRTOS task stacks performing string formatting or networking are allocated at least **2048 to 4096 bytes**.
- **Strapping GPIO Safety**: Verify pin assignments do not use target-specific strapping pins for critical signals:
  - *ESP32*: GPIO 0, 2, 5, 12, 15
  - *ESP32-S2*: GPIO 0, 26, 45, 46
  - *ESP32-S3*: GPIO 0, 3, 45, 46
  - *ESP32-C3*: GPIO 2, 8, 9
  - *ESP32-C6*: GPIO 8, 9, 15
  - *ESP32-H2*: GPIO 8, 9, 25

### Category 4: Dependency & Component Audit
- Check `main/idf_component.yml` and `dependencies.lock`.
- Ensure version constraints are strictly satisfied without unexpected transient dependency updates.

---

## 4. Standard Qualitative Build Report Format

Format compilation results using the following markdown structure:

```markdown
# ESP-IDF v5.5.x Qualitative Build Report

## Executive Summary
- **Target MCU**: `<target_mcu>`
- **ESP-IDF Version**: `v5.5.x`
- **Build Status**: `SUCCESS` / `FAILED`
- **Environment**: `eim` / `export.sh` / `MCP`

## Memory Footprint Analysis
| Memory Region | Used (Bytes) | Total (Bytes) | Usage (%) | Status |
|---------------|--------------|---------------|-----------|--------|
| DRAM          | X            | Y             | Z%        | OK / WARN |
| IRAM          | X            | Y             | Z%        | OK / WARN |
| Flash Code    | X            | Y             | Z%        | OK / WARN |

### Top Component Memory Consumers
1. `<component_1>`: X KB
2. `<component_2>`: Y KB
3. `<component_3>`: Z KB

## Compiler Diagnostics & Warnings Summary
- **Total Warnings**: N
- **Deprecation Warnings**: N
- **Type/Logic Warnings**: N

## Architectural & Safety Verification
- **FreeRTOS Stack Allocation**: Compliant / Needs Review
- **Strapping GPIO Check**: Clear / Conflict Detected
- **Component Dependency Status**: Locked & Clean
```

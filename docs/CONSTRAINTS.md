# MiniGauge56 — Platform & Architecture Constraints

## 1. Hardware & Target Constraints

| Parameter | Specification / Constraint | Rationale / Mitigation |
| :--- | :--- | :--- |
| **Target SoC** | ESP32-S3 (Xtensa Dual-Core, 240 MHz) | Required for Octal SPI PSRAM, DMA, and AMOLED driver. |
| **Framework Version** | ESP-IDF v5.5.5 & v6.1 | Compatible with both v5.5.5 and v6.1 toolchains via `eim`. |
| **CAN Transceiver TX** | GPIO 43 | Hardwired on board transceiver path. |
| **CAN Transceiver RX** | GPIO 44 | Hardwired on board transceiver path. |
| **Display Controller** | RM69090 / AMOLED 1.75" (466x466) | Managed via `waveshare/esp32_s3_touch_amoled_1_75`. |
| **SD Storage** | MicroSD via 4-wire SDMMC / SPI | Mounted to `/sdcard` via BSP FATFS driver. |

---

## 2. Software & Architectural Constraints

### 2.1 Unmodified Component Boundary
- The `twai_daemon` and `binocan` components are maintained as external Git repositories (`https://github.com/martinroger/twai_daemon` and `https://github.com/martinroger/binocan`) and consumed via the ESP-IDF Component Manager into `managed_components/` (strictly read-only).
- The remaining in-tree shared components (`components/racebox_ble/` and `components/racebox_twai/`) were developed and tested across other projects. They must remain **strictly unmodified**.
- Application code in `main/` adapts to the existing component APIs without altering component source files.
- Compiler warnings in external components (e.g. GCC 14 `-Wstringop-truncation`) are suppressed at the root project CMake level (`-Wno-stringop-truncation`) rather than modifying component code.

### 2.2 Real-Time Processing & Zero Dynamic Allocation in Hot Path
- In the CAN frame reception and routing callback (`log_can_frame_handler`), no dynamic memory allocations (`malloc`, `calloc`, `new`) are permitted.
- Records are copied by value into statically allocated stack structs and queued non-blocking into PSRAM `can_rb` with zero timeout (`0`).
- If the ringbuffer is saturated, newest frames are dropped immediately rather than stalling the `CAN_RX_Task` thread.

### 2.3 RaceBox BLE & GPS Time Synchronization Constraints
- **BLE Stack**: Apache NimBLE is configured in Central mode with GAP Service enabled (`CONFIG_BT_NIMBLE_GAP_SERVICE=y`) to support device name configuration.
- **RTC Clock Sync**: Time synchronization via `settimeofday()` is strictly restricted to valid 3D GPS fixes (`fix_status >= 3`, `valid_date`, `valid_time`, `valid_fix`, `num_sv >= 4`) to prevent syncing against unstable or drifting 2D/no-fix data.
- **Clock Drift & Monotonicity**: The RTC is synchronized only on the first valid 3D fix; subsequent time progression relies on the internal ESP32 RTC to avoid backward time jumps during active SD logging.
- **CAN Broadcast Throughput**: RaceBox 25 Hz telemetry translates to 6 CAN frames (`0x600`-`0x605`) every 40 ms (150 frames/sec). Frames are dispatched via `twai_daemon`'s zero-copy TX descriptor pool.

### 2.4 Hardware Loopback & Self-Reception Constraints
- **Loopback Mode**: Enabled via `CONFIG_CAN_ENABLE_LOOPBACK=y` in `twai_daemon`. Transmitted frames are driven onto the physical CAN bus with standard ACK/arbitration rules, while simultaneously entering the local RX FIFO to ensure unified, timestamped logging of self-generated traffic.
- **RX Queue Sizing**: The hardware loopback doubles peak reception load when actively broadcasting (150 frames/s from RaceBox plus incoming bus traffic). The static RX queue and PSRAM ringbuffer must sustain these burst rates without buffer exhaustion.

### 2.5 FreeRTOS Core Pinning & UI Thread-Safety
- `CAN_RX_Task` is pinned to Core 1 via `CONFIG_CAN_CORE_AFFINITY` to prevent contention with display rendering on Core 0.
- LVGL UI operations (including periodic telemetry and `objects.rbx_status` label updates) are synchronized using `bsp_display_lock()` mutex with bounded timeouts (100 ms).

### 2.6 Real-Time Bayesian Gear Estimation Constraints
- **Zero Dynamic Allocation**: `gear_bayesian_update()` operates exclusively on static `gear_bayesian_state_t` structures and stack memory; no heap operations (`malloc`, `free`, `new`, `delete`) are executed in the 40 Hz loop.
- **Microsecond Timestamp Precision**: Elapsed time (`dt_s`) must be computed by calculating the 64-bit microsecond integer difference (`now_us - prev_us`) before converting to floating-point seconds, avoiding integer division truncation and preserving 32-bit single-precision float mantissa resolution.
- **Task Scheduling**: The `upd_gear` task runs at FreeRTOS priority 5 with a 4096-byte stack depth, preventing starvation from lower-priority UI rendering tasks (priority 3).

### 2.7 AMOLED Display Power Management & Burn-In Mitigation
- **Inactivity Sleep Timeout**: The AMOLED display backlight powers off completely after 10 seconds of touch inactivity to minimize power consumption and protect the OLED panel.
- **Always-On Brightness Clamping**: When the "Always on" override mode is engaged via `objects.backlight_switch`, display brightness is clamped to 50% (`bsp_display_brightness_set(50)`) rather than full 100% brightness to mitigate permanent OLED burn-in during prolonged static telemetry display.

### 2.8 BMWP2000 Protocol Engine & Fast Ingestion Constraints
- **Zero Dynamic Allocation in Hot Path**: Incoming CAN frames are pre-filtered using a 4-tier fast rejection filter (`0x600 + target_ecu_id`, length >= 2, target address matching tester ID, valid ISO-TP PCI) and pushed into the FreeRTOS `rx_queue` by value without dynamic memory allocations (`malloc`/`new`).
- **Producer Non-Blocking Protection**: `bmwp2000_feed_can_frame()` performs zero-wait enqueueing (`xQueueSend(rx_queue, frame, 0)`). If the daemon queue is full, frames are dropped immediately to ensure `app_can_frame_router` and `twai_daemon`'s `CAN_RX_Task` are never blocked.
- **Anti-Hyper-Polling Backoff**: On un-terminated bench testbeds or when the engine ignition is switched OFF, the protocol engine backs off for 3 seconds (`CONFIG_BMWP2000_BACKOFF_DELAY_MS`) after 3 consecutive request timeouts (`CONFIG_BMWP2000_MAX_RETRY_COUNT`), avoiding bus flooding and CPU starvation.
- **Thread-Safe Snapshot Access**: Telemetry metrics are decoded within the isolated `bmwp_daemon_task` (Core 1, priority 5) and cached silently, making them safely accessible for future LVGL UI bindings via thread-safe getters (`bmwp2000_get_did_value()`).


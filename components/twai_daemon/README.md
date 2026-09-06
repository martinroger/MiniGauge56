# TWAI Daemon Component (`common/twai_daemon`)

## Overview

The `twai_daemon` component provides a unified, modernized ESP-IDF v5.5.x Two-Wire Automotive Interface (TWAI / CAN) driver daemon for the VX Binocle dual-display cluster ecosystem.

Migrated from the legacy `driver/twai.h` driver, this component leverages the new `esp_driver_twai` object-oriented architecture (`esp_twai.h`, `esp_twai_onchip.h`) with zero-copy transmission, event-driven ISR reception callbacks, and automated bus-off recovery.

---

## Key Capabilities

- **Zero-Copy Direct Transmission**: Telemetry packaging tasks directly transmit frames via `twai_transmit_msg()` or `twai_transmit_frame()`, completely eliminating intermediate TX FreeRTOS queues and tasks.
- **Event-Driven RX Dispatch**: Modern `on_rx_done` hardware ISR callbacks capture incoming frames into a FreeRTOS worker queue (`g_twai_rx_queue`) without task polling.
- **Automated Bus-Off Recovery**: The `on_state_change` event callback automatically detects `TWAI_ERROR_BUS_OFF` and initiates recovery via `twai_node_recover()`, restoring normal operation when the bus stabilizes.
- **Declarative Route Table Architecture**: Display nodes utilize an array of `twai_route_entry_t` structs mapping Frame IDs to handlers, timeout durations, callbacks, and automated watchdog timer resets.
- **Direct Queue Extraction**: Factory and diagnostic handlers can directly access or drain the RX queue via `twai_receive_queued_frame()` and `twai_clear_rx_queue()`.

---

## Hardware & Network Configuration

- **Bus Bitrate**: 500 kbps (Classic CAN 2.0B standard).
- **Default Pinout**:
  - CAN TX: GPIO 2 (configurable via `Kconfig`)
  - CAN RX: GPIO 3 (configurable via `Kconfig`)
- **Core Affinity**: Configurable FreeRTOS core affinity (Core 0 / Core 1) via `CONFIG_CAN_CORE_AFFINITY`.
- **Target Architecture**: ESP32-S3 (On-chip TWAI peripheral).

---

## Integration

Include `twai_daemon.h` in firmware components and register component dependencies:

```cpp
#include "twai_daemon.h"

// Initialize with optional frame dispatcher
initCAN(&dispatchFrame);

// Transmit telemetry payload
uint8_t payload[8] = {0x01, 0x02};
twai_transmit_msg(0x100, payload, 2, false, 10);
```

For in-depth architectural details and sequence diagrams, refer to [TOO.MD](TOO.MD).

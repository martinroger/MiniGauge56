# TWAI Daemon Component Integration Guide

## 1. Capabilities & Scope

`twai_daemon` is a modular, high-performance CAN 2.0B driver component built on the modern ESP-IDF `esp_driver_twai` architecture for ESP32 and ESP32-S3 targets.

### Key Capabilities
- **Zero-Copy Asynchronous TX Pool**: Manages a 32-slot static descriptor pool eliminating heap allocations and preventing dangling stack pointers during asynchronous transmission.
- **Event-Driven Interrupt RX Pipeline**: Ingests frames via `on_rx_done` ISR callback into a FreeRTOS handoff queue without polling.
- **Configurable Core Affinity**: Pins the frame ingestion worker task (`CAN_RX_Task`) to a specified CPU core (Core 0 or Core 1).
- **Automated Bus-Off Recovery**: Listens to state change events (`TWAI_ERROR_BUS_OFF`) and initiates non-blocking recovery via `twai_node_recover()`.
- **Hardware Loopback Logging**: Optionally receives transmitted frames back into the local RX queue with hardware timestamps for local telemetry logging.

---

## 2. Dependencies & CMake REQUIRES

### ESP-IDF Component Requirements
Declared in `components/twai_daemon/CMakeLists.txt`:
```cmake
REQUIRES esp_driver_twai esp_driver_gpio driver esp_timer
```

### Supported ESP-IDF Versions
- ESP-IDF v5.2 or newer (uses `esp_driver_twai/esp_twai_onchip.h`).

---

## 3. Copy-Paste Integration Snippets

### 3.1 Initializing the Driver with a Dispatcher Callback
```cpp
#include "twai_daemon.h"
#include "esp_log.h"

static esp_err_t on_frame_received(const twai_frame_t *rx_frame)
{
    ESP_LOGI("CAN", "Received ID 0x%03lX, DLC %d", rx_frame->header.id, rx_frame->header.dlc);
    return ESP_OK;
}

void app_main(void)
{
    esp_err_t ret = initCAN(on_frame_received);
    if (ret != ESP_OK) {
        ESP_LOGE("CAN", "Failed to start TWAI daemon: %s", esp_err_to_name(ret));
        return;
    }
    ESP_LOGI("CAN", "TWAI daemon initialized successfully");
}
```

### 3.2 Transmitting a CAN Message (Zero-Copy)
```cpp
#include "twai_daemon.h"

void send_sample_frame(void)
{
    uint8_t payload[8] = { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08 };
    
    // Transmit standard 11-bit ID with non-blocking 10 ms wait for TX pool slot
    esp_err_t ret = twai_transmit_msg(0x123, payload, sizeof(payload), false, 10);
    if (ret != ESP_OK) {
        // Handle timeout or bus-off state
    }
}
```

---

## 4. Kconfig Configuration Matrix

| Kconfig Symbol | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `CONFIG_CAN_TX` | int | `39` | GPIO pin assignment for CAN transceiver TX line (e.g., `43` on MiniGauge56). |
| `CONFIG_CAN_RX` | int | `38` | GPIO pin assignment for CAN transceiver RX line (e.g., `44` on MiniGauge56). |
| `CONFIG_CAN_TX_POLLING_RATE_MS` | int | `5` | Polling rate interval (ms) for transmit queues. |
| `CONFIG_CAN_RX_TIMEOUT_MS` | int | `3000` | Inactivity timeout (ms) before setting `CAN_RX_TimedOut = true`. |
| `CONFIG_CAN_CORE_AFFINITY` | int | `1` | CPU core affinity for `CAN_RX_Task` (`0` or `1`). |
| `CONFIG_CAN_ENABLE_LOOPBACK` | bool | `n` | Enables hardware loopback on the transceiver node to receive self-transmitted frames. |


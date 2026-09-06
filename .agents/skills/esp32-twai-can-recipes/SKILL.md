---
name: esp32-twai-can-recipes
description: Turnkey recipe for building high-performance, fault-tolerant CAN 2.0B / TWAI drivers on ESP32/ESP32-S3 using ESP-IDF. Covers zero-copy static TX descriptor pools, core-pinned RX worker tasks, thread-safe asynchronous transmission, and automated bus-off recovery.
---

# ESP32 TWAI / CAN 2.0B Driver & Daemon Recipe

This technical recipe provides an architectural blueprint and reference implementation for configuring the ESP32 / ESP32-S3 on-chip Two-Wire Automotive Interface (TWAI / CAN 2.0B) controller with zero-copy transmission, core-pinned interrupt-to-task queues, and fault-tolerant bus-off recovery.

---

## 1. Problem Statement & Architecture Rationale

Standard ESP-IDF CAN driver examples frequently run into critical issues in production:
* **Memory Fragmentation & Allocation Latency**: Allocating frame buffers dynamically per packet causes severe latency spikes and heap exhaustion in high-throughput automotive buses (up to 100 Hz).
* **Bus-Off Locking & Watchdog Resets**: When bench testing without a terminated harness or when an ECU disconnects, transmitting into an un-acknowledged bus triggers `TWAI_STATE_BUS_OFF`. Unhandled, this leads to infinite task retries and FreeRTOS task watchdog resets.
* **Thread Contention**: Mixed TX and RX operations on a single task lead to buffer overflows and missed messages.

### Solution Architecture
```
[TWAI Controller Hardware] 
        ▲                           │
        │ Transmit                  │ Hardware Interrupt (ISR)
        │                           ▼
[Static TX Pool]             [Buffered FreeRTOS RX Queue]
(Zero-copy pre-allocated)           │
                                    ▼
                             [Core-Pinned RX Task] ──► [Registered Callback Dispatcher]
```

---

## 2. Decision Matrix: TWAI Controller Configurations

| Characteristic | Modern On-Chip TWAI (`esp_twai_*.h` / `driver/twai.h`) | Legacy CAN Driver (`driver/can.h`) | External MCP2515 via SPI |
| :--- | :--- | :--- | :--- |
| **Throughput Capacity** | Up to 1 Mbps (Full hardware speed). | Up to 1 Mbps. | Limited by SPI bus clock & interrupt latency (~500 kbps max reliable). |
| **CPU Utilization** | Extremely low (Hardware filter & FIFO). | Low. | High (SPI transactions per frame). |
| **Bus-Off Handling** | Automated hardware alert hooks. | Manual polling required. | Manual SPI register reset required. |
| **Target Support** | ESP32, ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6. | ESP32 only. | Any MCU with SPI. |

---

## 3. Step-by-Step Implementation Sequence

### Stage 1: Hardware Timing & Filter Configuration
Configure timing for desired baud rate (typically 500 kbps or 250 kbps for automotive systems) and set acceptance filters (pass all frames or mask specific CAN IDs):
```c
twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(
    (gpio_num_t)CONFIG_CAN_TX,
    (gpio_num_t)CONFIG_CAN_RX,
    TWAI_MODE_NORMAL
);
g_config.rx_queue_len = 32;
g_config.tx_queue_len = 32;
g_config.alerts_mask = TWAI_ALERT_BUS_OFF | TWAI_ALERT_BUS_RECOVERED | TWAI_ALERT_ERR_PASS | TWAI_ALERT_AND_LOG;

twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();
```

### Stage 2: Driver Installation & Start
```c
ESP_ERROR_CHECK(twai_driver_install(&g_config, &t_config, &f_config));
ESP_ERROR_CHECK(twai_start());
```

### Stage 3: Core-Pinned RX Dispatch Task
Spawn a dedicated FreeRTOS worker task pinned to Core 1 (or Core 0 depending on CPU allocation architecture) to ingest frames from the hardware FIFO:
```c
xTaskCreatePinnedToCore(
    can_rx_worker_task,
    "CAN_RX_Task",
    4096,
    user_callback,
    configMAX_PRIORITIES - 3,
    &s_rx_task_handle,
    CONFIG_CAN_CORE_AFFINITY
);
```

### Stage 4: Non-Blocking Bus-Off Recovery Daemon
In the background or RX task, monitor TWAI alerts. When `TWAI_ALERT_BUS_OFF` fires, initiate automatic recovery without blocking the system:
```c
uint32_t alerts = 0;
twai_read_alerts(&alerts, pdMS_TO_TICKS(10));
if (alerts & TWAI_ALERT_BUS_OFF) {
    ESP_LOGW("TWAI", "Bus-Off detected! Initiating recovery...");
    twai_initiate_recovery();
}
if (alerts & TWAI_ALERT_BUS_RECOVERED) {
    ESP_LOGI("TWAI", "Bus recovered! Restarting controller...");
    twai_start();
}
```

---

## 4. Reference Implementation Files

Turnkey reference files are located in [`references/`](references/):
* **Header**: [`references/twai_can_daemon.h`](references/twai_can_daemon.h)
* **C Implementation**: [`references/twai_can_daemon.c`](references/twai_can_daemon.c)
* **CMake Snippet**: [`references/CMakeLists.txt.snippet`](references/CMakeLists.txt.snippet)
* **Kconfig Snippet**: [`references/Kconfig.snippet`](references/Kconfig.snippet)

---

## 5. Verification Checklist

- [ ] **Strapping Pin Verification**: Confirm CAN TX/RX GPIOs do not overlap with strapping pins (avoid GPIO 0, 3, 45, 46 on ESP32-S3).
- [ ] **Transceiver Termination**: Ensure physical bus has 120 $\Omega$ split termination across CANH and CANL.
- [ ] **Task Stack Allocation**: Minimum 4096 bytes for `CAN_RX_Task` when calling `ESP_LOG` or callback logic.
- [ ] **Zero Dynamic Allocation**: Verify that transmitting messages uses pre-allocated stack/ring buffers without calling `malloc`.

# MiniGauge56

MiniGauge56 is an ESP32-S3 embedded digital gauge, high-throughput CAN telemetry logger, and RaceBox companion with an integrated 1.75" AMOLED capacitive touch display.

## Architecture Overview
- **MCU**: ESP32-S3 (Xtensa Dual-Core 240 MHz, Octal PSRAM)
- **Framework**: ESP-IDF v5.5.5
- **CAN Subsystem**: High-performance `twai_daemon` component utilizing modern `esp_driver_twai` with zero-copy asynchronous TX pool and core-pinned RX worker task (Core 1).
- **CAN Pinout**: Transceiver TX on GPIO 43, RX on GPIO 44 (500 kbps).
- **RaceBox BLE & TWAI Integration**: Ingests high-rate (25 Hz) GPS/IMU telemetry from any neighbouring RaceBox unit (Mini, Mini S, Micro) over Apache NimBLE Central (`racebox_ble`), updates internal RTC system time on valid 3D GPS fix, and broadcasts telemetry frames (`0x600`-`0x605`) onto CAN (`racebox_twai`).
- **Real-Time Gear Estimation**: Kinematic-conditioned Bayesian classifier predicting transmission state (Neutral, 1..5, Uncertain) at 40 Hz using dynamic transition matrices, Gaussian emission likelihoods, and clutch drop suppression.
- **Telemetry Logger**: Asynchronous 32 KB PSRAM ringbuffer streaming 8 KB DMA-aligned batch blocks to FATFS on MicroSD (`/sdcard/YYYYMMDD_log_HHMMSS.bin` when GPS synced, or `/sdcard/log_<esp_timer>.bin` fallback).
- **UI Subsystem**: LVGL 9 running on Waveshare 1.75" Touch AMOLED (`RM69090` + `CST9217`) featuring multi-tab views (logging controls and live gear/frequency telemetry readouts) and configurable Always-On backlight override.

## External Dependency Matrix

| Sub-Project | External Dependency | Locally Installed Version | Version Requirement |
| :--- | :--- | :--- | :--- |
| `main` | `waveshare/esp32_s3_touch_amoled_1_75` | `2.0.6` | `^2.0.0` |

## Documentation
- [System Requirements & Traceability Matrix](docs/REQUIREMENTS.md)
- [Platform & Architectural Constraints](docs/CONSTRAINTS.md)
- [Theory of Operation (TOO)](docs/TOO.MD)
- [TWAI Daemon Component Guide](components/twai_daemon/README.md)
- [TWAI Daemon Integration HOWTO](components/twai_daemon/HOWTO.md)
- [TWAI Daemon Theory of Operation](components/twai_daemon/TOO.MD)
- [RaceBox BLE Component Guide](components/racebox_ble/HOWTO.md)
- [RaceBox TWAI Component Guide](components/racebox_twai/HOWTO.md)
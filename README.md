# MiniGauge56

MiniGauge56 is an ESP32-S3 embedded digital gauge and high-throughput CAN telemetry logger with an integrated 1.75" AMOLED capacitive touch display.

## Architecture Overview
- **MCU**: ESP32-S3 (Xtensa Dual-Core 240 MHz, Octal PSRAM)
- **Framework**: ESP-IDF v5.5.5
- **CAN Subsystem**: High-performance `twai_daemon` component utilizing modern `esp_driver_twai` with zero-copy asynchronous TX pool and core-pinned RX worker task (Core 1).
- **CAN Pinout**: Transceiver TX on GPIO 43, RX on GPIO 44 (500 kbps).
- **Telemetry Logger**: Asynchronous 32 KB PSRAM ringbuffer streaming 8 KB DMA-aligned batch blocks to FATFS on MicroSD.
- **UI Subsystem**: LVGL 9 running on Waveshare 1.75" Touch AMOLED (`RM69090` + `CST9217`).

## External Dependency Matrix

| Sub-Project | External Dependency | Locally Installed Version | Version Requirement |
| :--- | :--- | :--- | :--- |
| `main` | `waveshare/esp32_s3_touch_amoled_1_75` | `2.0.6` | `^2.0.0` |

## Documentation
- [System Requirements & Traceability Matrix](docs/REQUIREMENTS.md)
- [Platform & Architectural Constraints](docs/CONSTRAINTS.md)
- [TWAI Daemon Component Guide](components/twai_daemon/README.md)
- [TWAI Daemon Theory of Operation](components/twai_daemon/TOO.MD)
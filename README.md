# MiniGauge56

MiniGauge56 is an ESP32-S3 embedded digital gauge and high-throughput CAN telemetry logger with an integrated 1.75" AMOLED capacitive touch display.

## Architecture Overview
- **MCU**: ESP32-S3 (Xtensa Dual-Core 240 MHz, Octal PSRAM)
- **Framework**: ESP-IDF v5.5.5 & v6.1
- **CAN Subsystem**: High-performance `twai_daemon` component utilizing modern `esp_driver_twai` with zero-copy asynchronous TX pool and core-pinned RX worker task (Core 1).
- **CAN Pinout**: Transceiver TX on GPIO 43, RX on GPIO 44 (500 kbps).
- **BMWP2000 Diagnostic Daemon**: Modular ISO 14230-3 / ISO 15765-2 KWP2000 diagnostic engine (`bmwp2000`) dynamically querying engine parameters (DME 0x12) via periodic fast LID streaming, running concurrently with CAN logging.
- **Telemetry Logger**: Asynchronous 32 KB PSRAM ringbuffer streaming 8 KB DMA-aligned batch blocks to FATFS on MicroSD (`/sdcard/log_<esp_timer>.bin`).
- **UI Subsystem**: LVGL 9 running on Waveshare 1.75" Touch AMOLED (`RM69090` + `CST9217`) featuring multi-tab views (logging controls and live telemetry readouts) and configurable Always-On backlight override.

## External Dependency Matrix

| Sub-Project | External Dependency | Locally Installed Version | Version Requirement |
| :--- | :--- | :--- | :--- |
| `main` | `waveshare/esp32_s3_touch_amoled_1_75` | `3.0.1` | `^3.0.0` |
| `main` | `twai_daemon` | `v0.1.0` (`588c470`) | `git: https://github.com/martinroger/twai_daemon.git` (tag `v0.1.0`) |
| `main` | `bmwp2000` | `2.0.1` (`a561ef4`) | `git: https://github.com/martinroger/BMWP2000.git` (tag `v2.0.1`) |

## Documentation
- [System Requirements & Traceability Matrix](docs/REQUIREMENTS.md)
- [Platform & Architectural Constraints](docs/CONSTRAINTS.md)
- [Theory of Operation (TOO)](docs/TOO.MD)
- [BMWP2000 Diagnostic Component Repository](https://github.com/martinroger/BMWP2000)
- [TWAI Daemon Component Repository](https://github.com/martinroger/twai_daemon)
- [Diagnostic Tools Suite (BMWP2000 Viewer, LID Composer)](tools/README.md)
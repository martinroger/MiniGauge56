# MiniGauge56

[![Build](https://github.com/martinroger/MiniGauge56/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/martinroger/MiniGauge56/actions/workflows/build.yml)

MiniGauge56 is a side gauge for the Mini R56. It runs on an ESP32-S3 with a 1.75" round AMOLED touch display, reads engine data from the DME over the diagnostic CAN link, shows it on a retro dot-matrix styled UI, and can record all CAN traffic to a MicroSD card.

## What it does today
- **CAN interface**: on-chip TWAI controller at 500 kbps through the external `twai_daemon` component (transceiver TX on GPIO 43, RX on GPIO 44, hardware loopback enabled so the gauge's own requests are logged too).
- **Engine telemetry (BMWP2000)**: the `bmwp2000` component (KWP2000 / ISO 14230-3 over ISO-TP, BMW FAST addressing) defines one dynamic local identifier (`0xF0`, "engineCore") on the DME and polls it. It carries 13 parameters, listed in [config/lids.json](config/lids.json) and scaled from [config/cids.json](config/cids.json): RPM, vehicle speed, MAF, intake air temperature, pre-throttle and manifold boost pressure, HPFP rail pressure, two oil temperatures, oil pressure, two coolant temperatures and actual gear.
- **CAN logger**: every received frame is packed into a 16-byte record, buffered in a 32 KB PSRAM ring buffer and written to `/sdcard/log_<uptime_us>.bin` in 8 KB blocks. Logging is started and stopped from the UI.
- **UI**: LVGL 9 tabview generated with EEZ Studio ([eezMG56.eez-project](eezMG56.eez-project)), five swipeable pages with a hidden tab bar:
  1. Coolant temperature (large readout)
  2. Oil temperature (large readout)
  3. BMWP2000 page: frame counter, RPM, oil and coolant temperature, HPFP and daemon state
  4. Logger page: file size, logging status, backlight (BKLT) and LOG switches
  5. Widget test page: switch to bypass the LCD emulation filter
- **Retro LCD emulator**: in-tree `lcd_emulator` flush decorator that renders the 8-bit LVGL frame as an amber dot-matrix LCD (cell 3 px, 8-bit grayscale, custom primary and alternate palettes). The alternate palette is shown while the BMWP2000 daemon is clearing its LID or uninitialised.
- **Display power**: always-on at 40 % brightness by default; with the BKLT switch off the panel sleeps after 10 s without touch and wakes on the next touch.
- **Host tools**: zero-dependency Python web tools to inspect logs, compose LID trains and plot signals ([tools/README.md](tools/README.md)).

## Hardware
- Waveshare ESP32-S3 Touch AMOLED 1.75" (ESP32-S3, 16 MB flash, octal PSRAM, 466x466 CO5300 AMOLED over QSPI, CST9217 touch, MicroSD slot)
- External CAN transceiver on GPIO 43 / 44

## Building
ESP-IDF v6.1, target `esp32s3`:

```
idf.py set-target esp32s3
idf.py build
```

`bmwp2000` is a private repository, so building needs read access to it. CI builds every pull request and every push to `main` in the `espressif/idf:v6.1` container ([.github/workflows/build.yml](.github/workflows/build.yml)); it reads `bmwp2000` with the `PRIVATE_REPOS_TOKEN` repository secret. A local build server setup through the ESP-IDF MCP server is described in [docs/TOO.MD](docs/TOO.MD#8-build-and-ci).

## Dependencies

Resolved versions come from [dependencies.lock](dependencies.lock).

| Dependency | Requested in `main/idf_component.yml` | Resolved |
| :--- | :--- | :--- |
| `waveshare/esp32_s3_touch_amoled_1_75` | `^3.0.0` | `3.0.1` |
| `bmwp2000` | git tag `v3.1.0` | `4845bf0` |
| `twai_daemon` | git tag `v0.1.0` | `da6507e` (`v0.1.0` + 1 commit; `bmwp2000` requests `twai_daemon` without a version, which resolves to the default branch) |
| `lvgl/lvgl` (via BSP) | | `9.5.0` |
| `espressif/esp_lvgl_adapter` (via BSP) | | `0.6.4` |

## Documentation
- [Requirements and traceability](docs/REQUIREMENTS.md)
- [Platform and architecture constraints](docs/CONSTRAINTS.md)
- [Theory of operation](docs/TOO.MD)
- [LCD emulator integration guide](components/lcd_emulator/HOWTO.md) and [LCD emulator theory of operation](components/lcd_emulator/TOO.MD)
- [BMWP2000 component](https://github.com/martinroger/BMWP2000) and [TWAI daemon component](https://github.com/martinroger/twai_daemon)
- [Host tools (log viewer, LID composer, signal plotter, LCD simulator)](tools/README.md)

# MiniGauge56 — System Requirements & Traceability Matrix

## 1. Summary
MiniGauge56 is an ESP32-S3 side gauge for the Mini R56. It reads engine parameters from the DME over the diagnostic CAN link with the `bmwp2000` KWP2000 engine, shows them on a 1.75" AMOLED touch display rendered as a retro dot-matrix LCD, and records all received CAN frames to a MicroSD card.

This document describes what the firmware in `main/` and `components/` does today. Requirements for the host tools live in [tools/REQUIREMENTS.md](../tools/REQUIREMENTS.md).

---

## 2. Scope

### In scope
- CAN access through the external `twai_daemon` component (500 kbps, GPIO 43 / 44, loopback on).
- One top-level CAN frame router feeding the SD logger and the `bmwp2000` engine.
- Engine telemetry through `bmwp2000`, configured by the project's `config/cids.json` and `config/lids.json`.
- Asynchronous CAN logging to SD card through a PSRAM ring buffer.
- An EEZ Studio generated LVGL UI (`components/ui/`) with five pages, refreshed per active page.
- The in-tree `lcd_emulator` flush decorator.
- Display power management with an always-on override.
- CI build on ESP-IDF v6.1.

### Out of scope
- Changes to external managed components (`managed_components/`, including `twai_daemon` and `bmwp2000`); they are changed in their own repositories.
- Hand edits to generated UI sources in `components/ui/`; the UI is edited in `eezMG56.eez-project` and regenerated.

### Removed features
These were described in earlier revisions of this document and no longer exist in the code: RaceBox BLE companion and GPS time sync, GPS-timestamped log filenames, RaceBox CAN broadcast (`0x600`-`0x605`), `binocan` speed/RPM frequency decoding (`0x300` / `0x301`), and the Bayesian gear estimator.

---

## 3. Requirements

| ID | Requirement | Success criteria |
| :--- | :--- | :--- |
| **REQ-CAN-01** | TWAI through `twai_daemon` | `initCAN(app_can_frame_router)` brings up the on-chip TWAI node; frames are transmitted with the `twai_daemon` TX API. |
| **REQ-CAN-02** | Transceiver pinout | `CONFIG_CAN_TX=43`, `CONFIG_CAN_RX=44` in `sdkconfig.defaults`. |
| **REQ-CAN-03** | Bus timing and mode | 500 kbps, normal (not listen-only) mode so diagnostic requests can be sent. |
| **REQ-CAN-04** | Frame routing | `app_can_frame_router()` passes every received frame to `log_can_frame_handler()` and `bmwp2000_feed_can_frame()`, in that order. |
| **REQ-CAN-05** | Self-reception | `CONFIG_CAN_ENABLE_LOOPBACK=y` so transmitted diagnostic requests are received and logged with the responses. |
| **REQ-LOG-01** | PSRAM ring buffer | `init_can_logging()` allocates a 32 KB no-split ring buffer in PSRAM once, after the SD card mounts. |
| **REQ-LOG-02** | Record format | Each frame becomes a packed 16-byte record: uptime ms (u32), CAN ID (u16), DLC (u8), 8 data bytes, 1 padding byte. |
| **REQ-LOG-03** | Non-blocking ingestion | The router-side handler copies the record by value and enqueues it with zero wait; frames are dropped when the buffer is full. Nothing is enqueued while logging is stopped. |
| **REQ-LOG-04** | Block writes | `sd_writer_task` writes 512-record (8 KB) blocks from a DMA-capable buffer, flushes a partial block after 5 s, and `fsync`s after every write. |
| **REQ-LOG-05** | Session lifecycle | `start_logging()` purges stale records and opens `/sdcard/log_<esp_timer_us>.bin`; `stop_logging()` lets the writer drain everything before closing. A new session is refused while the previous writer is still draining. |
| **REQ-LOG-06** | SD card mount | SD mount failure is logged and leaves logging unavailable without stopping the rest of the firmware. `CONFIG_BSP_SD_FORMAT_ON_MOUNT_FAIL=y` lets the BSP format a card it cannot mount. |
| **REQ-BMWP-01** | Component version | `bmwp2000` git tag `v3.3.0` in `main/idf_component.yml`, pinned in `dependencies.lock`. |
| **REQ-BMWP-02** | Project configuration | `CONFIG_BMWP2000_CUSTOM_CIDS_PATH="config/cids.json"` and `CONFIG_BMWP2000_CUSTOM_LIDS_PATH="config/lids.json"`. |
| **REQ-BMWP-03** | LID train | One LID `0xF0` ("engineCore") polled with `0x21 0xF0` at the poll rate (no `transmission_mode` key; the DME has no periodic transmission) carrying 10 CIDs, the maximum per LID: `rpm`, `vehicleSpeed`, `throttlePressure`, `manifoldPressureBoost1`, `hpfpPressure`, `oilTemp`, `engineOilTemp`, `oilPressureActual`, `engineTemp`, `coolantTemp`. |
| **REQ-BMWP-04** | Lifecycle | `bmwp2000_init()`, `bmwp2000_register_callback()` and `bmwp2000_start()` run at boot after CAN init; failures are logged and the rest of the firmware keeps running. |
| **REQ-BMWP-05** | Telemetry cache | `on_bmwp_telemetry_updated()` counts updates, timestamps the last one and reads 13 CIDs with `bmwp2000_get_cid_value()`: the 10 in the LID plus `maf`, `iat` and `gearActual`, which are no longer in the LID and stay at 0. |
| **REQ-UI-01** | Page layout | One tabview, tab bar hidden, horizontal swipe between five pages: coolant, oil, BMWP2000, logger, widget test. |
| **REQ-UI-02** | Per-page refresh | `update_display()` runs every 100 ms and only updates the active page's widgets under `bsp_display_lock(100)`; a lock timeout skips the cycle. |
| **REQ-UI-03** | Readouts | Coolant page shows `engineTemp`; oil page shows `oilTemp`; BMWP2000 page shows update count, RPM, `oilTemp`, `engineTemp`, `hpfpPressure` and the daemon state. |
| **REQ-UI-04** | Daemon state indication | The state label names the `bmwp2000_get_state()` state; the LCD emulator switches to the alternate palette in `CLEAR_LID` and `UNINIT`, and to the primary palette otherwise. |
| **REQ-UI-05** | Logging control | The LOG switch starts and stops logging; the switch is reverted if the start is refused or the writer aborts. The logger page shows written plus buffered size and LOGGING / PAUSED. |
| **REQ-UI-06** | Display power | Always-on is the boot default (BKLT switch checked) at 40 % brightness. With BKLT off, the backlight turns off after 10 s without touch; any touch wakes it. A LOG switch touch while asleep only wakes the display. |
| **REQ-UI-07** | Emulation bypass | The widget test page switch turns the LCD emulation off when checked and on when unchecked; its boot state mirrors `lcd_emulator_is_enabled()`. |
| **REQ-LCD-01** | LCD emulation | `lcd_emulator_init()` decorates the display flush at boot: 8-bit grayscale mode, 3 px cells, custom amber primary and red-amber alternate palettes, 8-bit LVGL frame expanded to RGB565 for the panel. |
| **REQ-BUILD-01** | CI build | GitHub Actions builds the firmware with ESP-IDF v6.1 on every pull request and push to `main`, and publishes the binaries and `dependencies.lock` as an artifact. |
| **REQ-BUILD-02** | Reproducible dependencies | `dependencies.lock` is tracked in git. |
| **REQ-DOC-01** | Doxygen | Exported functions and file headers in `main/` carry Doxygen comments. |

---

## 4. Traceability

| ID | Source | Key symbols | Verification |
| :--- | :--- | :--- | :--- |
| **REQ-CAN-01** | [`main/main.cpp`](../main/main.cpp) | `initCAN()` | Build, boot log |
| **REQ-CAN-02** | [`sdkconfig.defaults`](../sdkconfig.defaults) | `CONFIG_CAN_TX`, `CONFIG_CAN_RX` | Generated `sdkconfig` |
| **REQ-CAN-03** | `twai_daemon` (`src/twai_daemon.cpp`) | `bit_timing.bitrate = 500000` | Component review |
| **REQ-CAN-04** | [`main/main.cpp`](../main/main.cpp) | `app_can_frame_router()` | Code review |
| **REQ-CAN-05** | [`sdkconfig.defaults`](../sdkconfig.defaults) | `CONFIG_CAN_ENABLE_LOOPBACK` | Requests visible in SD logs |
| **REQ-LOG-01** | [`main/logging.cpp`](../main/logging.cpp) | `init_can_logging()`, `RB_SIZE` | Boot log |
| **REQ-LOG-02** | [`main/logging.cpp`](../main/logging.cpp) | `can_log_record_t` | Host tools parse `.bin` logs ([tools/common/can_core.py](../tools/common/can_core.py)) |
| **REQ-LOG-03** | [`main/logging.cpp`](../main/logging.cpp) | `log_can_frame_handler()` | Code review |
| **REQ-LOG-04** | [`main/logging.cpp`](../main/logging.cpp) | `sd_writer_task()`, `FRAMES_PER_BLOCK`, `LAZY_FLUSH_MS` | Code review, log file sizes |
| **REQ-LOG-05** | [`main/logging.cpp`](../main/logging.cpp) | `start_logging()`, `stop_logging()`, `sd_writer_running` | Start/stop on device |
| **REQ-LOG-06** | [`main/main.cpp`](../main/main.cpp), [`sdkconfig.defaults`](../sdkconfig.defaults) | `bsp_sdcard_mount()` | Boot without card |
| **REQ-BMWP-01** | [`main/idf_component.yml`](../main/idf_component.yml), [`dependencies.lock`](../dependencies.lock) | `bmwp2000` | CI build |
| **REQ-BMWP-02** | [`sdkconfig.defaults`](../sdkconfig.defaults) | `CONFIG_BMWP2000_CUSTOM_CIDS_PATH`, `CONFIG_BMWP2000_CUSTOM_LIDS_PATH` | Generated `sdkconfig` |
| **REQ-BMWP-03** | [`config/lids.json`](../config/lids.json), [`config/cids.json`](../config/cids.json) | `0xF0`, `engineCore` | LID composer, SD log in viewer |
| **REQ-BMWP-04** | [`main/main.cpp`](../main/main.cpp) | `bmwp2000_init()`, `bmwp2000_start()` | Boot log |
| **REQ-BMWP-05** | [`main/main.cpp`](../main/main.cpp) | `on_bmwp_telemetry_updated()` | `BMWP_STATUS` debug log |
| **REQ-UI-01** | [`components/ui/src/screens.c`](../components/ui/src/screens.c) | `objects.global_tabview` | On device |
| **REQ-UI-02** | [`main/main.cpp`](../main/main.cpp) | `update_display()` | Code review |
| **REQ-UI-03** | [`main/main.cpp`](../main/main.cpp) | `objects.engine_temp`, `objects.oil_temp`, `objects.bmw_*` | On device |
| **REQ-UI-04** | [`main/main.cpp`](../main/main.cpp) | `bmwp2000_get_state()`, `lcd_emulator_select_palette_slot()` | On device |
| **REQ-UI-05** | [`main/main.cpp`](../main/main.cpp) | `action_start_stop_clicked()`, `objects.log_sw` | On device |
| **REQ-UI-06** | [`main/main.cpp`](../main/main.cpp) | `wakeDisplay()`, `sleepDisplay()`, `backlight_override`, `sleepDisplayTimer` | On device |
| **REQ-UI-07** | [`main/main.cpp`](../main/main.cpp) | `action_filter_sw_actuated()`, `objects.filter_sw` | On device |
| **REQ-LCD-01** | [`components/lcd_emulator/`](../components/lcd_emulator/), [`sdkconfig.defaults`](../sdkconfig.defaults) | `lcd_emulator_init()`, `CONFIG_LCD_EMULATOR_*` | Host checks in `components/lcd_emulator/test/`, on device |
| **REQ-BUILD-01** | [`.github/workflows/build.yml`](../.github/workflows/build.yml) | `build` job | CI status |
| **REQ-BUILD-02** | [`dependencies.lock`](../dependencies.lock), [`.gitignore`](../.gitignore) | `!dependencies.lock` | `git ls-files` |
| **REQ-DOC-01** | [`main/`](../main/) | `@file`, `@brief` | Review |

---

## 5. Known gaps
Observed in the current code, not requirements:
- The coolant and oil page arcs (`engine_temp_arc`, `oil_temp_arc`) are never updated.
- Six of the 10 polled CIDs are cached but not displayed: `vehicleSpeed`, `throttlePressure`, `manifoldPressureBoost1`, `engineOilTemp`, `oilPressureActual`, `coolantTemp`.
- `on_bmwp_telemetry_updated()` still reads `maf`, `iat` and `gearActual`, which were removed from the LID to stay within 10 CIDs.
- `hpfpPressure` is scaled to MPa in `config/cids.json`, while the UI caption and code comments say bar.
- Log records keep 16 bits of the CAN ID, so 29-bit extended IDs are truncated.
- Log filenames use uptime, not wall-clock time.
- `start_logging_test()` (synthetic 500 Hz generator) is not reachable from the UI.

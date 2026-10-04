# LCD Emulator Component Integration Guide (`HOWTO.md`)

The `lcd_emulator` component provides turnkey, real-time retro dot-matrix monochrome LCD emulation for LVGL 9 displays on ESP32 / ESP32-S3 platforms. It enables authentic physical LCD rendering (reflective substrate, active dark ink, and physical inter-pixel inactive gaps) on high-density color panels (OLED / IPS / TFT) without requiring modifications to prebuilt vendor BSP drivers or changes to existing full-resolution vector UI layouts.

---

## 1. Capabilities & Standalone Guarantees

- **Decorator Pattern Architecture**: Intercepts the display flush pipeline via LVGL 9's `lv_display_set_flush_cb()`. Completely decouples from board support packages (`managed_components/`) and works cleanly alongside `esp_lv_adapter`.
- **Zero Dynamic Memory Allocation**: Performs all in-place screen-space transformations using fixed stack scratch space (< 300 bytes), strictly satisfying zero-heap-allocation invariants in high-rate rendering loops.
- **Dirty-Rectangle Screen-Space Modulo Continuity**: Perfectly preserves matrix grid alignment and dot pitch across arbitrary partial redraw buffer tiles (`area->x1`, `area->y1`), preventing visual phase drift or seam artifacts.
- **Dynamic Runtime Mode Switching**: Instant runtime switching between modern full-color AMOLED mode and classic retro monochrome LCD mode.
- **Built-in Palette Presets**:
  - `LCD_PRESET_OLIVE`: Classic Game Boy DMG / Nokia 5110 reflective olive-green STN.
  - `LCD_PRESET_CASIO_GREY`: Reflective silver/grey digital watch.
  - `LCD_PRESET_AMBER`: High-contrast industrial automotive amber backlight.
  - `LCD_PRESET_CYAN`: Electroluminescent cyan backlit panel.

---

## 2. Dependencies & CMake `REQUIRES`

### ESP-IDF Component Dependencies
Add `lcd_emulator` to your component or application's `CMakeLists.txt`:

```cmake
idf_component_register(
    ...
    REQUIRES lvgl esp_timer log
)
```

### Supported Environments
- **Framework**: ESP-IDF v5.x and v6.x
- **GUI Engine**: LVGL v9.x (RGB565 16-bit color depth)
- **Target SoCs**: ESP32, ESP32-S3, ESP32-C3, ESP32-C6 (Host unit-testable under macOS `clang++` / Linux `g++`).

---

## 3. Copy-Paste Integration Snippets

### Quick Initialization in `main.cpp`

```cpp
#include "esp32_s3_touch_amoled_1_75.h"
#include "lcd_emulator.h"

extern "C" void app_main(void)
{
    // 1. Initialize display hardware via BSP
    lv_display_t *disp = bsp_display_start();

    // 2. Attach the retro LCD flush decorator
    if (lcd_emulator_init(disp) == ESP_OK) {
        ESP_LOGI("APP", "Retro LCD decorator installed successfully");
    }

    // 3. Initialize UI scene graph (EEZ Studio or native LVGL)
    if (bsp_display_lock(-1) == ESP_OK) {
        ui_init();
        bsp_display_unlock();
    }
}
```

### Runtime Toggle & Palette Control

```cpp
// Toggle between full-color AMOLED and Retro LCD mode (e.g. on button click or touch)
lcd_emulator_toggle();

// Or explicitly enable / disable:
lcd_emulator_set_enabled(true);

// Change palette preset:
lcd_emulator_set_preset(LCD_PRESET_AMBER);

// Adjust dot pitch, gap width, and luminance threshold on the fly:
// (cell_size = 4 px, gap_size = 1 px, threshold = 135)
lcd_emulator_set_grid(4, 1, 135);
```

---

## 4. Kconfig Configuration Matrix

| Kconfig Symbol | Type | Default | Range / Choices | Operational Effect |
| :--- | :--- | :--- | :--- | :--- |
| `CONFIG_LCD_EMULATOR_ENABLE_AT_BOOT` | `bool` | `y` | `y / n` | Output boots in retro LCD mode (`y`) or bypassed color mode (`n`). |
| `CONFIG_LCD_EMULATOR_DEFAULT_CELL_SIZE` | `int` | `4` | `2 .. 8` | Physical dot pitch in OLED pixels (4 px yields 116×116 grid on 466×466 panel). |
| `CONFIG_LCD_EMULATOR_DEFAULT_GAP_SIZE` | `int` | `1` | `0 .. 2` | Physical pixel width of inactive substrate separator lines between dots. |
| `CONFIG_LCD_EMULATOR_DEFAULT_THRESHOLD` | `int` | `135` | `0 .. 255` | 8-bit luminance threshold detecting active dark LCD ink segments. |
| `CONFIG_LCD_EMULATOR_DEFAULT_PALETTE` | `choice` | `OLIVE` | `OLIVE`, `CASIO`, `AMBER`, `CYAN` | Active substrate and ink color palette applied at initialization. |

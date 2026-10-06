/**
 * @file lcd_emulator.h
 * @brief Retro dot-matrix monochrome LCD flush decorator and decimation filter for LVGL 9.
 *
 * Implements real-time screen-space pixel decimation, sub-pixel matrix gap modulation,
 * and classic STN/TN reflective palettes (Olive, Casio Grey, Amber, Cyan).
 *
 * Supports thread-safe decorator state getters/setters and pluggable render switching.
 * Designed for circular or rectangular OLED/LCD panels (e.g. 466x466 AMOLED) running LVGL 9.x.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#if defined(__has_include) && __has_include("esp_err.h")
#include "esp_err.h"
#else
typedef int esp_err_t;
#ifndef ESP_OK
#define ESP_OK 0
#endif
#ifndef ESP_FAIL
#define ESP_FAIL -1
#endif
#ifndef ESP_ERR_INVALID_ARG
#define ESP_ERR_INVALID_ARG 0x102
#endif
#endif

#if defined(__has_include) && __has_include("sdkconfig.h")
#include "sdkconfig.h"
#endif

#if defined(__has_include) && __has_include("lvgl.h")
#include "lvgl.h"
#else
#ifndef LVGL_H
typedef struct {
    int32_t x1;
    int32_t y1;
    int32_t x2;
    int32_t y2;
} lv_area_t;
typedef struct _lv_display_t lv_display_t;
#endif
#endif

#ifndef LV_COLOR_DEPTH
  #if defined(CONFIG_LV_COLOR_DEPTH)
    #define LV_COLOR_DEPTH CONFIG_LV_COLOR_DEPTH
  #else
    #define LV_COLOR_DEPTH 16
  #endif
#endif

#if LV_COLOR_DEPTH == 8
typedef uint8_t lcd_color_t;
#define LCD_COLOR_DEPTH_BYTES 1

/**
 * @brief Fast 8-bit luminance color pack macro (ITU-R BT.601 integer luminance: 0..255).
 */
#define LCD_COLOR_MAKE(r, g, b) \
    ((lcd_color_t)(((uint16_t)(77u * (r) + 150u * (g) + 29u * (b))) >> 8))

#else
typedef uint16_t lcd_color_t;
#define LCD_COLOR_DEPTH_BYTES 2

/**
 * @brief Fast 16-bit RGB565 pack macro (R: 5 bits, G: 6 bits, B: 5 bits).
 */
#define LCD_COLOR_MAKE(r, g, b) \
    ((lcd_color_t)((((uint16_t)(r) & 0xF8) << 8) | (((uint16_t)(g) & 0xFC) << 3) | (((uint16_t)(b) & 0xF8) >> 3)))

#endif

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Fast 16-bit RGB565 pack macro (R: 5 bits, G: 6 bits, B: 5 bits).
 */
#define LCD_RGB565(r, g, b) \
    ((uint16_t)((((uint16_t)(r) & 0xF8) << 8) | (((uint16_t)(g) & 0xFC) << 3) | (((uint16_t)(b) & 0xF8) >> 3)))

/**
 * @brief Endianness swap macro for 16-bit RGB565 pixels to match SPI/QSPI DMA panel wire-order (big-endian).
 */
#define LCD_RGB565_SWAP(val) \
    ((uint16_t)((((uint16_t)(val) >> 8) & 0x00FF) | (((uint16_t)(val) << 8) & 0xFF00)))

/**
 * @brief Retro LCD color palette configuration in native display color format (RGB565 or 8-bit L8).
 */
typedef struct {
    lcd_color_t color_bg;       /**< Substrate background color */
    lcd_color_t color_active;   /**< Active segment / dark ink */
    lcd_color_t color_inactive; /**< Unenergized segment / faint substrate */
    lcd_color_t color_gap;      /**< Inactive physical gap line between dots */
    uint16_t color_bg_rgb565;       /**< Full-fidelity 16-bit RGB565 substrate background */
    uint16_t color_active_rgb565;   /**< Full-fidelity 16-bit RGB565 active segment / ink */
    uint16_t color_inactive_rgb565; /**< Full-fidelity 16-bit RGB565 unenergized segment */
    uint16_t color_gap_rgb565;      /**< Full-fidelity 16-bit RGB565 gap line */
} lcd_palette_t;

/**
 * @brief Predefined classic retro LCD color palettes.
 */
typedef enum {
    LCD_PRESET_OLIVE = 0,    /**< Game Boy DMG / Nokia 5110 reflective olive-green STN */
    LCD_PRESET_CASIO_GREY,   /**< Casio / Timex reflective grey/silver digital watch */
    LCD_PRESET_AMBER,        /**< Industrial automotive amber backlit monochrome LCD */
    LCD_PRESET_CYAN,         /**< Electroluminescent cyan backlit matrix panel */
    LCD_PRESET_COUNT
} lcd_preset_t;

/**
 * @brief Pluggable render function callback type for custom post-processing.
 *
 * @param[in] area Coordinates of the redraw buffer relative to the physical screen.
 * @param[in,out] pixels Pointer to pixel buffer (length: width * height, element size: sizeof(lcd_color_t)).
 * @param[in] user_ctx Optional user context pointer registered with the callback.
 */
typedef void (*lcd_render_fn_t)(const lv_area_t *area, lcd_color_t *pixels, void *user_ctx);

/**
 * @brief Available rendering modes supported by the flush decorator.
 */
typedef enum {
    LCD_RENDER_MODE_PASSTHROUGH = 0,     /**< Direct full-color AMOLED rendering (decorator bypassed) */
    LCD_RENDER_MODE_RETRO_MONOCHROME,    /**< Classic dot-matrix monochrome LCD (dark ink on substrate) */
    LCD_RENDER_MODE_RETRO_INVERTED,      /**< Inverted dot-matrix monochrome LCD (illuminated ink on dark substrate) */
    LCD_RENDER_MODE_GRAYSCALE_4BIT,      /**< 4-bit grayscale dot-matrix LCD (16 discrete levels) */
    LCD_RENDER_MODE_GRAYSCALE_8BIT,      /**< 8-bit grayscale dot-matrix LCD (256 continuous levels) */
    LCD_RENDER_MODE_CUSTOM,              /**< Custom user-provided render callback function */
    LCD_RENDER_MODE_COUNT
} lcd_render_mode_t;

/**
 * @brief Grayscale shading style configuration.
 */
typedef enum {
    LCD_SHADING_PALETTE_TINTED = 0,      /**< Linearly interpolate between color_inactive and color_active */
    LCD_SHADING_NEUTRAL_GRAY,            /**< True neutral monochrome gray (R = G = B) */
    LCD_SHADING_COUNT
} lcd_shading_mode_t;

/**
 * @brief Comprehensive decorator state representation.
 */
typedef struct {
    lcd_render_mode_t mode;              /**< Active render mode */
    lcd_shading_mode_t shading_mode;     /**< Grayscale shading style (palette-tinted vs neutral gray) */
    bool dark_theme;                     /**< True if input UI has dark background (AMOLED / black bg with bright text) */
    uint8_t cell_size;                   /**< Dot pitch in physical pixels (minimum 2) */
    uint8_t gap_size;                    /**< Inactive gap width in pixels (< cell_size) */
    uint8_t threshold;                   /**< Luminance binarization threshold (0..255) */
    lcd_palette_t palette;               /**< Active RGB565 palette */
    lcd_render_fn_t custom_render_fn;    /**< Custom render callback (used when mode == LCD_RENDER_MODE_CUSTOM) */
    void *custom_user_ctx;               /**< User context passed to custom_render_fn */
} lcd_decorator_state_t;

/**
 * @brief Legacy configuration alias for backward compatibility.
 */
typedef struct {
    bool enabled;
    uint8_t cell_size;
    uint8_t gap_size;
    uint8_t threshold;
    lcd_palette_t palette;
} lcd_emulator_cfg_t;

/**
 * @brief Attach the LCD emulator decorator to an active LVGL 9 display.
 *
 * Saves the original display flush callback and installs the LCD emulator decorator.
 *
 * @param[in] disp Pointer to active LVGL display (`main_display`).
 * @return ESP_OK on success, or error code on invalid argument / state.
 */
esp_err_t lcd_emulator_init(lv_display_t *disp);

/**
 * @brief Set the complete decorator state with thread-safety and display invalidation.
 *
 * Validates all parameters, takes internal recursive mutex lock, updates active state,
 * and safely triggers a full display redraw under the LVGL display lock.
 *
 * @param[in] state Pointer to new decorator state.
 * @return ESP_OK on success, ESP_ERR_INVALID_ARG on NULL or out-of-range parameters.
 */
esp_err_t lcd_emulator_set_decorator_state(const lcd_decorator_state_t *state);

/**
 * @brief Get an atomic copy of the current decorator state.
 *
 * Thread-safe; captures an atomic snapshot of active parameters under internal lock.
 *
 * @param[out] out_state Pointer to buffer receiving current decorator state.
 * @return ESP_OK on success, ESP_ERR_INVALID_ARG on NULL pointer.
 */
esp_err_t lcd_emulator_get_decorator_state(lcd_decorator_state_t *out_state);

/**
 * @brief Switch the active render mode with thread-safety.
 *
 * @param[in] mode Desired render mode (e.g. LCD_RENDER_MODE_PASSTHROUGH, LCD_RENDER_MODE_RETRO_MONOCHROME).
 * @return ESP_OK on success, ESP_ERR_INVALID_ARG if mode is out of range.
 */
esp_err_t lcd_emulator_set_render_mode(lcd_render_mode_t mode);

/**
 * @brief Retrieve the current active render mode.
 *
 * @return Active lcd_render_mode_t.
 */
lcd_render_mode_t lcd_emulator_get_render_mode(void);

/**
 * @brief Configure grayscale shading style (palette-tinted vs neutral monochrome gray).
 *
 * @param[in] shading_mode Shading mode enum (e.g. LCD_SHADING_PALETTE_TINTED, LCD_SHADING_NEUTRAL_GRAY).
 * @return ESP_OK on success, ESP_ERR_INVALID_ARG if out of range.
 */
esp_err_t lcd_emulator_set_shading_mode(lcd_shading_mode_t shading_mode);

/**
 * @brief Retrieve the current active grayscale shading style.
 *
 * @return Active lcd_shading_mode_t.
 */
lcd_shading_mode_t lcd_emulator_get_shading_mode(void);

/**
 * @brief Register a custom render callback and switch decorator to LCD_RENDER_MODE_CUSTOM.
 *
 * @param[in] render_fn Custom render callback function.
 * @param[in] user_ctx Optional user context pointer.
 * @return ESP_OK on success, ESP_ERR_INVALID_ARG if render_fn is NULL.
 */
esp_err_t lcd_emulator_set_custom_render(lcd_render_fn_t render_fn, void *user_ctx);

/**
 * @brief Enable or disable retro LCD emulation dynamically at runtime (legacy wrapper).
 *
 * Maps to LCD_RENDER_MODE_RETRO_MONOCHROME (true) or LCD_RENDER_MODE_PASSTHROUGH (false).
 *
 * @param[in] enabled True to enable retro LCD emulation, false for modern full-color AMOLED mode.
 */
void lcd_emulator_set_enabled(bool enabled);

/**
 * @brief Check whether retro LCD emulation is currently active.
 *
 * @return true if mode != LCD_RENDER_MODE_PASSTHROUGH, false if bypassed.
 */
bool lcd_emulator_is_enabled(void);

/**
 * @brief Toggle between full-color passthrough and retro monochrome LCD mode.
 */
void lcd_emulator_toggle(void);

/**
 * @brief Select one of the built-in retro LCD palette presets.
 *
 * @param[in] preset Preset enum value (e.g. LCD_PRESET_OLIVE, LCD_PRESET_AMBER).
 */
void lcd_emulator_set_preset(lcd_preset_t preset);

/**
 * @brief Configure a custom retro LCD palette.
 *
 * @param[in] palette Pointer to custom RGB565 palette structure.
 */
void lcd_emulator_set_palette(const lcd_palette_t *palette);

/**
 * @brief Configure dot matrix geometry and threshold parameters.
 *
 * @param[in] cell_size Dot pitch in physical pixels (minimum 2).
 * @param[in] gap_size Inactive gap width in physical pixels (must be strictly less than cell_size).
 * @param[in] threshold Binarization threshold for dark ink detection (0..255).
 */
void lcd_emulator_set_grid(uint8_t cell_size, uint8_t gap_size, uint8_t threshold);

/**
 * @brief Configure source UI theme expectation (dark AMOLED vs light canvas).
 *
 * @param[in] dark_theme True if input UI has dark background with bright text (default for AMOLED).
 */
void lcd_emulator_set_dark_theme(bool dark_theme);

/**
 * @brief Check whether decorator expects a dark-themed source UI.
 *
 * @return True if dark theme mode is active.
 */
bool lcd_emulator_is_dark_theme(void);

/**
 * @brief Configure monochrome dot matrix inversion polarity.
 *
 * @param[in] inverted True for inverted / negative LCD (illuminated dots on dark substrate),
 *                     false for standard monochrome LCD.
 */
void lcd_emulator_set_inverted(bool inverted);

/**
 * @brief Check whether output inversion is active.
 *
 * @return True if mode == LCD_RENDER_MODE_RETRO_INVERTED.
 */
bool lcd_emulator_is_inverted(void);

/**
 * @brief Get legacy configuration pointer.
 *
 * @return Pointer to const configuration struct.
 */
const lcd_emulator_cfg_t* lcd_emulator_get_config(void);

/**
 * @brief Pure C in-place pixel decimation filter.
 *
 * Transforms an arbitrary dirty rectangle of display pixels in-place according to
 * screen-space dot matrix coordinates. Safe to call on partial redraw buffers.
 *
 * @param[in] area Coordinates of the redraw buffer relative to the physical screen.
 * @param[in,out] pixels Pointer to pixel buffer (length: width * height, element size: sizeof(lcd_color_t)).
 * @param[in] state Decorator state parameters containing grid sizing, threshold, and palette.
 * @param[in] inverted If true, inverts ink logic (illuminated dots on dark substrate).
 */
void lcd_emulator_apply_filter_ex(const lv_area_t *area, lcd_color_t *pixels, const lcd_decorator_state_t *state, bool inverted);

/**
 * @brief Legacy filter wrapper.
 */
void lcd_emulator_apply_filter(const lv_area_t *area, lcd_color_t *pixels, const lcd_emulator_cfg_t *cfg);

/**
 * @brief Configure whether 8-bit input buffers are decoded as RGB232 (true) or L8 luminance (false).
 *
 * @param[in] is_rgb232 True for RGB232 (LVGL 8 style), false for L8 luminance (LVGL 9 default).
 */
void lcd_emulator_set_8bit_input_rgb232(bool is_rgb232);

/**
 * @brief Check whether 8-bit input buffers are currently treated as RGB232.
 *
 * @return True if RGB232, false if L8 luminance.
 */
bool lcd_emulator_is_8bit_input_rgb232(void);

/**
 * @brief Single-pass streaming decimation filter from 8-bit input to 16-bit RGB565 output.
 *
 * Directly box-samples 8-bit pixels from the LVGL draw buffer and emits byte-swapped
 * 16-bit RGB565 pixels into out_rgb565 with zero buffer re-reading or intermediate passes.
 *
 * @param[in] area Coordinates of the redraw buffer relative to the physical screen.
 * @param[in] pixels_8 Pointer to read-only 8-bit pixel buffer.
 * @param[out] out_rgb565 Pointer to destination 16-bit RGB565 buffer.
 * @param[in] state Decorator state parameters containing grid sizing, threshold, and palette.
 * @param[in] inverted If true, inverts ink logic.
 * @param[in] wire_swap If true, swaps byte endianness (big-endian) for direct SPI/QSPI DMA transmission.
 */
void lcd_emulator_apply_filter_8to16(const lv_area_t *area, const uint8_t *pixels_8,
                                    uint16_t *out_rgb565, const lcd_decorator_state_t *state,
                                    bool inverted, bool wire_swap);

#ifdef __cplusplus
}
#endif

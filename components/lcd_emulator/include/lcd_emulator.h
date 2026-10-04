/**
 * @file lcd_emulator.h
 * @brief Retro dot-matrix monochrome LCD flush decorator and decimation filter for LVGL 9.
 *
 * Implements real-time screen-space pixel decimation, sub-pixel matrix gap modulation,
 * and classic STN/TN reflective palettes (Olive, Casio Grey, Amber, Cyan).
 *
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

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Fast 16-bit RGB565 pack macro (R: 5 bits, G: 6 bits, B: 5 bits).
 */
#define LCD_RGB565(r, g, b) \
    ((uint16_t)((((uint16_t)(r) & 0xF8) << 8) | (((uint16_t)(g) & 0xFC) << 3) | (((uint16_t)(b) & 0xF8) >> 3)))

/**
 * @brief Retro LCD color palette configuration in RGB565 format.
 */
typedef struct {
    uint16_t color_bg;       /**< Substrate background color (RGB565) */
    uint16_t color_active;   /**< Active segment / dark ink (RGB565) */
    uint16_t color_inactive; /**< Unenergized segment / faint substrate (RGB565) */
    uint16_t color_gap;      /**< Inactive physical gap line between dots (RGB565) */
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
 * @brief Runtime configuration parameters for retro LCD emulation.
 */
typedef struct {
    bool enabled;            /**< Whether retro LCD emulation is active */
    uint8_t cell_size;       /**< Dot pitch in physical pixels (e.g. 2..8, default: 4) */
    uint8_t gap_size;        /**< Inactive gap width in pixels (e.g. 0..2, default: 1) */
    uint8_t threshold;       /**< Luminance binarization threshold (0..255, default: 135) */
    lcd_palette_t palette;   /**< Active RGB565 color palette */
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
 * @brief Enable or disable retro LCD emulation dynamically at runtime.
 *
 * When disabled, the decorator acts as a zero-overhead passthrough to the vendor flush callback.
 *
 * @param[in] enabled True to enable retro LCD emulation, false for modern full-color AMOLED mode.
 */
void lcd_emulator_set_enabled(bool enabled);

/**
 * @brief Check whether retro LCD emulation is currently active.
 *
 * @return true if enabled, false if bypassed.
 */
bool lcd_emulator_is_enabled(void);

/**
 * @brief Toggle retro LCD emulation on/off.
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
 * @brief Get read-only pointer to the current active emulator configuration.
 *
 * @return Pointer to const configuration struct.
 */
const lcd_emulator_cfg_t* lcd_emulator_get_config(void);

/**
 * @brief Pure C in-place pixel decimation filter.
 *
 * Transforms an arbitrary dirty rectangle of RGB565 pixels in-place according to
 * screen-space dot matrix coordinates. Safe to call on partial redraw buffers.
 *
 * @param[in] area Coordinates of the redraw buffer relative to the physical screen.
 * @param[in,out] pixels Pointer to RGB565 pixel buffer (length: width * height).
 * @param[in] cfg Configuration parameters containing grid sizing, threshold, and palette.
 */
void lcd_emulator_apply_filter(const lv_area_t *area, uint16_t *pixels, const lcd_emulator_cfg_t *cfg);

#ifdef __cplusplus
}
#endif

/**
 * @file lcd_emulator.c
 * @brief Implementation of retro dot-matrix monochrome LCD flush decorator and decimation filter.
 */

#if defined(__has_include) && __has_include("sdkconfig.h")
#include "sdkconfig.h"
#endif

#include "lcd_emulator.h"

#include <stdlib.h>

#if defined(ESP_PLATFORM)
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
static const char *TAG = "lcd_emulator";
#else
#define ESP_LOGI(tag, fmt, ...)
#define ESP_LOGW(tag, fmt, ...)
#define ESP_LOGE(tag, fmt, ...)
#endif

/* Kconfig Default Mappings */
#if defined(CONFIG_LCD_EMULATOR_MODE_PASSTHROUGH)
#define LCD_KCONFIG_RENDER_MODE   LCD_RENDER_MODE_PASSTHROUGH
#define LCD_KCONFIG_ENABLED       false
#elif defined(CONFIG_LCD_EMULATOR_MODE_RETRO_INVERTED)
#define LCD_KCONFIG_RENDER_MODE   LCD_RENDER_MODE_RETRO_INVERTED
#define LCD_KCONFIG_ENABLED       true
#elif defined(CONFIG_LCD_EMULATOR_MODE_GRAYSCALE_4BIT)
#define LCD_KCONFIG_RENDER_MODE   LCD_RENDER_MODE_GRAYSCALE_4BIT
#define LCD_KCONFIG_ENABLED       true
#elif defined(CONFIG_LCD_EMULATOR_MODE_GRAYSCALE_8BIT)
#define LCD_KCONFIG_RENDER_MODE   LCD_RENDER_MODE_GRAYSCALE_8BIT
#define LCD_KCONFIG_ENABLED       true
#elif defined(CONFIG_LCD_EMULATOR_MODE_RETRO_MONOCHROME)
#if defined(CONFIG_LCD_EMULATOR_INVERT_OUTPUT) && (CONFIG_LCD_EMULATOR_INVERT_OUTPUT == 1)
#define LCD_KCONFIG_RENDER_MODE   LCD_RENDER_MODE_RETRO_INVERTED
#else
#define LCD_KCONFIG_RENDER_MODE   LCD_RENDER_MODE_RETRO_MONOCHROME
#endif
#define LCD_KCONFIG_ENABLED       true
#elif defined(CONFIG_LCD_EMULATOR_ENABLE_AT_BOOT) && (CONFIG_LCD_EMULATOR_ENABLE_AT_BOOT == 0)
#define LCD_KCONFIG_RENDER_MODE   LCD_RENDER_MODE_PASSTHROUGH
#define LCD_KCONFIG_ENABLED       false
#elif defined(CONFIG_LCD_EMULATOR_INVERT_OUTPUT) && (CONFIG_LCD_EMULATOR_INVERT_OUTPUT == 1)
#define LCD_KCONFIG_RENDER_MODE   LCD_RENDER_MODE_RETRO_INVERTED
#define LCD_KCONFIG_ENABLED       true
#elif defined(CONFIG_LCD_EMULATOR_ENABLE_AT_BOOT) && (CONFIG_LCD_EMULATOR_ENABLE_AT_BOOT == 1)
#define LCD_KCONFIG_RENDER_MODE   LCD_RENDER_MODE_RETRO_MONOCHROME
#define LCD_KCONFIG_ENABLED       true
#elif !defined(CONFIG_LCD_EMULATOR_ENABLE_AT_BOOT) && defined(CONFIG_IDF_TARGET)
#define LCD_KCONFIG_RENDER_MODE   LCD_RENDER_MODE_PASSTHROUGH
#define LCD_KCONFIG_ENABLED       false
#else
#define LCD_KCONFIG_RENDER_MODE   LCD_RENDER_MODE_RETRO_MONOCHROME
#define LCD_KCONFIG_ENABLED       true
#endif

#if defined(CONFIG_LCD_EMULATOR_SHADING_NEUTRAL_GRAY)
#define LCD_KCONFIG_SHADING_MODE  LCD_SHADING_NEUTRAL_GRAY
#else
#define LCD_KCONFIG_SHADING_MODE  LCD_SHADING_PALETTE_TINTED
#endif

#if defined(CONFIG_LCD_EMULATOR_DARK_THEME_INPUT) && (CONFIG_LCD_EMULATOR_DARK_THEME_INPUT == 0)
#define LCD_KCONFIG_DARK_THEME    false
#else
#define LCD_KCONFIG_DARK_THEME    true
#endif

#ifdef CONFIG_LCD_EMULATOR_DEFAULT_CELL_SIZE
#define LCD_KCONFIG_CELL_SIZE     ((uint8_t)CONFIG_LCD_EMULATOR_DEFAULT_CELL_SIZE)
#else
#define LCD_KCONFIG_CELL_SIZE     ((uint8_t)4)
#endif

#ifdef CONFIG_LCD_EMULATOR_DEFAULT_GAP_SIZE
#define LCD_KCONFIG_GAP_SIZE      ((uint8_t)CONFIG_LCD_EMULATOR_DEFAULT_GAP_SIZE)
#else
#define LCD_KCONFIG_GAP_SIZE      ((uint8_t)1)
#endif

#ifdef CONFIG_LCD_EMULATOR_DEFAULT_THRESHOLD
#define LCD_KCONFIG_THRESHOLD     ((uint8_t)CONFIG_LCD_EMULATOR_DEFAULT_THRESHOLD)
#else
#define LCD_KCONFIG_THRESHOLD     ((uint8_t)100)
#endif

#if defined(CONFIG_LCD_EMULATOR_PALETTE_CASIO)
#define LCD_KCONFIG_PRESET        LCD_PRESET_CASIO_GREY
#elif defined(CONFIG_LCD_EMULATOR_PALETTE_AMBER)
#define LCD_KCONFIG_PRESET        LCD_PRESET_AMBER
#elif defined(CONFIG_LCD_EMULATOR_PALETTE_CYAN)
#define LCD_KCONFIG_PRESET        LCD_PRESET_CYAN
#else
#define LCD_KCONFIG_PRESET        LCD_PRESET_OLIVE
#endif

#define LCD_MAX_CELL_COLS 256

#if LV_COLOR_DEPTH == 8
static uint16_t *s_rgb565_buf = NULL;
static size_t s_rgb565_buf_pixels = 0;
#endif

/* Preset Palette Definitions */
static const lcd_palette_t s_palettes[LCD_PRESET_COUNT] = {
    [LCD_PRESET_OLIVE] = {
        .color_bg       = LCD_COLOR_MAKE(0x8A, 0x9A, 0x5B),
        .color_active   = LCD_COLOR_MAKE(0x1B, 0x28, 0x12),
        .color_inactive = LCD_COLOR_MAKE(0x7D, 0x8C, 0x50),
        .color_gap      = LCD_COLOR_MAKE(0x6F, 0x7E, 0x45),
    },
    [LCD_PRESET_CASIO_GREY] = {
        .color_bg       = LCD_COLOR_MAKE(0xA0, 0xB0, 0xA2),
        .color_active   = LCD_COLOR_MAKE(0x14, 0x1D, 0x15),
        .color_inactive = LCD_COLOR_MAKE(0x91, 0xA1, 0x93),
        .color_gap      = LCD_COLOR_MAKE(0x7E, 0x8E, 0x80),
    },
    [LCD_PRESET_AMBER] = {
        .color_bg       = LCD_COLOR_MAKE(0x18, 0x10, 0x02),
        .color_active   = LCD_COLOR_MAKE(0xFF, 0xAA, 0x00),
        .color_inactive = LCD_COLOR_MAKE(0x36, 0x21, 0x04),
        .color_gap      = LCD_COLOR_MAKE(0x0D, 0x07, 0x00),
    },
    [LCD_PRESET_CYAN] = {
        .color_bg       = LCD_COLOR_MAKE(0x08, 0x1D, 0x22),
        .color_active   = LCD_COLOR_MAKE(0x00, 0xF0, 0xFF),
        .color_inactive = LCD_COLOR_MAKE(0x12, 0x39, 0x42),
        .color_gap      = LCD_COLOR_MAKE(0x04, 0x0F, 0x12),
    },
};

/* Active Decorator State (initialized with Kconfig defaults) */
static lcd_decorator_state_t s_state = {
    .mode             = LCD_KCONFIG_RENDER_MODE,
    .shading_mode     = LCD_KCONFIG_SHADING_MODE,
    .dark_theme       = LCD_KCONFIG_DARK_THEME,
    .cell_size        = LCD_KCONFIG_CELL_SIZE,
    .gap_size         = LCD_KCONFIG_GAP_SIZE,
    .threshold        = LCD_KCONFIG_THRESHOLD,
    .palette          = {
        .color_bg       = LCD_COLOR_MAKE(0x8A, 0x9A, 0x5B),
        .color_active   = LCD_COLOR_MAKE(0x1B, 0x28, 0x12),
        .color_inactive = LCD_COLOR_MAKE(0x7D, 0x8C, 0x50),
        .color_gap      = LCD_COLOR_MAKE(0x6F, 0x7E, 0x45),
    },
    .custom_render_fn = NULL,
    .custom_user_ctx  = NULL,
};

static lcd_emulator_cfg_t s_legacy_cfg = {
    .enabled    = LCD_KCONFIG_ENABLED,
    .cell_size  = LCD_KCONFIG_CELL_SIZE,
    .gap_size   = LCD_KCONFIG_GAP_SIZE,
    .threshold  = LCD_KCONFIG_THRESHOLD,
    .palette    = {
        .color_bg       = LCD_COLOR_MAKE(0x8A, 0x9A, 0x5B),
        .color_active   = LCD_COLOR_MAKE(0x1B, 0x28, 0x12),
        .color_inactive = LCD_COLOR_MAKE(0x7D, 0x8C, 0x50),
        .color_gap      = LCD_COLOR_MAKE(0x6F, 0x7E, 0x45),
    },
};

#if defined(ESP_PLATFORM)
static SemaphoreHandle_t s_state_mutex = NULL;

static inline void state_lock(void)
{
    if (s_state_mutex) {
        xSemaphoreTakeRecursive(s_state_mutex, portMAX_DELAY);
    }
}

static inline void state_unlock(void)
{
    if (s_state_mutex) {
        xSemaphoreGiveRecursive(s_state_mutex);
    }
}
#else
static inline void state_lock(void) {}
static inline void state_unlock(void) {}
#endif

#if defined(LVGL_H) || (defined(__has_include) && __has_include("lvgl.h"))
#if defined(__has_include) && __has_include("display/lv_display_private.h")
#include "display/lv_display_private.h"
#elif defined(__has_include) && __has_include("src/display/lv_display_private.h")
#include "src/display/lv_display_private.h"
#endif

static lv_display_t *s_target_disp = NULL;
static lv_display_flush_cb_t s_orig_flush_cb = NULL;

static void trigger_display_invalidation(void)
{
    if (s_target_disp) {
        lv_lock();
        lv_obj_t *act_screen = lv_display_get_screen_active(s_target_disp);
        if (act_screen) {
            lv_obj_invalidate(act_screen);
        }
        lv_unlock();
    }
}

static void lcd_decorator_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    lcd_decorator_state_t snap;
    state_lock();
    snap = s_state;
    state_unlock();

    if (area && px_map) {
        lcd_color_t *color_buf = (lcd_color_t *)px_map;
        switch (snap.mode) {
        case LCD_RENDER_MODE_RETRO_MONOCHROME:
            lcd_emulator_apply_filter_ex(area, color_buf, &snap, false);
            break;
        case LCD_RENDER_MODE_RETRO_INVERTED:
            lcd_emulator_apply_filter_ex(area, color_buf, &snap, true);
            break;
        case LCD_RENDER_MODE_GRAYSCALE_4BIT:
        case LCD_RENDER_MODE_GRAYSCALE_8BIT:
            lcd_emulator_apply_filter_ex(area, color_buf, &snap, false);
            break;
        case LCD_RENDER_MODE_CUSTOM:
            if (snap.custom_render_fn) {
                snap.custom_render_fn(area, color_buf, snap.custom_user_ctx);
            }
            break;
        case LCD_RENDER_MODE_PASSTHROUGH:
        default:
            // Zero-overhead passthrough
            break;
        }

#if LV_COLOR_DEPTH == 8
#if defined(CONFIG_LCD_EMULATOR_EXPAND_TO_RGB565) || !defined(ESP_PLATFORM)
        const int32_t width = area->x2 - area->x1 + 1;
        const int32_t height = area->y2 - area->y1 + 1;
        const size_t area_pixels = (size_t)(width * height);
        if (s_rgb565_buf && area_pixels <= s_rgb565_buf_pixels) {
            const uint8_t *src8 = (const uint8_t *)px_map;
            for (size_t i = 0; i < area_pixels; i++) {
                const uint8_t v = src8[i];
                const uint16_t r5 = (uint16_t)((v >> 3) & 0x1F);
                const uint16_t g6 = (uint16_t)((v >> 2) & 0x3F);
                const uint16_t b5 = (uint16_t)((v >> 3) & 0x1F);
                s_rgb565_buf[i] = (uint16_t)((r5 << 11) | (g6 << 5) | b5);
            }
            if (s_orig_flush_cb) {
                s_orig_flush_cb(disp, area, (uint8_t *)s_rgb565_buf);
            } else {
                lv_display_flush_ready(disp);
            }
            return;
        }
#endif
#endif
    }

    if (s_orig_flush_cb) {
        s_orig_flush_cb(disp, area, px_map);
    } else {
        lv_display_flush_ready(disp);
    }
}
#else
static void trigger_display_invalidation(void) {}
#endif

esp_err_t lcd_emulator_init(lv_display_t *disp)
{
#if defined(ESP_PLATFORM)
    if (!s_state_mutex) {
        s_state_mutex = xSemaphoreCreateRecursiveMutex();
        if (!s_state_mutex) {
            return ESP_FAIL;
        }
    }
#endif

    state_lock();
    s_state.mode             = LCD_KCONFIG_RENDER_MODE;
    s_state.shading_mode     = LCD_KCONFIG_SHADING_MODE;
    s_state.dark_theme       = LCD_KCONFIG_DARK_THEME;
    s_state.cell_size        = LCD_KCONFIG_CELL_SIZE;
    s_state.gap_size         = LCD_KCONFIG_GAP_SIZE;
    s_state.threshold        = LCD_KCONFIG_THRESHOLD;
    s_state.palette          = s_palettes[LCD_KCONFIG_PRESET];
    s_state.custom_render_fn = NULL;
    s_state.custom_user_ctx  = NULL;

    s_legacy_cfg.enabled     = LCD_KCONFIG_ENABLED;
    s_legacy_cfg.cell_size   = LCD_KCONFIG_CELL_SIZE;
    s_legacy_cfg.gap_size    = LCD_KCONFIG_GAP_SIZE;
    s_legacy_cfg.threshold   = LCD_KCONFIG_THRESHOLD;
    s_legacy_cfg.palette     = s_palettes[LCD_KCONFIG_PRESET];
    state_unlock();

#if LV_COLOR_DEPTH == 8
#if defined(CONFIG_LCD_EMULATOR_EXPAND_TO_RGB565) || !defined(ESP_PLATFORM)
    int32_t hor_res = 466;
    int32_t ver_res = 466;
#if defined(LVGL_H) || (defined(__has_include) && __has_include("lvgl.h"))
    if (disp) {
        int32_t h = lv_display_get_horizontal_resolution(disp);
        int32_t v = lv_display_get_vertical_resolution(disp);
        if (h > 0 && v > 0) {
            hor_res = h;
            ver_res = v;
        }
    }
#endif
    size_t req_pixels = (size_t)(hor_res * ver_res);
    if (!s_rgb565_buf || s_rgb565_buf_pixels < req_pixels) {
#if defined(ESP_PLATFORM)
        if (s_rgb565_buf) {
            free(s_rgb565_buf);
        }
        s_rgb565_buf = (uint16_t *)heap_caps_malloc(req_pixels * sizeof(uint16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!s_rgb565_buf) {
            s_rgb565_buf = (uint16_t *)malloc(req_pixels * sizeof(uint16_t));
        }
#else
        if (s_rgb565_buf) {
            free(s_rgb565_buf);
        }
        s_rgb565_buf = (uint16_t *)malloc(req_pixels * sizeof(uint16_t));
#endif
        if (s_rgb565_buf) {
            s_rgb565_buf_pixels = req_pixels;
        } else {
            s_rgb565_buf_pixels = 0;
            ESP_LOGE(TAG, "Failed to allocate %zu bytes for RGB565 expansion buffer", req_pixels * sizeof(uint16_t));
        }
    }
#endif
#endif

#if defined(LVGL_H) || (defined(__has_include) && __has_include("lvgl.h"))
    if (!disp) {
        ESP_LOGE(TAG, "Invalid display handle");
        return ESP_ERR_INVALID_ARG;
    }

    lv_lock();
    s_target_disp = disp;
    s_orig_flush_cb = disp->flush_cb;
    lv_display_set_flush_cb(disp, lcd_decorator_flush_cb);
    lv_unlock();

    ESP_LOGI(TAG, "LCD decorator attached to display %p: mode=%d, shading=%d, cell=%u, gap=%u, threshold=%u, preset=%d, dark_theme=%d, depth=%d",
             disp, (int)s_state.mode, (int)s_state.shading_mode, (unsigned)s_state.cell_size,
             (unsigned)s_state.gap_size, (unsigned)s_state.threshold, (int)LCD_KCONFIG_PRESET,
             (int)s_state.dark_theme, (int)LV_COLOR_DEPTH);
    return ESP_OK;
#else
    (void)disp;
    return ESP_OK;
#endif
}

esp_err_t lcd_emulator_set_decorator_state(const lcd_decorator_state_t *state)
{
    if (!state) {
        return ESP_ERR_INVALID_ARG;
    }
    if (state->mode >= LCD_RENDER_MODE_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    if (state->shading_mode >= LCD_SHADING_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    if (state->cell_size < 2) {
        return ESP_ERR_INVALID_ARG;
    }
    if (state->gap_size >= state->cell_size) {
        return ESP_ERR_INVALID_ARG;
    }
    if (state->mode == LCD_RENDER_MODE_CUSTOM && !state->custom_render_fn) {
        return ESP_ERR_INVALID_ARG;
    }

    state_lock();
    s_state = *state;

    // Synchronize legacy configuration mirror
    s_legacy_cfg.enabled   = (s_state.mode != LCD_RENDER_MODE_PASSTHROUGH);
    s_legacy_cfg.cell_size = s_state.cell_size;
    s_legacy_cfg.gap_size  = s_state.gap_size;
    s_legacy_cfg.threshold = s_state.threshold;
    s_legacy_cfg.palette   = s_state.palette;
    state_unlock();

    trigger_display_invalidation();
    return ESP_OK;
}

esp_err_t lcd_emulator_get_decorator_state(lcd_decorator_state_t *out_state)
{
    if (!out_state) {
        return ESP_ERR_INVALID_ARG;
    }
    state_lock();
    *out_state = s_state;
    state_unlock();
    return ESP_OK;
}

esp_err_t lcd_emulator_set_render_mode(lcd_render_mode_t mode)
{
    if (mode >= LCD_RENDER_MODE_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    state_lock();
    if (mode == LCD_RENDER_MODE_CUSTOM && !s_state.custom_render_fn) {
        state_unlock();
        return ESP_ERR_INVALID_ARG;
    }
    s_state.mode = mode;
    s_legacy_cfg.enabled = (mode != LCD_RENDER_MODE_PASSTHROUGH);
    state_unlock();

    trigger_display_invalidation();
    return ESP_OK;
}

lcd_render_mode_t lcd_emulator_get_render_mode(void)
{
    state_lock();
    lcd_render_mode_t mode = s_state.mode;
    state_unlock();
    return mode;
}

esp_err_t lcd_emulator_set_shading_mode(lcd_shading_mode_t shading_mode)
{
    if (shading_mode >= LCD_SHADING_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    state_lock();
    s_state.shading_mode = shading_mode;
    state_unlock();

    trigger_display_invalidation();
    return ESP_OK;
}

lcd_shading_mode_t lcd_emulator_get_shading_mode(void)
{
    state_lock();
    lcd_shading_mode_t sm = s_state.shading_mode;
    state_unlock();
    return sm;
}

esp_err_t lcd_emulator_set_custom_render(lcd_render_fn_t render_fn, void *user_ctx)
{
    if (!render_fn) {
        return ESP_ERR_INVALID_ARG;
    }
    state_lock();
    s_state.custom_render_fn = render_fn;
    s_state.custom_user_ctx  = user_ctx;
    s_state.mode             = LCD_RENDER_MODE_CUSTOM;
    s_legacy_cfg.enabled     = true;
    state_unlock();

    trigger_display_invalidation();
    return ESP_OK;
}

void lcd_emulator_set_enabled(bool enabled)
{
    lcd_emulator_set_render_mode(enabled ? LCD_RENDER_MODE_RETRO_MONOCHROME : LCD_RENDER_MODE_PASSTHROUGH);
}

bool lcd_emulator_is_enabled(void)
{
    return (lcd_emulator_get_render_mode() != LCD_RENDER_MODE_PASSTHROUGH);
}

void lcd_emulator_toggle(void)
{
    lcd_emulator_set_enabled(!lcd_emulator_is_enabled());
}

void lcd_emulator_set_preset(lcd_preset_t preset)
{
    if (preset >= LCD_PRESET_COUNT) {
        return;
    }
    state_lock();
    s_state.palette = s_palettes[preset];
    s_legacy_cfg.palette = s_palettes[preset];
    state_unlock();

    trigger_display_invalidation();
}

void lcd_emulator_set_palette(const lcd_palette_t *palette)
{
    if (!palette) {
        return;
    }
    state_lock();
    s_state.palette = *palette;
    s_legacy_cfg.palette = *palette;
    state_unlock();

    trigger_display_invalidation();
}

void lcd_emulator_set_grid(uint8_t cell_size, uint8_t gap_size, uint8_t threshold)
{
    if (cell_size < 2) {
        cell_size = 2;
    }
    if (gap_size >= cell_size) {
        gap_size = cell_size - 1;
    }
    state_lock();
    s_state.cell_size = cell_size;
    s_state.gap_size  = gap_size;
    s_state.threshold = threshold;

    s_legacy_cfg.cell_size = cell_size;
    s_legacy_cfg.gap_size  = gap_size;
    s_legacy_cfg.threshold = threshold;
    state_unlock();

    trigger_display_invalidation();
}

void lcd_emulator_set_dark_theme(bool dark_theme)
{
    state_lock();
    s_state.dark_theme = dark_theme;
    state_unlock();

    trigger_display_invalidation();
}

bool lcd_emulator_is_dark_theme(void)
{
    state_lock();
    bool dt = s_state.dark_theme;
    state_unlock();
    return dt;
}

void lcd_emulator_set_inverted(bool inverted)
{
    lcd_emulator_set_render_mode(inverted ? LCD_RENDER_MODE_RETRO_INVERTED : LCD_RENDER_MODE_RETRO_MONOCHROME);
}

bool lcd_emulator_is_inverted(void)
{
    return (lcd_emulator_get_render_mode() == LCD_RENDER_MODE_RETRO_INVERTED);
}

const lcd_emulator_cfg_t* lcd_emulator_get_config(void)
{
    return &s_legacy_cfg;
}

void lcd_emulator_apply_filter_ex(const lv_area_t *area, lcd_color_t *pixels, const lcd_decorator_state_t *state, bool inverted)
{
    if (!area || !pixels || !state) {
        return;
    }

    const int32_t width = area->x2 - area->x1 + 1;
    const int32_t height = area->y2 - area->y1 + 1;
    if (width <= 0 || height <= 0) {
        return;
    }

    const uint8_t cell_size = (state->cell_size >= 2) ? state->cell_size : 4;
    const uint8_t gap_size = (state->gap_size < cell_size) ? state->gap_size : 1;
    const uint8_t threshold = state->threshold;
    const lcd_color_t col_gap = state->palette.color_gap;
    const lcd_color_t col_active = state->palette.color_active;
    const lcd_color_t col_inactive = state->palette.color_inactive;

    const bool is_grayscale_4bit = (state->mode == LCD_RENDER_MODE_GRAYSCALE_4BIT);
    const bool is_grayscale_8bit = (state->mode == LCD_RENDER_MODE_GRAYSCALE_8BIT);
    const bool is_grayscale = is_grayscale_4bit || is_grayscale_8bit;

    lcd_color_t effective_col_gap = col_gap;
#if LV_COLOR_DEPTH == 8
    (void)is_grayscale;
#else
    if (state->shading_mode == LCD_SHADING_NEUTRAL_GRAY && is_grayscale) {
        const uint8_t gr5 = (col_gap >> 11) & 0x1F;
        const uint8_t gg6 = (col_gap >> 5) & 0x3F;
        const uint8_t gb5 = col_gap & 0x1F;
        const uint8_t gr = (gr5 << 3) | (gr5 >> 2);
        const uint8_t gg = (gg6 << 2) | (gg6 >> 4);
        const uint8_t gb = (gb5 << 3) | (gb5 >> 2);
        const uint8_t glum = (uint8_t)((77u * gr + 150u * gg + 29u * gb) >> 8);
        const uint16_t r5 = (uint16_t)((glum >> 3) & 0x1F);
        const uint16_t g6 = (uint16_t)((glum >> 2) & 0x3F);
        const uint16_t b5 = (uint16_t)((glum >> 3) & 0x1F);
        effective_col_gap = (uint16_t)((r5 << 11) | (g6 << 5) | b5);
    }
#endif

#if LV_COLOR_DEPTH == 8
    const int32_t c0 = (int32_t)col_inactive;
    const int32_t dc = (int32_t)col_active - c0;
#else
    // Precalculate palette RGB565 deltas for fast linear interpolation in palette-tinted mode
    const int32_t r0 = (int32_t)((col_inactive >> 11) & 0x1F);
    const int32_t g0 = (int32_t)((col_inactive >> 5) & 0x3F);
    const int32_t b0 = (int32_t)(col_inactive & 0x1F);
    const int32_t dr = (int32_t)((col_active >> 11) & 0x1F) - r0;
    const int32_t dg = (int32_t)((col_active >> 5) & 0x3F) - g0;
    const int32_t db = (int32_t)(col_active & 0x1F) - b0;
#endif

    const int32_t first_cell_x = area->x1 / cell_size;
    const int32_t last_cell_x = area->x2 / cell_size;
    const int32_t num_cols = last_cell_x - first_cell_x + 1;
    if (num_cols <= 0 || num_cols > LCD_MAX_CELL_COLS) {
        return;
    }

    const int32_t first_cell_y = area->y1 / cell_size;
    const int32_t last_cell_y = area->y2 / cell_size;

    lcd_color_t cell_color[LCD_MAX_CELL_COLS];

    /* Process dirty rectangle in horizontal cell bands to guarantee zero in-place read corruption */
    for (int32_t cell_y = first_cell_y; cell_y <= last_cell_y; cell_y++) {
        const int32_t y_cell_start = cell_y * cell_size;
        const int32_t y_cell_end = y_cell_start + cell_size - 1;

        const int32_t band_y1 = (area->y1 > y_cell_start) ? area->y1 : y_cell_start;
        const int32_t band_y2 = (area->y2 < y_cell_end) ? area->y2 : y_cell_end;

        /* Calculate vertical active dot bounds inside this cell band */
        const int32_t dot_y_end = y_cell_start + cell_size - gap_size - 1;
        const int32_t sample_y_start = band_y1;
        const int32_t sample_y_end = (band_y2 < dot_y_end) ? band_y2 : dot_y_end;
        const bool has_dot_rows = (sample_y_start <= sample_y_end);

        /* Pass 1: Multi-pixel box sampling across cell active area to preserve fine strokes */
        for (int32_t c = 0; c < num_cols; c++) {
            if (!has_dot_rows) {
                cell_color[c] = col_inactive;
                continue;
            }

            const int32_t curr_cell_x = first_cell_x + c;
            const int32_t x_cell_start = curr_cell_x * cell_size;
            const int32_t x_dot_end = x_cell_start + cell_size - gap_size - 1;

            const int32_t sample_x_start = (x_cell_start > area->x1) ? x_cell_start : area->x1;
            const int32_t sample_x_end = (x_dot_end < area->x2) ? x_dot_end : area->x2;

            if (sample_x_start > sample_x_end) {
                cell_color[c] = col_inactive;
                continue;
            }

            if (!is_grayscale) {
                bool active = false;
                for (int32_t sy = sample_y_start; sy <= sample_y_end; sy++) {
                    const lcd_color_t *row = &pixels[(sy - area->y1) * width];
                    for (int32_t sx = sample_x_start; sx <= sample_x_end; sx++) {
                        const lcd_color_t px = row[sx - area->x1];

#if LV_COLOR_DEPTH == 8
                        const uint8_t lum = (uint8_t)px;
#else
                        /* Exact bit-replication integer luminance extraction (RGB565 -> 0..255 range) */
                        const uint8_t r5 = (px >> 11) & 0x1F;
                        const uint8_t g6 = (px >> 5) & 0x3F;
                        const uint8_t b5 = px & 0x1F;
                        const uint8_t r = (r5 << 3) | (r5 >> 2);
                        const uint8_t g = (g6 << 2) | (g6 >> 4);
                        const uint8_t b = (b5 << 3) | (b5 >> 2);

                        /* ITU-R BT.601 integer luminance: Y = (77*R + 150*G + 29*B) >> 8 */
                        const uint16_t lum = (uint16_t)((77u * r + 150u * g + 29u * b) >> 8);
#endif

                        if (state->dark_theme ? (lum >= threshold) : (lum < threshold)) {
                            active = true;
                            break;
                        }
                    }
                    if (active) {
                        break;
                    }
                }

                const bool cell_is_active = inverted ? (!active) : active;
                cell_color[c] = cell_is_active ? col_active : col_inactive;
            } else {
                uint32_t sum_lum = 0;
                uint16_t sample_count = 0;
                for (int32_t sy = sample_y_start; sy <= sample_y_end; sy++) {
                    const lcd_color_t *row = &pixels[(sy - area->y1) * width];
                    for (int32_t sx = sample_x_start; sx <= sample_x_end; sx++) {
                        const lcd_color_t px = row[sx - area->x1];
#if LV_COLOR_DEPTH == 8
                        sum_lum += (uint32_t)px;
#else
                        const uint8_t r5 = (px >> 11) & 0x1F;
                        const uint8_t g6 = (px >> 5) & 0x3F;
                        const uint8_t b5 = px & 0x1F;
                        const uint8_t r = (r5 << 3) | (r5 >> 2);
                        const uint8_t g = (g6 << 2) | (g6 >> 4);
                        const uint8_t b = (b5 << 3) | (b5 >> 2);
                        sum_lum += (uint32_t)((77u * r + 150u * g + 29u * b) >> 8);
#endif
                        sample_count++;
                    }
                }
                const uint8_t cell_lum = (sample_count > 0) ? (uint8_t)(sum_lum / sample_count) : 0;
                uint8_t intensity = state->dark_theme ? cell_lum : (uint8_t)(255 - cell_lum);
                if (inverted) {
                    intensity = 255 - intensity;
                }

                uint8_t q;
                if (is_grayscale_4bit) {
                    uint8_t level = (uint8_t)((intensity + 8) / 17);
                    if (level > 15) level = 15;
                    q = (uint8_t)(level * 17);
                } else {
                    q = intensity;
                }

#if LV_COLOR_DEPTH == 8
                if (state->shading_mode == LCD_SHADING_NEUTRAL_GRAY) {
                    cell_color[c] = (lcd_color_t)q;
                } else {
                    if (q == 0) {
                        cell_color[c] = col_inactive;
                    } else if (q == 255) {
                        cell_color[c] = col_active;
                    } else {
                        const int32_t nc = dc * (int32_t)q;
                        int32_t val = c0 + ((nc >= 0) ? (nc + 127) : (nc - 127)) / 255;
                        if (val < 0) val = 0; else if (val > 255) val = 255;
                        cell_color[c] = (lcd_color_t)val;
                    }
                }
#else
                if (state->shading_mode == LCD_SHADING_NEUTRAL_GRAY) {
                    const uint16_t r5 = (uint16_t)((q >> 3) & 0x1F);
                    const uint16_t g6 = (uint16_t)((q >> 2) & 0x3F);
                    const uint16_t b5 = (uint16_t)((q >> 3) & 0x1F);
                    cell_color[c] = (uint16_t)((r5 << 11) | (g6 << 5) | b5);
                } else {
                    if (q == 0) {
                        cell_color[c] = col_inactive;
                    } else if (q == 255) {
                        cell_color[c] = col_active;
                    } else {
                        const int32_t nr = dr * (int32_t)q;
                        const int32_t ng = dg * (int32_t)q;
                        const int32_t nb = db * (int32_t)q;
                        int32_t r = r0 + ((nr >= 0) ? (nr + 127) : (nr - 127)) / 255;
                        int32_t g = g0 + ((ng >= 0) ? (ng + 127) : (ng - 127)) / 255;
                        int32_t b = b0 + ((nb >= 0) ? (nb + 127) : (nb - 127)) / 255;
                        if (r < 0) r = 0; else if (r > 31) r = 31;
                        if (g < 0) g = 0; else if (g > 63) g = 63;
                        if (b < 0) b = 0; else if (b > 31) b = 31;
                        cell_color[c] = (uint16_t)(((uint16_t)r << 11) | ((uint16_t)g << 5) | (uint16_t)b);
                    }
                }
#endif
            }
        }

        /* Pass 2: Overwrite scanlines in this band with sub-pixel gaps and quantized dot colors */
        for (int32_t y_screen = band_y1; y_screen <= band_y2; y_screen++) {
            const bool is_gap_row = ((y_screen % cell_size) >= (cell_size - gap_size));
            const int32_t local_y = y_screen - area->y1;
            lcd_color_t *dst_row = &pixels[local_y * width];

            for (int32_t x_screen = area->x1; x_screen <= area->x2; x_screen++) {
                const bool is_gap_col = ((x_screen % cell_size) >= (cell_size - gap_size));
                const int32_t local_x = x_screen - area->x1;

                if (is_gap_row || is_gap_col) {
                    dst_row[local_x] = effective_col_gap;
                } else {
                    const int32_t col_idx = (x_screen / cell_size) - first_cell_x;
                    dst_row[local_x] = cell_color[col_idx];
                }
            }
        }
    }
}

void lcd_emulator_apply_filter(const lv_area_t *area, lcd_color_t *pixels, const lcd_emulator_cfg_t *cfg)
{
    if (!cfg) return;
    lcd_decorator_state_t temp_state = {
        .mode             = cfg->enabled ? LCD_RENDER_MODE_RETRO_MONOCHROME : LCD_RENDER_MODE_PASSTHROUGH,
        .shading_mode     = LCD_SHADING_PALETTE_TINTED,
        .dark_theme       = false,
        .cell_size        = cfg->cell_size,
        .gap_size         = cfg->gap_size,
        .threshold        = cfg->threshold,
        .palette          = cfg->palette,
        .custom_render_fn = NULL,
        .custom_user_ctx  = NULL,
    };
    lcd_emulator_apply_filter_ex(area, pixels, &temp_state, false);
}

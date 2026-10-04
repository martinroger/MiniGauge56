/**
 * @file lcd_emulator.c
 * @brief Implementation of retro dot-matrix monochrome LCD flush decorator and decimation filter.
 */

#include "lcd_emulator.h"

#if defined(__has_include) && __has_include("esp_log.h")
#include "esp_log.h"
static const char *TAG = "lcd_emulator";
#else
#define ESP_LOGI(tag, fmt, ...)
#define ESP_LOGW(tag, fmt, ...)
#define ESP_LOGE(tag, fmt, ...)
#endif

#define LCD_MAX_CELL_COLS 256

/* Preset Palette Definitions */
static const lcd_palette_t s_palettes[LCD_PRESET_COUNT] = {
    [LCD_PRESET_OLIVE] = {
        .color_bg       = LCD_RGB565(0x8A, 0x9A, 0x5B),
        .color_active   = LCD_RGB565(0x1B, 0x28, 0x12),
        .color_inactive = LCD_RGB565(0x7D, 0x8C, 0x50),
        .color_gap      = LCD_RGB565(0x6F, 0x7E, 0x45),
    },
    [LCD_PRESET_CASIO_GREY] = {
        .color_bg       = LCD_RGB565(0xA0, 0xB0, 0xA2),
        .color_active   = LCD_RGB565(0x14, 0x1D, 0x15),
        .color_inactive = LCD_RGB565(0x91, 0xA1, 0x93),
        .color_gap      = LCD_RGB565(0x7E, 0x8E, 0x80),
    },
    [LCD_PRESET_AMBER] = {
        .color_bg       = LCD_RGB565(0x18, 0x10, 0x02),
        .color_active   = LCD_RGB565(0xFF, 0xAA, 0x00),
        .color_inactive = LCD_RGB565(0x36, 0x21, 0x04),
        .color_gap      = LCD_RGB565(0x0D, 0x07, 0x00),
    },
    [LCD_PRESET_CYAN] = {
        .color_bg       = LCD_RGB565(0x08, 0x1D, 0x22),
        .color_active   = LCD_RGB565(0x00, 0xF0, 0xFF),
        .color_inactive = LCD_RGB565(0x12, 0x39, 0x42),
        .color_gap      = LCD_RGB565(0x04, 0x0F, 0x12),
    },
};

/* Active Emulator Configuration (Zero dynamic allocation) */
static lcd_emulator_cfg_t s_cfg = {
    .enabled    = true,
    .cell_size  = 4,
    .gap_size   = 1,
    .threshold  = 135,
    .palette    = {
        .color_bg       = LCD_RGB565(0x8A, 0x9A, 0x5B),
        .color_active   = LCD_RGB565(0x1B, 0x28, 0x12),
        .color_inactive = LCD_RGB565(0x7D, 0x8C, 0x50),
        .color_gap      = LCD_RGB565(0x6F, 0x7E, 0x45),
    },
};

#if defined(LVGL_H) || (defined(__has_include) && __has_include("lvgl.h"))
#if defined(__has_include) && __has_include("display/lv_display_private.h")
#include "display/lv_display_private.h"
#elif defined(__has_include) && __has_include("src/display/lv_display_private.h")
#include "src/display/lv_display_private.h"
#endif

static lv_display_t *s_target_disp = NULL;
static lv_display_flush_cb_t s_orig_flush_cb = NULL;

static void lcd_decorator_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    if (s_cfg.enabled && area && px_map) {
        lcd_emulator_apply_filter(area, (uint16_t *)px_map, &s_cfg);
    }

    if (s_orig_flush_cb) {
        s_orig_flush_cb(disp, area, px_map);
    } else {
        lv_display_flush_ready(disp);
    }
}
#endif

esp_err_t lcd_emulator_init(lv_display_t *disp)
{
#if defined(LVGL_H) || (defined(__has_include) && __has_include("lvgl.h"))
    if (!disp) {
        ESP_LOGE(TAG, "Invalid display handle");
        return ESP_ERR_INVALID_ARG;
    }

    s_target_disp = disp;
    s_orig_flush_cb = disp->flush_cb;
    lv_display_set_flush_cb(disp, lcd_decorator_flush_cb);
    ESP_LOGI(TAG, "LCD decorator attached to display %p (orig_flush_cb=%p)", disp, s_orig_flush_cb);
    return ESP_OK;
#else
    (void)disp;
    return ESP_OK;
#endif
}

void lcd_emulator_set_enabled(bool enabled)
{
    s_cfg.enabled = enabled;
    ESP_LOGI(TAG, "Retro LCD emulation %s", enabled ? "ENABLED" : "BYPASSED");
#if defined(LVGL_H) || (defined(__has_include) && __has_include("lvgl.h"))
    if (s_target_disp) {
        lv_obj_invalidate(lv_display_get_screen_active(s_target_disp));
    }
#endif
}

bool lcd_emulator_is_enabled(void)
{
    return s_cfg.enabled;
}

void lcd_emulator_toggle(void)
{
    lcd_emulator_set_enabled(!s_cfg.enabled);
}

void lcd_emulator_set_preset(lcd_preset_t preset)
{
    if (preset >= LCD_PRESET_COUNT) {
        return;
    }
    s_cfg.palette = s_palettes[preset];
#if defined(LVGL_H) || (defined(__has_include) && __has_include("lvgl.h"))
    if (s_target_disp && s_cfg.enabled) {
        lv_obj_invalidate(lv_display_get_screen_active(s_target_disp));
    }
#endif
}

void lcd_emulator_set_palette(const lcd_palette_t *palette)
{
    if (palette) {
        s_cfg.palette = *palette;
#if defined(LVGL_H) || (defined(__has_include) && __has_include("lvgl.h"))
        if (s_target_disp && s_cfg.enabled) {
            lv_obj_invalidate(lv_display_get_screen_active(s_target_disp));
        }
#endif
    }
}

void lcd_emulator_set_grid(uint8_t cell_size, uint8_t gap_size, uint8_t threshold)
{
    if (cell_size < 2) {
        cell_size = 2;
    }
    if (gap_size >= cell_size) {
        gap_size = cell_size - 1;
    }
    s_cfg.cell_size = cell_size;
    s_cfg.gap_size = gap_size;
    s_cfg.threshold = threshold;

#if defined(LVGL_H) || (defined(__has_include) && __has_include("lvgl.h"))
    if (s_target_disp && s_cfg.enabled) {
        lv_obj_invalidate(lv_display_get_screen_active(s_target_disp));
    }
#endif
}

const lcd_emulator_cfg_t* lcd_emulator_get_config(void)
{
    return &s_cfg;
}

void lcd_emulator_apply_filter(const lv_area_t *area, uint16_t *pixels, const lcd_emulator_cfg_t *cfg)
{
    if (!area || !pixels || !cfg) {
        return;
    }

    const int32_t width = area->x2 - area->x1 + 1;
    const int32_t height = area->y2 - area->y1 + 1;
    if (width <= 0 || height <= 0) {
        return;
    }

    const uint8_t cell_size = (cfg->cell_size >= 2) ? cfg->cell_size : 4;
    const uint8_t gap_size = (cfg->gap_size < cell_size) ? cfg->gap_size : 1;
    const uint8_t threshold = cfg->threshold;
    const uint16_t col_gap = cfg->palette.color_gap;
    const uint16_t col_active = cfg->palette.color_active;
    const uint16_t col_inactive = cfg->palette.color_inactive;

    const int32_t first_cell_x = area->x1 / cell_size;
    const int32_t last_cell_x = area->x2 / cell_size;
    const int32_t num_cols = last_cell_x - first_cell_x + 1;
    if (num_cols <= 0 || num_cols > LCD_MAX_CELL_COLS) {
        return;
    }

    const int32_t first_cell_y = area->y1 / cell_size;
    const int32_t last_cell_y = area->y2 / cell_size;

    uint8_t cell_active[LCD_MAX_CELL_COLS];

    /* Process dirty rectangle in horizontal cell bands to guarantee zero in-place read corruption */
    for (int32_t cell_y = first_cell_y; cell_y <= last_cell_y; cell_y++) {
        const int32_t y_cell_start = cell_y * cell_size;
        const int32_t y_cell_end = y_cell_start + cell_size - 1;

        const int32_t band_y1 = (area->y1 > y_cell_start) ? area->y1 : y_cell_start;
        const int32_t band_y2 = (area->y2 < y_cell_end) ? area->y2 : y_cell_end;

        /* Pick sample scanline inside this band */
        int32_t sample_screen_y = y_cell_start + (cell_size - gap_size) / 2;
        if (sample_screen_y < band_y1) {
            sample_screen_y = band_y1;
        } else if (sample_screen_y > band_y2) {
            sample_screen_y = band_y2;
        }

        const int32_t sample_local_y = sample_screen_y - area->y1;
        const uint16_t *sample_row = &pixels[sample_local_y * width];

        /* Pass 1: Sample un-modified source pixels for every cell column in this band */
        for (int32_t c = 0; c < num_cols; c++) {
            const int32_t curr_cell_x = first_cell_x + c;
            const int32_t x_cell_start = curr_cell_x * cell_size;
            int32_t sample_screen_x = x_cell_start + (cell_size - gap_size) / 2;
            if (sample_screen_x < area->x1) {
                sample_screen_x = area->x1;
            } else if (sample_screen_x > area->x2) {
                sample_screen_x = area->x2;
            }

            const int32_t sample_local_x = sample_screen_x - area->x1;
            const uint16_t px = sample_row[sample_local_x];

            /* Fast integer luminance extraction (RGB565 -> 0..255 range) */
            const uint8_t r = ((px >> 11) & 0x1F) << 3;
            const uint8_t g = ((px >> 5) & 0x3F) << 2;
            const uint8_t b = (px & 0x1F) << 3;

            /* Fast approximation: Y = (77*R + 150*G + 29*B) >> 8 */
            const uint16_t lum = (uint16_t)((77u * r + 150u * g + 29u * b) >> 8);
            cell_active[c] = (lum < threshold) ? 1u : 0u;
        }

        /* Pass 2: Overwrite scanlines in this band with sub-pixel gaps and quantized dot colors */
        for (int32_t y_screen = band_y1; y_screen <= band_y2; y_screen++) {
            const bool is_gap_row = ((y_screen % cell_size) >= (cell_size - gap_size));
            const int32_t local_y = y_screen - area->y1;
            uint16_t *dst_row = &pixels[local_y * width];

            for (int32_t x_screen = area->x1; x_screen <= area->x2; x_screen++) {
                const bool is_gap_col = ((x_screen % cell_size) >= (cell_size - gap_size));
                const int32_t local_x = x_screen - area->x1;

                if (is_gap_row || is_gap_col) {
                    dst_row[local_x] = col_gap;
                } else {
                    const int32_t col_idx = (x_screen / cell_size) - first_cell_x;
                    dst_row[local_x] = cell_active[col_idx] ? col_active : col_inactive;
                }
            }
        }
    }
}

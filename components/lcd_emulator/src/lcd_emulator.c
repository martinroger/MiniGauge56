/**
 * @file lcd_emulator.c
 * @brief Implementation of retro dot-matrix monochrome LCD flush decorator and decimation filter.
 */

#if defined(__has_include) && __has_include("sdkconfig.h")
#include "sdkconfig.h"
#endif

#include "lcd_emulator.h"

#include <stdlib.h>
#include <string.h>
#include <stdint.h>

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
static size_t s_rgb565_buf_req_pixels = 0;
#if defined(CONFIG_LCD_EMULATOR_STAGING_INTERNAL) && defined(ESP_PLATFORM)
#define LCD_STAGING_INTERNAL 1
/* Internal DMA-capable staging tile (sized to the draw buffer); s_rgb565_buf stays the lazy PSRAM fallback. */
static uint16_t *s_stage_buf = NULL;
static size_t s_stage_buf_pixels = 0;
#endif
#endif

static uint8_t s_lum_lut[256];
static uint16_t s_passthrough_lut[256];
static bool s_8bit_is_rgb232 = false;
static bool s_luts_inited = false;
static lcd_render_mode_t s_last_emulation_mode = LCD_KCONFIG_RENDER_MODE;

static void recompute_luts(void)
{
    for (int i = 0; i < 256; i++) {
        uint8_t r8, g8, b8;
        if (s_8bit_is_rgb232) {
            uint8_t r = (uint8_t)((i >> 5) & 0x03);
            uint8_t g = (uint8_t)((i >> 2) & 0x07);
            uint8_t b = (uint8_t)(i & 0x03);
            r8 = (uint8_t)((r * 255) / 3);
            g8 = (uint8_t)((g * 255) / 7);
            b8 = (uint8_t)((b * 255) / 3);
            s_lum_lut[i] = (uint8_t)((77u * r8 + 150u * g8 + 29u * b8) >> 8);
        } else {
            r8 = (uint8_t)i;
            g8 = (uint8_t)i;
            b8 = (uint8_t)i;
            s_lum_lut[i] = (uint8_t)i;
        }
        uint16_t rgb = LCD_RGB565(r8, g8, b8);
        s_passthrough_lut[i] = LCD_RGB565_SWAP(rgb);
    }
    s_luts_inited = true;
}

static inline void ensure_luts_inited(void)
{
    if (!s_luts_inited) {
        recompute_luts();
    }
}

/* Preset Palette Definitions */
static const lcd_palette_t s_palettes[LCD_PRESET_COUNT] = {
    [LCD_PRESET_OLIVE] = {
        .color_bg       = LCD_COLOR_MAKE(0x8A, 0x9A, 0x5B),
        .color_active   = LCD_COLOR_MAKE(0x1B, 0x28, 0x12),
        .color_inactive = LCD_COLOR_MAKE(0x7D, 0x8C, 0x50),
        .color_gap      = LCD_COLOR_MAKE(0x6F, 0x7E, 0x45),
        .color_bg_rgb565       = LCD_RGB565(0x8A, 0x9A, 0x5B),
        .color_active_rgb565   = LCD_RGB565(0x1B, 0x28, 0x12),
        .color_inactive_rgb565 = LCD_RGB565(0x7D, 0x8C, 0x50),
        .color_gap_rgb565      = LCD_RGB565(0x6F, 0x7E, 0x45),
    },
    [LCD_PRESET_CASIO_GREY] = {
        .color_bg       = LCD_COLOR_MAKE(0xA0, 0xB0, 0xA2),
        .color_active   = LCD_COLOR_MAKE(0x14, 0x1D, 0x15),
        .color_inactive = LCD_COLOR_MAKE(0x91, 0xA1, 0x93),
        .color_gap      = LCD_COLOR_MAKE(0x7E, 0x8E, 0x80),
        .color_bg_rgb565       = LCD_RGB565(0xA0, 0xB0, 0xA2),
        .color_active_rgb565   = LCD_RGB565(0x14, 0x1D, 0x15),
        .color_inactive_rgb565 = LCD_RGB565(0x91, 0xA1, 0x93),
        .color_gap_rgb565      = LCD_RGB565(0x7E, 0x8E, 0x80),
    },
    [LCD_PRESET_AMBER] = {
        .color_bg       = LCD_COLOR_MAKE(0x18, 0x10, 0x02),
        .color_active   = LCD_COLOR_MAKE(0xFF, 0xAA, 0x00),
        .color_inactive = LCD_COLOR_MAKE(0x36, 0x21, 0x04),
        .color_gap      = LCD_COLOR_MAKE(0x0D, 0x07, 0x00),
        .color_bg_rgb565       = LCD_RGB565(0x18, 0x10, 0x02),
        .color_active_rgb565   = LCD_RGB565(0xFF, 0xAA, 0x00),
        .color_inactive_rgb565 = LCD_RGB565(0x36, 0x21, 0x04),
        .color_gap_rgb565      = LCD_RGB565(0x0D, 0x07, 0x00),
    },
    [LCD_PRESET_CYAN] = {
        .color_bg       = LCD_COLOR_MAKE(0x08, 0x1D, 0x22),
        .color_active   = LCD_COLOR_MAKE(0x00, 0xF0, 0xFF),
        .color_inactive = LCD_COLOR_MAKE(0x12, 0x39, 0x42),
        .color_gap      = LCD_COLOR_MAKE(0x04, 0x0F, 0x12),
        .color_bg_rgb565       = LCD_RGB565(0x08, 0x1D, 0x22),
        .color_active_rgb565   = LCD_RGB565(0x00, 0xF0, 0xFF),
        .color_inactive_rgb565 = LCD_RGB565(0x12, 0x39, 0x42),
        .color_gap_rgb565      = LCD_RGB565(0x04, 0x0F, 0x12),
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
        .color_bg              = LCD_COLOR_MAKE(0x8A, 0x9A, 0x5B),
        .color_active          = LCD_COLOR_MAKE(0x1B, 0x28, 0x12),
        .color_inactive        = LCD_COLOR_MAKE(0x7D, 0x8C, 0x50),
        .color_gap             = LCD_COLOR_MAKE(0x6F, 0x7E, 0x45),
        .color_bg_rgb565       = LCD_RGB565(0x8A, 0x9A, 0x5B),
        .color_active_rgb565   = LCD_RGB565(0x1B, 0x28, 0x12),
        .color_inactive_rgb565 = LCD_RGB565(0x7D, 0x8C, 0x50),
        .color_gap_rgb565      = LCD_RGB565(0x6F, 0x7E, 0x45),
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
        .color_bg              = LCD_COLOR_MAKE(0x8A, 0x9A, 0x5B),
        .color_active          = LCD_COLOR_MAKE(0x1B, 0x28, 0x12),
        .color_inactive        = LCD_COLOR_MAKE(0x7D, 0x8C, 0x50),
        .color_gap             = LCD_COLOR_MAKE(0x6F, 0x7E, 0x45),
        .color_bg_rgb565       = LCD_RGB565(0x8A, 0x9A, 0x5B),
        .color_active_rgb565   = LCD_RGB565(0x1B, 0x28, 0x12),
        .color_inactive_rgb565 = LCD_RGB565(0x7D, 0x8C, 0x50),
        .color_gap_rgb565      = LCD_RGB565(0x6F, 0x7E, 0x45),
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

#if defined(CONFIG_LCD_EMULATOR_PROFILE) && defined(ESP_PLATFORM)
#define LCD_PROFILE 1
#include "esp_cpu.h"
#include "esp_timer.h"
#include "esp_clk_tree.h"
#include "freertos/task.h"

typedef struct {
    uint64_t tiles;
    uint64_t pixels;
    uint32_t max_tile_pixels;
    uint64_t frames;
    uint64_t decorate_cyc;
    uint64_t orig_cyc;
    uint64_t finish_us;
    uint64_t finish_cnt;
    uint64_t bypass_tiles;
    uint64_t migrated_tiles; /* tiles whose cycle delta was discarded (LVGL task changed core) */
} lcd_prof_t;

static lcd_prof_t s_prof;
static portMUX_TYPE s_prof_mux = portMUX_INITIALIZER_UNLOCKED;
static volatile int64_t s_prof_flush_start_us;
static TaskHandle_t s_prof_task = NULL;
static esp_timer_handle_t s_prof_timer = NULL;
static int64_t s_prof_last_us = 0;

static inline uint32_t prof_cyc(void)
{
    return (uint32_t)esp_cpu_get_cycle_count();
}

static void lcd_prof_flush_finish_cb(lv_event_t *e)
{
    (void)e;
    /* May fire from an ISR on either core: use the shared esp_timer clock, not CCOUNT. */
    const int64_t dt = esp_timer_get_time() - s_prof_flush_start_us;
    portENTER_CRITICAL(&s_prof_mux);
    s_prof.finish_us += (uint64_t)(dt > 0 ? dt : 0);
    s_prof.finish_cnt++;
    portEXIT_CRITICAL(&s_prof_mux);
}

static void lcd_prof_report_cb(void *arg)
{
    (void)arg;
    lcd_prof_t p;
    portENTER_CRITICAL(&s_prof_mux);
    p = s_prof;
    memset(&s_prof, 0, sizeof(s_prof));
    portEXIT_CRITICAL(&s_prof_mux);

    const int64_t now = esp_timer_get_time();
    const double secs = (s_prof_last_us > 0) ? (double)(now - s_prof_last_us) / 1e6 : 1.0;
    s_prof_last_us = now;

    uint32_t cpu_hz = 240000000u;
    esp_clk_tree_src_get_freq_hz(SOC_MOD_CLK_CPU, ESP_CLK_TREE_SRC_FREQ_PRECISION_CACHED, &cpu_hz);
    const double us_per_cyc = 1e6 / (double)cpu_hz;

    const double dec_us = (double)p.decorate_cyc * us_per_cyc;
    const double orig_us = (double)p.orig_cyc * us_per_cyc;
    const double fin_us = (double)p.finish_us;
    const double tiles = (double)p.tiles;
    const double valid = (double)(p.tiles - p.migrated_tiles);
    const double mpix = (double)p.pixels / 1e6 * (tiles > 0 ? valid / tiles : 0.0);

    UBaseType_t hwm = s_prof_task ? uxTaskGetStackHighWaterMark(s_prof_task) : 0;
    ESP_LOGI(TAG, "PROF %.2fs tiles/s=%.1f px/s=%.0f avg_px/tile=%.0f max_px/tile=%u fps=%.1f bypass=%u migrated=%u | "
             "decorate us/tile=%.1f us/Mpx=%.0f | orig_flush us/tile=%.1f | finish_latency us/tile=%.1f | "
             "lvgl_stack_hwm=%u B (%s) heap_int_free=%u largest=%u",
             secs, tiles / secs, (double)p.pixels / secs,
             tiles > 0 ? (double)p.pixels / tiles : 0.0, (unsigned)p.max_tile_pixels,
             (double)p.frames / secs, (unsigned)p.bypass_tiles, (unsigned)p.migrated_tiles,
             valid > 0 ? dec_us / valid : 0.0, mpix > 0 ? dec_us / mpix : 0.0,
             valid > 0 ? orig_us / valid : 0.0,
             p.finish_cnt > 0 ? fin_us / (double)p.finish_cnt : 0.0,
             (unsigned)(hwm * sizeof(StackType_t)), s_prof_task ? pcTaskGetName(s_prof_task) : "?",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
}

static void lcd_prof_start(lv_display_t *disp)
{
    lv_display_add_event_cb(disp, lcd_prof_flush_finish_cb, LV_EVENT_FLUSH_FINISH, NULL);
    if (!s_prof_timer) {
        const esp_timer_create_args_t args = { .callback = lcd_prof_report_cb, .name = "lcd_prof" };
        if (esp_timer_create(&args, &s_prof_timer) == ESP_OK) {
            esp_timer_start_periodic(s_prof_timer, 1000000);
        }
    }
}

/* Called right before the original flush callback; t0 is the cycle stamp at decorator entry. */
static inline void prof_call_orig(lv_display_t *disp, const lv_area_t *area, uint8_t *buf,
                                  lv_display_flush_cb_t orig, uint32_t t0, bool decorated)
{
    const uint32_t t1 = prof_cyc();
    s_prof_flush_start_us = esp_timer_get_time();
    s_prof_task = xTaskGetCurrentTaskHandle();
    if (orig) {
        orig(disp, area, buf);
    } else {
        lv_display_flush_ready(disp);
    }
    const uint32_t t2 = prof_cyc();
    const uint32_t px = (uint32_t)((area->x2 - area->x1 + 1) * (area->y2 - area->y1 + 1));
    const bool last = lv_display_flush_is_last(disp);
    portENTER_CRITICAL(&s_prof_mux);
    s_prof.tiles++;
    s_prof.pixels += px;
    if (px > s_prof.max_tile_pixels) {
        s_prof.max_tile_pixels = px;
    }
    if (last) {
        s_prof.frames++;
    }
    /* CCOUNT is per-core: a negative delta (>= 2^31 unsigned) means the task migrated; drop it. */
    if ((t1 - t0) >= 0x80000000u || (t2 - t1) >= 0x80000000u) {
        s_prof.migrated_tiles++;
    } else {
        if (decorated) {
            s_prof.decorate_cyc += (t1 - t0);
        }
        s_prof.orig_cyc += (t2 - t1);
    }
    if (!decorated) {
        s_prof.bypass_tiles++;
    }
    portEXIT_CRITICAL(&s_prof_mux);
}
#define PROF_T0()                      const uint32_t prof_t0 = prof_cyc()
#define CALL_ORIG(d, a, b, dec)        prof_call_orig((d), (a), (b), s_orig_flush_cb, prof_t0, (dec))
#else
#define PROF_T0()                      ((void)0)
#define CALL_ORIG(d, a, b, dec)        do { if (s_orig_flush_cb) { s_orig_flush_cb((d), (a), (b)); } else { lv_display_flush_ready(d); } } while (0)
#endif

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
    PROF_T0();
    lcd_decorator_state_t snap;
    state_lock();
    snap = s_state;
    state_unlock();

    if (area && px_map) {
#if LV_COLOR_DEPTH == 8
#if defined(CONFIG_LCD_EMULATOR_EXPAND_TO_RGB565) || !defined(ESP_PLATFORM)
        const int32_t width = area->x2 - area->x1 + 1;
        const int32_t height = area->y2 - area->y1 + 1;
        const size_t area_pixels = (size_t)(width * height);
        uint16_t *out_buf = s_rgb565_buf;
        size_t out_pixels = s_rgb565_buf_pixels;
#ifdef LCD_STAGING_INTERNAL
        if (s_stage_buf && area_pixels <= s_stage_buf_pixels) {
            out_buf = s_stage_buf;
            out_pixels = s_stage_buf_pixels;
        } else if (s_stage_buf && !s_rgb565_buf) {
            /* Oversize tile: lazily allocate the full-frame PSRAM fallback */
            s_rgb565_buf = (uint16_t *)heap_caps_malloc(s_rgb565_buf_req_pixels * sizeof(uint16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
            if (s_rgb565_buf) {
                s_rgb565_buf_pixels = s_rgb565_buf_req_pixels;
                ESP_LOGW(TAG, "Staging tile too small for %zu px, PSRAM fallback allocated", area_pixels);
            }
            out_buf = s_rgb565_buf;
            out_pixels = s_rgb565_buf_pixels;
        }
#endif
        if (out_buf && area_pixels <= out_pixels) {
            if (snap.mode == LCD_RENDER_MODE_PASSTHROUGH) {
                // High-speed LUT expansion for passthrough mode (with wire byte-swap)
                const uint8_t *src8 = (const uint8_t *)px_map;
                for (size_t i = 0; i < area_pixels; i++) {
                    out_buf[i] = s_passthrough_lut[src8[i]];
                }
            } else if (snap.mode == LCD_RENDER_MODE_CUSTOM) {
                if (snap.custom_render_fn) {
                    snap.custom_render_fn(area, (lcd_color_t *)px_map, snap.custom_user_ctx);
                }
                const uint8_t *src8 = (const uint8_t *)px_map;
                for (size_t i = 0; i < area_pixels; i++) {
                    out_buf[i] = s_passthrough_lut[src8[i]];
                }
            } else {
                // Direct single-pass stream into 16-bit RGB565 buffer (wire-swapped, full palette colors)
                const bool inv = (snap.mode == LCD_RENDER_MODE_RETRO_INVERTED);
                lcd_emulator_apply_filter_8to16(area, (const uint8_t *)px_map, out_buf, &snap, inv, true);
            }

            CALL_ORIG(disp, area, (uint8_t *)out_buf, true);
            return;
        }
#endif
#else
        // 16-bit native LVGL depth: direct in-place filtering on px_map
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
#endif
    }

#if LV_COLOR_DEPTH == 8
    CALL_ORIG(disp, area, px_map, false);
#else
    CALL_ORIG(disp, area, px_map, true);
#endif
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
    recompute_luts();
    s_state.mode             = LCD_KCONFIG_RENDER_MODE;
    s_last_emulation_mode    = (LCD_KCONFIG_RENDER_MODE != LCD_RENDER_MODE_PASSTHROUGH) ? LCD_KCONFIG_RENDER_MODE : LCD_RENDER_MODE_RETRO_MONOCHROME;
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
    s_rgb565_buf_req_pixels = req_pixels;
#ifdef LCD_STAGING_INTERNAL
    if (!s_stage_buf && disp) {
        size_t tile_px = req_pixels;
        if (disp->buf_1 && disp->buf_1->data_size > 0) {
            tile_px = disp->buf_1->data_size / lv_color_format_get_size(lv_display_get_color_format(disp));
            if (tile_px > req_pixels) {
                tile_px = req_pixels;
            }
        }
        s_stage_buf = (uint16_t *)heap_caps_malloc(tile_px * sizeof(uint16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA | MALLOC_CAP_8BIT);
        if (s_stage_buf) {
            s_stage_buf_pixels = tile_px;
            ESP_LOGI(TAG, "Internal staging tile: %zu px (%zu B), draw buf %zu px", tile_px, tile_px * sizeof(uint16_t), tile_px);
        } else {
            ESP_LOGW(TAG, "Internal staging alloc of %zu B failed, using PSRAM buffer", tile_px * sizeof(uint16_t));
        }
    }
    if (s_stage_buf) {
        goto skip_psram_alloc; /* PSRAM fallback is allocated lazily on first oversize tile */
    }
#endif
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
#ifdef LCD_STAGING_INTERNAL
skip_psram_alloc:;
#endif
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
#ifdef LCD_PROFILE
    lcd_prof_start(disp);
#endif
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
    if (mode != LCD_RENDER_MODE_PASSTHROUGH) {
        s_last_emulation_mode = mode;
    }
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
    if (enabled) {
        lcd_render_mode_t target = s_last_emulation_mode;
        if (target == LCD_RENDER_MODE_PASSTHROUGH) {
            target = LCD_RENDER_MODE_RETRO_MONOCHROME;
        }
        lcd_emulator_set_render_mode(target);
    } else {
        lcd_emulator_set_render_mode(LCD_RENDER_MODE_PASSTHROUGH);
    }
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
    if (s_state.palette.color_bg_rgb565 == 0 && s_state.palette.color_active_rgb565 == 0) {
#if LV_COLOR_DEPTH == 8
        uint8_t bg = s_state.palette.color_bg;
        uint8_t act = s_state.palette.color_active;
        uint8_t inact = s_state.palette.color_inactive;
        uint8_t gap = s_state.palette.color_gap;
        s_state.palette.color_bg_rgb565 = LCD_RGB565(bg, bg, bg);
        s_state.palette.color_active_rgb565 = LCD_RGB565(act, act, act);
        s_state.palette.color_inactive_rgb565 = LCD_RGB565(inact, inact, inact);
        s_state.palette.color_gap_rgb565 = LCD_RGB565(gap, gap, gap);
#else
        s_state.palette.color_bg_rgb565 = s_state.palette.color_bg;
        s_state.palette.color_active_rgb565 = s_state.palette.color_active;
        s_state.palette.color_inactive_rgb565 = s_state.palette.color_inactive;
        s_state.palette.color_gap_rgb565 = s_state.palette.color_gap;
#endif
    }
    s_legacy_cfg.palette = s_state.palette;
    state_unlock();

    trigger_display_invalidation();
}

void lcd_emulator_set_8bit_input_rgb232(bool is_rgb232)
{
    state_lock();
    s_8bit_is_rgb232 = is_rgb232;
    recompute_luts();
    state_unlock();

    trigger_display_invalidation();
}

bool lcd_emulator_is_8bit_input_rgb232(void)
{
    state_lock();
    bool res = s_8bit_is_rgb232;
    state_unlock();
    return res;
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

/* ------------------------------------------------------------------------------------------
 * 8-bit -> RGB565 streaming decimator (hot path)
 *
 * Output is bit-exact with the straightforward per-pixel formulation (a cell is a cell_size x
 * cell_size block whose leading (cell_size - gap_size) columns/rows are the dot and whose trailing
 * gap_size columns/rows are the gap). Differences are purely in how the work is organised:
 *   - one output row template is built per cell band and replicated with memcpy for the remaining
 *     dot rows; gap rows are a constant fill (no per-pixel modulo/division),
 *   - the final RGB565 of every possible cell luminance is looked up from a 256-entry ramp built
 *     with the same arithmetic (when the tile has enough cells to amortise building it),
 *   - the average luminance divides by a reciprocal multiply when exact (verified for all sums),
 *   - the identity luminance table is skipped for L8 input.
 * ---------------------------------------------------------------------------------------- */

#if defined(__GNUC__)
#define LCD_FORCE_INLINE static inline __attribute__((always_inline))
typedef uint32_t __attribute__((may_alias)) lcd_u32_alias_t;
#else
#define LCD_FORCE_INLINE static inline
typedef uint32_t lcd_u32_alias_t;
#endif

#define LCD_RECIP_SHIFT 24
#define LCD_RECIP_MAX_CNT 255u
#define LCD_RAMP_MIN_CELLS 384

typedef struct {
    bool neutral;
    bool gray4;
    bool dark;
    bool inverted;
    bool wire_swap;
    uint16_t col_active;    /* raw (unswapped) */
    uint16_t col_inactive;  /* raw (unswapped) */
    int32_t r0, g0, b0, dr, dg, db;
} lcd_shade_t;

/** Final (optionally wire-swapped) RGB565 for a cell of average luminance @p lum. */
LCD_FORCE_INLINE uint16_t lcd_lum_to_color(const lcd_shade_t *sh, uint8_t lum)
{
    uint8_t intensity = sh->dark ? lum : (uint8_t)(255 - lum);
    if (sh->inverted) {
        intensity = (uint8_t)(255 - intensity);
    }

    uint8_t q;
    if (sh->gray4) {
        uint8_t level = (uint8_t)((intensity + 8) / 17);
        if (level > 15) level = 15;
        q = (uint8_t)(level * 17);
    } else {
        q = intensity;
    }

    uint16_t raw;
    if (sh->neutral) {
        raw = LCD_RGB565(q, q, q);
    } else if (q == 0) {
        raw = sh->col_inactive;
    } else if (q == 255) {
        raw = sh->col_active;
    } else {
        const int32_t nr = sh->dr * (int32_t)q;
        const int32_t ng = sh->dg * (int32_t)q;
        const int32_t nb = sh->db * (int32_t)q;
        int32_t r = sh->r0 + ((nr >= 0) ? (nr + 127) : (nr - 127)) / 255;
        int32_t g = sh->g0 + ((ng >= 0) ? (ng + 127) : (ng - 127)) / 255;
        int32_t b = sh->b0 + ((nb >= 0) ? (nb + 127) : (nb - 127)) / 255;
        if (r < 0) r = 0; else if (r > 31) r = 31;
        if (g < 0) g = 0; else if (g > 63) g = 63;
        if (b < 0) b = 0; else if (b > 31) b = 31;
        raw = (uint16_t)(((uint16_t)r << 11) | ((uint16_t)g << 5) | (uint16_t)b);
    }
    return sh->wire_swap ? LCD_RGB565_SWAP(raw) : raw;
}

LCD_FORCE_INLINE void lcd_fill16(uint16_t *p, uint16_t v, int32_t n)
{
    if (n >= 4) {
        if (((uintptr_t)p) & 2u) {
            *p++ = v;
            n--;
        }
        const uint32_t v2 = ((uint32_t)v << 16) | v;
        lcd_u32_alias_t *w = (lcd_u32_alias_t *)p;
        for (int32_t k = n >> 1; k > 0; k--) {
            *w++ = v2;
        }
        p = (uint16_t *)w;
        n &= 1;
    }
    while (n-- > 0) {
        *p++ = v;
    }
}

/** Reciprocal such that floor(sum * recip >> 24) == floor(sum / cnt) for all sum <= 255 * cnt. */
LCD_FORCE_INLINE uint32_t lcd_recip(uint32_t cnt)
{
    return (cnt <= LCD_RECIP_MAX_CNT) ? (((1u << LCD_RECIP_SHIFT) + cnt - 1u) / cnt) : 0u;
}

LCD_FORCE_INLINE uint32_t lcd_div_by_count(uint32_t sum, uint32_t cnt, uint32_t recip)
{
    return recip ? ((sum * recip) >> LCD_RECIP_SHIFT) : (sum / cnt);
}

/**
 * Core decimator. @p gray and @p lut are compile-time constants at every call site so the unused
 * variants fold away (lut == NULL means the 8-bit input already is luminance).
 */
LCD_FORCE_INLINE void lcd_decimate_core(const lv_area_t *area, const uint8_t *src, uint16_t *dst,
                                        const lcd_shade_t *sh, const uint16_t *ramp,
                                        uint8_t threshold, uint16_t col_gap,
                                        uint16_t mono_active, uint16_t mono_inactive,
                                        int32_t cs, int32_t gs, bool gray, const uint8_t *lut)
{
    const int32_t width = area->x2 - area->x1 + 1;
    const int32_t dotw = cs - gs;
    const int32_t first_cell_x = area->x1 / cs;
    const int32_t num_cols = area->x2 / cs - first_cell_x + 1;
    const int32_t first_cell_y = area->y1 / cs;
    const int32_t last_cell_y = area->y2 / cs;
    const size_t row_bytes = (size_t)width * sizeof(uint16_t);

    uint16_t cell_color[LCD_MAX_CELL_COLS];
    uint8_t cell_nx[LCD_MAX_CELL_COLS];

    for (int32_t cell_y = first_cell_y; cell_y <= last_cell_y; cell_y++) {
        const int32_t y_cell_start = cell_y * cs;
        const int32_t band_y1 = (area->y1 > y_cell_start) ? area->y1 : y_cell_start;
        const int32_t y_cell_end = y_cell_start + cs - 1;
        const int32_t band_y2 = (area->y2 < y_cell_end) ? area->y2 : y_cell_end;
        const int32_t dot_y_end = y_cell_start + dotw - 1;
        const int32_t sy0 = band_y1;
        const int32_t sy1 = (band_y2 < dot_y_end) ? band_y2 : dot_y_end;

        if (sy0 > sy1) {
            /* Band lies entirely in the gap rows. */
            for (int32_t y = band_y1; y <= band_y2; y++) {
                lcd_fill16(dst + (size_t)(y - area->y1) * width, col_gap, width);
            }
            continue;
        }

        const int32_t ny = sy1 - sy0 + 1;
        const uint8_t *band_src = src + (size_t)(sy0 - area->y1) * width;
        const uint32_t full_recip = gray ? lcd_recip((uint32_t)(dotw * ny)) : 0u;

        for (int32_t c = 0; c < num_cols; c++) {
            const int32_t x_cell_start = (first_cell_x + c) * cs;
            const int32_t sx_start = (x_cell_start > area->x1) ? x_cell_start : area->x1;
            const int32_t x_dot_end = x_cell_start + dotw - 1;
            const int32_t sx_end = (x_dot_end < area->x2) ? x_dot_end : area->x2;
            if (sx_start > sx_end) {
                cell_nx[c] = 0;
                continue;
            }
            const int32_t nx = sx_end - sx_start + 1;
            cell_nx[c] = (uint8_t)nx;
            const uint8_t *cell_src = band_src + (sx_start - area->x1);

            if (gray) {
                uint32_t sum = 0;
                for (int32_t y = 0; y < ny; y++) {
                    const uint8_t *row = cell_src + (size_t)y * width;
                    for (int32_t x = 0; x < nx; x++) {
                        sum += lut ? lut[row[x]] : row[x];
                    }
                }
                const uint32_t cnt = (uint32_t)(nx * ny);
                const uint32_t recip = (nx == dotw) ? full_recip : lcd_recip(cnt);
                const uint8_t lum = (uint8_t)lcd_div_by_count(sum, cnt, recip);
                cell_color[c] = ramp ? ramp[lum] : lcd_lum_to_color(sh, lum);
            } else {
                uint8_t ext = sh->dark ? 0 : 255;
                for (int32_t y = 0; y < ny; y++) {
                    const uint8_t *row = cell_src + (size_t)y * width;
                    for (int32_t x = 0; x < nx; x++) {
                        const uint8_t v = lut ? lut[row[x]] : row[x];
                        if (sh->dark) {
                            ext = (v > ext) ? v : ext;
                        } else {
                            ext = (v < ext) ? v : ext;
                        }
                    }
                }
                const bool active = sh->dark ? (ext >= threshold) : (ext < threshold);
                const bool cell_is_active = sh->inverted ? !active : active;
                cell_color[c] = cell_is_active ? mono_active : mono_inactive;
            }
        }

        /* Build the first dot row of the band, then replicate it for the other dot rows. */
        uint16_t *row0 = dst + (size_t)(sy0 - area->y1) * width;
        uint16_t *p = row0;
        for (int32_t c = 0; c < num_cols; c++) {
            const int32_t nx = cell_nx[c];
            int32_t gl;
            if (c == 0 || c == num_cols - 1) {
                const int32_t x_cell_start = (first_cell_x + c) * cs;
                const int32_t lo = (x_cell_start > area->x1) ? x_cell_start : area->x1;
                const int32_t x_cell_end = x_cell_start + cs - 1;
                const int32_t hi = (x_cell_end < area->x2) ? x_cell_end : area->x2;
                gl = (hi - lo + 1) - nx;
            } else {
                gl = gs;
            }
            const uint16_t color = cell_color[c];
            for (int32_t k = 0; k < nx; k++) {
                *p++ = color;
            }
            for (int32_t k = 0; k < gl; k++) {
                *p++ = col_gap;
            }
        }
        for (int32_t y = sy0 + 1; y <= sy1; y++) {
            memcpy(dst + (size_t)(y - area->y1) * width, row0, row_bytes);
        }
        for (int32_t y = sy1 + 1; y <= band_y2; y++) {
            lcd_fill16(dst + (size_t)(y - area->y1) * width, col_gap, width);
        }
    }
}

void lcd_emulator_apply_filter_8to16(const lv_area_t *area,
                                     const uint8_t *src_pixels,
                                     uint16_t *dst_rgb565,
                                     const lcd_decorator_state_t *state,
                                     bool inverted,
                                     bool wire_swap)
{
    if (!area || !src_pixels || !dst_rgb565 || !state) {
        return;
    }

    const int32_t width = area->x2 - area->x1 + 1;
    const int32_t height = area->y2 - area->y1 + 1;
    if (width <= 0 || height <= 0) {
        return;
    }

    ensure_luts_inited();

    const uint8_t cell_size = (state->cell_size >= 2) ? state->cell_size : 4;
    const uint8_t gap_size = (state->gap_size < cell_size) ? state->gap_size : 1;

    const uint16_t col_gap = state->palette.color_gap_rgb565 ? state->palette.color_gap_rgb565 : (uint16_t)state->palette.color_gap;
    const uint16_t col_active = state->palette.color_active_rgb565 ? state->palette.color_active_rgb565 : (uint16_t)state->palette.color_active;
    const uint16_t col_inactive = state->palette.color_inactive_rgb565 ? state->palette.color_inactive_rgb565 : (uint16_t)state->palette.color_inactive;

    const bool is_grayscale_4bit = (state->mode == LCD_RENDER_MODE_GRAYSCALE_4BIT);
    const bool is_grayscale_8bit = (state->mode == LCD_RENDER_MODE_GRAYSCALE_8BIT);
    const bool is_grayscale = is_grayscale_4bit || is_grayscale_8bit;

    uint16_t effective_col_gap = col_gap;
    if (state->shading_mode == LCD_SHADING_NEUTRAL_GRAY && is_grayscale) {
        const uint8_t gr5 = (uint8_t)((col_gap >> 11) & 0x1F);
        const uint8_t gg6 = (uint8_t)((col_gap >> 5) & 0x3F);
        const uint8_t gb5 = (uint8_t)(col_gap & 0x1F);
        const uint8_t gr = (uint8_t)((gr5 << 3) | (gr5 >> 2));
        const uint8_t gg = (uint8_t)((gg6 << 2) | (gg6 >> 4));
        const uint8_t gb = (uint8_t)((gb5 << 3) | (gb5 >> 2));
        const uint8_t glum = (uint8_t)((77u * gr + 150u * gg + 29u * gb) >> 8);
        effective_col_gap = LCD_RGB565(glum, glum, glum);
    }
    if (wire_swap) {
        effective_col_gap = LCD_RGB565_SWAP(effective_col_gap);
    }

    const int32_t num_cols = area->x2 / cell_size - area->x1 / cell_size + 1;
    if (num_cols <= 0 || num_cols > LCD_MAX_CELL_COLS) {
        return;
    }

    lcd_shade_t sh;
    sh.neutral = (state->shading_mode == LCD_SHADING_NEUTRAL_GRAY);
    sh.gray4 = is_grayscale_4bit;
    sh.dark = state->dark_theme;
    sh.inverted = inverted;
    sh.wire_swap = wire_swap;
    sh.col_active = col_active;
    sh.col_inactive = col_inactive;
    sh.r0 = (int32_t)((col_inactive >> 11) & 0x1F);
    sh.g0 = (int32_t)((col_inactive >> 5) & 0x3F);
    sh.b0 = (int32_t)(col_inactive & 0x1F);
    sh.dr = (int32_t)((col_active >> 11) & 0x1F) - sh.r0;
    sh.dg = (int32_t)((col_active >> 5) & 0x3F) - sh.g0;
    sh.db = (int32_t)(col_active & 0x1F) - sh.b0;

    const uint16_t mono_active = wire_swap ? LCD_RGB565_SWAP(col_active) : col_active;
    const uint16_t mono_inactive = wire_swap ? LCD_RGB565_SWAP(col_inactive) : col_inactive;

    uint16_t ramp_storage[256];
    const uint16_t *ramp = NULL;
    if (is_grayscale) {
        const int32_t cells = num_cols * (area->y2 / cell_size - area->y1 / cell_size + 1);
        if (cells >= LCD_RAMP_MIN_CELLS) {
            for (int i = 0; i < 256; i++) {
                ramp_storage[i] = lcd_lum_to_color(&sh, (uint8_t)i);
            }
            ramp = ramp_storage;
        }
    }

    const uint8_t *lut = s_8bit_is_rgb232 ? s_lum_lut : NULL;
    if (is_grayscale) {
        if (lut) {
            lcd_decimate_core(area, src_pixels, dst_rgb565, &sh, ramp, state->threshold, effective_col_gap,
                              mono_active, mono_inactive, cell_size, gap_size, true, s_lum_lut);
        } else {
            lcd_decimate_core(area, src_pixels, dst_rgb565, &sh, ramp, state->threshold, effective_col_gap,
                              mono_active, mono_inactive, cell_size, gap_size, true, NULL);
        }
    } else {
        if (lut) {
            lcd_decimate_core(area, src_pixels, dst_rgb565, &sh, NULL, state->threshold, effective_col_gap,
                              mono_active, mono_inactive, cell_size, gap_size, false, s_lum_lut);
        } else {
            lcd_decimate_core(area, src_pixels, dst_rgb565, &sh, NULL, state->threshold, effective_col_gap,
                              mono_active, mono_inactive, cell_size, gap_size, false, NULL);
        }
    }
}

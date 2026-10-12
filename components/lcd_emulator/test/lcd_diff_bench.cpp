/**
 * @file lcd_diff_bench.cpp
 * @brief Differential fuzz and benchmark harness for lcd_emulator_apply_filter_8to16().
 *
 * Links the production lcd_emulator.c against a baseline copy of the same file extracted from git
 * history at build time (see run_host_checks.sh). The baseline's public symbols are renamed with a
 * "ref_" prefix, so the baseline algorithm is never copied into the repository.
 *
 *   lcd_diff_bench fuzz [iterations] [seed]   bit-exact comparison against the baseline
 *   lcd_diff_bench bench                      timing table: baseline vs current implementation
 */

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <vector>

#include "../include/lcd_emulator.h"

extern "C" {
void ref_lcd_emulator_apply_filter_8to16(const lv_area_t *area, const uint8_t *pixels_8,
                                         uint16_t *out_rgb565, const lcd_decorator_state_t *state,
                                         bool inverted, bool wire_swap);
esp_err_t ref_lcd_emulator_set_8bit_input_rgb232(bool is_rgb232);
}

static const lcd_palette_t kPresets[] = {
    {0, 0, 0, 0, LCD_RGB565(0x8A, 0x9A, 0x5B), LCD_RGB565(0x1B, 0x28, 0x12), LCD_RGB565(0x7D, 0x8C, 0x50), LCD_RGB565(0x6F, 0x7E, 0x45)},
    {0, 0, 0, 0, LCD_RGB565(0xA0, 0xB0, 0xA2), LCD_RGB565(0x14, 0x1D, 0x15), LCD_RGB565(0x91, 0xA1, 0x93), LCD_RGB565(0x7E, 0x8E, 0x80)},
    {0, 0, 0, 0, LCD_RGB565(0x18, 0x10, 0x02), LCD_RGB565(0xFF, 0xAA, 0x00), LCD_RGB565(0x36, 0x21, 0x04), LCD_RGB565(0x0D, 0x07, 0x00)},
    {0, 0, 0, 0, LCD_RGB565(0x08, 0x1D, 0x22), LCD_RGB565(0x00, 0xF0, 0xFF), LCD_RGB565(0x12, 0x39, 0x42), LCD_RGB565(0x04, 0x0F, 0x12)},
};
static const int kAmber = 2;

enum Content { CONTENT_NOISE, CONTENT_UI_SPARSE, CONTENT_WHITE, CONTENT_BLACK, CONTENT_COUNT };
static const char *kContentName[] = {"noise", "ui-sparse", "white", "black"};

static void fill_content(std::vector<uint8_t> &buf, int w, int h, int x0, int y0, Content c, std::mt19937 &rng)
{
    switch (c) {
    case CONTENT_NOISE:
        for (auto &p : buf) p = (uint8_t)rng();
        break;
    case CONTENT_WHITE:
        std::fill(buf.begin(), buf.end(), 255);
        break;
    case CONTENT_BLACK:
        std::fill(buf.begin(), buf.end(), 0);
        break;
    case CONTENT_UI_SPARSE:
    default:
        // Black AMOLED-style background with a bright ring (gauge) + anti-aliased text-like bars.
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                const int ax = x0 + x - 233, ay = y0 + y - 233;
                const int r2 = ax * ax + ay * ay;
                uint8_t v = 0;
                if (r2 > 200 * 200 && r2 < 214 * 214) v = 255;
                else if (r2 > 198 * 198 && r2 < 216 * 216) v = 120;
                else if ((y0 + y) > 210 && (y0 + y) < 250 && (x0 + x) > 150 && (x0 + x) < 320 && (((x0 + x) / 7) & 1)) v = 220;
                buf[(size_t)y * w + x] = v;
            }
        }
        break;
    }
}

struct Cfg {
    lcd_render_mode_t mode;
    lcd_shading_mode_t shading;
    bool dark;
    int cell, gap;
    int preset;
    bool inverted;
    bool wire_swap;
};

static lcd_decorator_state_t make_state(const Cfg &c)
{
    lcd_decorator_state_t s;
    memset(&s, 0, sizeof(s));
    s.mode = c.mode;
    s.shading_mode = c.shading;
    s.dark_theme = c.dark;
    s.cell_size = (uint8_t)c.cell;
    s.gap_size = (uint8_t)c.gap;
    s.threshold = 100;
    s.palette = kPresets[c.preset];
    return s;
}

/* ------------------------------------------------------------------------------------ fuzz */

static int run_fuzz(long iterations, uint32_t seed)
{
    std::mt19937 rng(seed);
    long failures = 0;
    const uint16_t kSentinel = 0xA55A;

    for (long it = 0; it < iterations; it++) {
        lcd_decorator_state_t s;
        memset(&s, 0, sizeof(s));
        s.mode = (lcd_render_mode_t)(rng() % 5);                 // passthrough..gray8
        s.shading_mode = (lcd_shading_mode_t)(rng() % 2);
        s.dark_theme = rng() & 1;
        s.cell_size = (uint8_t)(rng() % 11);                     // includes <2 fallback
        s.gap_size = (uint8_t)(rng() % 12);                      // includes >= cell fallback
        s.threshold = (uint8_t)rng();
        if (rng() % 4 == 0) {                                    // random palette incl. zero rgb565 fields
            s.palette.color_bg = (lcd_color_t)rng();
            s.palette.color_active = (lcd_color_t)rng();
            s.palette.color_inactive = (lcd_color_t)rng();
            s.palette.color_gap = (lcd_color_t)rng();
            if (rng() & 1) {
                s.palette.color_active_rgb565 = (uint16_t)rng();
                s.palette.color_inactive_rgb565 = (uint16_t)rng();
                s.palette.color_gap_rgb565 = (uint16_t)rng();
            }
        } else {
            s.palette = kPresets[rng() % 4];
        }
        const bool inverted = rng() & 1;
        const bool wire_swap = rng() & 1;
        const bool rgb232 = (rng() % 8 == 0);
        lcd_emulator_set_8bit_input_rgb232(rgb232);
        ref_lcd_emulator_set_8bit_input_rgb232(rgb232);

        int w, h;
        if (rng() % 16 == 0) { w = 700 + rng() % 500; h = 1 + rng() % 4; }   // exercises > LCD_MAX_CELL_COLS
        else if (rng() % 3 == 0) { w = 1 + rng() % 12; h = 1 + rng() % 12; }
        else { w = 1 + rng() % 120; h = 1 + rng() % 60; }
        const int x1 = rng() % 466, y1 = rng() % 466;
        lv_area_t area = {x1, y1, x1 + w - 1, y1 + h - 1};

        std::vector<uint8_t> src((size_t)w * h);
        fill_content(src, w, h, x1, y1, (Content)(rng() % CONTENT_COUNT), rng);

        const size_t n = (size_t)w * h, pad = 32;
        std::vector<uint16_t> a(n + 2 * pad, kSentinel), b(n + 2 * pad, kSentinel);
        ref_lcd_emulator_apply_filter_8to16(&area, src.data(), a.data() + pad, &s, inverted, wire_swap);
        lcd_emulator_apply_filter_8to16(&area, src.data(), b.data() + pad, &s, inverted, wire_swap);

        if (memcmp(a.data(), b.data(), a.size() * sizeof(uint16_t)) != 0) {
            failures++;
            if (failures <= 5) {
                size_t first = 0;
                while (first < a.size() && a[first] == b[first]) first++;
                fprintf(stderr,
                        "MISMATCH it=%ld mode=%d shade=%d dark=%d cell=%u gap=%u thr=%u inv=%d swap=%d rgb232=%d "
                        "area=(%d,%d)-(%d,%d) first_diff_idx=%zu ref=0x%04X new=0x%04X\n",
                        it, s.mode, s.shading_mode, s.dark_theme, s.cell_size, s.gap_size, s.threshold, inverted,
                        wire_swap, rgb232, area.x1, area.y1, area.x2, area.y2, first, a[first], b[first]);
            }
        }
    }
    lcd_emulator_set_8bit_input_rgb232(false);
    ref_lcd_emulator_set_8bit_input_rgb232(false);
    printf("fuzz: %ld iterations, seed %u, %ld mismatches\n", iterations, seed, failures);
    return failures ? 1 : 0;
}

/* ------------------------------------------------------------------------------------ bench */

typedef void (*fn_t)(const lv_area_t *, const uint8_t *, uint16_t *, const lcd_decorator_state_t *, bool, bool);

static double time_ns_per_call(fn_t fn, const lv_area_t &area, const uint8_t *src, uint16_t *dst,
                               const lcd_decorator_state_t &s, bool inv, bool swap)
{
    using clk = std::chrono::steady_clock;
    // Calibrate repetitions to ~15 ms per batch, take the minimum of 9 batches.
    long reps = 1;
    for (;;) {
        auto t0 = clk::now();
        for (long i = 0; i < reps; i++) fn(&area, src, dst, &s, inv, swap);
        double ms = std::chrono::duration<double, std::milli>(clk::now() - t0).count();
        if (ms > 15.0 || reps > (1L << 24)) break;
        reps *= 2;
    }
    double best = 1e30;
    for (int b = 0; b < 9; b++) {
        auto t0 = clk::now();
        for (long i = 0; i < reps; i++) fn(&area, src, dst, &s, inv, swap);
        double ns = std::chrono::duration<double, std::nano>(clk::now() - t0).count() / (double)reps;
        if (ns < best) best = ns;
    }
    return best;
}

static void run_bench()
{
    std::mt19937 rng(1234);
    struct Tile { const char *name; int x, y, w, h; };
    const Tile tiles[] = {
        {"466x466 full", 0, 0, 466, 466},
        {"466x50 strip", 0, 100, 466, 50},
        {"466x16 strip", 0, 101, 466, 16},
        {"150x40 widget", 157, 211, 150, 40},
        {"37x23 small odd", 101, 53, 37, 23},
    };
    struct Named { const char *name; Cfg cfg; };
    const Named cfgs[] = {
        {"TARGET gray8 tinted amber dark cell3/gap1", {LCD_RENDER_MODE_GRAYSCALE_8BIT, LCD_SHADING_PALETTE_TINTED, true, 3, 1, kAmber, false, true}},
        {"gray8 tinted amber dark cell4/gap1",        {LCD_RENDER_MODE_GRAYSCALE_8BIT, LCD_SHADING_PALETTE_TINTED, true, 4, 1, kAmber, false, true}},
        {"gray8 neutral dark cell3/gap1",             {LCD_RENDER_MODE_GRAYSCALE_8BIT, LCD_SHADING_NEUTRAL_GRAY, true, 3, 1, kAmber, false, true}},
        {"gray4 tinted amber dark cell3/gap1",        {LCD_RENDER_MODE_GRAYSCALE_4BIT, LCD_SHADING_PALETTE_TINTED, true, 3, 1, kAmber, false, true}},
        {"mono amber dark cell3/gap1",                {LCD_RENDER_MODE_RETRO_MONOCHROME, LCD_SHADING_PALETTE_TINTED, true, 3, 1, kAmber, false, true}},
    };

    printf("%-44s %-16s %-10s %12s %12s %8s\n", "config", "tile", "content", "ref ns/px", "new ns/px", "speedup");
    for (const auto &nc : cfgs) {
        const lcd_decorator_state_t s = make_state(nc.cfg);
        for (const auto &t : tiles) {
            for (int c = 0; c < CONTENT_COUNT; c++) {
                if (c == CONTENT_BLACK && &t != &tiles[0] && &t != &tiles[1]) continue;
                if (&nc != &cfgs[0] && (c == CONTENT_WHITE || c == CONTENT_BLACK)) continue;
                lv_area_t area = {t.x, t.y, t.x + t.w - 1, t.y + t.h - 1};
                std::vector<uint8_t> src((size_t)t.w * t.h);
                fill_content(src, t.w, t.h, t.x, t.y, (Content)c, rng);
                std::vector<uint16_t> dst((size_t)t.w * t.h);
                const double px = (double)t.w * t.h;
                double ref_ns = time_ns_per_call(ref_lcd_emulator_apply_filter_8to16, area, src.data(), dst.data(), s, nc.cfg.inverted, nc.cfg.wire_swap);
                double new_ns = time_ns_per_call(lcd_emulator_apply_filter_8to16, area, src.data(), dst.data(), s, nc.cfg.inverted, nc.cfg.wire_swap);
                printf("%-44s %-16s %-10s %12.3f %12.3f %7.2fx\n", nc.name, t.name, kContentName[c], ref_ns / px, new_ns / px, ref_ns / new_ns);
            }
        }
    }
}

/* Exhaustive check of the reciprocal-multiply identity used by the production code:
 * floor(sum * ceil(2^24 / cnt) >> 24) == floor(sum / cnt) for all sum <= 255 * cnt, cnt <= 255,
 * with the product fitting in 32 bits. */
static int run_recip_selftest()
{
    long bad = 0;
    for (uint32_t cnt = 1; cnt <= 255; cnt++) {
        const uint32_t recip = ((1u << 24) + cnt - 1u) / cnt;
        for (uint32_t sum = 0; sum <= 255 * cnt; sum++) {
            const uint64_t prod = (uint64_t)sum * recip;
            if (prod > 0xFFFFFFFFull || (uint32_t)(prod >> 24) != sum / cnt) bad++;
        }
    }
    printf("recip selftest: %ld failures\n", bad);
    return bad ? 1 : 0;
}

int main(int argc, char **argv)
{
    if (run_recip_selftest()) return 1;
    const char *mode = argc > 1 ? argv[1] : "fuzz";
    if (!strcmp(mode, "bench")) {
        run_bench();
        return 0;
    }
    long iters = argc > 2 ? atol(argv[2]) : 200000;
    uint32_t seed = argc > 3 ? (uint32_t)strtoul(argv[3], NULL, 10) : 1;
    return run_fuzz(iters, seed);
}

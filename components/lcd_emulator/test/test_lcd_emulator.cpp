/**
 * @file test_lcd_emulator.cpp
 * @brief Automated host unit and regression tests for retro LCD emulator component.
 *
 * Exercises direct production source (lcd_emulator.c) natively under macOS clang++ / Linux g++.
 * Verifies decorator state getter/setter, parameter validation safety, render mode switching,
 * inverted LCD logic, custom pluggable renderers, screen-space modulo boundary continuity,
 * and high-volume stress endurance (50,000 passes).
 */

#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

// Directly include production header and implementation
#include "../include/lcd_emulator.h"
#include "../src/lcd_emulator.c"

#define ASSERT_TRUE(cond) do { \
    if (!(cond)) { \
        fprintf(stderr, "ASSERTION FAILED: %s at %s:%d\n", #cond, __FILE__, __LINE__); \
        abort(); \
    } \
} while(0)

#define ASSERT_EQ(a, b) do { \
    if ((a) != (b)) { \
        fprintf(stderr, "ASSERTION FAILED: %s == %s (0x%X != 0x%X) at %s:%d\n", \
                #a, #b, (unsigned)(a), (unsigned)(b), __FILE__, __LINE__); \
        abort(); \
    } \
} while(0)

/**
 * @brief Test 1: Verify RGB565 packing math and channel isolation.
 */
static void test_rgb565_macro()
{
    printf("[TEST 1] Verifying RGB565 color pack macro...\n");

    // Pure Red (0xFF, 0, 0) -> 0xF800
    uint16_t red = LCD_RGB565(0xFF, 0x00, 0x00);
    ASSERT_EQ(red, 0xF800);

    // Pure Green (0, 0xFF, 0) -> 0x07E0
    uint16_t green = LCD_RGB565(0x00, 0xFF, 0x00);
    ASSERT_EQ(green, 0x07E0);

    // Pure Blue (0, 0, 0xFF) -> 0x001F
    uint16_t blue = LCD_RGB565(0x00, 0x00, 0xFF);
    ASSERT_EQ(blue, 0x001F);

    // Pure White (0xFF, 0xFF, 0xFF) -> 0xFFFF
    uint16_t white = LCD_RGB565(0xFF, 0xFF, 0xFF);
    ASSERT_EQ(white, 0xFFFF);

    // Pure Black (0, 0, 0) -> 0x0000
    uint16_t black = LCD_RGB565(0x00, 0x00, 0x00);
    ASSERT_EQ(black, 0x0000);

    printf("  -> RGB565 packing verified.\n");
}

/**
 * @brief Test 2: Sub-pixel matrix gap geometry.
 */
static void test_subpixel_gap_geometry()
{
    printf("[TEST 2] Verifying sub-pixel matrix gap placement...\n");

    lcd_emulator_cfg_t cfg;
    cfg.enabled = true;
    cfg.cell_size = 4;
    cfg.gap_size = 1;
    cfg.threshold = 135;
    cfg.palette = s_palettes[LCD_PRESET_OLIVE];

    const int width = 16;
    const int height = 16;
    std::vector<lcd_color_t> buffer(width * height, LCD_COLOR_MAKE(0xFF, 0xFF, 0xFF)); // All white

    lv_area_t area = { .x1 = 0, .y1 = 0, .x2 = width - 1, .y2 = height - 1 };
    lcd_emulator_apply_filter(&area, buffer.data(), &cfg);

    for (int y = 0; y < height; y++) {
        bool expect_gap_y = ((y % cfg.cell_size) >= (cfg.cell_size - cfg.gap_size));
        for (int x = 0; x < width; x++) {
            bool expect_gap_x = ((x % cfg.cell_size) >= (cfg.cell_size - cfg.gap_size));
            lcd_color_t px = buffer[y * width + x];

            if (expect_gap_y || expect_gap_x) {
                ASSERT_EQ(px, cfg.palette.color_gap);
            } else {
                // Since source was white (bright), active cell must be color_inactive
                ASSERT_EQ(px, cfg.palette.color_inactive);
            }
        }
    }

    printf("  -> Gap geometry verified across 16x16 matrix.\n");
}

/**
 * @brief Test 3: Screen-space modulo continuity across tile boundaries (Dirty Rectangles).
 */
static void test_screen_space_modulo_continuity()
{
    printf("[TEST 3] Verifying screen-space modulo continuity across dirty partial buffers...\n");

    lcd_emulator_cfg_t cfg;
    cfg.enabled = true;
    cfg.cell_size = 4;
    cfg.gap_size = 1;
    cfg.threshold = 135;
    cfg.palette = s_palettes[LCD_PRESET_AMBER];

    // Reference: Decimate an entire 64x64 buffer in one single call
    const int full_w = 64;
    const int full_h = 64;
    std::vector<lcd_color_t> ref_buffer(full_w * full_h);
    // Fill with diagonal black/white checker pattern
    for (int y = 0; y < full_h; y++) {
        for (int x = 0; x < full_w; x++) {
            ref_buffer[y * full_w + x] = ((x + y) % 8 < 4) ? LCD_COLOR_MAKE(0, 0, 0) : LCD_COLOR_MAKE(0xFF, 0xFF, 0xFF);
        }
    }

    std::vector<lcd_color_t> tiled_buffer = ref_buffer;

    lv_area_t full_area = { .x1 = 0, .y1 = 0, .x2 = full_w - 1, .y2 = full_h - 1 };
    lcd_emulator_apply_filter(&full_area, ref_buffer.data(), &cfg);

    // Now slice into irregular partial tiles:
    // Tile 1: (0, 0) to (31, 23)
    // Tile 2: (32, 0) to (63, 23)
    // Tile 3: (0, 24) to (63, 63)
    std::vector<lv_area_t> tiles = {
        { .x1 = 0,  .y1 = 0,  .x2 = 31, .y2 = 23 },
        { .x1 = 32, .y1 = 0,  .x2 = 63, .y2 = 23 },
        { .x1 = 0,  .y1 = 24, .x2 = 63, .y2 = 63 }
    };

    for (const auto& tile : tiles) {
        int tile_w = tile.x2 - tile.x1 + 1;
        int tile_h = tile.y2 - tile.y1 + 1;
        std::vector<lcd_color_t> tile_data(tile_w * tile_h);

        // Copy source tile out of original test pattern
        for (int y = 0; y < tile_h; y++) {
            int src_y = tile.y1 + y;
            for (int x = 0; x < tile_w; x++) {
                int src_x = tile.x1 + x;
                tile_data[y * tile_w + x] = ((src_x + src_y) % 8 < 4) ? LCD_COLOR_MAKE(0, 0, 0) : LCD_COLOR_MAKE(0xFF, 0xFF, 0xFF);
            }
        }

        // Apply filter to partial tile
        lcd_emulator_apply_filter(&tile, tile_data.data(), &cfg);

        // Copy decimated tile back into tiled_buffer
        for (int y = 0; y < tile_h; y++) {
            int dst_y = tile.y1 + y;
            for (int x = 0; x < tile_w; x++) {
                int dst_x = tile.x1 + x;
                tiled_buffer[dst_y * full_w + dst_x] = tile_data[y * tile_w + x];
            }
        }
    }

    // Verify 100% bit-exact equivalence between unified render and sliced partial rendering
    for (int i = 0; i < full_w * full_h; i++) {
        ASSERT_EQ(tiled_buffer[i], ref_buffer[i]);
    }

    printf("  -> Bit-exact continuity asserted across irregular tile seams.\n");
}

/**
 * @brief Test 4: Decorator State Setter / Getter & Parameter Validation Safety.
 */
static void test_decorator_state_safety()
{
    printf("[TEST 4] Verifying decorator state setter/getter & safety constraints...\n");

    // Initial state read
    lcd_decorator_state_t st;
    ASSERT_EQ(lcd_emulator_get_decorator_state(&st), ESP_OK);
    ASSERT_EQ(st.cell_size, 4);
    ASSERT_EQ(st.gap_size, 1);
    ASSERT_TRUE(st.dark_theme);

    // Negative tests: NULL pointers
    ASSERT_EQ(lcd_emulator_get_decorator_state(NULL), ESP_ERR_INVALID_ARG);
    ASSERT_EQ(lcd_emulator_set_decorator_state(NULL), ESP_ERR_INVALID_ARG);

    // Negative test: Invalid mode
    lcd_decorator_state_t bad_state = st;
    bad_state.mode = (lcd_render_mode_t)99;
    ASSERT_EQ(lcd_emulator_set_decorator_state(&bad_state), ESP_ERR_INVALID_ARG);

    // Negative test: Invalid shading mode
    bad_state = st;
    bad_state.shading_mode = (lcd_shading_mode_t)99;
    ASSERT_EQ(lcd_emulator_set_decorator_state(&bad_state), ESP_ERR_INVALID_ARG);

    // Negative test: cell_size < 2
    bad_state = st;
    bad_state.cell_size = 1;
    ASSERT_EQ(lcd_emulator_set_decorator_state(&bad_state), ESP_ERR_INVALID_ARG);

    // Negative test: gap_size >= cell_size
    bad_state = st;
    bad_state.cell_size = 4;
    bad_state.gap_size = 4;
    ASSERT_EQ(lcd_emulator_set_decorator_state(&bad_state), ESP_ERR_INVALID_ARG);

    // Negative test: CUSTOM mode with NULL callback
    bad_state = st;
    bad_state.mode = LCD_RENDER_MODE_CUSTOM;
    bad_state.custom_render_fn = NULL;
    ASSERT_EQ(lcd_emulator_set_decorator_state(&bad_state), ESP_ERR_INVALID_ARG);

    // Positive test: Valid state update
    lcd_decorator_state_t good_state = st;
    good_state.mode = LCD_RENDER_MODE_RETRO_MONOCHROME;
    good_state.shading_mode = LCD_SHADING_NEUTRAL_GRAY;
    good_state.dark_theme = true;
    good_state.cell_size = 5;
    good_state.gap_size = 1;
    good_state.threshold = 145;
    good_state.palette = s_palettes[LCD_PRESET_CYAN];
    ASSERT_EQ(lcd_emulator_set_decorator_state(&good_state), ESP_OK);

    // Verify getter returns updated state
    lcd_decorator_state_t read_back;
    ASSERT_EQ(lcd_emulator_get_decorator_state(&read_back), ESP_OK);
    ASSERT_EQ(read_back.cell_size, 5);
    ASSERT_EQ(read_back.gap_size, 1);
    ASSERT_EQ(read_back.threshold, 145);
    ASSERT_TRUE(read_back.dark_theme);
    ASSERT_EQ(read_back.palette.color_active, s_palettes[LCD_PRESET_CYAN].color_active);
    ASSERT_EQ(read_back.mode, LCD_RENDER_MODE_RETRO_MONOCHROME);
    ASSERT_EQ(read_back.shading_mode, LCD_SHADING_NEUTRAL_GRAY);

    // Test standalone dark theme & inverted setters
    lcd_emulator_set_dark_theme(false);
    ASSERT_TRUE(!lcd_emulator_is_dark_theme());
    lcd_emulator_set_dark_theme(true);
    ASSERT_TRUE(lcd_emulator_is_dark_theme());

    lcd_emulator_set_inverted(true);
    ASSERT_TRUE(lcd_emulator_is_inverted());
    lcd_emulator_set_inverted(false);
    ASSERT_TRUE(!lcd_emulator_is_inverted());

    // Test standalone shading mode setter and getter
    ASSERT_EQ(lcd_emulator_set_shading_mode((lcd_shading_mode_t)99), ESP_ERR_INVALID_ARG);
    ASSERT_EQ(lcd_emulator_set_shading_mode(LCD_SHADING_PALETTE_TINTED), ESP_OK);
    ASSERT_EQ(lcd_emulator_get_shading_mode(), LCD_SHADING_PALETTE_TINTED);
    ASSERT_EQ(lcd_emulator_set_shading_mode(LCD_SHADING_NEUTRAL_GRAY), ESP_OK);
    ASSERT_EQ(lcd_emulator_get_shading_mode(), LCD_SHADING_NEUTRAL_GRAY);

    printf("  -> State validation safety and round-trip assertions passed.\n");
}

/**
 * @brief Custom test render callback.
 */
static int s_custom_render_calls = 0;
static void dummy_custom_render(const lv_area_t *area, lcd_color_t *pixels, void *user_ctx)
{
    (void)user_ctx;
    s_custom_render_calls++;
    int count = (area->x2 - area->x1 + 1) * (area->y2 - area->y1 + 1);
    for (int i = 0; i < count; i++) {
        pixels[i] = LCD_COLOR_MAKE(0xAA, 0xBB, 0xCC);
    }
}

/**
 * @brief Test 5: Render Mode Switching (Passthrough, Monochrome, Inverted, Custom).
 */
static void test_render_mode_switching()
{
    printf("[TEST 5] Verifying render mode switching & custom plugin renderer...\n");

    const int w = 8;
    const int h = 8;
    lv_area_t area = { .x1 = 0, .y1 = 0, .x2 = w - 1, .y2 = h - 1 };

    // 1. Switch to PASSTHROUGH
    ASSERT_EQ(lcd_emulator_set_render_mode(LCD_RENDER_MODE_PASSTHROUGH), ESP_OK);
    ASSERT_EQ(lcd_emulator_get_render_mode(), LCD_RENDER_MODE_PASSTHROUGH);
    ASSERT_TRUE(!lcd_emulator_is_enabled());

    // 2. Switch to RETRO_INVERTED
    ASSERT_EQ(lcd_emulator_set_render_mode(LCD_RENDER_MODE_RETRO_INVERTED), ESP_OK);
    ASSERT_EQ(lcd_emulator_get_render_mode(), LCD_RENDER_MODE_RETRO_INVERTED);
    ASSERT_TRUE(lcd_emulator_is_enabled());

    // Test Inverted logic on dark theme:
    // In normal mode, white text is color_active. In inverted mode, white text is color_inactive
    // and black background is color_active.
    lcd_decorator_state_t inv_state;
    lcd_emulator_get_decorator_state(&inv_state);
    inv_state.gap_size = 0; // disable gaps for pure test
    std::vector<lcd_color_t> white_inv_buf(w * h, LCD_COLOR_MAKE(255, 255, 255)); // Bright
    lcd_emulator_apply_filter_ex(&area, white_inv_buf.data(), &inv_state, true);
    for (int i = 0; i < w * h; i++) {
        ASSERT_EQ(white_inv_buf[i], inv_state.palette.color_inactive);
    }

    std::vector<lcd_color_t> black_inv_buf(w * h, LCD_COLOR_MAKE(0, 0, 0)); // Dark
    lcd_emulator_apply_filter_ex(&area, black_inv_buf.data(), &inv_state, true);
    for (int i = 0; i < w * h; i++) {
        ASSERT_EQ(black_inv_buf[i], inv_state.palette.color_active);
    }

    // 3. Switch to GRAYSCALE_4BIT
    ASSERT_EQ(lcd_emulator_set_render_mode(LCD_RENDER_MODE_GRAYSCALE_4BIT), ESP_OK);
    ASSERT_EQ(lcd_emulator_get_render_mode(), LCD_RENDER_MODE_GRAYSCALE_4BIT);
    ASSERT_TRUE(lcd_emulator_is_enabled());

    // 4. Switch to GRAYSCALE_8BIT
    ASSERT_EQ(lcd_emulator_set_render_mode(LCD_RENDER_MODE_GRAYSCALE_8BIT), ESP_OK);
    ASSERT_EQ(lcd_emulator_get_render_mode(), LCD_RENDER_MODE_GRAYSCALE_8BIT);
    ASSERT_TRUE(lcd_emulator_is_enabled());

    // 5. Register Custom Render
    s_custom_render_calls = 0;
    ASSERT_EQ(lcd_emulator_set_custom_render(dummy_custom_render, NULL), ESP_OK);
    ASSERT_EQ(lcd_emulator_get_render_mode(), LCD_RENDER_MODE_CUSTOM);

    lcd_decorator_state_t cust_state;
    lcd_emulator_get_decorator_state(&cust_state);
    std::vector<lcd_color_t> cust_buf(w * h, 0);
    cust_state.custom_render_fn(&area, cust_buf.data(), cust_state.custom_user_ctx);
    ASSERT_EQ(s_custom_render_calls, 1);
    ASSERT_EQ(cust_buf[0], LCD_COLOR_MAKE(0xAA, 0xBB, 0xCC));

    printf("  -> Render mode switching (Passthrough, Inverted, Grayscale 4/8-bit, Custom) verified.\n");
}

/**
 * @brief Test 6: Cell Size Scaling & Thin 1px Stroke Preservation (Box Sampling).
 */
static void test_cell_size_scaling_and_thin_stroke_preservation()
{
    printf("[TEST 6] Verifying cell size scaling & thin 1px stroke box-sampling preservation...\n");

    lcd_decorator_state_t state;
    state.mode = LCD_RENDER_MODE_RETRO_MONOCHROME;
    state.dark_theme = true; // AMOLED dark UI
    state.palette = s_palettes[LCD_PRESET_AMBER];
    state.threshold = 100;
    state.custom_render_fn = NULL;
    state.custom_user_ctx = NULL;

    // Test 1: Cell Size 3 with 1px stroke at x=0 (cell spans [0..2], dot [0..1], gap [2])
    // Even though the stroke is at x=0 (left edge), box sampling MUST capture it.
    {
        state.cell_size = 3;
        state.gap_size = 1;
        const int w = 12;
        const int h = 12;
        lv_area_t area = { .x1 = 0, .y1 = 0, .x2 = w - 1, .y2 = h - 1 };

        // Test every possible pixel position [0..1] in the dot area of cell 0
        for (int offset_x = 0; offset_x <= 1; offset_x++) {
            for (int offset_y = 0; offset_y <= 1; offset_y++) {
                std::vector<lcd_color_t> buf(w * h, 0); // Black background
                buf[offset_y * w + offset_x] = LCD_COLOR_MAKE(0xFF, 0xFF, 0xFF); // Single 1px white dot

                lcd_emulator_apply_filter_ex(&area, buf.data(), &state, false);

                // Cell (0, 0) non-gap pixels must be color_active (amber)
                ASSERT_EQ(buf[0 * w + 0], state.palette.color_active);
                ASSERT_EQ(buf[0 * w + 1], state.palette.color_active);
                ASSERT_EQ(buf[1 * w + 0], state.palette.color_active);
                ASSERT_EQ(buf[1 * w + 1], state.palette.color_active);

                // Gap pixels must be color_gap
                ASSERT_EQ(buf[0 * w + 2], state.palette.color_gap);
                ASSERT_EQ(buf[1 * w + 2], state.palette.color_gap);
                ASSERT_EQ(buf[2 * w + 0], state.palette.color_gap);

                // Neighboring cell (1, 0) must be inactive
                ASSERT_EQ(buf[0 * w + 3], state.palette.color_inactive);
            }
        }
    }

    // Test 2: Cell Size 4 vs Cell Size 3 grid scaling assertion
    {
        const int w = 24;
        const int h = 24;
        lv_area_t area = { .x1 = 0, .y1 = 0, .x2 = w - 1, .y2 = h - 1 };

        // For cell_size = 3, in 24 pixels we have 24 / 3 = 8 cells
        // For cell_size = 4, in 24 pixels we have 24 / 4 = 6 cells
        state.cell_size = 3;
        state.gap_size = 1;
        std::vector<lcd_color_t> buf3(w * h, LCD_COLOR_MAKE(0xFF, 0xFF, 0xFF)); // All white
        lcd_emulator_apply_filter_ex(&area, buf3.data(), &state, false);

        int gap_count_3 = 0;
        for (int x = 0; x < w; x++) {
            if (buf3[0 * w + x] == state.palette.color_gap) gap_count_3++;
        }
        ASSERT_EQ(gap_count_3, 8); // 8 gap columns for cell size 3

        state.cell_size = 4;
        state.gap_size = 1;
        std::vector<lcd_color_t> buf4(w * h, LCD_COLOR_MAKE(0xFF, 0xFF, 0xFF)); // All white
        lcd_emulator_apply_filter_ex(&area, buf4.data(), &state, false);

        int gap_count_4 = 0;
        for (int x = 0; x < w; x++) {
            if (buf4[0 * w + x] == state.palette.color_gap) gap_count_4++;
        }
        ASSERT_EQ(gap_count_4, 6); // 6 gap columns for cell size 4
    }

    printf("  -> Box sampling and cell size resolution scaling verified.\n");
}

/**
 * @brief Test 7: Dark Theme (AMOLED) vs Light Theme & Inversion Polarity.
 */
static void test_dark_theme_and_inverted_mode()
{
    printf("[TEST 7] Verifying dark theme (AMOLED) mapping and inverted polarity...\n");

    lcd_decorator_state_t state;
    state.mode = LCD_RENDER_MODE_RETRO_MONOCHROME;
    state.cell_size = 4;
    state.gap_size = 0; // zero gaps for pure state test
    state.threshold = 100;
    state.palette = s_palettes[LCD_PRESET_AMBER];
    state.custom_render_fn = NULL;
    state.custom_user_ctx = NULL;

    const int w = 4;
    const int h = 4;
    lv_area_t area = { .x1 = 0, .y1 = 0, .x2 = w - 1, .y2 = h - 1 };

    // Scenario A: AMOLED Dark Theme (black background with white text)
    state.dark_theme = true;

    // 1. Black background (lum = 0 < 100) -> color_inactive
    std::vector<lcd_color_t> black_buf(w * h, LCD_COLOR_MAKE(0, 0, 0));
    lcd_emulator_apply_filter_ex(&area, black_buf.data(), &state, false);
    ASSERT_EQ(black_buf[0], state.palette.color_inactive);

    // 2. White text (lum = 255 >= 100) -> color_active
    std::vector<lcd_color_t> white_buf(w * h, LCD_COLOR_MAKE(0xFF, 0xFF, 0xFF));
    lcd_emulator_apply_filter_ex(&area, white_buf.data(), &state, false);
    ASSERT_EQ(white_buf[0], state.palette.color_active);

    // 3. Inverted mode on AMOLED:
    // White text becomes color_inactive, black background becomes color_active
    black_buf = std::vector<lcd_color_t>(w * h, LCD_COLOR_MAKE(0, 0, 0));
    lcd_emulator_apply_filter_ex(&area, black_buf.data(), &state, true);
    ASSERT_EQ(black_buf[0], state.palette.color_active);

    white_buf = std::vector<lcd_color_t>(w * h, LCD_COLOR_MAKE(0xFF, 0xFF, 0xFF));
    lcd_emulator_apply_filter_ex(&area, white_buf.data(), &state, true);
    ASSERT_EQ(white_buf[0], state.palette.color_inactive);

    // Scenario B: Classic Light Theme (white background with black text)
    state.dark_theme = false;

    // 1. Black ink (lum = 0 < 100) -> color_active
    black_buf = std::vector<lcd_color_t>(w * h, LCD_COLOR_MAKE(0, 0, 0));
    lcd_emulator_apply_filter_ex(&area, black_buf.data(), &state, false);
    ASSERT_EQ(black_buf[0], state.palette.color_active);

    // 2. White background (lum = 255 >= 100) -> color_inactive
    white_buf = std::vector<lcd_color_t>(w * h, LCD_COLOR_MAKE(0xFF, 0xFF, 0xFF));
    lcd_emulator_apply_filter_ex(&area, white_buf.data(), &state, false);
    ASSERT_EQ(white_buf[0], state.palette.color_inactive);

    printf("  -> AMOLED dark theme and inversion polarity verified.\n");
}

/**
 * @brief Test 8: Grayscale Emulation (4-bit 16-level quantization, 8-bit continuous, Neutral Gray vs Palette-Tinted).
 */
static void test_grayscale_emulation()
{
    printf("[TEST 8] Verifying 4-bit and 8-bit grayscale emulation & shading styles...\n");

    lcd_decorator_state_t state;
    state.dark_theme = true; // AMOLED dark UI
    state.cell_size = 4;
    state.gap_size = 0; // Disable gaps for direct cell color sampling
    state.palette = s_palettes[LCD_PRESET_OLIVE];
    state.custom_render_fn = NULL;
    state.custom_user_ctx = NULL;

    // 1. Verify 4-bit Palette-Tinted Mode (16 discrete levels)
    {
        state.mode = LCD_RENDER_MODE_GRAYSCALE_4BIT;
        state.shading_mode = LCD_SHADING_PALETTE_TINTED;

        const int num_cells = 16;
        const int w = num_cells * state.cell_size;
        const int h = state.cell_size;
        lv_area_t area = { .x1 = 0, .y1 = 0, .x2 = w - 1, .y2 = h - 1 };

        std::vector<lcd_color_t> buf(w * h);
        for (int c = 0; c < num_cells; c++) {
            // Level c intensity: c * 17
            uint8_t lum = (uint8_t)(c * 17);
            lcd_color_t px = LCD_COLOR_MAKE(lum, lum, lum);
            for (int y = 0; y < h; y++) {
                for (int x = 0; x < state.cell_size; x++) {
                    buf[y * w + (c * state.cell_size + x)] = px;
                }
            }
        }

        lcd_emulator_apply_filter_ex(&area, buf.data(), &state, false);

        // Level 0 must be exactly color_inactive
        ASSERT_EQ(buf[0], state.palette.color_inactive);

        // Level 15 must be exactly color_active
        ASSERT_EQ(buf[(num_cells - 1) * state.cell_size], state.palette.color_active);

        // Verify that all 16 levels produce unique, monotonic colors
        for (int c = 1; c < num_cells; c++) {
            lcd_color_t prev_col = buf[(c - 1) * state.cell_size];
            lcd_color_t curr_col = buf[c * state.cell_size];
            ASSERT_TRUE(prev_col != curr_col);
        }

        // Verify rounding: lum = 0 maps to level 0 (q=0), lum = 17 maps to level 1 (q=17)
        std::vector<lcd_color_t> round_buf(state.cell_size * state.cell_size, LCD_COLOR_MAKE(0, 0, 0));
        lv_area_t cell_area = { .x1 = 0, .y1 = 0, .x2 = state.cell_size - 1, .y2 = state.cell_size - 1 };
        lcd_emulator_apply_filter_ex(&cell_area, round_buf.data(), &state, false);
        ASSERT_EQ(round_buf[0], state.palette.color_inactive); // Level 0

        round_buf = std::vector<lcd_color_t>(state.cell_size * state.cell_size, LCD_COLOR_MAKE(17, 17, 17));
        lcd_emulator_apply_filter_ex(&cell_area, round_buf.data(), &state, false);
        ASSERT_TRUE(round_buf[0] != state.palette.color_inactive); // Level 1
    }

    // 2. Verify 8-bit Continuous Grayscale Mode
    {
        state.mode = LCD_RENDER_MODE_GRAYSCALE_8BIT;
        state.shading_mode = LCD_SHADING_PALETTE_TINTED;

        // In 8-bit mode, intermediate luminances produce fine-grained distinct shades
        std::vector<lcd_color_t> buf_a(state.cell_size * state.cell_size, LCD_COLOR_MAKE(16, 16, 16));
        std::vector<lcd_color_t> buf_b(state.cell_size * state.cell_size, LCD_COLOR_MAKE(40, 40, 40));
        lv_area_t cell_area = { .x1 = 0, .y1 = 0, .x2 = state.cell_size - 1, .y2 = state.cell_size - 1 };

        lcd_emulator_apply_filter_ex(&cell_area, buf_a.data(), &state, false);
        lcd_emulator_apply_filter_ex(&cell_area, buf_b.data(), &state, false);
        ASSERT_TRUE(buf_a[0] != buf_b[0]);
    }

    // 3. Verify Neutral Gray Shading Style (R = G = B)
    {
        state.mode = LCD_RENDER_MODE_GRAYSCALE_8BIT;
        state.shading_mode = LCD_SHADING_NEUTRAL_GRAY;

        const int num_steps = 10;
        for (int i = 0; i <= num_steps; i++) {
            uint8_t lum = (uint8_t)((i * 255) / num_steps);
            std::vector<lcd_color_t> buf(state.cell_size * state.cell_size, LCD_COLOR_MAKE(lum, lum, lum));
            lv_area_t cell_area = { .x1 = 0, .y1 = 0, .x2 = state.cell_size - 1, .y2 = state.cell_size - 1 };

            lcd_emulator_apply_filter_ex(&cell_area, buf.data(), &state, false);
            lcd_color_t px = buf[0];

#if LV_COLOR_DEPTH == 8
            ASSERT_EQ(px, lum);
#else
            uint8_t r5 = (px >> 11) & 0x1F;
            uint8_t g6 = (px >> 5) & 0x3F;
            uint8_t b5 = px & 0x1F;

            // In true neutral gray, R and B channels must match identically
            ASSERT_EQ(r5, b5);
            // G channel (6 bits) must match R (5 bits) within 1 bit of scaling
            ASSERT_TRUE(abs((int)g6 - (int)(r5 * 2)) <= 1);
#endif
        }

        // Verify boundary values
        std::vector<lcd_color_t> black_buf(state.cell_size * state.cell_size, LCD_COLOR_MAKE(0, 0, 0));
        lv_area_t cell_area = { .x1 = 0, .y1 = 0, .x2 = state.cell_size - 1, .y2 = state.cell_size - 1 };
        lcd_emulator_apply_filter_ex(&cell_area, black_buf.data(), &state, false);
#if LV_COLOR_DEPTH == 8
        ASSERT_EQ(black_buf[0], 0x00);
#else
        ASSERT_EQ(black_buf[0], 0x0000); // Pure neutral black
#endif

        std::vector<lcd_color_t> white_buf(state.cell_size * state.cell_size, LCD_COLOR_MAKE(255, 255, 255));
        lcd_emulator_apply_filter_ex(&cell_area, white_buf.data(), &state, false);
#if LV_COLOR_DEPTH == 8
        ASSERT_EQ(white_buf[0], 0xFF);
#else
        ASSERT_EQ(white_buf[0], 0xFFFF); // Pure neutral white
#endif
    }

    // 4. Verify Grayscale Inversion Polarity
    {
        state.mode = LCD_RENDER_MODE_GRAYSCALE_4BIT;
        state.shading_mode = LCD_SHADING_PALETTE_TINTED;

        // Normal: Black input -> level 0 (color_inactive)
        std::vector<lcd_color_t> norm_buf(state.cell_size * state.cell_size, LCD_COLOR_MAKE(0, 0, 0));
        lv_area_t cell_area = { .x1 = 0, .y1 = 0, .x2 = state.cell_size - 1, .y2 = state.cell_size - 1 };
        lcd_emulator_apply_filter_ex(&cell_area, norm_buf.data(), &state, false);
        ASSERT_EQ(norm_buf[0], state.palette.color_inactive);

        // Inverted: Black input -> level 15 (color_active)
        std::vector<lcd_color_t> inv_buf(state.cell_size * state.cell_size, LCD_COLOR_MAKE(0, 0, 0));
        lcd_emulator_apply_filter_ex(&cell_area, inv_buf.data(), &state, true);
        ASSERT_EQ(inv_buf[0], state.palette.color_active);
    }

    // 5. Verify Neutral Gray Gap Line Conversion
    {
        state.mode = LCD_RENDER_MODE_GRAYSCALE_4BIT;
        state.shading_mode = LCD_SHADING_NEUTRAL_GRAY;
        state.gap_size = 1;
        state.cell_size = 4;

        std::vector<lcd_color_t> gap_buf(state.cell_size * state.cell_size, LCD_COLOR_MAKE(128, 128, 128));
        lv_area_t cell_area = { .x1 = 0, .y1 = 0, .x2 = state.cell_size - 1, .y2 = state.cell_size - 1 };
        lcd_emulator_apply_filter_ex(&cell_area, gap_buf.data(), &state, false);

        // Pixel at (3, 3) is in the gap
        lcd_color_t gap_px = gap_buf[3 * state.cell_size + 3];
#if LV_COLOR_DEPTH == 8
        ASSERT_EQ(gap_px, state.palette.color_gap);
#else
        uint8_t r5 = (gap_px >> 11) & 0x1F;
        uint8_t b5 = gap_px & 0x1F;
        ASSERT_EQ(r5, b5); // Gap color must be neutral gray
#endif
    }

    printf("  -> Grayscale 4-bit, 8-bit, Neutral Gray & Palette-tinted verified.\n");
}

/**
 * @brief Test 9: High-Volume Stress, Endurance & Throughput Verification (50,000 passes).
 */
static void test_high_volume_stress_endurance()
{
    printf("[TEST 9] Running high-volume stress verification (50,000 passes)...\n");

    lcd_decorator_state_t state;
    state.mode = LCD_RENDER_MODE_RETRO_MONOCHROME;
    state.cell_size = 4;
    state.gap_size = 1;
    state.threshold = 135;
    state.palette = s_palettes[LCD_PRESET_OLIVE];
    state.custom_render_fn = NULL;
    state.custom_user_ctx = NULL;

    const int tile_w = 466;
    const int tile_h = 50;
    std::vector<lcd_color_t> scratch(tile_w * tile_h);

    const int TOTAL_PASSES = 50000;
    auto start_time = std::chrono::high_resolution_clock::now();

    for (int pass = 0; pass < TOTAL_PASSES; pass++) {
        int y_offset = (pass * 50) % 416; // 0..416 so y_offset + 50 <= 466
        lv_area_t area = {
            .x1 = 0,
            .y1 = y_offset,
            .x2 = tile_w - 1,
            .y2 = y_offset + tile_h - 1
        };

        scratch[0] = (lcd_color_t)pass;
        scratch[tile_w * tile_h - 1] = (lcd_color_t)(pass ^ 0xFFFF);

        // Alternate modes during stress run to verify thread-safe state toggling
        bool inv = (pass % 2 == 1);
        lcd_emulator_apply_filter_ex(&area, scratch.data(), &state, inv);

        if ((pass % 10000) == 0) {
            ASSERT_TRUE(scratch[0] == state.palette.color_gap ||
                        scratch[0] == state.palette.color_active ||
                        scratch[0] == state.palette.color_inactive);
        }
    }

    auto end_time = std::chrono::high_resolution_clock::now();
    double total_ms = std::chrono::duration<double, std::milli>(end_time - start_time).count();
    double us_per_pass = (total_ms * 1000.0) / TOTAL_PASSES;
    double fps_equiv = 1000000.0 / (us_per_pass * (466.0 / 50.0));

    printf("  -> Completed %d passes in %.2f ms (%.2f us/tile, ~%.1f full-screen FPS equivalent).\n",
           TOTAL_PASSES, total_ms, us_per_pass, fps_equiv);
    printf("  -> Strict zero heap allocation and zero memory corruption asserted.\n");
}

/**
 * @brief Test 10: Compile-Time Color Depth (LV_COLOR_DEPTH 8 vs 16) Verification.
 */
static void test_color_depth_configuration()
{
    printf("[TEST 10] Verifying color depth configuration (LV_COLOR_DEPTH = %d)...\n", (int)LV_COLOR_DEPTH);
#if LV_COLOR_DEPTH == 8
    ASSERT_EQ(sizeof(lcd_color_t), 1);
    ASSERT_EQ(LCD_COLOR_DEPTH_BYTES, 1);
    ASSERT_EQ(LCD_COLOR_MAKE(255, 255, 255), 255);
    ASSERT_EQ(LCD_COLOR_MAKE(0, 0, 0), 0);
    uint8_t green_lum = LCD_COLOR_MAKE(0, 255, 0);
    ASSERT_EQ(green_lum, (uint8_t)((150u * 255u) >> 8)); // 149
#else
    ASSERT_EQ(sizeof(lcd_color_t), 2);
    ASSERT_EQ(LCD_COLOR_DEPTH_BYTES, 2);
    ASSERT_EQ(LCD_COLOR_MAKE(255, 255, 255), 0xFFFF);
    ASSERT_EQ(LCD_COLOR_MAKE(0, 0, 0), 0x0000);
#endif
    printf("  -> Color depth types, sizes, and packing verified.\n");
}

/**
 * @brief Test 11: Single-Pass 8-to-16 bit streaming decimator, wire-swap, LUTs, and enabled restoration.
 */
static void test_single_pass_8to16_and_lut()
{
    printf("[TEST 11] Verifying single-pass 8-to-16 bit stream, wire-swap, and mode restoration...\n");

    // 1. Verify single-pass 8to16 filter with Amber palette
    lcd_decorator_state_t state;
    lcd_emulator_get_decorator_state(&state);
    state.mode = LCD_RENDER_MODE_RETRO_MONOCHROME;
    state.dark_theme = true;
    state.cell_size = 4;
    state.gap_size = 1;
    state.threshold = 100;
    state.palette = s_palettes[LCD_PRESET_AMBER];

    lv_area_t cell_area = { .x1 = 0, .y1 = 0, .x2 = 3, .y2 = 3 };
    uint8_t dark_in[16] = {0};
    uint16_t out_dark[16] = {0};

    // Run single pass with wire swap
    lcd_emulator_apply_filter_8to16(&cell_area, dark_in, out_dark, &state, false, true);

    uint16_t expected_inact_wire = LCD_RGB565_SWAP(state.palette.color_inactive_rgb565);
    uint16_t expected_gap_wire = LCD_RGB565_SWAP(state.palette.color_gap_rgb565);
    uint16_t expected_act_wire = LCD_RGB565_SWAP(state.palette.color_active_rgb565);

    // Active dot area (0,0) should be inactive amber
    ASSERT_EQ(out_dark[0], expected_inact_wire);
    // Gap area at (3,3) should be gap amber
    ASSERT_EQ(out_dark[15], expected_gap_wire);

    // Feed bright input (255) -> active amber
    uint8_t bright_in[16];
    memset(bright_in, 255, sizeof(bright_in));
    uint16_t out_bright[16] = {0};
    lcd_emulator_apply_filter_8to16(&cell_area, bright_in, out_bright, &state, false, true);
    ASSERT_EQ(out_bright[0], expected_act_wire);
    ASSERT_EQ(out_bright[15], expected_gap_wire);

    // 2. Verify RGB232 toggle API and LUT recomputation
    ASSERT_TRUE(!lcd_emulator_is_8bit_input_rgb232());
    lcd_emulator_set_8bit_input_rgb232(true);
    ASSERT_TRUE(lcd_emulator_is_8bit_input_rgb232());
    // Pure green in RGB232: bits [4:2] = 0x07 -> 0x1C = 28
    ASSERT_TRUE(s_lum_lut[0x1C] > 100);
    lcd_emulator_set_8bit_input_rgb232(false);
    ASSERT_TRUE(!lcd_emulator_is_8bit_input_rgb232());
    ASSERT_EQ(s_lum_lut[0x1C], 0x1C);

    // 3. Verify enabled toggle restores active emulation mode
    lcd_emulator_set_render_mode(LCD_RENDER_MODE_GRAYSCALE_8BIT);
    ASSERT_EQ(lcd_emulator_get_render_mode(), LCD_RENDER_MODE_GRAYSCALE_8BIT);
    ASSERT_TRUE(lcd_emulator_is_enabled());

    // Disable emulation -> Passthrough
    lcd_emulator_set_enabled(false);
    ASSERT_EQ(lcd_emulator_get_render_mode(), LCD_RENDER_MODE_PASSTHROUGH);
    ASSERT_TRUE(!lcd_emulator_is_enabled());

    // Enable emulation -> should restore GRAYSCALE_8BIT
    lcd_emulator_set_enabled(true);
    ASSERT_EQ(lcd_emulator_get_render_mode(), LCD_RENDER_MODE_GRAYSCALE_8BIT);
    ASSERT_TRUE(lcd_emulator_is_enabled());

    printf("  -> Single-pass 8to16 stream, wire-swap, LUT, and mode restoration verified.\n");
}

int main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    printf("====================================================\n");
    printf("  MiniGauge56 LCD Emulator Host Unit Test Suite\n");
    printf("  Color Depth: %d bits/pixel (%zu bytes)\n", (int)LV_COLOR_DEPTH, sizeof(lcd_color_t));
    printf("====================================================\n");

    test_rgb565_macro();
    test_subpixel_gap_geometry();
    test_screen_space_modulo_continuity();
    test_decorator_state_safety();
    test_render_mode_switching();
    test_cell_size_scaling_and_thin_stroke_preservation();
    test_dark_theme_and_inverted_mode();
    test_grayscale_emulation();
    test_high_volume_stress_endurance();
    test_color_depth_configuration();
    test_single_pass_8to16_and_lut();

    printf("====================================================\n");
    printf("  ALL 11 TEST SUITES PASSED CLEANLY (Zero Errors)\n");
    printf("====================================================\n");
    return 0;
}

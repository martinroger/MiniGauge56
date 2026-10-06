# Theory of Operation - Retro LCD Emulator Component (`TOO.MD`)

## 1. Overview & Purpose
The `lcd_emulator` component enables high-density color OLED/TFT displays running LVGL 9 (such as the 466×466 circular AMOLED on MiniGauge56) to emulate authentic monochrome dot-matrix reflective LCDs (e.g. Game Boy DMG, Nokia 5110, Casio digital watches, or industrial amber displays).

It achieves this through **screen-space modulo pixel decimation** and **procedural sub-pixel matrix gap modulation** during display flushing, without requiring changes to existing high-resolution vector UI layouts or modifying vendor display drivers in `managed_components/`.

---

## 2. Architecture & The Decorator Pattern

Vendor Board Support Packages (BSPs) typically register a hardware-specific flush function that transmits pixel maps directly to the display controller over SPI/QSPI DMA.

To interject without modifying read-only vendor components:
1. `lcd_emulator_init(disp)` inspects the active LVGL display handle `lv_display_t *disp`.
2. It retrieves the vendor's internal flush function pointer: `disp->flush_cb`.
3. It installs `lcd_decorator_flush_cb()` as the new active flush callback.
4. When LVGL completes rendering a dirty tile, `lcd_decorator_flush_cb()` is invoked.
5. If emulation is active, the dirty tile pixels are transformed in-place.
6. The buffer is forwarded to `s_orig_flush_cb()`, executing the native vendor DMA transmission pipeline.

```mermaid
sequenceDiagram
    autonumber
    participant LVGL as LVGL 9 Core (Task)
    participant Decorator as lcd_decorator_flush_cb
    participant Filter as lcd_emulator_apply_filter
    participant Vendor as Vendor Flush Callback (disp->flush_cb)
    participant Hardware as AMOLED Controller (DMA)

    LVGL->>Decorator: Flush request (area, px_map)
    alt Retro LCD Emulation Enabled
        Decorator->>Filter: In-place decimation & gap modulation(area, px_map)
        Filter-->>Decorator: Transformed RGB565 buffer
    end
    Decorator->>Vendor: Forward buffer (area, px_map)
    Vendor->>Hardware: esp_lcd_panel_draw_bitmap() (DMA)
    Hardware-->>LVGL: lv_display_flush_ready()
```

---

## 3. Screen-Space Modulo & Tile Boundary Continuity

In LVGL 9, displays typically operate in partial redraw mode (e.g., 50-line buffers). A dirty rectangle is defined by `area->x1`, `area->y1`, `area->x2`, `area->y2`.

If decimation were computed relative to the local buffer index `(x, y)`, partial redraws would suffer from phase distortion and seam artifacts.

To guarantee bit-exact spatial continuity across arbitrary tile boundaries:
1. Every calculation maps to absolute physical screen space:
   $$x_{\text{screen}} = \text{area}\rightarrow x_1 + x_{\text{local}}$$
   $$y_{\text{screen}} = \text{area}\rightarrow y_1 + y_{\text{local}}$$
2. Sub-pixel matrix gap condition:
   $$\text{is\_gap\_x} = (x_{\text{screen}} \pmod{\text{cell\_size}}) \ge (\text{cell\_size} - \text{gap\_size})$$
   $$\text{is\_gap\_y} = (y_{\text{screen}} \pmod{\text{cell\_size}}) \ge (\text{cell\_size} - \text{gap\_size})$$
3. Gap pixels receive the physical separator substrate color (`palette.color_gap`).

---

## 4. In-Place Band Processing (Multi-Pixel Box Sampling & Stroke Preservation)

When transforming a tile in-place, reading an anchor pixel from an earlier scanline that was already overwritten would cause state corruption. Furthermore, sampling only a single center pixel per cell causes thin 1px font strokes or needle vectors to be skipped (aliasing dropout).

To eliminate read corruption and preserve fine vector strokes with zero dynamic memory allocation:
1. The dirty tile is partitioned into horizontal cell bands of height $\le \text{cell\_size}$.
2. **Pass 1 (Read-Only Multi-Pixel Box Sampling)**:
   For every cell column $c$ in the band, the algorithm samples across the active non-gap pixels of the cell:
   - For dark-theme UIs (AMOLED `#000000` background with bright text):
     If ANY pixel within the cell has luminance $Y \ge \text{threshold}$, the cell is marked active ($1$), and scanning early-exits for that cell.
   - For light-theme UIs (white canvas with dark ink):
     If ANY pixel within the cell has luminance $Y < \text{threshold}$, the cell is marked active ($1$).
   - Luminance is computed using ITU-R BT.601 integer arithmetic:
     $$Y = (77 R + 150 G + 29 B) \gg 8$$
   - Inverted mode polarity inverts the active flag ($1 \leftrightarrow 0$).
   - The resulting states are cached in a statically allocated 256-byte stack array `cell_active[]`.
3. **Pass 2 (Write-Only Overwrite)**:
   All scanlines in the cell band are overwritten with `palette.color_gap`, `palette.color_active`, or `palette.color_inactive`.

This guarantees:
- Zero dynamic memory allocation (`malloc`/`free`) in the hot rendering path.
- Zero read-after-write hazards.
- Complete geometric preservation of fine 1px font stems, needles, and borders.
- Bit-exact visual reproduction across any buffer tile height.

---

## 5. Single-Pass 8-to-16 Streaming Decimator & Wire Endianness

When compiling with `LV_COLOR_DEPTH == 8` and `CONFIG_LCD_EMULATOR_EXPAND_TO_RGB565` enabled, the pipeline previously required two sequential buffer passes:
1. In-place 8-bit decimation (`lcd_emulator_apply_filter`) modifying the LVGL draw buffer.
2. Naive 8-to-16 bit expansion copying into a secondary panel buffer (`s_rgb565_buf`).

### Single-Pass Architecture (`lcd_emulator_apply_filter_8to16`)
The engine replaces this two-pass pipeline with a single-pass streaming kernel:
- **Zero In-Place Mutation**: The 8-bit LVGL draw buffer (`pixels_8`) is treated as read-only.
- **Direct Scanline Streaming**: The kernel performs box-sampling across the 8-bit input tile and directly writes 16-bit RGB565 output pixels into `s_rgb565_buf`.
- **Wire-Endianness Pre-Swapping**: Hardware controllers such as the CO5300 AMOLED on QSPI/SPI DMA expect big-endian byte order (high byte followed by low byte). When LVGL operates in 8-bit mode (`LV_COLOR_FORMAT_L8`), driver bridges (such as `esp_lv_adapter`) bypass `lv_draw_sw_rgb565_swap()`. To prevent color bit translocation (which previously caused black backgrounds to display bright green and bright text to display purple), the streaming kernel applies `LCD_RGB565_SWAP()` at pixel emission time:
  $$\text{wire\_pixel} = ((\text{pixel} \gg 8) \ \& \ 0\text{x}00\text{FF}) \mid ((\text{pixel} \ll 8) \ \& \ 0\text{xFF}00)$$
- **Full 16-Bit Palette Fidelity**: Active, inactive, and gap colors retain their unquantized 16-bit RGB565 definitions (`color_active_rgb565`, `color_inactive_rgb565`, `color_gap_rgb565`), ensuring authentic Amber, Olive, Cyan, and Casio hues without 8-bit color quantization artifacts.

```mermaid
flowchart LR
    LVGL["8-bit LVGL Draw Buffer (L8 / RGB232)"] --> Decimator["lcd_emulator_apply_filter_8to16()<br/>Single-Pass Box Sampling & Decimation"]
    LUT["s_lum_lut[256]<br/>Luminance Weight Table"] -.-> Decimator
    Decimator --> WireSwap["LCD_RGB565_SWAP()<br/>SPI Wire Endianness Byte Swap"]
    WireSwap --> PanelBuf["16-bit RGB565 Panel Buffer (s_rgb565_buf)"]
    PanelBuf --> DMA["CO5300 AMOLED Panel (SPI/QSPI DMA)"]
```

---

## 6. Dual 8-Bit Color Encoding & Precomputed Lookup Tables

LVGL 9 native 8-bit color depth uses `LV_COLOR_FORMAT_L8` (pure 8-bit luminance), whereas LVGL 8 historically utilized `RGB232`. To ensure seamless compatibility with both workflows without runtime branching in inner loops:

1. **Luminance LUT (`s_lum_lut[256]`)**:
   - In L8 mode: Identity mapping ($Y = i$).
   - In RGB232 mode: Precomputed ITU-R BT.601 integer luminance:
     $$Y = (77 \cdot R_8 + 150 \cdot G_8 + 29 \cdot B_8) \gg 8$$
     where $R_8 = (i \gg 5) \cdot 255 / 7$, $G_8 = ((i \gg 2) \& 7) \cdot 255 / 7$, and $B_8 = (i \& 3) \cdot 255 / 3$.

2. **Passthrough LUT (`s_passthrough_lut[256]`)**:
   - In passthrough mode (retro emulation disabled), the 8-bit buffer is mapped into 16-bit wire-swapped RGB565 via a 256-word lookup table in a single memory pass.
   - In L8 mode: Expands grayscale intensity $Y$ to $R=Y, G=Y, B=Y$ in swapped RGB565.
   - In RGB232 mode: Expands 8-bit color directly to full 16-bit swapped RGB565.


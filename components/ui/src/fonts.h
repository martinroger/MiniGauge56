#ifndef EEZ_LVGL_UI_FONTS_H
#define EEZ_LVGL_UI_FONTS_H

#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

extern const lv_font_t ui_font_league_192px;
extern const lv_font_t ui_font_league_120px;
extern const lv_font_t ui_font_league_96px;
extern const lv_font_t ui_font_league_48px;
extern const lv_font_t ui_font_league_42px;
extern const lv_font_t ui_font_teko_36px;

#ifndef EXT_FONT_DESC_T
#define EXT_FONT_DESC_T
typedef struct _ext_font_desc_t {
    const char *name;
    const void *font_ptr;
} ext_font_desc_t;
#endif

extern ext_font_desc_t fonts[];

#ifdef __cplusplus
}
#endif

#endif /*EEZ_LVGL_UI_FONTS_H*/
#ifndef EEZ_LVGL_UI_STYLES_H
#define EEZ_LVGL_UI_STYLES_H

#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

// Style: mg_screen
lv_style_t *get_style_mg_screen_MAIN_DEFAULT();
void add_style_mg_screen(lv_obj_t *obj);
void remove_style_mg_screen(lv_obj_t *obj);

// Style: mg_text_value_192
lv_style_t *get_style_mg_text_value_192_MAIN_DEFAULT();
void add_style_mg_text_value_192(lv_obj_t *obj);
void remove_style_mg_text_value_192(lv_obj_t *obj);

// Style: mg_text_value_120
lv_style_t *get_style_mg_text_value_120_MAIN_DEFAULT();
void add_style_mg_text_value_120(lv_obj_t *obj);
void remove_style_mg_text_value_120(lv_obj_t *obj);

// Style: mg_text_value_96
lv_style_t *get_style_mg_text_value_96_MAIN_DEFAULT();
void add_style_mg_text_value_96(lv_obj_t *obj);
void remove_style_mg_text_value_96(lv_obj_t *obj);

// Style: mg_text_label_48
lv_style_t *get_style_mg_text_label_48_MAIN_DEFAULT();
void add_style_mg_text_label_48(lv_obj_t *obj);
void remove_style_mg_text_label_48(lv_obj_t *obj);

// Style: mg_text_caption_42
lv_style_t *get_style_mg_text_caption_42_MAIN_DEFAULT();
void add_style_mg_text_caption_42(lv_obj_t *obj);
void remove_style_mg_text_caption_42(lv_obj_t *obj);

// Style: mg_text_status
lv_style_t *get_style_mg_text_status_MAIN_DEFAULT();
void add_style_mg_text_status(lv_obj_t *obj);
void remove_style_mg_text_status(lv_obj_t *obj);

// Style: mg_switch
lv_style_t *get_style_mg_switch_MAIN_DEFAULT();
lv_style_t *get_style_mg_switch_MAIN_CHECKED();
lv_style_t *get_style_mg_switch_MAIN_FOCUSED();
lv_style_t *get_style_mg_switch_MAIN_FOCUS_KEY();
lv_style_t *get_style_mg_switch_MAIN_PRESSED();
lv_style_t *get_style_mg_switch_MAIN_CHECKED_PRESSED();
lv_style_t *get_style_mg_switch_INDICATOR_DEFAULT();
lv_style_t *get_style_mg_switch_INDICATOR_CHECKED();
lv_style_t *get_style_mg_switch_KNOB_DEFAULT();
lv_style_t *get_style_mg_switch_KNOB_CHECKED();
void add_style_mg_switch(lv_obj_t *obj);
void remove_style_mg_switch(lv_obj_t *obj);

// Style: mg_arc
lv_style_t *get_style_mg_arc_MAIN_DEFAULT();
lv_style_t *get_style_mg_arc_INDICATOR_DEFAULT();
lv_style_t *get_style_mg_arc_KNOB_DEFAULT();
void add_style_mg_arc(lv_obj_t *obj);
void remove_style_mg_arc(lv_obj_t *obj);

// Style: mg_scale
lv_style_t *get_style_mg_scale_MAIN_DEFAULT();
lv_style_t *get_style_mg_scale_INDICATOR_DEFAULT();
lv_style_t *get_style_mg_scale_ITEMS_DEFAULT();
void add_style_mg_scale(lv_obj_t *obj);
void remove_style_mg_scale(lv_obj_t *obj);

// Style: mg_rule
lv_style_t *get_style_mg_rule_MAIN_DEFAULT();
void add_style_mg_rule(lv_obj_t *obj);
void remove_style_mg_rule(lv_obj_t *obj);

#ifdef __cplusplus
}
#endif

#endif /*EEZ_LVGL_UI_STYLES_H*/
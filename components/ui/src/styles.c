#include "styles.h"
#include "images.h"
#include "fonts.h"

#include "ui.h"
#include "screens.h"

//
// Style: mg_screen
//

void init_style_mg_screen_MAIN_DEFAULT(lv_style_t *style) {
    lv_style_set_bg_color(style, lv_color_hex(0x000000));
    lv_style_set_pad_top(style, 0);
    lv_style_set_pad_bottom(style, 0);
    lv_style_set_pad_left(style, 0);
    lv_style_set_pad_right(style, 0);
    lv_style_set_pad_row(style, 0);
    lv_style_set_pad_column(style, 0);
    lv_style_set_border_width(style, 0);
    lv_style_set_outline_width(style, 0);
    lv_style_set_shadow_width(style, 0);
};

lv_style_t *get_style_mg_screen_MAIN_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_screen_MAIN_DEFAULT(style);
    }
    return style;
};

void add_style_mg_screen(lv_obj_t *obj) {
    (void)obj;
    lv_obj_add_style(obj, get_style_mg_screen_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

void remove_style_mg_screen(lv_obj_t *obj) {
    (void)obj;
    lv_obj_remove_style(obj, get_style_mg_screen_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

//
// Style: mg_text_value_192
//

void init_style_mg_text_value_192_MAIN_DEFAULT(lv_style_t *style) {
    lv_style_set_text_color(style, lv_color_hex(0xffffff));
    lv_style_set_text_font(style, &ui_font_league_192px);
    lv_style_set_text_align(style, LV_TEXT_ALIGN_CENTER);
    lv_style_set_align(style, LV_ALIGN_CENTER);
};

lv_style_t *get_style_mg_text_value_192_MAIN_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_text_value_192_MAIN_DEFAULT(style);
    }
    return style;
};

void add_style_mg_text_value_192(lv_obj_t *obj) {
    (void)obj;
    lv_obj_add_style(obj, get_style_mg_text_value_192_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

void remove_style_mg_text_value_192(lv_obj_t *obj) {
    (void)obj;
    lv_obj_remove_style(obj, get_style_mg_text_value_192_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

//
// Style: mg_text_value_120
//

void init_style_mg_text_value_120_MAIN_DEFAULT(lv_style_t *style) {
    lv_style_set_text_color(style, lv_color_hex(0xffffff));
    lv_style_set_text_font(style, &ui_font_league_120px);
    lv_style_set_text_align(style, LV_TEXT_ALIGN_CENTER);
    lv_style_set_align(style, LV_ALIGN_CENTER);
};

lv_style_t *get_style_mg_text_value_120_MAIN_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_text_value_120_MAIN_DEFAULT(style);
    }
    return style;
};

void add_style_mg_text_value_120(lv_obj_t *obj) {
    (void)obj;
    lv_obj_add_style(obj, get_style_mg_text_value_120_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

void remove_style_mg_text_value_120(lv_obj_t *obj) {
    (void)obj;
    lv_obj_remove_style(obj, get_style_mg_text_value_120_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

//
// Style: mg_text_value_96
//

void init_style_mg_text_value_96_MAIN_DEFAULT(lv_style_t *style) {
    lv_style_set_text_color(style, lv_color_hex(0xffffff));
    lv_style_set_text_font(style, &ui_font_league_96px);
    lv_style_set_text_align(style, LV_TEXT_ALIGN_CENTER);
    lv_style_set_align(style, LV_ALIGN_CENTER);
};

lv_style_t *get_style_mg_text_value_96_MAIN_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_text_value_96_MAIN_DEFAULT(style);
    }
    return style;
};

void add_style_mg_text_value_96(lv_obj_t *obj) {
    (void)obj;
    lv_obj_add_style(obj, get_style_mg_text_value_96_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

void remove_style_mg_text_value_96(lv_obj_t *obj) {
    (void)obj;
    lv_obj_remove_style(obj, get_style_mg_text_value_96_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

//
// Style: mg_text_label_48
//

void init_style_mg_text_label_48_MAIN_DEFAULT(lv_style_t *style) {
    lv_style_set_text_color(style, lv_color_hex(0xffffff));
    lv_style_set_text_font(style, &ui_font_league_48px);
    lv_style_set_text_align(style, LV_TEXT_ALIGN_CENTER);
    lv_style_set_text_letter_space(style, 3);
    lv_style_set_align(style, LV_ALIGN_CENTER);
};

lv_style_t *get_style_mg_text_label_48_MAIN_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_text_label_48_MAIN_DEFAULT(style);
    }
    return style;
};

void add_style_mg_text_label_48(lv_obj_t *obj) {
    (void)obj;
    lv_obj_add_style(obj, get_style_mg_text_label_48_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

void remove_style_mg_text_label_48(lv_obj_t *obj) {
    (void)obj;
    lv_obj_remove_style(obj, get_style_mg_text_label_48_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

//
// Style: mg_text_caption_42
//

void init_style_mg_text_caption_42_MAIN_DEFAULT(lv_style_t *style) {
    lv_style_set_text_color(style, lv_color_hex(0xffffff));
    lv_style_set_text_font(style, &ui_font_league_42px);
    lv_style_set_text_letter_space(style, 3);
    lv_style_set_text_align(style, LV_TEXT_ALIGN_CENTER);
    lv_style_set_align(style, LV_ALIGN_CENTER);
};

lv_style_t *get_style_mg_text_caption_42_MAIN_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_text_caption_42_MAIN_DEFAULT(style);
    }
    return style;
};

void add_style_mg_text_caption_42(lv_obj_t *obj) {
    (void)obj;
    lv_obj_add_style(obj, get_style_mg_text_caption_42_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

void remove_style_mg_text_caption_42(lv_obj_t *obj) {
    (void)obj;
    lv_obj_remove_style(obj, get_style_mg_text_caption_42_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

//
// Style: mg_text_status
//

void init_style_mg_text_status_MAIN_DEFAULT(lv_style_t *style) {
    lv_style_set_text_color(style, lv_color_hex(0xcccccc));
    lv_style_set_text_font(style, &ui_font_teko_36px);
    lv_style_set_text_letter_space(style, 3);
    lv_style_set_text_align(style, LV_TEXT_ALIGN_CENTER);
    lv_style_set_align(style, LV_ALIGN_CENTER);
};

lv_style_t *get_style_mg_text_status_MAIN_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_text_status_MAIN_DEFAULT(style);
    }
    return style;
};

void add_style_mg_text_status(lv_obj_t *obj) {
    (void)obj;
    lv_obj_add_style(obj, get_style_mg_text_status_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

void remove_style_mg_text_status(lv_obj_t *obj) {
    (void)obj;
    lv_obj_remove_style(obj, get_style_mg_text_status_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

//
// Style: mg_switch
//

void init_style_mg_switch_MAIN_DEFAULT(lv_style_t *style) {
    lv_style_set_height(style, 132);
    lv_style_set_width(style, 72);
    lv_style_set_bg_opa(style, 0);
    lv_style_set_border_color(style, lv_color_hex(0xcccccc));
    lv_style_set_border_width(style, 6);
    lv_style_set_radius(style, 12);
    lv_style_set_outline_width(style, 0);
    lv_style_set_shadow_width(style, 0);
    lv_style_set_anim_duration(style, 0);
    lv_style_set_align(style, LV_ALIGN_CENTER);
};

lv_style_t *get_style_mg_switch_MAIN_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_switch_MAIN_DEFAULT(style);
    }
    return style;
};

void init_style_mg_switch_MAIN_CHECKED(lv_style_t *style) {
    lv_style_set_border_width(style, 0);
};

lv_style_t *get_style_mg_switch_MAIN_CHECKED() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_switch_MAIN_CHECKED(style);
    }
    return style;
};

void init_style_mg_switch_MAIN_FOCUSED(lv_style_t *style) {
    lv_style_set_outline_width(style, 0);
};

lv_style_t *get_style_mg_switch_MAIN_FOCUSED() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_switch_MAIN_FOCUSED(style);
    }
    return style;
};

void init_style_mg_switch_MAIN_FOCUS_KEY(lv_style_t *style) {
    lv_style_set_outline_width(style, 0);
};

lv_style_t *get_style_mg_switch_MAIN_FOCUS_KEY() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_switch_MAIN_FOCUS_KEY(style);
    }
    return style;
};

void init_style_mg_switch_MAIN_PRESSED(lv_style_t *style) {
    lv_style_set_anim_duration(style, 0);
};

lv_style_t *get_style_mg_switch_MAIN_PRESSED() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_switch_MAIN_PRESSED(style);
    }
    return style;
};

void init_style_mg_switch_MAIN_CHECKED_PRESSED(lv_style_t *style) {
    lv_style_set_anim_duration(style, 0);
};

lv_style_t *get_style_mg_switch_MAIN_CHECKED_PRESSED() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_switch_MAIN_CHECKED_PRESSED(style);
    }
    return style;
};

void init_style_mg_switch_INDICATOR_DEFAULT(lv_style_t *style) {
    lv_style_set_bg_opa(style, 0);
};

lv_style_t *get_style_mg_switch_INDICATOR_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_switch_INDICATOR_DEFAULT(style);
    }
    return style;
};

void init_style_mg_switch_INDICATOR_CHECKED(lv_style_t *style) {
    lv_style_set_bg_color(style, lv_color_hex(0xffffff));
    lv_style_set_bg_opa(style, 255);
    lv_style_set_radius(style, 12);
};

lv_style_t *get_style_mg_switch_INDICATOR_CHECKED() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_switch_INDICATOR_CHECKED(style);
    }
    return style;
};

void init_style_mg_switch_KNOB_DEFAULT(lv_style_t *style) {
    lv_style_set_bg_opa(style, 0);
    lv_style_set_border_color(style, lv_color_hex(0xcccccc));
    lv_style_set_border_width(style, 6);
    lv_style_set_radius(style, 9);
    lv_style_set_pad_top(style, -9);
    lv_style_set_pad_bottom(style, -9);
    lv_style_set_pad_left(style, -9);
    lv_style_set_pad_right(style, -9);
    lv_style_set_shadow_width(style, 0);
};

lv_style_t *get_style_mg_switch_KNOB_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_switch_KNOB_DEFAULT(style);
    }
    return style;
};

void init_style_mg_switch_KNOB_CHECKED(lv_style_t *style) {
    lv_style_set_bg_opa(style, 255);
    lv_style_set_bg_color(style, lv_color_hex(0x000000));
    lv_style_set_border_width(style, 0);
};

lv_style_t *get_style_mg_switch_KNOB_CHECKED() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_switch_KNOB_CHECKED(style);
    }
    return style;
};

void add_style_mg_switch(lv_obj_t *obj) {
    (void)obj;
    lv_obj_add_style(obj, get_style_mg_switch_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_add_style(obj, get_style_mg_switch_MAIN_CHECKED(), LV_PART_MAIN | LV_STATE_CHECKED);
    lv_obj_add_style(obj, get_style_mg_switch_MAIN_FOCUSED(), LV_PART_MAIN | LV_STATE_FOCUSED);
    lv_obj_add_style(obj, get_style_mg_switch_MAIN_FOCUS_KEY(), LV_PART_MAIN | LV_STATE_FOCUS_KEY);
    lv_obj_add_style(obj, get_style_mg_switch_MAIN_PRESSED(), LV_PART_MAIN | LV_STATE_PRESSED);
    lv_obj_add_style(obj, get_style_mg_switch_MAIN_CHECKED_PRESSED(), LV_PART_MAIN | LV_STATE_CHECKED | LV_STATE_PRESSED);
    lv_obj_add_style(obj, get_style_mg_switch_INDICATOR_DEFAULT(), LV_PART_INDICATOR | LV_STATE_DEFAULT);
    lv_obj_add_style(obj, get_style_mg_switch_INDICATOR_CHECKED(), LV_PART_INDICATOR | LV_STATE_CHECKED);
    lv_obj_add_style(obj, get_style_mg_switch_KNOB_DEFAULT(), LV_PART_KNOB | LV_STATE_DEFAULT);
    lv_obj_add_style(obj, get_style_mg_switch_KNOB_CHECKED(), LV_PART_KNOB | LV_STATE_CHECKED);
};

void remove_style_mg_switch(lv_obj_t *obj) {
    (void)obj;
    lv_obj_remove_style(obj, get_style_mg_switch_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_remove_style(obj, get_style_mg_switch_MAIN_CHECKED(), LV_PART_MAIN | LV_STATE_CHECKED);
    lv_obj_remove_style(obj, get_style_mg_switch_MAIN_FOCUSED(), LV_PART_MAIN | LV_STATE_FOCUSED);
    lv_obj_remove_style(obj, get_style_mg_switch_MAIN_FOCUS_KEY(), LV_PART_MAIN | LV_STATE_FOCUS_KEY);
    lv_obj_remove_style(obj, get_style_mg_switch_MAIN_PRESSED(), LV_PART_MAIN | LV_STATE_PRESSED);
    lv_obj_remove_style(obj, get_style_mg_switch_MAIN_CHECKED_PRESSED(), LV_PART_MAIN | LV_STATE_CHECKED | LV_STATE_PRESSED);
    lv_obj_remove_style(obj, get_style_mg_switch_INDICATOR_DEFAULT(), LV_PART_INDICATOR | LV_STATE_DEFAULT);
    lv_obj_remove_style(obj, get_style_mg_switch_INDICATOR_CHECKED(), LV_PART_INDICATOR | LV_STATE_CHECKED);
    lv_obj_remove_style(obj, get_style_mg_switch_KNOB_DEFAULT(), LV_PART_KNOB | LV_STATE_DEFAULT);
    lv_obj_remove_style(obj, get_style_mg_switch_KNOB_CHECKED(), LV_PART_KNOB | LV_STATE_CHECKED);
};

//
// Style: mg_arc
//

void init_style_mg_arc_MAIN_DEFAULT(lv_style_t *style) {
    lv_style_set_arc_width(style, 12);
    lv_style_set_arc_color(style, lv_color_hex(0x333333));
    lv_style_set_arc_rounded(style, false);
    lv_style_set_bg_opa(style, 0);
    lv_style_set_pad_top(style, 0);
    lv_style_set_pad_bottom(style, 0);
    lv_style_set_pad_left(style, 0);
    lv_style_set_pad_right(style, 0);
    lv_style_set_align(style, LV_ALIGN_CENTER);
    lv_style_set_width(style, 376);
    lv_style_set_height(style, 376);
};

lv_style_t *get_style_mg_arc_MAIN_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_arc_MAIN_DEFAULT(style);
    }
    return style;
};

void init_style_mg_arc_INDICATOR_DEFAULT(lv_style_t *style) {
    lv_style_set_arc_width(style, 12);
    lv_style_set_arc_color(style, lv_color_hex(0xffffff));
    lv_style_set_arc_rounded(style, false);
    lv_style_set_pad_top(style, 0);
    lv_style_set_pad_bottom(style, 0);
    lv_style_set_pad_left(style, 0);
    lv_style_set_pad_right(style, 0);
};

lv_style_t *get_style_mg_arc_INDICATOR_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_arc_INDICATOR_DEFAULT(style);
    }
    return style;
};

void init_style_mg_arc_KNOB_DEFAULT(lv_style_t *style) {
    lv_style_set_bg_opa(style, 0);
    lv_style_set_pad_top(style, 0);
    lv_style_set_pad_bottom(style, 0);
    lv_style_set_pad_left(style, 0);
    lv_style_set_pad_right(style, 0);
};

lv_style_t *get_style_mg_arc_KNOB_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_arc_KNOB_DEFAULT(style);
    }
    return style;
};

void add_style_mg_arc(lv_obj_t *obj) {
    (void)obj;
    lv_obj_add_style(obj, get_style_mg_arc_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_add_style(obj, get_style_mg_arc_INDICATOR_DEFAULT(), LV_PART_INDICATOR | LV_STATE_DEFAULT);
    lv_obj_add_style(obj, get_style_mg_arc_KNOB_DEFAULT(), LV_PART_KNOB | LV_STATE_DEFAULT);
};

void remove_style_mg_arc(lv_obj_t *obj) {
    (void)obj;
    lv_obj_remove_style(obj, get_style_mg_arc_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_remove_style(obj, get_style_mg_arc_INDICATOR_DEFAULT(), LV_PART_INDICATOR | LV_STATE_DEFAULT);
    lv_obj_remove_style(obj, get_style_mg_arc_KNOB_DEFAULT(), LV_PART_KNOB | LV_STATE_DEFAULT);
};

//
// Style: mg_scale
//

void init_style_mg_scale_MAIN_DEFAULT(lv_style_t *style) {
    lv_style_set_arc_width(style, 0);
    lv_style_set_bg_opa(style, 0);
};

lv_style_t *get_style_mg_scale_MAIN_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_scale_MAIN_DEFAULT(style);
    }
    return style;
};

void init_style_mg_scale_INDICATOR_DEFAULT(lv_style_t *style) {
    lv_style_set_length(style, 30);
    lv_style_set_line_width(style, 6);
    lv_style_set_line_color(style, lv_color_hex(0xcccccc));
    lv_style_set_line_rounded(style, false);
};

lv_style_t *get_style_mg_scale_INDICATOR_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_scale_INDICATOR_DEFAULT(style);
    }
    return style;
};

void init_style_mg_scale_ITEMS_DEFAULT(lv_style_t *style) {
    lv_style_set_length(style, 12);
    lv_style_set_line_width(style, 3);
    lv_style_set_line_color(style, lv_color_hex(0x808080));
};

lv_style_t *get_style_mg_scale_ITEMS_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_scale_ITEMS_DEFAULT(style);
    }
    return style;
};

void add_style_mg_scale(lv_obj_t *obj) {
    (void)obj;
    lv_obj_add_style(obj, get_style_mg_scale_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_add_style(obj, get_style_mg_scale_INDICATOR_DEFAULT(), LV_PART_INDICATOR | LV_STATE_DEFAULT);
    lv_obj_add_style(obj, get_style_mg_scale_ITEMS_DEFAULT(), LV_PART_ITEMS | LV_STATE_DEFAULT);
};

void remove_style_mg_scale(lv_obj_t *obj) {
    (void)obj;
    lv_obj_remove_style(obj, get_style_mg_scale_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_remove_style(obj, get_style_mg_scale_INDICATOR_DEFAULT(), LV_PART_INDICATOR | LV_STATE_DEFAULT);
    lv_obj_remove_style(obj, get_style_mg_scale_ITEMS_DEFAULT(), LV_PART_ITEMS | LV_STATE_DEFAULT);
};

//
// Style: mg_rule
//

void init_style_mg_rule_MAIN_DEFAULT(lv_style_t *style) {
    lv_style_set_line_width(style, 3);
    lv_style_set_line_color(style, lv_color_hex(0x666666));
    lv_style_set_line_rounded(style, false);
};

lv_style_t *get_style_mg_rule_MAIN_DEFAULT() {
    static lv_style_t *style;
    if (!style) {
        style = (lv_style_t *)lv_malloc(sizeof(lv_style_t));
        lv_style_init(style);
        init_style_mg_rule_MAIN_DEFAULT(style);
    }
    return style;
};

void add_style_mg_rule(lv_obj_t *obj) {
    (void)obj;
    lv_obj_add_style(obj, get_style_mg_rule_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

void remove_style_mg_rule(lv_obj_t *obj) {
    (void)obj;
    lv_obj_remove_style(obj, get_style_mg_rule_MAIN_DEFAULT(), LV_PART_MAIN | LV_STATE_DEFAULT);
};

//
//
//

void add_style(lv_obj_t *obj, int32_t styleIndex) {
    typedef void (*AddStyleFunc)(lv_obj_t *obj);
    static const AddStyleFunc add_style_funcs[] = {
        add_style_mg_screen,
        add_style_mg_text_value_192,
        add_style_mg_text_value_120,
        add_style_mg_text_value_96,
        add_style_mg_text_label_48,
        add_style_mg_text_caption_42,
        add_style_mg_text_status,
        add_style_mg_switch,
        add_style_mg_arc,
        add_style_mg_scale,
        add_style_mg_rule,
    };
    add_style_funcs[styleIndex](obj);
}

void remove_style(lv_obj_t *obj, int32_t styleIndex) {
    typedef void (*RemoveStyleFunc)(lv_obj_t *obj);
    static const RemoveStyleFunc remove_style_funcs[] = {
        remove_style_mg_screen,
        remove_style_mg_text_value_192,
        remove_style_mg_text_value_120,
        remove_style_mg_text_value_96,
        remove_style_mg_text_label_48,
        remove_style_mg_text_caption_42,
        remove_style_mg_text_status,
        remove_style_mg_switch,
        remove_style_mg_arc,
        remove_style_mg_scale,
        remove_style_mg_rule,
    };
    remove_style_funcs[styleIndex](obj);
}
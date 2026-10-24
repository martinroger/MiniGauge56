#include <string.h>

#include "screens.h"
#include "images.h"
#include "fonts.h"
#include "actions.h"
#include "vars.h"
#include "styles.h"
#include "ui.h"

static void event_handler_cb_main_backlight_sw(lv_event_t *e) {
    
}

#include <string.h>

objects_t objects;

//
// Event handlers
//

lv_obj_t *tick_value_change_obj;

static void event_handler_checked_cb_main_backlight_sw(lv_event_t *e) {
    if (lv_obj_has_state(lv_event_get_target_obj(e), LV_STATE_CHECKED)) {
        action_backlight_sw_checked(e);
    }
}

static void event_handler_unchecked_cb_main_backlight_sw(lv_event_t *e) {
    if (!lv_obj_has_state(lv_event_get_target_obj(e), LV_STATE_CHECKED)) {
        action_backlight_sw_unchecked(e);
    }
}

//
// Screens
//

void create_screen_loading() {
    lv_obj_t *obj = lv_obj_create(0);
    objects.loading = obj;
    lv_obj_set_pos(obj, 0, 0);
    lv_obj_set_size(obj, 466, 466);
    add_style_mg_screen(obj);
    {
        lv_obj_t *parent_obj = obj;
        {
            // load_0_25
            lv_obj_t *obj = lv_arc_create(parent_obj);
            objects.load_0_25 = obj;
            lv_obj_set_pos(obj, 0, 0);
            lv_obj_set_size(obj, 426, 426);
            lv_arc_set_value(obj, 0);
            lv_arc_set_bg_start_angle(obj, 0);
            lv_arc_set_bg_end_angle(obj, 360);
            lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
            add_style_mg_arc(obj);
            lv_obj_set_style_arc_width(obj, 24, LV_PART_MAIN | LV_STATE_DEFAULT);
            lv_obj_set_style_arc_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
        }
        {
            // load_25_50
            lv_obj_t *obj = lv_arc_create(parent_obj);
            objects.load_25_50 = obj;
            lv_obj_set_pos(obj, 0, 0);
            lv_obj_set_size(obj, 342, 342);
            lv_arc_set_value(obj, 0);
            lv_arc_set_bg_start_angle(obj, 0);
            lv_arc_set_bg_end_angle(obj, 360);
            lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
            add_style_mg_arc(obj);
            lv_obj_set_style_arc_width(obj, 24, LV_PART_MAIN | LV_STATE_DEFAULT);
            lv_obj_set_style_arc_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
        }
        {
            // load_50_75
            lv_obj_t *obj = lv_arc_create(parent_obj);
            objects.load_50_75 = obj;
            lv_obj_set_pos(obj, 0, 0);
            lv_obj_set_size(obj, 258, 258);
            lv_arc_set_value(obj, 0);
            lv_arc_set_bg_start_angle(obj, 0);
            lv_arc_set_bg_end_angle(obj, 360);
            lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
            add_style_mg_arc(obj);
            lv_obj_set_style_arc_width(obj, 24, LV_PART_MAIN | LV_STATE_DEFAULT);
            lv_obj_set_style_arc_color(obj, lv_color_hex(0x808080), LV_PART_MAIN | LV_STATE_DEFAULT);
        }
        {
            // load_75_100
            lv_obj_t *obj = lv_arc_create(parent_obj);
            objects.load_75_100 = obj;
            lv_obj_set_pos(obj, 0, 0);
            lv_obj_set_size(obj, 174, 174);
            lv_arc_set_value(obj, 0);
            lv_arc_set_bg_start_angle(obj, 0);
            lv_arc_set_bg_end_angle(obj, 360);
            lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
            add_style_mg_arc(obj);
            lv_obj_set_style_arc_width(obj, 24, LV_PART_MAIN | LV_STATE_DEFAULT);
            lv_obj_set_style_arc_color(obj, lv_color_hex(0x666666), LV_PART_MAIN | LV_STATE_DEFAULT);
        }
    }
    
    tick_screen_loading();
}

void tick_screen_loading() {
}

void create_screen_main() {
    lv_obj_t *obj = lv_obj_create(0);
    objects.main = obj;
    lv_obj_set_pos(obj, 0, 0);
    lv_obj_set_size(obj, 466, 466);
    lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
    add_style_mg_screen(obj);
    lv_obj_set_style_bg_color(obj, lv_color_hex(0x000000), LV_PART_MAIN | LV_STATE_DEFAULT);
    {
        lv_obj_t *parent_obj = obj;
        {
            // global_tabview
            lv_obj_t *obj = lv_tabview_create(parent_obj);
            objects.global_tabview = obj;
            lv_obj_set_pos(obj, 0, 0);
            lv_obj_set_size(obj, LV_PCT(100), LV_PCT(100));
            lv_tabview_set_tab_bar_position(obj, LV_DIR_TOP);
            lv_tabview_set_tab_bar_size(obj, 0);
            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
            lv_obj_set_scrollbar_mode(obj, LV_SCROLLBAR_MODE_OFF);
            lv_obj_set_scroll_dir(obj, LV_DIR_HOR);
            lv_obj_set_style_bg_color(obj, lv_color_hex(0x000000), LV_PART_MAIN | LV_STATE_DEFAULT);
            {
                lv_obj_t *parent_obj = obj;
                {
                    lv_obj_t *obj = lv_tabview_add_tab(parent_obj, "engine_temp");
                    lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                    lv_obj_set_scrollbar_mode(obj, LV_SCROLLBAR_MODE_OFF);
                    lv_obj_set_scroll_dir(obj, LV_DIR_NONE);
                    {
                        lv_obj_t *parent_obj = obj;
                        {
                            lv_obj_t *obj = lv_scale_create(parent_obj);
                            objects.obj0 = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 448, 448);
                            lv_scale_set_mode(obj, LV_SCALE_MODE_ROUND_INNER);
                            lv_scale_set_range(obj, 10, 40);
                            lv_scale_set_angle_range(obj, 210);
                            lv_scale_set_rotation(obj, 165);
                            lv_scale_set_total_tick_count(obj, 15);
                            lv_scale_set_major_tick_every(obj, 2);
                            lv_scale_set_label_show(obj, false);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_scale(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // engine_temp_arc
                            lv_obj_t *obj = lv_arc_create(parent_obj);
                            objects.engine_temp_arc = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 376, 376);
                            lv_arc_set_range(obj, 0, 1000);
                            lv_arc_set_value(obj, 25);
                            lv_arc_set_bg_start_angle(obj, 165);
                            lv_arc_set_bg_end_angle(obj, 15);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_arc(obj);
                        }
                        {
                            // engine_temp
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.engine_temp = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            add_style_mg_text_value_192(obj);
                            lv_label_set_text_static(obj, "00.0");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj1 = obj;
                            lv_obj_set_pos(obj, 0, 184);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "COOL");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj2 = obj;
                            lv_obj_set_pos(obj, 0, -112);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "ºC");
                        }
                    }
                }
                {
                    lv_obj_t *obj = lv_tabview_add_tab(parent_obj, "oil_temp");
                    lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                    lv_obj_set_scrollbar_mode(obj, LV_SCROLLBAR_MODE_OFF);
                    lv_obj_set_scroll_dir(obj, LV_DIR_NONE);
                    {
                        lv_obj_t *parent_obj = obj;
                        {
                            lv_obj_t *obj = lv_scale_create(parent_obj);
                            objects.obj3 = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 448, 448);
                            lv_scale_set_mode(obj, LV_SCALE_MODE_ROUND_INNER);
                            lv_scale_set_range(obj, 10, 40);
                            lv_scale_set_angle_range(obj, 210);
                            lv_scale_set_rotation(obj, 165);
                            lv_scale_set_total_tick_count(obj, 15);
                            lv_scale_set_major_tick_every(obj, 2);
                            lv_scale_set_label_show(obj, false);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_scale(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // oil_temp_arc
                            lv_obj_t *obj = lv_arc_create(parent_obj);
                            objects.oil_temp_arc = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 376, 376);
                            lv_arc_set_range(obj, 0, 1000);
                            lv_arc_set_value(obj, 25);
                            lv_arc_set_bg_start_angle(obj, 165);
                            lv_arc_set_bg_end_angle(obj, 15);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_arc(obj);
                        }
                        {
                            // oil_temp
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.oil_temp = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            add_style_mg_text_value_192(obj);
                            lv_label_set_text_static(obj, "00.0");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj4 = obj;
                            lv_obj_set_pos(obj, 0, 184);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "OIL");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj5 = obj;
                            lv_obj_set_pos(obj, 0, -112);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "ºC");
                        }
                    }
                }
                {
                    lv_obj_t *obj = lv_tabview_add_tab(parent_obj, "oil_pressure");
                    lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                    lv_obj_set_scrollbar_mode(obj, LV_SCROLLBAR_MODE_OFF);
                    lv_obj_set_scroll_dir(obj, LV_DIR_NONE);
                    {
                        lv_obj_t *parent_obj = obj;
                        {
                            lv_obj_t *obj = lv_scale_create(parent_obj);
                            objects.obj6 = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 448, 448);
                            lv_scale_set_mode(obj, LV_SCALE_MODE_ROUND_INNER);
                            lv_scale_set_range(obj, 10, 40);
                            lv_scale_set_angle_range(obj, 210);
                            lv_scale_set_rotation(obj, 165);
                            lv_scale_set_total_tick_count(obj, 15);
                            lv_scale_set_major_tick_every(obj, 2);
                            lv_scale_set_label_show(obj, false);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_scale(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // oil_pressure_arc
                            lv_obj_t *obj = lv_arc_create(parent_obj);
                            objects.oil_pressure_arc = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 376, 376);
                            lv_arc_set_range(obj, 0, 1000);
                            lv_arc_set_value(obj, 25);
                            lv_arc_set_bg_start_angle(obj, 165);
                            lv_arc_set_bg_end_angle(obj, 15);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_arc(obj);
                        }
                        {
                            // oil_pressure
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.oil_pressure = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            add_style_mg_text_value_192(obj);
                            lv_label_set_text_static(obj, "00.0");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj7 = obj;
                            lv_obj_set_pos(obj, 0, 184);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "OIL");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj8 = obj;
                            lv_obj_set_pos(obj, 0, -112);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "hPa");
                        }
                    }
                }
                {
                    lv_obj_t *obj = lv_tabview_add_tab(parent_obj, "oil_temp_2");
                    lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                    lv_obj_set_scrollbar_mode(obj, LV_SCROLLBAR_MODE_OFF);
                    lv_obj_set_scroll_dir(obj, LV_DIR_NONE);
                    {
                        lv_obj_t *parent_obj = obj;
                        {
                            lv_obj_t *obj = lv_scale_create(parent_obj);
                            objects.obj9 = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 448, 448);
                            lv_scale_set_mode(obj, LV_SCALE_MODE_ROUND_INNER);
                            lv_scale_set_range(obj, 10, 40);
                            lv_scale_set_angle_range(obj, 156);
                            lv_scale_set_rotation(obj, 192);
                            lv_scale_set_total_tick_count(obj, 11);
                            lv_scale_set_major_tick_every(obj, 2);
                            lv_scale_set_label_show(obj, false);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_scale(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // oil_temp_arc_2
                            lv_obj_t *obj = lv_arc_create(parent_obj);
                            objects.oil_temp_arc_2 = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 376, 376);
                            lv_arc_set_range(obj, 0, 1000);
                            lv_arc_set_value(obj, 25);
                            lv_arc_set_bg_start_angle(obj, 192);
                            lv_arc_set_bg_end_angle(obj, 348);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_arc(obj);
                        }
                        {
                            lv_obj_t *obj = lv_scale_create(parent_obj);
                            objects.obj10 = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 448, 448);
                            lv_scale_set_mode(obj, LV_SCALE_MODE_ROUND_INNER);
                            lv_scale_set_range(obj, 10, 40);
                            lv_scale_set_angle_range(obj, 156);
                            lv_scale_set_rotation(obj, 12);
                            lv_scale_set_total_tick_count(obj, 11);
                            lv_scale_set_major_tick_every(obj, 2);
                            lv_scale_set_label_show(obj, false);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_scale(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // engine_oil_temp_arc
                            lv_obj_t *obj = lv_arc_create(parent_obj);
                            objects.engine_oil_temp_arc = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 376, 376);
                            lv_arc_set_range(obj, 0, 1000);
                            lv_arc_set_value(obj, 25);
                            lv_arc_set_bg_start_angle(obj, 12);
                            lv_arc_set_bg_end_angle(obj, 168);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_arc(obj);
                        }
                        {
                            // oil_temp_2
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.oil_temp_2 = obj;
                            lv_obj_set_pos(obj, -13, -58);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            add_style_mg_text_value_120(obj);
                            lv_label_set_text_static(obj, "00.0");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj11 = obj;
                            lv_obj_set_pos(obj, 0, -144);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "OIL");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj12 = obj;
                            lv_obj_set_pos(obj, 74, -35);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "ºC");
                        }
                        {
                            lv_obj_t *obj = lv_line_create(parent_obj);
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            static lv_point_precise_t line_points[] = {
                                { 0, 0 },
                                { 240, 0 }
                            };
                            lv_line_set_points(obj, line_points, 2);
                            add_style_mg_rule(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // engine_oil_temp
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.engine_oil_temp = obj;
                            lv_obj_set_pos(obj, -13, 58);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            add_style_mg_text_value_120(obj);
                            lv_label_set_text_static(obj, "00.0");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj13 = obj;
                            lv_obj_set_pos(obj, 0, 144);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "E-OIL");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj14 = obj;
                            lv_obj_set_pos(obj, 74, 81);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "ºC");
                        }
                    }
                }
                {
                    lv_obj_t *obj = lv_tabview_add_tab(parent_obj, "coolant_temps");
                    lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                    lv_obj_set_scrollbar_mode(obj, LV_SCROLLBAR_MODE_OFF);
                    lv_obj_set_scroll_dir(obj, LV_DIR_NONE);
                    {
                        lv_obj_t *parent_obj = obj;
                        {
                            lv_obj_t *obj = lv_scale_create(parent_obj);
                            objects.obj15 = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 448, 448);
                            lv_scale_set_mode(obj, LV_SCALE_MODE_ROUND_INNER);
                            lv_scale_set_range(obj, 10, 40);
                            lv_scale_set_angle_range(obj, 156);
                            lv_scale_set_rotation(obj, 192);
                            lv_scale_set_total_tick_count(obj, 11);
                            lv_scale_set_major_tick_every(obj, 2);
                            lv_scale_set_label_show(obj, false);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_scale(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // engine_temp_arc_2
                            lv_obj_t *obj = lv_arc_create(parent_obj);
                            objects.engine_temp_arc_2 = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 376, 376);
                            lv_arc_set_range(obj, 0, 1000);
                            lv_arc_set_value(obj, 25);
                            lv_arc_set_bg_start_angle(obj, 192);
                            lv_arc_set_bg_end_angle(obj, 348);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_arc(obj);
                        }
                        {
                            lv_obj_t *obj = lv_scale_create(parent_obj);
                            objects.obj16 = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 448, 448);
                            lv_scale_set_mode(obj, LV_SCALE_MODE_ROUND_INNER);
                            lv_scale_set_range(obj, 10, 40);
                            lv_scale_set_angle_range(obj, 156);
                            lv_scale_set_rotation(obj, 12);
                            lv_scale_set_total_tick_count(obj, 11);
                            lv_scale_set_major_tick_every(obj, 2);
                            lv_scale_set_label_show(obj, false);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_scale(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // coolant_temp_arc
                            lv_obj_t *obj = lv_arc_create(parent_obj);
                            objects.coolant_temp_arc = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 376, 376);
                            lv_arc_set_range(obj, 0, 1000);
                            lv_arc_set_value(obj, 25);
                            lv_arc_set_bg_start_angle(obj, 12);
                            lv_arc_set_bg_end_angle(obj, 168);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_arc(obj);
                        }
                        {
                            // engine_temp_2
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.engine_temp_2 = obj;
                            lv_obj_set_pos(obj, -13, -58);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            add_style_mg_text_value_120(obj);
                            lv_label_set_text_static(obj, "00.0");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj17 = obj;
                            lv_obj_set_pos(obj, 0, -144);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "ENG");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj18 = obj;
                            lv_obj_set_pos(obj, 74, -35);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "ºC");
                        }
                        {
                            lv_obj_t *obj = lv_line_create(parent_obj);
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            static lv_point_precise_t line_points[] = {
                                { 0, 0 },
                                { 240, 0 }
                            };
                            lv_line_set_points(obj, line_points, 2);
                            add_style_mg_rule(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // coolant_temp
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.coolant_temp = obj;
                            lv_obj_set_pos(obj, -13, 58);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            add_style_mg_text_value_120(obj);
                            lv_label_set_text_static(obj, "00.0");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj19 = obj;
                            lv_obj_set_pos(obj, 0, 144);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "CLNT");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj20 = obj;
                            lv_obj_set_pos(obj, 74, 81);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "ºC");
                        }
                    }
                }
                {
                    lv_obj_t *obj = lv_tabview_add_tab(parent_obj, "pressures");
                    lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                    lv_obj_set_scrollbar_mode(obj, LV_SCROLLBAR_MODE_OFF);
                    lv_obj_set_scroll_dir(obj, LV_DIR_NONE);
                    {
                        lv_obj_t *parent_obj = obj;
                        {
                            lv_obj_t *obj = lv_scale_create(parent_obj);
                            objects.obj21 = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 448, 448);
                            lv_scale_set_mode(obj, LV_SCALE_MODE_ROUND_INNER);
                            lv_scale_set_range(obj, 10, 40);
                            lv_scale_set_angle_range(obj, 156);
                            lv_scale_set_rotation(obj, 192);
                            lv_scale_set_total_tick_count(obj, 11);
                            lv_scale_set_major_tick_every(obj, 2);
                            lv_scale_set_label_show(obj, false);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_scale(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // manifold_pressure_arc
                            lv_obj_t *obj = lv_arc_create(parent_obj);
                            objects.manifold_pressure_arc = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 376, 376);
                            lv_arc_set_range(obj, 0, 1000);
                            lv_arc_set_value(obj, 25);
                            lv_arc_set_bg_start_angle(obj, 192);
                            lv_arc_set_bg_end_angle(obj, 348);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_arc(obj);
                        }
                        {
                            lv_obj_t *obj = lv_scale_create(parent_obj);
                            objects.obj22 = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 448, 448);
                            lv_scale_set_mode(obj, LV_SCALE_MODE_ROUND_INNER);
                            lv_scale_set_range(obj, 10, 40);
                            lv_scale_set_angle_range(obj, 156);
                            lv_scale_set_rotation(obj, 12);
                            lv_scale_set_total_tick_count(obj, 11);
                            lv_scale_set_major_tick_every(obj, 2);
                            lv_scale_set_label_show(obj, false);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_scale(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // throttle_pressure_arc
                            lv_obj_t *obj = lv_arc_create(parent_obj);
                            objects.throttle_pressure_arc = obj;
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, 376, 376);
                            lv_arc_set_range(obj, 0, 1000);
                            lv_arc_set_value(obj, 25);
                            lv_arc_set_bg_start_angle(obj, 12);
                            lv_arc_set_bg_end_angle(obj, 168);
                            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
                            add_style_mg_arc(obj);
                        }
                        {
                            // manifold_pressure
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.manifold_pressure = obj;
                            lv_obj_set_pos(obj, -13, -58);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            add_style_mg_text_value_120(obj);
                            lv_label_set_text_static(obj, "00.0");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj23 = obj;
                            lv_obj_set_pos(obj, 0, -144);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "MANF");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj24 = obj;
                            lv_obj_set_pos(obj, 88, -35);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "hPA");
                        }
                        {
                            lv_obj_t *obj = lv_line_create(parent_obj);
                            lv_obj_set_pos(obj, 0, 0);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            static lv_point_precise_t line_points[] = {
                                { 0, 0 },
                                { 240, 0 }
                            };
                            lv_line_set_points(obj, line_points, 2);
                            add_style_mg_rule(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // throttle_pressure
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.throttle_pressure = obj;
                            lv_obj_set_pos(obj, -13, 58);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                            add_style_mg_text_value_120(obj);
                            lv_label_set_text_static(obj, "00.0");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj25 = obj;
                            lv_obj_set_pos(obj, 0, 144);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "THROT");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.obj26 = obj;
                            lv_obj_set_pos(obj, 88, 81);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_caption_42(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "hPA");
                        }
                    }
                }
                {
                    lv_obj_t *obj = lv_tabview_add_tab(parent_obj, "bm_daemon");
                    lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                    {
                        lv_obj_t *parent_obj = obj;
                        {
                            // bmw_state
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.bmw_state = obj;
                            lv_obj_set_pos(obj, 0, -165);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xcccccc), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "BMWP2000");
                        }
                        {
                            // bmw_frames_count
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.bmw_frames_count = obj;
                            lv_obj_set_pos(obj, -60, -120);
                            lv_obj_set_size(obj, 120, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "000000");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 50, -120);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "FRMS");
                        }
                        {
                            // bmw_rpm
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.bmw_rpm = obj;
                            lv_obj_set_pos(obj, -60, -80);
                            lv_obj_set_size(obj, 120, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "000000");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 41, -80);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "RPM");
                        }
                        {
                            // bmw_oil_temp
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.bmw_oil_temp = obj;
                            lv_obj_set_pos(obj, -60, -55);
                            lv_obj_set_size(obj, 120, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "000000");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 54, -55);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "ºC OIL");
                        }
                        {
                            // bmw_engine_temp
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.bmw_engine_temp = obj;
                            lv_obj_set_pos(obj, -60, -30);
                            lv_obj_set_size(obj, 120, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "000000");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 68, -30);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "ºC COOL");
                        }
                        {
                            // bmw_hpfp
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.bmw_hpfp = obj;
                            lv_obj_set_pos(obj, -60, -5);
                            lv_obj_set_size(obj, 120, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "000000");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 82, -5);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "BAR HPFP");
                        }
                        {
                            // bmw_throttle_pressure
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.bmw_throttle_pressure = obj;
                            lv_obj_set_pos(obj, -60, 20);
                            lv_obj_set_size(obj, 120, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "000000");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 90, 20);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "hPa THROT");
                        }
                        {
                            // bmw_manifold_boost
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.bmw_manifold_boost = obj;
                            lv_obj_set_pos(obj, -60, 45);
                            lv_obj_set_size(obj, 120, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "000000");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 90, 45);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "hPa BOOST");
                        }
                        {
                            // bmw_engine_oil_temp
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.bmw_engine_oil_temp = obj;
                            lv_obj_set_pos(obj, -60, 70);
                            lv_obj_set_size(obj, 120, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "000000");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 68, 70);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "ºC E OIL");
                        }
                        {
                            // bmw_engine_oil_pressure
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.bmw_engine_oil_pressure = obj;
                            lv_obj_set_pos(obj, -60, 95);
                            lv_obj_set_size(obj, 120, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "000000");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 66, 95);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "hPa OIL");
                        }
                        {
                            // bmw_coolant_temp
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.bmw_coolant_temp = obj;
                            lv_obj_set_pos(obj, -60, 120);
                            lv_obj_set_size(obj, 120, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "000000");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 81, 120);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "ºC COOL 2");
                        }
                    }
                }
                {
                    lv_obj_t *obj = lv_tabview_add_tab(parent_obj, "logger");
                    lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                    lv_obj_set_scrollbar_mode(obj, LV_SCROLLBAR_MODE_OFF);
                    {
                        lv_obj_t *parent_obj = obj;
                        {
                            // current_file_size
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.current_file_size = obj;
                            lv_obj_set_pos(obj, 67, -135);
                            lv_obj_set_size(obj, 125, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "99.9MB");
                        }
                        {
                            // status
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            objects.status = obj;
                            lv_obj_set_pos(obj, -78, -135);
                            lv_obj_set_size(obj, 132, LV_SIZE_CONTENT);
                            lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
                            add_style_mg_text_status(obj);
                            lv_obj_set_style_text_color(obj, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
                            lv_label_set_text_static(obj, "LOGGING");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 0, -135);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "·");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, -78, 91);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "BKLT");
                        }
                        {
                            lv_obj_t *obj = lv_label_create(parent_obj);
                            lv_obj_set_pos(obj, 80, 91);
                            lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
                            add_style_mg_text_status(obj);
                            lv_label_set_text_static(obj, "LOG");
                        }
                        {
                            // backlight_sw
                            lv_obj_t *obj = lv_switch_create(parent_obj);
                            objects.backlight_sw = obj;
                            lv_obj_set_pos(obj, -80, 0);
                            lv_obj_set_size(obj, 72, 132);
                            lv_obj_add_event_cb(obj, event_handler_checked_cb_main_backlight_sw, LV_EVENT_VALUE_CHANGED, (void *)0);
                            lv_obj_add_event_cb(obj, event_handler_unchecked_cb_main_backlight_sw, LV_EVENT_VALUE_CHANGED, (void *)0);
                            lv_obj_add_event_cb(obj, event_handler_cb_main_backlight_sw, LV_EVENT_ALL, 0);
                            add_style_mg_switch(obj);
                        }
                        {
                            // log_sw
                            lv_obj_t *obj = lv_switch_create(parent_obj);
                            objects.log_sw = obj;
                            lv_obj_set_pos(obj, 80, 0);
                            lv_obj_set_size(obj, 72, 132);
                            lv_obj_add_event_cb(obj, action_start_stop_clicked, LV_EVENT_VALUE_CHANGED, (void *)0);
                            add_style_mg_switch(obj);
                        }
                    }
                }
                {
                    lv_obj_t *obj = lv_tabview_add_tab(parent_obj, "widget test");
                    lv_obj_add_event_cb(obj, action_global_pressed, LV_EVENT_PRESSED, (void *)0);
                    {
                        lv_obj_t *parent_obj = obj;
                        {
                            // filter_sw
                            lv_obj_t *obj = lv_switch_create(parent_obj);
                            objects.filter_sw = obj;
                            lv_obj_set_pos(obj, -110, 0);
                            lv_obj_set_size(obj, 72, 132);
                            lv_obj_add_event_cb(obj, action_filter_sw_actuated, LV_EVENT_VALUE_CHANGED, (void *)0);
                            add_style_mg_switch(obj);
                            lv_obj_set_style_align(obj, LV_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
                        }
                        {
                            // brightness_slider
                            lv_obj_t *obj = lv_slider_create(parent_obj);
                            objects.brightness_slider = obj;
                            lv_obj_set_pos(obj, 261, 96);
                            lv_obj_set_size(obj, 25, 255);
                            lv_slider_set_value(obj, 25, LV_ANIM_OFF);
                        }
                    }
                }
            }
        }
    }
    
    tick_screen_main();
}

void tick_screen_main() {
}

typedef void (*tick_screen_func_t)();
tick_screen_func_t tick_screen_funcs[] = {
    tick_screen_loading,
    tick_screen_main,
};
void tick_screen(int screen_index) {
    if (screen_index >= 0 && screen_index < 2) {
        tick_screen_funcs[screen_index]();
    }
}
void tick_screen_by_id(enum ScreensEnum screenId) {
    tick_screen(screenId - 1);
}

//
// Fonts
//

ext_font_desc_t fonts[] = {
    { "league_192px", &ui_font_league_192px },
    { "league_120px", &ui_font_league_120px },
    { "league_96px", &ui_font_league_96px },
    { "league_48px", &ui_font_league_48px },
    { "league_42px", &ui_font_league_42px },
    { "teko_36px", &ui_font_teko_36px },
#if LV_FONT_MONTSERRAT_8
    { "MONTSERRAT_8", &lv_font_montserrat_8 },
#endif
#if LV_FONT_MONTSERRAT_10
    { "MONTSERRAT_10", &lv_font_montserrat_10 },
#endif
#if LV_FONT_MONTSERRAT_12
    { "MONTSERRAT_12", &lv_font_montserrat_12 },
#endif
#if LV_FONT_MONTSERRAT_14
    { "MONTSERRAT_14", &lv_font_montserrat_14 },
#endif
#if LV_FONT_MONTSERRAT_16
    { "MONTSERRAT_16", &lv_font_montserrat_16 },
#endif
#if LV_FONT_MONTSERRAT_18
    { "MONTSERRAT_18", &lv_font_montserrat_18 },
#endif
#if LV_FONT_MONTSERRAT_20
    { "MONTSERRAT_20", &lv_font_montserrat_20 },
#endif
#if LV_FONT_MONTSERRAT_22
    { "MONTSERRAT_22", &lv_font_montserrat_22 },
#endif
#if LV_FONT_MONTSERRAT_24
    { "MONTSERRAT_24", &lv_font_montserrat_24 },
#endif
#if LV_FONT_MONTSERRAT_26
    { "MONTSERRAT_26", &lv_font_montserrat_26 },
#endif
#if LV_FONT_MONTSERRAT_28
    { "MONTSERRAT_28", &lv_font_montserrat_28 },
#endif
#if LV_FONT_MONTSERRAT_30
    { "MONTSERRAT_30", &lv_font_montserrat_30 },
#endif
#if LV_FONT_MONTSERRAT_32
    { "MONTSERRAT_32", &lv_font_montserrat_32 },
#endif
#if LV_FONT_MONTSERRAT_34
    { "MONTSERRAT_34", &lv_font_montserrat_34 },
#endif
#if LV_FONT_MONTSERRAT_36
    { "MONTSERRAT_36", &lv_font_montserrat_36 },
#endif
#if LV_FONT_MONTSERRAT_38
    { "MONTSERRAT_38", &lv_font_montserrat_38 },
#endif
#if LV_FONT_MONTSERRAT_40
    { "MONTSERRAT_40", &lv_font_montserrat_40 },
#endif
#if LV_FONT_MONTSERRAT_42
    { "MONTSERRAT_42", &lv_font_montserrat_42 },
#endif
#if LV_FONT_MONTSERRAT_44
    { "MONTSERRAT_44", &lv_font_montserrat_44 },
#endif
#if LV_FONT_MONTSERRAT_46
    { "MONTSERRAT_46", &lv_font_montserrat_46 },
#endif
#if LV_FONT_MONTSERRAT_48
    { "MONTSERRAT_48", &lv_font_montserrat_48 },
#endif
};

//
// Color themes
//

uint32_t active_theme_index = 0;

//
//
//

void create_screens() {

// Set default LVGL theme
    lv_display_t *dispp = lv_display_get_default();
    lv_theme_t *theme = lv_theme_default_init(dispp, lv_palette_main(LV_PALETTE_BLUE), lv_palette_main(LV_PALETTE_RED), true, LV_FONT_DEFAULT);
    lv_display_set_theme(dispp, theme);
    
    // Initialize screens
    // Create screens
    create_screen_loading();
    create_screen_main();
}
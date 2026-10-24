#ifndef EEZ_LVGL_UI_SCREENS_H
#define EEZ_LVGL_UI_SCREENS_H

#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

// Screens

enum ScreensEnum {
    _SCREEN_ID_FIRST = 1,
    SCREEN_ID_LOADING = 1,
    SCREEN_ID_MAIN = 2,
    _SCREEN_ID_LAST = 2
};

typedef struct _objects_t {
    lv_obj_t *loading;
    lv_obj_t *main;
    lv_obj_t *load_0_25;
    lv_obj_t *load_25_50;
    lv_obj_t *load_50_75;
    lv_obj_t *load_75_100;
    lv_obj_t *global_tabview;
    lv_obj_t *obj0;
    lv_obj_t *engine_temp_arc;
    lv_obj_t *engine_temp;
    lv_obj_t *obj1;
    lv_obj_t *obj2;
    lv_obj_t *obj3;
    lv_obj_t *oil_temp_arc;
    lv_obj_t *oil_temp;
    lv_obj_t *obj4;
    lv_obj_t *obj5;
    lv_obj_t *obj6;
    lv_obj_t *oil_pressure_arc;
    lv_obj_t *oil_pressure;
    lv_obj_t *obj7;
    lv_obj_t *obj8;
    lv_obj_t *obj9;
    lv_obj_t *oil_temp_arc_2;
    lv_obj_t *obj10;
    lv_obj_t *engine_oil_temp_arc;
    lv_obj_t *oil_temp_2;
    lv_obj_t *obj11;
    lv_obj_t *obj12;
    lv_obj_t *engine_oil_temp;
    lv_obj_t *obj13;
    lv_obj_t *obj14;
    lv_obj_t *obj15;
    lv_obj_t *engine_temp_arc_2;
    lv_obj_t *obj16;
    lv_obj_t *coolant_temp_arc;
    lv_obj_t *engine_temp_2;
    lv_obj_t *obj17;
    lv_obj_t *obj18;
    lv_obj_t *coolant_temp;
    lv_obj_t *obj19;
    lv_obj_t *obj20;
    lv_obj_t *obj21;
    lv_obj_t *manifold_pressure_arc;
    lv_obj_t *obj22;
    lv_obj_t *throttle_pressure_arc;
    lv_obj_t *manifold_pressure;
    lv_obj_t *obj23;
    lv_obj_t *obj24;
    lv_obj_t *throttle_pressure;
    lv_obj_t *obj25;
    lv_obj_t *obj26;
    lv_obj_t *bmw_state;
    lv_obj_t *bmw_frames_count;
    lv_obj_t *bmw_rpm;
    lv_obj_t *bmw_oil_temp;
    lv_obj_t *bmw_engine_temp;
    lv_obj_t *bmw_hpfp;
    lv_obj_t *bmw_throttle_pressure;
    lv_obj_t *bmw_manifold_boost;
    lv_obj_t *bmw_engine_oil_temp;
    lv_obj_t *bmw_engine_oil_pressure;
    lv_obj_t *bmw_coolant_temp;
    lv_obj_t *current_file_size;
    lv_obj_t *status;
    lv_obj_t *backlight_sw;
    lv_obj_t *log_sw;
    lv_obj_t *filter_sw;
} objects_t;

extern objects_t objects;

void create_screen_loading();
void tick_screen_loading();

void create_screen_main();
void tick_screen_main();

void tick_screen_by_id(enum ScreensEnum screenId);
void tick_screen(int screen_index);

void create_screens();

#ifdef __cplusplus
}
#endif

#endif /*EEZ_LVGL_UI_SCREENS_H*/
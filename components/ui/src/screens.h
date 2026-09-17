#ifndef EEZ_LVGL_UI_SCREENS_H
#define EEZ_LVGL_UI_SCREENS_H

#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

// Screens

enum ScreensEnum {
    _SCREEN_ID_FIRST = 1,
    SCREEN_ID_MAIN = 1,
    _SCREEN_ID_LAST = 1
};

typedef struct _objects_t {
    lv_obj_t *main;
    lv_obj_t *filename;
    lv_obj_t *filesize;
    lv_obj_t *buffered_size;
    lv_obj_t *status;
    lv_obj_t *start_stop_btn;
    lv_obj_t *start_stop_lbl;
    lv_obj_t *rbx_status;
    lv_obj_t *backlight_switch;
    lv_obj_t *rpm_readout;
    lv_obj_t *kph_readout;
    lv_obj_t *ratio_readout;
    lv_obj_t *gear_readout;
} objects_t;

extern objects_t objects;

void create_screen_main();
void tick_screen_main();

void tick_screen_by_id(enum ScreensEnum screenId);
void tick_screen(int screen_index);

void create_screens();

#ifdef __cplusplus
}
#endif

#endif /*EEZ_LVGL_UI_SCREENS_H*/
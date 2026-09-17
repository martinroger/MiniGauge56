#ifndef EEZ_LVGL_UI_EVENTS_H
#define EEZ_LVGL_UI_EVENTS_H

#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

extern void action_start_stop_clicked(lv_event_t * e);
extern void action_global_pressed(lv_event_t * e);
extern void action_backlight_sw_checked(lv_event_t * e);
extern void action_backlight_sw_unchecked(lv_event_t * e);

#ifdef __cplusplus
}
#endif

#endif /*EEZ_LVGL_UI_EVENTS_H*/
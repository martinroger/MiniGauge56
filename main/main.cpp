#include <stdio.h>
#include "esp32_s3_touch_amoled_1_75.h"
#include "ui.h"

lv_display_t *main_display;

extern "C" void app_main(void)
{
    main_display = bsp_display_start();
    bsp_display_lock(1);
    ui_init();
    bsp_display_unlock();

    while(true)
    {
        vTaskDelay(pdMS_TO_TICKS(100));
    }

}

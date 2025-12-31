#include <stdio.h>
#include "esp32_s3_touch_amoled_1_75.h"
#include "ui.h"
#include "esp_log.h"

lv_display_t *main_display;

extern "C" void app_main(void)
{
    main_display = bsp_display_start();
    bsp_display_brightness_set(100);
    // if(bsp_display_lock(100))
    // {
    //     ESP_LOGI(__func__,"first mutex taken");
        
    //     bsp_display_unlock();
    // }
    bsp_display_lock(-1);
    ui_init();
    bsp_display_unlock();

    uint8_t brightness = 0;
    // bsp_display_brightness_set(10);

    ESP_LOGI("TAG", "Test");
    while (true)
    {

        vTaskDelay(pdMS_TO_TICKS(100));
        brightness += 1;
        brightness %= 100;
        
        if (!bsp_display_lock(-1))
        {
            bsp_display_brightness_set(brightness);
            bsp_display_unlock();
        }

        
        // bsp_display_brightness_set(brightness);
        // if (bsp_display_lock(1000))
        // {
        //     if (bsp_display_brightness_set(brightness) != ESP_OK)
        //         ESP_LOGE(__func__, "Cannot set brightness");
        //     else
        //         ESP_LOGI(__func__, "Brightness set to %u", brightness);
        //     bsp_display_unlock();
        // }
        // else
        // {
        //     ESP_LOGW(__func__,"mutex not available");
        // }
    }
}

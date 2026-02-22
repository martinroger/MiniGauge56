#include <stdio.h>
#include "esp32_s3_touch_amoled_1_75.h"
#include "ui.h"
#include "esp_log.h"
#include "sdLogger.h"

lv_display_t *main_display;

extern "C" void app_main(void)
{
    if(bsp_sdcard_mount() != ESP_OK)
    {
        ESP_LOGW(__func__,"Could not mount SD CARD");
    }
    else
    {
        ESP_LOGI(__func__, "SD card mounted at %s", BSP_SD_MOUNT_POINT);
        check_and_prepare_storage();
        open_next_log_file();

    }
    main_display = bsp_display_start();
    bsp_display_brightness_set(0);
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

    log_to_sd("Test-log!");

    while (true)
    {

        vTaskDelay(pdMS_TO_TICKS(100));


        // // Testing brightness control
        // brightness += 1;
        // brightness %= 100;
        
        // if (bsp_display_lock(-1) == ESP_OK)
        // {
        //     bsp_display_brightness_set(brightness);
        //     bsp_display_unlock();
        // }

        
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

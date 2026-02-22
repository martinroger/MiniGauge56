#include <stdio.h>
#include "esp32_s3_touch_amoled_1_75.h"
#include "ui.h"
#include "esp_log.h"
// Courtesy of https://github.com/ubx/CAN-logger2
#include "logging.h"

lv_display_t *main_display;

extern "C" void app_main(void)
{
    if (bsp_sdcard_mount() != ESP_OK)
    {
        ESP_LOGW(__func__, "Could not mount SD CARD");
    }
    else
    {
        ESP_LOGI(__func__, "SD card mounted at %s", BSP_SD_MOUNT_POINT);
        start_logging_mode();
    }

    // Display init
    main_display = bsp_display_start();

    if (bsp_display_lock(-1) == ESP_OK)
    {
        bsp_display_brightness_set(0);
        ui_init();
        bsp_display_unlock();
    }
    else
    {
        ESP_LOGE(__func__, "Could not catch mutex for LVGL, aborting");
        return;
    }

    // uint8_t brightness = 0;

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
    }
}
